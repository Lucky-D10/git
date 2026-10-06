"""Read-only queries on API workers. Full records drive statistics; only plots thin."""
from contextlib import closing
from datetime import date, timedelta
import hashlib
import json
from backend.storage import _read_only, read_report, list_sessions


def conditions(metadata):
    config = dict(metadata["config"])
    for key in ("storage_path", "log_max_bytes", "log_backup_count", "disk_warning_mb", "headband_ports", "simulation_seed"):
        config.pop(key, None)
    body = {"config": config, **{k: metadata.get(k) for k in ("algorithm", "activity", "duration", "distance", "references", "bindings")}}
    return hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()[:16]


def history_rows(path, player_id=None, date_from=None, date_to=None, condition=None, limit=50):
    if date_from:
        date_from = date.fromisoformat(date_from).isoformat()
    if date_to:
        date_to = (date.fromisoformat(date_to) + timedelta(days=1)).isoformat()
    rows = list_sessions(path, player_id, date_from, date_to, 200)
    with closing(_read_only(path)) as db:
        result = []
        for row in rows:
            metadata = db.execute("SELECT json FROM configs WHERE session_id=?", (row["session_id"],)).fetchone()
            if not metadata:
                continue
            metadata = json.loads(metadata[0])
            row["condition"] = conditions(metadata)
            row["settings"] = {k: metadata.get(k) for k in ("duration", "distance", "references")}
            row["settings"]["session_kind"] = metadata["config"]["session_kind"]
            if condition and row["condition"] != condition:
                continue
            row["players"] = [{"player_id": pid, **json.loads(stats)} for pid, stats in db.execute(
                "SELECT p.player_id,st.json FROM participants p JOIN statistics st ON st.session_id=p.session_id AND st.lane=p.lane WHERE p.session_id=? ORDER BY p.lane", (row["session_id"],))]
            result.append(row)
            if len(result) >= max(1, min(limit, 200)):
                break
        return result


def thin(points, size=1600):
    if len(points) <= size:
        return points
    # Preserve extrema and a missing marker in each bucket. No stats use this.
    width = max(1, (len(points) + size // 4 - 1) // (size // 4))
    result = []
    for start in range(0, len(points), width):
        bucket = points[start:start + width]
        indices = {0, len(bucket) - 1}
        valid = [(i, p[1]) for i, p in enumerate(bucket) if p[1] is not None]
        if valid:
            indices.update([min(valid, key=lambda x: x[1])[0], max(valid, key=lambda x: x[1])[0]])
        missing = next((i for i, p in enumerate(bucket) if p[1] is None), None)
        if missing is not None:
            indices.add(missing)
        result.extend(bucket[i] for i in sorted(indices))
    return result


def report_data(path, sid):
    from ai.worker import read_analysis
    report = read_report(path, sid)
    report["analysis"] = read_analysis(path, sid)
    with closing(_read_only(path)) as db:
        status = db.execute("SELECT status,end_reason FROM sessions WHERE id=?", (sid,)).fetchone()
        if status and status[1] == 'process_restart':
            report['base']['state'], report['base']['reason'] = status
        metadata = json.loads(db.execute("SELECT json FROM configs WHERE session_id=?", (sid,)).fetchone()[0])
        events = [json.loads(row[0]) for row in db.execute("SELECT details FROM events WHERE session_id=? ORDER BY t,id", (sid,))]
        samples = [json.loads(row[0]) for row in db.execute("SELECT facts FROM samples WHERE session_id=? ORDER BY t,id", (sid,))]
    source = "模拟样本" if metadata["config"]["mode"] == "simulation" else "设备样本"
    report.update(config=metadata, events=events, condition=conditions(metadata), charts=[], measurement_note=f"原始 Attention 来自{source}。按各自接收时间绘图，不按行号对齐；竞速位置为虚拟赛程。")
    end = report["base"].get("now", 0)
    timeline = []
    for event in events:
        if event.get("event") in ("state_transition", "device_transition"):
            timeline.append((event.get("t", end), 0, event))
    for sample in samples:
        timeline.append((sample["t"], 1, sample))
    timeline.sort(key=lambda item: (item[0], item[1]))
    timeout = metadata["config"]["data_timeout"]
    for lane in range(1, metadata["config"]["players"] + 1):
        points, bins = [], [0.] * 5
        raw, smoothed, expires, running, last = None, None, 0., False, 0.
        for t, kind, value in timeline + [(end, 2, {})]:
            if running and raw is not None:
                duration = max(0, min(t, expires) - last)
                bins[min(4, int(raw // 20))] += duration
                if last < expires < t:
                    points.append([expires, None, None])
            last = t
            if kind == 0:
                if value["event"] == "state_transition":
                    was_running = running
                    running = value.get("new") == "running"
                    if running and expires > t and raw is not None:
                        points.append([t, raw, smoothed])
                    elif was_running:
                        points.append([t, None, None])
                elif value.get("lane") == lane and value.get("new") != "valid":
                    raw = None
                    points.append([t, None, None])
            elif kind == 1 and value["lane"] == lane:
                raw = value["raw"] if value["valid"] else None
                smoothed = value.get("smoothed")
                expires = value["source_t"] + timeout
                points.append([t, raw if running else None, smoothed if running and raw is not None else None])
        report["charts"].append({"lane": lane, "points": thin(points), "full_point_count": len(points),
                                  "distribution_seconds": bins, "valid_seconds": sum(bins),
                                  "labels": ["0–<20", "20–<40", "40–<60", "60–<80", "80–100"]})
    return report
