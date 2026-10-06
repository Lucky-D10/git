"""Time-weighted features from full records, with explicit missing intervals."""
import hashlib
import json
import math
from contextlib import closing

from backend.storage import _read_only

VERSION = "guest-analysis-v1"
RULE_VERSION = "guest-rules-v2"
MIN_VALID_SECONDS = 10.0
MIN_COVERAGE = .8


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def features(base, metadata, samples, events, lane):
    """Integrate held readings only while running and before their expiry.

    Zero-order hold matches the engine. Never interpolate across a missing interval.
    Segment boundaries use active time, so pauses cannot change segment membership.
    """
    total = float(base.get("elapsed", 0))
    reference = metadata["references"][lane-1]
    timeout = metadata["config"]["data_timeout"]
    timeline = [(e["t"], 0, e) for e in events if e.get("event") in ("state_transition", "device_transition")]
    timeline += [(s["t"], 1, s) for s in samples if s["lane"] == lane]
    timeline.sort(key=lambda row: (row[0], row[1]))
    end = float(base.get("now", 0))
    timeline.append((end, 2, {}))
    raw, expires, running, last, elapsed = None, 0., False, 0., 0.
    valid = target = weighted = squared = streak = best = 0.
    count = bouts = 0
    values, missing = [], {}
    reason = "missing_attention"
    segments = [{"valid_seconds": 0., "weighted": 0., "target_seconds": 0.} for _ in range(3)]
    for stamp, kind, value in timeline:
        t = max(last, min(end, float(stamp)))
        dt = t - last
        if running and dt > 0:
            good = max(0., min(t, expires) - last) if raw is not None else 0.
            if good:
                valid += good
                weighted += raw * good
                squared += raw * raw * good
                values.append((raw, good))
                if raw >= reference:
                    if streak == 0:
                        bouts += 1
                    target += good
                    streak += good
                    best = max(best, streak)
                else:
                    streak = 0.
                for i, segment in enumerate(segments):
                    overlap = max(0., min(elapsed + good, total * (i+1)/3) - max(elapsed, total*i/3))
                    segment["valid_seconds"] += overlap
                    segment["weighted"] += raw * overlap
                    segment["target_seconds"] += overlap if raw >= reference else 0
            gap = max(0., dt - good)
            if gap:
                cause = "stale" if raw is not None else reason
                missing[cause] = missing.get(cause, 0.) + gap
                streak = 0.
            elapsed += dt
        last = t
        if kind == 0:
            if value["event"] == "state_transition":
                running = value.get("new") == "running"
                if not running:
                    streak = 0.
            elif value.get("lane") == lane and value.get("new") != "valid":
                raw, reason, streak = None, value.get("new", "unknown"), 0.
        elif kind == 1:
            candidate = value.get("raw")
            good_value = value.get("valid") and type(candidate) in (int, float) and math.isfinite(candidate) and 0 <= candidate <= 100
            raw = float(candidate) if good_value else None
            reason = value.get("reason", "unknown")
            expires = value.get("source_t", t) + timeout
            if running and good_value:
                count += 1
            if raw is None or raw < reference:
                streak = 0.
    values.sort()
    def quantile(q):
        cumulative = 0.
        for value, weight in values:
            cumulative += weight
            if cumulative >= valid*q:
                return value
        return None
    average = weighted/valid if valid else None
    for segment in segments:
        duration = segment["valid_seconds"]
        segment["average"] = segment.pop("weighted") / duration if duration else None
        segment["coverage"] = min(1., duration/(total/3)) if total else 0.
    return {"active_seconds": total, "valid_seconds": valid,
            "coverage": min(1., valid/total) if total else 0., "sample_count": count,
            "weighted_average": average, "median": quantile(.5),
            "iqr": quantile(.75)-quantile(.25) if valid else None,
            "standard_deviation": math.sqrt(max(0., squared/valid-average**2)) if valid else None,
            "target_ratio": target/valid if valid else None, "target_seconds": target,
            "best_streak": best, "target_bouts": bouts, "reference": reference,
            "segments": segments, "missing_seconds_by_reason": missing}


def condition(metadata, lane):
    c = metadata["config"]
    return digest({"activity": metadata["activity"], "duration": metadata["duration"],
                   "distance": metadata["distance"], "reference": metadata["references"][lane-1],
                   "algorithm": metadata["algorithm"],
                   "config": {k: c.get(k) for k in ("mode", "players", "session_kind", "zero_is_valid", "data_timeout", "smoothing_seconds", "start_threshold", "high_focus_threshold")}})


def build_report(path, sid, participant_id):
    with closing(_read_only(path)) as db:
        identity = db.execute("SELECT lane,visit_id,identity_kind FROM participant_identity WHERE session_id=? AND participant_id=?", (sid, participant_id)).fetchone()
        row = db.execute("SELECT r.status,r.base_json,c.json,s.started_utc FROM reports r JOIN configs c ON c.session_id=r.session_id JOIN sessions s ON s.id=r.session_id WHERE r.session_id=?", (sid,)).fetchone()
        if not identity or not row or row[0] != "ready":
            raise ValueError("report_not_ready")
        lane, visit_id, kind = identity
        base, metadata = json.loads(row[1]), json.loads(row[2])
        samples = [json.loads(r[0]) for r in db.execute("SELECT facts FROM samples WHERE session_id=? AND lane=? ORDER BY t,id", (sid, lane))]
        events = [json.loads(r[0]) for r in db.execute("SELECT details FROM events WHERE session_id=? ORDER BY t,id", (sid,))]
        metrics = features(base, metadata, samples, events, lane)
        eligible = base["state"] == "finished" and metrics["valid_seconds"] >= MIN_VALID_SECONDS and metrics["coverage"] >= MIN_COVERAGE and metrics["sample_count"] >= 2
        key = condition(metadata, lane)
        previous = None
        if eligible and visit_id:
            # Only earlier, complete reports for THIS visit; lane changes are allowed.
            rows = db.execute("SELECT a.json FROM analysis_reports a JOIN participant_identity p ON p.participant_id=a.participant_id JOIN sessions s ON s.id=p.session_id WHERE p.visit_id=? AND s.started_utc<? AND s.complete=1 AND s.status='finished' ORDER BY s.started_utc DESC LIMIT 30", (visit_id, row[3])).fetchall()
            for (text,) in rows:
                candidate = json.loads(text)
                if candidate.get("eligible") and candidate.get("condition") == key and candidate.get("version") == VERSION:
                    previous = candidate
                    break
    facts = [{"id": "quality", "text": "本轮有效记录 %.1f 秒，数据覆盖率 %.1f%%。" % (metrics["valid_seconds"], metrics["coverage"]*100)}]
    limitations = ["仅描述本次设备指标，不代表智力、学习成绩或健康诊断。"]
    if metadata["config"]["mode"] == "simulation":
        limitations.insert(0, "模拟数据，仅用于演示分析流程。")
    if not eligible:
        limitations.append("记录过短、覆盖不足或体验中断，本次仅提供基础事实。")
    else:
        facts.append({"id": "target", "text": "本轮目标为 %.0f，达标时间占有效时间 %.1f%%，最长连续达标 %.1f 秒。" % (metrics["reference"], metrics["target_ratio"]*100, metrics["best_streak"])})
        facts.append({"id": "level", "text": "按有效时长加权的平均读数为 %.1f，四分位距为 %.1f。" % (metrics["weighted_average"], metrics["iqr"])})
        if all(s["coverage"] >= MIN_COVERAGE for s in metrics["segments"]):
            facts.append({"id": "segments", "text": "前、中、后段平均读数分别为 %.1f、%.1f、%.1f。" % tuple(s["average"] for s in metrics["segments"])})
    comparison = None
    if previous:
        delta = (metrics["target_ratio"]-previous["metrics"]["target_ratio"])*100
        comparison = {"session_id": previous["session_id"], "target_ratio_delta_pp": delta}
        facts.append({"id": "comparison", "text": "与本次到访上一轮同条件合格记录相比，达标率变化为 %+.1f 个百分点。" % delta})
        limitations.append("两轮差异只是观察结果，不能证明由某条建议造成。")
    else:
        limitations.append("暂无本次到访的同条件合格记录，不生成历史进步结论。")
    from .coaching import coaching
    guidance = coaching(metrics, eligible, facts, comparison)
    result = {"session_id": sid, "participant_id": participant_id, "lane": lane,
              "visit_id": visit_id, "identity_kind": kind, "version": VERSION, "rule_version": RULE_VERSION,
              "condition": key, "mode": metadata["config"]["mode"], "eligible": eligible,
              "scope": "same_visit" if previous else "single_session", "metrics": metrics,
              "comparison": comparison, "facts": facts, "limitations": limitations,
              "source": "template", "ai_status": "disabled", **guidance}
    result["input_hash"] = digest(result)
    return result
