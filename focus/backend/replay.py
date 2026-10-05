"""Replay the exact accepted input/intent/clock journal through the production engine."""
from contextlib import closing
import json
import sqlite3
import math
from .engine import Engine, ALGORITHM_VERSION
from .storage import dumps, _read_only
from settings import Config


def replay_session(path, session_id):
    with closing(_read_only(path)) as db:
        row = db.execute("SELECT json FROM configs WHERE session_id=?", (session_id,)).fetchone()
        if row is None:
            raise ValueError("找不到会话配置")
        metadata = json.loads(row[0])
        if metadata["algorithm"] != ALGORITHM_VERSION:
            raise ValueError("算法版本不匹配；必须使用记录时的版本回放")
        engine = Engine(Config(**metadata["config"]), session_id, metadata["activity"],
                        metadata["duration"], metadata["distance"], metadata["references"])
        rows = db.execute("SELECT ordinal,kind,payload FROM journal WHERE session_id=? ORDER BY ordinal", (session_id,))
        checks = 0
        for expected_ordinal, (ordinal, kind, payload) in enumerate(rows):
            if ordinal != expected_ordinal:
                raise ValueError("记录序号存在缺口，无法验证完整回放")
            data = json.loads(payload)
            if kind == "advance":
                engine.advance(data["t"])
            elif kind == "frame":
                engine.feed(data["lane"], data["frame"])
            elif kind == "intent":
                engine.intent(data["action"], data["session_id"], **data["options"])
            elif kind == "checkpoint":
                if not equivalent(engine.snapshot(), data):
                    raise AssertionError(f"回放与原始结果不一致：journal ordinal={ordinal}")
                checks += 1
            else:
                raise ValueError(f"未知回放事件: {kind}")
            engine.events.clear()
            engine.sample_rows.clear()
        if checks == 0:
            raise ValueError("记录没有检查点，无法验证回放")
        status = db.execute("SELECT complete FROM sessions WHERE id=?", (session_id,)).fetchone()[0]
        return {"session_id": session_id, "checkpoints_verified": checks, "record_complete": bool(status),
                "matched": True, "snapshot": engine.snapshot()}


def equivalent(left, right, tolerance=1e-8):
    if isinstance(left, float) or isinstance(right, float):
        return isinstance(left, (int, float)) and isinstance(right, (int, float)) and math.isclose(float(left), float(right), rel_tol=tolerance, abs_tol=tolerance)
    if isinstance(left, dict) and isinstance(right, dict):
        return left.keys() == right.keys() and all(equivalent(left[key], right[key], tolerance) for key in left)
    if isinstance(left, (list, tuple)) and isinstance(right, (list, tuple)):
        return len(left) == len(right) and all(equivalent(a, b, tolerance) for a, b in zip(left, right))
    return left == right
