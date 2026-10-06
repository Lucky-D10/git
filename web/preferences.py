"""UI preferences on API workers; writes never alter the active engine config."""
from contextlib import closing
import json
import math
import sqlite3
from backend.storage import _read_only

DEFAULTS = {"duration": 180, "distance": 100, "references": [50, 60],
            "bindings": [1, 2], "session_kind": "experience", "reduced_motion": False}
AVATARS = {"wave", "star", "leaf", "rocket", "car"}


def preferences(path):
    with closing(_read_only(path)) as db:
        row = db.execute("SELECT json FROM application_settings WHERE key='teacher-preset'").fetchone()
    return {**DEFAULTS, **(json.loads(row[0]) if row else {})}


def players(path):
    with closing(_read_only(path)) as db:
        rows = db.execute("SELECT p.id,p.nickname,COALESCE(a.avatar,'wave') FROM players p "
                          "LEFT JOIN player_profiles a ON a.player_id=p.id WHERE p.id NOT LIKE 'guest-%' ORDER BY p.id LIMIT 200").fetchall()
    result = [{"id": pid, "nickname": nick or ({"local-1": "小蓝", "local-2": "小橙"}.get(pid, pid)),
               "avatar": avatar} for pid, nick, avatar in rows]
    ids = {p["id"] for p in result}
    for pid, nick, avatar in [("local-1", "小蓝", "wave"), ("local-2", "小橙", "star")]:
        if pid not in ids:
            result.append({"id": pid, "nickname": nick, "avatar": avatar})
    return result


def save_preset(path, value):
    if not isinstance(value, dict) or set(value) != set(DEFAULTS):
        raise ValueError("预设字段不完整或包含未知字段")
    for key, maximum in [("duration", 7200), ("distance", 10000)]:
        number = value[key]
        if type(number) not in (int, float) or not math.isfinite(number) or not 1 <= number <= maximum:
            raise ValueError("时长或虚拟距离超出范围")
    refs, bindings = value["references"], value["bindings"]
    if not isinstance(refs, list) or len(refs) != 2 or any(type(v) not in (int, float) or not math.isfinite(v) or not 0 <= v <= 100 for v in refs):
        raise ValueError("两位玩家的目标必须为 0..100")
    if not isinstance(bindings, list) or len(bindings) != 2 or any(type(v) is not int for v in bindings) or set(bindings) != {1, 2}:
        raise ValueError("两路头环绑定必须为不同的 1 和 2")
    if value["session_kind"] not in ("experience", "formal") or type(value["reduced_motion"]) is not bool:
        raise ValueError("规则或动画设置无效")
    with closing(sqlite3.connect(str(path), timeout=1)) as db, db:
        db.execute("PRAGMA synchronous=FULL")
        db.execute("INSERT OR REPLACE INTO application_settings VALUES('teacher-preset',?)",
                   (json.dumps(value, ensure_ascii=False, allow_nan=False),))
    return value


def save_player(path, value):
    if not isinstance(value, dict) or set(value) != {"id", "nickname", "avatar"}:
        raise ValueError("玩家资料字段无效")
    pid, nick, avatar = value["id"], value["nickname"], value["avatar"]
    if isinstance(pid, str) and pid.startswith("guest-"):
        raise ValueError("临时访客不能修改为长期档案")
    if not isinstance(pid, str) or not pid.strip() or len(pid) > 48:
        raise ValueError("玩家编号须为 1..48 字符")
    if not isinstance(nick, str) or not nick.strip() or len(nick) > 20 or not isinstance(avatar, str) or avatar not in AVATARS:
        raise ValueError("昵称须为 1..20 字符，头像必须来自预设")
    with closing(sqlite3.connect(str(path), timeout=1)) as db, db:
        db.execute("PRAGMA synchronous=FULL")
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("INSERT INTO players(id,nickname) VALUES(?,?) ON CONFLICT(id) DO UPDATE SET nickname=excluded.nickname", (pid, nick.strip()))
        db.execute("INSERT OR REPLACE INTO player_profiles VALUES(?,?)", (pid, avatar))
    return {"id": pid, "nickname": nick.strip(), "avatar": avatar}
