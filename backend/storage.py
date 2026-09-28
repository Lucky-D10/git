"""Bounded asynchronous SQLite writer. SQL and report/export work never run on control thread."""
import csv
from datetime import datetime, timezone, timedelta
import json
from pathlib import Path
import queue
import shutil
import sqlite3
import threading
import time
import os
from contextlib import closing
import logging


def dumps(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)


def utc_now():
    return datetime.now(timezone.utc).isoformat()


SCHEMA = """
CREATE TABLE IF NOT EXISTS players(id TEXT PRIMARY KEY, nickname TEXT);
CREATE TABLE IF NOT EXISTS sessions(id TEXT PRIMARY KEY, mode TEXT, activity TEXT,
 started_utc TEXT, ended_utc TEXT, status TEXT, end_reason TEXT, complete INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS participants(session_id TEXT REFERENCES sessions(id), lane INTEGER,
 player_id TEXT REFERENCES players(id), PRIMARY KEY(session_id,lane));
CREATE TABLE IF NOT EXISTS configs(session_id TEXT PRIMARY KEY REFERENCES sessions(id), json TEXT);
CREATE TABLE IF NOT EXISTS journal(session_id TEXT REFERENCES sessions(id), ordinal INTEGER,
 t REAL, utc TEXT, kind TEXT, payload TEXT, PRIMARY KEY(session_id,ordinal));
CREATE TABLE IF NOT EXISTS samples(id INTEGER PRIMARY KEY, session_id TEXT REFERENCES sessions(id),
 lane INTEGER, device TEXT, utc TEXT, t REAL, source_t REAL, sequence INTEGER, generation INTEGER,
 raw TEXT, smoothed REAL, valid INTEGER, reason TEXT, facts TEXT);
CREATE INDEX IF NOT EXISTS samples_time ON samples(session_id,lane,t,id);
CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY, session_id TEXT REFERENCES sessions(id),
 utc TEXT, t REAL, event TEXT, details TEXT);
CREATE TABLE IF NOT EXISTS statistics(session_id TEXT REFERENCES sessions(id), lane INTEGER,
 json TEXT, PRIMARY KEY(session_id,lane));
CREATE TABLE IF NOT EXISTS reports(session_id TEXT PRIMARY KEY REFERENCES sessions(id),
 version TEXT, status TEXT, base_json TEXT, ai_json TEXT);
"""


class Store:
    def __init__(self, config):
        self.config = config
        self.path = Path(config.storage_path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.error = None
        self.warning = None
        self.committed_at = time.monotonic()
        self.pending_since = None
        self.committed = {}
        self.queue = queue.Queue(config.storage_queue_size)
        self.stopping = threading.Event()
        self.ready = threading.Event()
        self._lockfile = open(str(self.path) + ".lock", "a+b")
        try:
            if os.name == "nt":
                import msvcrt
                self._lockfile.seek(0)
                if not self._lockfile.read(1):
                    self._lockfile.write(b"0")
                    self._lockfile.flush()
                self._lockfile.seek(0)
                msvcrt.locking(self._lockfile.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self._lockfile, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self._lockfile.close()
            raise RuntimeError("另一个后台正在使用该数据库")
        self.thread = threading.Thread(target=self._run, name="focus-storage", daemon=True)
        self.thread.start()
        if not self.ready.wait(10) or self.error:
            self.close()
            raise RuntimeError(self.error or "数据库初始化超时")

    def submit(self, batch):
        if self.error or self.stopping.is_set():
            return False
        try:
            self.queue.put_nowait((time.monotonic(), batch))
            return True
        except queue.Full:
            self.error = "存储队列已满，记录不完整"
            return False

    def health(self):
        oldest = self.pending_since
        with self.queue.mutex:
            if self.queue.queue:
                oldest = min(oldest or float("inf"), self.queue.queue[0][0])
        lag = max(0, time.monotonic() - oldest) if oldest is not None else 0
        return {"error": self.error, "warning": self.warning, "lag_seconds": lag,
                "healthy": self.error is None and lag <= self.config.storage_max_lag_seconds}

    def _run(self):
        db = None
        try:
            db = sqlite3.connect(str(self.path), timeout=1)
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("PRAGMA synchronous=FULL")
            db.execute("PRAGMA foreign_keys=ON")
            db.executescript(SCHEMA)
            now = utc_now()
            interrupted = db.execute("SELECT id FROM sessions WHERE complete=0 AND end_reason IS NOT 'process_restart'").fetchall()
            for (sid,) in interrupted:
                last_t = db.execute("SELECT COALESCE(MAX(t), 0) FROM journal WHERE session_id=?", (sid,)).fetchone()[0]
                db.execute("UPDATE sessions SET status='aborted', end_reason='process_restart', ended_utc=? WHERE id=?", (now, sid))
                db.execute("INSERT INTO events(session_id,utc,t,event,details) VALUES(?,?,?,?,?)",
                           (sid, now, last_t, "process_restart",
                            dumps({"reason": "unfinished session recovered; outputs inhibited",
                                   "recovered_at": now})))
                db.execute("UPDATE reports SET status='incomplete' WHERE session_id=?", (sid,))
            db.commit()
            # SQLite backup API includes WAL data; retain five startup snapshots.
            if self.path.stat().st_size > 4096:
                folder = self.path.parent / "backups"
                folder.mkdir(exist_ok=True)
                backup_path = folder / (datetime.now().strftime("%Y%m%d-%H%M%S-%f") + ".sqlite3")
                with closing(sqlite3.connect(str(backup_path))) as dest:
                    db.backup(dest)
                for old in sorted(folder.glob("*.sqlite3"))[:-5]:
                    old.unlink()
            self.ready.set()
            while not self.stopping.is_set() or not self.queue.empty():
                try:
                    created, batch = self.queue.get(timeout=.1)
                except queue.Empty:
                    continue
                self.pending_since = created
                batches = [batch]
                deadline = time.monotonic() + self.config.storage_flush_seconds
                while not self.stopping.is_set() and time.monotonic() < deadline:
                    try:
                        _, extra = self.queue.get(timeout=max(.001, deadline - time.monotonic()))
                        batches.append(extra)
                    except queue.Empty:
                        break
                free = shutil.disk_usage(self.path.parent).free
                self.warning = "磁盘空间不足提醒" if free < self.config.disk_warning_mb * 1024 ** 2 else None
                with db:
                    for item in batches:
                        self._write(db, item)
                self.committed_at = time.monotonic()
                for item in batches:
                    self.committed[item["session_id"]] = (item["journal"][-1]["ordinal"] if item["journal"] else self.committed.get(item["session_id"], -1))
                    self.queue.task_done()
                self.pending_since = None
        except Exception as exc:
            self.error = f"记录故障: {type(exc).__name__}: {exc}"
            logging.getLogger("focus.storage").error(self.error)
        finally:
            self.ready.set()
            if db is not None:
                db.close()

    def _write(self, db, batch):
        sid, start = batch["session_id"], batch["start_utc"]
        def wall(t):
            return (datetime.fromisoformat(start) + timedelta(seconds=t)).isoformat()
        if "config" in batch:
            c = batch["config"]
            db.execute("INSERT INTO sessions(id,mode,activity,started_utc,status) VALUES(?,?,?,?,?)", (sid, c["config"]["mode"], c["activity"], start, "preparing"))
            db.execute("INSERT INTO configs VALUES(?,?)", (sid, dumps(c)))
            for lane in range(1, c["config"]["players"] + 1):
                player_id = batch.get("player_ids", ["local-1", "local-2"])[lane-1]
                db.execute("INSERT OR IGNORE INTO players(id) VALUES(?)", (player_id,))
                db.execute("INSERT INTO participants VALUES(?,?,?)", (sid, lane, player_id))
        for row in batch["journal"]:
            db.execute("INSERT INTO journal VALUES(?,?,?,?,?,?)", (sid, row["ordinal"], row["t"], wall(row["t"]), row["kind"], dumps(row["payload"])))
        for row in batch["samples"]:
            db.execute("INSERT INTO samples(session_id,lane,device,utc,t,source_t,sequence,generation,raw,smoothed,valid,reason,facts) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                       (sid, row["lane"], row.get("device", f"headband-{row['lane']}"), wall(row["t"]), row["t"], row["source_t"], row["sequence"], row["generation"], dumps(row["raw"]), row["smoothed"], row["valid"], row["reason"], dumps(row)))
        for row in batch["events"]:
            db.execute("INSERT INTO events(session_id,utc,t,event,details) VALUES(?,?,?,?,?)", (sid, wall(row["t"]), row["t"], row["event"], dumps(row)))
        snap = batch["snapshot"]
        terminal = snap["state"] in ("finished", "aborted")
        db.execute("UPDATE sessions SET status=?,end_reason=?,ended_utc=?,complete=? WHERE id=?", (snap["state"], snap["reason"], wall(snap["now"]) if terminal else None, int(terminal and not batch.get("incomplete")), sid))
        for lane in snap["players"]:
            db.execute("INSERT OR REPLACE INTO statistics VALUES(?,?,?)", (sid, lane["player"], dumps(lane)))
        db.execute("INSERT OR REPLACE INTO reports VALUES(?,?,?,?,NULL)", (sid, snap["algorithm"], "incomplete" if batch.get("incomplete") else "ready" if terminal else "pending", dumps(snap)))

    def close(self):
        self.stopping.set()
        self.thread.join(timeout=5)
        if self.thread.is_alive():
            self.error = "存储线程未完成，记录可能不完整"
        else:
            self._lockfile.close()


def export_session(path, sid, directory):
    """Long-format samples, independently timestamped; no ordinal alignment."""
    with closing(_read_only(path)) as db:
        row = db.execute("SELECT status,base_json FROM reports WHERE session_id=?", (sid,)).fetchone()
        if not row or row[0] != "ready":
            raise RuntimeError("记录尚未完整保存，不能导出完整报告")
        report = json.loads(row[1])
        report["config_snapshot"] = json.loads(db.execute("SELECT json FROM configs WHERE session_id=?", (sid,)).fetchone()[0])
        report["events"] = [json.loads(r[0]) for r in db.execute("SELECT details FROM events WHERE session_id=? ORDER BY t,id", (sid,))]
        report["measurement_note"] = "赛程为虚拟成绩；样本按各自接收时间排序，不按行号对齐，不插值补测。"
        output = Path(directory)
        output.mkdir(parents=True, exist_ok=True)
        json_path, csv_path = output / (sid + ".json"), output / (sid + ".csv")
        json_path.write_text(dumps(report), encoding="utf-8")
        cursor = db.execute("SELECT lane,device,utc,t,source_t,sequence,generation,raw,smoothed,valid,reason FROM samples WHERE session_id=? ORDER BY t,id", (sid,))
        with csv_path.open("w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow([c[0] for c in cursor.description])
            writer.writerows(cursor)
        return json_path, csv_path


def _read_only(path):
    """Open an existing database without creating a file as a side effect."""
    resolved = Path(path).resolve()
    if not resolved.exists():
        raise FileNotFoundError(str(resolved))
    return sqlite3.connect(resolved.as_uri() + "?mode=ro", uri=True)


def list_sessions(path, player_id=None, date_from=None, date_to=None, limit=50):
    """Read-only history query; each row is a completed or interrupted session."""
    limit = max(1, min(int(limit), 200))
    clauses, values = [], []
    if player_id:
        clauses.append("EXISTS (SELECT 1 FROM participants p WHERE p.session_id=s.id AND p.player_id=?)")
        values.append(player_id)
    if date_from:
        clauses.append("s.started_utc >= ?")
        values.append(date_from)
    if date_to:
        clauses.append("s.started_utc < ?")
        values.append(date_to)
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    with closing(_read_only(path)) as db:
        rows = db.execute(
            "SELECT s.id,s.mode,s.activity,s.started_utc,s.ended_utc,s.status,s.end_reason,s.complete "
            "FROM sessions s" + where + " ORDER BY s.started_utc DESC LIMIT ?", (*values, limit)).fetchall()
        return [{"session_id": row[0], "mode": row[1], "activity": row[2], "started_utc": row[3],
                 "ended_utc": row[4], "status": row[5], "end_reason": row[6], "complete": bool(row[7])}
                for row in rows]


def read_report(path, sid):
    with closing(_read_only(path)) as db:
        row = db.execute("SELECT status,version,base_json,ai_json FROM reports WHERE session_id=?", (sid,)).fetchone()
        if row is None:
            raise KeyError("找不到报告")
        report = json.loads(row[2]) if row[2] else {}
        return {"session_id": sid, "status": row[0], "algorithm": row[1], "base": report,
                "ai": json.loads(row[3]) if row[3] else None}
