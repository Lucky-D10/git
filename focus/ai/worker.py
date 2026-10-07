"""Persisted post-commit jobs. One worker, short writes, no control-thread I/O."""
from contextlib import closing
import json
import logging
import sqlite3
import threading
import time

from .provider import ProviderConfig, PROMPT_VERSION, generate
from .validator import VALIDATION_FEEDBACK, ValidationError, validate

SCHEMA = """
CREATE TABLE IF NOT EXISTS analysis_jobs(
 participant_id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES sessions(id),
 status TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0, next_attempt REAL NOT NULL DEFAULT 0,
 error TEXT, updated_at REAL NOT NULL DEFAULT 0);
CREATE INDEX IF NOT EXISTS analysis_job_status ON analysis_jobs(status,next_attempt);
CREATE TABLE IF NOT EXISTS analysis_reports(
 participant_id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES sessions(id),
 input_hash TEXT NOT NULL, version TEXT NOT NULL, json TEXT NOT NULL);
"""


class AnalysisWorker:
    def __init__(self, path, config=None, provider=None):
        self.path = str(path)
        self.config = config or ProviderConfig.from_env()
        self.provider = provider or generate
        self.stopping = threading.Event()
        self.thread = threading.Thread(target=self._run, name="focus-analysis", daemon=True)

    def start(self):
        self.thread.start()

    def stop(self):
        self.stopping.set()
        if self.thread.is_alive():
            self.thread.join(timeout=self.config.timeout + 4)

    def _connect(self):
        return sqlite3.connect(self.path, timeout=.1)

    def _run(self):
        while not self.stopping.is_set():
            try:
                if not self.process_one():
                    self.stopping.wait(.3)
            except sqlite3.Error:
                self.stopping.wait(.5)
            except Exception:
                logging.getLogger("focus.analysis").exception("分析任务故障；训练与基础记录不受影响")
                self.stopping.wait(1)

    def _save(self, db, report, status, error=None):
        from backend.storage import dumps
        db.execute("INSERT INTO analysis_reports VALUES(?,?,?,?,?) ON CONFLICT(participant_id) DO UPDATE SET input_hash=excluded.input_hash,version=excluded.version,json=excluded.json",
                   (report["participant_id"], report["session_id"], report["input_hash"], report["version"], dumps(report)))
        db.execute("UPDATE analysis_jobs SET status=?,error=?,updated_at=? WHERE participant_id=?",
                   (status, error, time.time(), report["participant_id"]))

    def process_one(self):
        from analytics.report import build_report
        with closing(self._connect()) as db:
            # Always finish local templates before spending time on cloud requests.
            job = db.execute("SELECT j.participant_id,j.session_id FROM analysis_jobs j JOIN reports r ON r.session_id=j.session_id WHERE j.status='pending' AND r.status='ready' ORDER BY j.rowid LIMIT 1").fetchone()
            if job:
                try:
                    report = build_report(self.path, job[1], job[0])
                except (ValueError, KeyError, TypeError, ArithmeticError):
                    with db:
                        db.execute("UPDATE analysis_jobs SET status='failed',error='invalid_record' WHERE participant_id=?", (job[0],))
                    return True
                queued = db.execute("SELECT COUNT(*) FROM analysis_jobs WHERE status IN ('ai_pending','running')").fetchone()[0]
                reason = "disabled"
                if self.config.provider != "disabled" and not self.config.enabled:
                    reason = "not_configured"
                elif not report["eligible"]:
                    reason = "insufficient_data"
                elif report["mode"] == "simulation" and not self.config.allow_simulation:
                    reason = "simulation_local"
                elif self.config.enabled:
                    reason = "pending" if queued < 8 else "busy_fallback"
                report.update(ai_status=reason, provider=self.config.provider, model=self.config.model, prompt_version=PROMPT_VERSION)
                with db:
                    self._save(db, report, "ai_pending" if reason == "pending" else "template")
                return True
            # 'running' with an expired lease resumes after a process restart.
            job = db.execute("SELECT j.participant_id,a.json,j.attempts,j.error FROM analysis_jobs j JOIN analysis_reports a ON a.participant_id=j.participant_id JOIN reports r ON r.session_id=j.session_id WHERE j.status IN ('ai_pending','running') AND j.next_attempt<=? AND r.status='ready' ORDER BY j.rowid LIMIT 1", (time.time(),)).fetchone()
            if not job:
                return False
            report, attempts = json.loads(job[1]), job[2]
            if "goal" not in report:
                # Old cached reports lack the inputs required by the new prompt.
                report["ai_status"] = "legacy_template"
                with db:
                    self._save(db, report, "template")
                return True
            if attempts >= 2 or not self.config.enabled:
                report["ai_status"] = "fallback"
                with db:
                    self._save(db, report, "template", "attempt_limit_or_disabled")
                return True
            with db:
                db.execute("UPDATE analysis_jobs SET status='running',attempts=attempts+1,next_attempt=? WHERE participant_id=?", (time.time()+self.config.timeout+5, job[0]))
        # No database connection/transaction held during the external call.
        try:
            request_report = dict(report)
            if job[3] in VALIDATION_FEEDBACK:
                request_report["_validation_error"] = job[3]
            output = validate(self.provider(self.config, request_report), report)
            report.update(output, source="ai", ai_status="ready", model=self.config.model, provider=self.config.provider)
            status, error = "ready", None
        except Exception as exc:
            # Known error categories only, never exception messages containing secrets.
            from .provider import ProviderError
            error = str(exc) if isinstance(exc, (ProviderError, ValueError)) and str(exc) in {"provider_unavailable", "provider_incomplete", "provider_limit", "invalid_schema", "unsupported_claim", "unsupported_history", "unknown_evidence", "invalid_observations", "unknown_recommendation"} else "provider_failed"
            retry = (error == "provider_unavailable" or error in VALIDATION_FEEDBACK) and attempts == 0
            if isinstance(exc, ValidationError):
                logging.getLogger("focus.analysis").warning(
                    "AI validation rejected: code=%s field=%s rule=%s", error, exc.field, exc.rule)
            report["ai_status"] = "retrying" if retry else "fallback"
            status = "ai_pending" if retry else "template"
        with closing(self._connect()) as db, db:
            self._save(db, report, status, error)
        return True


def read_analysis(path, sid):
    from backend.storage import _read_only
    with closing(_read_only(path)) as db:
        rows = db.execute("SELECT p.participant_id,p.lane,j.status,a.json FROM participant_identity p LEFT JOIN analysis_jobs j ON j.participant_id=p.participant_id LEFT JOIN analysis_reports a ON a.participant_id=p.participant_id WHERE p.session_id=? ORDER BY p.lane", (sid,)).fetchall()
    results = []
    for pid, lane, status, text in rows:
        report = json.loads(text) if text else {"participant_id": pid, "lane": lane, "ai_status": status or "not_available", "source": "template"}
        if status in ("pending", "ai_pending", "running") and report.get("ai_status") != "retrying":
            report["ai_status"] = status
        results.append(report)
    return results
