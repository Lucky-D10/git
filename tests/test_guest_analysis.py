import json
import sqlite3
import tempfile
import threading
import time
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from analytics.report import features, build_report
from ai.provider import ProviderConfig, ProviderError, generate
from ai.validator import validate
from ai.worker import AnalysisWorker, read_analysis
from backend.service import BackendService
from backend.replay import replay_session
from settings import Config
from web.app import create_app
from fastapi.testclient import TestClient


class FeatureTests(unittest.TestCase):
    def test_irregular_intervals_are_time_weighted_and_missing_not_zero(self):
        base = {"elapsed": 10, "now": 12}
        meta = {"references": [50], "config": {"data_timeout": 4}}
        events = [{"t": 0, "event": "state_transition", "new": "running"},
                  {"t": 4, "event": "state_transition", "new": "paused"},
                  {"t": 6, "event": "state_transition", "new": "running"},
                  {"t": 12, "event": "state_transition", "new": "finished"}]
        samples = [{"t": t, "source_t": t, "raw": v, "valid": True, "lane": 1} for t, v in [(0, 20), (1, 80), (6, 60)]]
        m = features(base, meta, samples, events, 1)
        self.assertAlmostEqual(m["valid_seconds"], 8)
        self.assertAlmostEqual(m["coverage"], .8)
        self.assertAlmostEqual(m["weighted_average"], 62.5)
        self.assertAlmostEqual(m["target_ratio"], 7/8)
        self.assertEqual(m["best_streak"], 4)
        self.assertEqual(m["target_bouts"], 2)
        self.assertEqual(m["missing_seconds_by_reason"], {"stale": 2})
        self.assertAlmostEqual(sum(s["valid_seconds"] for s in m["segments"]), 8)

    def test_invalid_event_breaks_streak_without_new_sample(self):
        m = features({"elapsed": 8, "now": 8}, {"references": [50], "config": {"data_timeout": 20}},
                     [{"t": t, "source_t": t, "raw": 90, "valid": True, "lane": 1} for t in [0, 5]],
                     [{"t": 0, "event": "state_transition", "new": "running"},
                      {"t": 3, "event": "device_transition", "lane": 1, "new": "not_worn"},
                      {"t": 8, "event": "state_transition", "new": "finished"}], 1)
        self.assertEqual(m["valid_seconds"], 6)
        self.assertEqual(m["best_streak"], 3)
        self.assertEqual(m["target_bouts"], 2)
        self.assertEqual(m["missing_seconds_by_reason"], {"not_worn": 2})


class GuestAnalysisTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.now = [time.monotonic()]
        self.config = Config(mode="simulation", players=2, countdown_seconds=.01, data_timeout=2,
                             storage_flush_seconds=.01, storage_max_lag_seconds=1000,
                             storage_path=str(Path(self.folder.name)/"test.sqlite3"))
        self.service = BackendService(self.config, duration=12, references=[50, 50], clock=lambda: self.now[0])
        self.addCleanup(self.service.stop)
        self.worker = AnalysisWorker(self.service.store.path, ProviderConfig())
        self.sequence = 0

    def step(self, delta=0):
        self.now[0] += delta
        self.service.step(self.now[0])

    def command(self, action, **options):
        self.service.submit_intent(action, **options)
        self.step()

    def frame(self, value=70):
        self.sequence += 1
        for lane in (1, 2):
            self.service.submit_frame(dict(lane=lane, raw=value, sequence=self.sequence,
                                           received=self.now[0], generation=1, connected=True, worn=True, state="normal"), absolute=True)
        self.step()

    def finish_round(self, value=70):
        self.frame(value)
        self.command("start")
        self.step(.02)
        for _ in range(12):
            self.now[0] += 1
            self.frame(value)
        self.assertEqual(self.service.engine.state, "finished")
        self.wait_saved()
        return self.service.session_id, list(self.service.participant_ids)

    def wait_saved(self):
        end = time.monotonic()+3
        while time.monotonic() < end:
            if self.service.snapshot()["saved"]:
                return
            time.sleep(.01)
        self.fail("records were not committed")

    def drain(self):
        for _ in range(30):
            if not self.worker.process_one():
                break

    def test_new_visitors_and_continue_lane_swap_have_distinct_participants(self):
        sid, pids = self.finish_round()
        visits = list(self.service.visit_ids)
        self.drain()
        self.command("prepare", visit_action="continue", continuing_lanes=[2, 1], references=[50, 50])
        self.assertEqual(self.service.visit_ids, visits[::-1])
        self.assertNotEqual(pids, self.service.participant_ids)
        sid2, _ = self.finish_round(80)
        self.drain()
        reports = read_analysis(self.service.store.path, sid2)
        self.assertTrue(all(r["scope"] == "same_visit" for r in reports))
        self.assertTrue(all(r["comparison"]["session_id"] == sid for r in reports))
        self.command("prepare", visit_action="new")
        self.assertFalse(set(visits) & set(self.service.visit_ids))
        sid3, _ = self.finish_round()
        self.drain()
        self.assertTrue(all(r["scope"] == "single_session" for r in read_analysis(self.service.store.path, sid3)))

    def test_one_continues_other_is_new_and_duplicate_is_rejected(self):
        self.finish_round()
        old = list(self.service.visit_ids)
        sid = self.service.session_id
        self.command("prepare", visit_action="continue", continuing_lanes=[1, 1])
        self.assertEqual(self.service.session_id, sid)
        self.command("prepare", visit_action="continue", continuing_lanes=[2, 0])
        self.assertEqual(self.service.visit_ids[0], old[1])
        self.assertNotIn(self.service.visit_ids[1], old)

    def test_finish_visit_revokes_report_export_and_back_navigation(self):
        sid, _ = self.finish_round()
        client = TestClient(create_app(self.service, staff_pin="test-secret"))
        self.addCleanup(client.close)
        self.assertEqual(client.get(f"/api/sessions/{sid}/report").status_code, 200)
        from backend.storage import export_session
        export_session(self.service.store.path, sid, Path(self.service.store.path).parent / "exports")
        self.assertEqual(client.get(f"/api/download/{sid}.json").status_code, 200)
        self.command("finish_visit")
        self.assertEqual(client.get(f"/api/sessions/{sid}/report").status_code, 403)
        self.assertEqual(client.get(f"/api/download/{sid}.json").status_code, 403)
        self.assertEqual(client.post(f"/api/sessions/{sid}/export", json={}, headers={"x-focus-client": "web"}).status_code, 403)
        self.assertEqual(client.get("/api/sessions").json()["sessions"], [])
        self.assertEqual(client.get("/api/players").json()["players"], [])
        snapshot = client.get("/api/session").json()["snapshot"]
        self.assertEqual(snapshot["visit_ids"], [])
        self.assertEqual(snapshot["elapsed"], 0)
        self.assertTrue(all(p["raw"] is None and p["history"] == [] for p in snapshot["players"]))
        self.command("prepare", visit_action="continue")
        self.assertEqual(self.service.session_id, sid)

    def test_staff_access_expires_on_handoff_and_guests_cannot_be_impersonated(self):
        sid, _ = self.finish_round()
        from web.access import ReportAccess
        from starlette.requests import Request
        access = ReportAccess(self.service, pin="staff-123")
        token = access.unlock("staff-123")
        request = Request({"type": "http", "headers": [(b"x-focus-staff", token.encode())]})
        self.assertTrue(access.staff(request))
        old = list(self.service.player_ids)
        self.command("prepare", player_ids=old)
        self.assertEqual(sid, self.service.session_id)
        self.command("finish_visit")
        self.assertFalse(access.staff(request))

    def test_new_jobs_visible_only_after_committed_final_report(self):
        self.frame()
        self.command("start")
        self.step(.1)
        self.assertFalse(self.worker.process_one())
        self.command("end")
        self.wait_saved()
        self.drain()
        reports = read_analysis(self.service.store.path, self.service.session_id)
        self.assertTrue(all(not r["eligible"] for r in reports))
        self.assertTrue(replay_session(self.service.store.path, self.service.session_id)["matched"])

    def test_completed_analysis_is_cached_and_survives_base_rewrite(self):
        sid, _ = self.finish_round()
        self.drain()
        original = read_analysis(self.service.store.path, sid)
        self.command("pause")  # rejected intent still flushes a terminal checkpoint
        self.wait_saved()
        self.assertFalse(self.worker.process_one())
        self.assertEqual(original, read_analysis(self.service.store.path, sid))
        rebuilt = build_report(self.service.store.path, sid, original[0]["participant_id"])
        self.assertEqual(original[0]["input_hash"], rebuilt["input_hash"])

    def cloud(self, provider):
        return AnalysisWorker(self.service.store.path, ProviderConfig("deepseek", "test-model", "test-key", allow_simulation=True), provider)

    @staticmethod
    def good_output(config, report):
        return {"summary": "本轮体验回顾", "observations": [
            {"evidence_id": "quality", "text": "本轮有{有效时长}的有效记录，可以一起看看。"},
            {"evidence_id": "target", "text": "最长连续达标是{连续达标}，下一轮可以从这个片段出发。"}],
            "goal_id": report["goal"]["id"], "recommendation_ids": [s["id"] for s in report["suggestions"][:2]],
            "encouragement": "按自己的节奏尝试，没达到目标也没关系。"}

    def test_cloud_result_is_bound_to_old_participant_during_handoff(self):
        sid, pids = self.finish_round()
        entered, release = threading.Event(), threading.Event()
        def slow(config, report):
            entered.set()
            self.assertTrue(release.wait(3))
            return self.good_output(config, report)
        worker = self.cloud(slow)
        worker.process_one(); worker.process_one()  # local templates for both lanes
        thread = threading.Thread(target=worker.process_one)
        thread.start()
        self.assertTrue(entered.wait(3))
        self.command("prepare", visit_action="new")
        release.set(); thread.join(3)
        report = read_analysis(self.service.store.path, sid)[0]
        self.assertEqual(report["source"], "ai")
        self.assertEqual(report["participant_id"], pids[0])
        client = TestClient(create_app(self.service))
        with client:
            self.assertEqual(client.get(f"/api/sessions/{sid}/report").status_code, 403)

    def test_invalid_cloud_output_falls_back_without_changing_metrics(self):
        sid, _ = self.finish_round()
        worker = self.cloud(lambda *_: {"summary": "你的智商是130"})
        worker.process_one(); worker.process_one()
        before = read_analysis(self.service.store.path, sid)[0]["metrics"]
        worker.process_one()
        report = read_analysis(self.service.store.path, sid)[0]
        self.assertEqual(report["ai_status"], "fallback")
        self.assertEqual(report["metrics"], before)
        self.assertEqual(report["source"], "template")

    def test_legacy_queued_reports_do_not_send_incompatible_cloud_requests(self):
        sid, pids = self.finish_round()
        provider = lambda *_: self.fail("legacy report must not call the provider")
        worker = self.cloud(provider)
        worker.process_one(); worker.process_one()
        with closing(sqlite3.connect(self.service.store.path)) as db, db:
            report = json.loads(db.execute("SELECT json FROM analysis_reports WHERE participant_id=?", (pids[0],)).fetchone()[0])
            report.pop("goal")
            db.execute("UPDATE analysis_reports SET json=? WHERE participant_id=?", (json.dumps(report), pids[0]))
        worker.process_one()
        self.assertEqual(read_analysis(self.service.store.path, sid)[0]["ai_status"], "legacy_template")

    def test_network_failure_retries_are_bounded_and_recover_after_restart(self):
        sid, _ = self.finish_round()
        def unavailable(*_):
            raise ProviderError("provider_unavailable")
        worker = self.cloud(unavailable)
        worker.process_one(); worker.process_one(); worker.process_one()
        self.assertEqual(read_analysis(self.service.store.path, sid)[0]["ai_status"], "retrying")
        with closing(sqlite3.connect(self.service.store.path)) as db, db:
            db.execute("UPDATE analysis_jobs SET next_attempt=0")
        restarted = self.cloud(unavailable)
        restarted.process_one()
        self.assertEqual(read_analysis(self.service.store.path, sid)[0]["ai_status"], "fallback")
        with closing(sqlite3.connect(self.service.store.path)) as db:
            self.assertEqual(db.execute("SELECT attempts FROM analysis_jobs ORDER BY rowid LIMIT 1").fetchone()[0], 2)

    def test_changed_target_prevents_same_visit_comparison(self):
        self.finish_round(); self.drain()
        self.command("prepare", visit_action="continue", references=[80, 80])
        sid, _ = self.finish_round(); self.drain()
        self.assertTrue(all(r["scope"] == "single_session" for r in read_analysis(self.service.store.path, sid)))

    def test_validator_rejects_fabricated_evidence_and_history(self):
        sid, pids = self.finish_round()
        report = build_report(self.service.store.path, sid, pids[0])
        output = self.good_output(None, report)
        output["observations"][0]["evidence_id"] = "not-real"
        with self.assertRaises(ValueError):
            validate(output, report)
        output = self.good_output(None, report)
        output["summary"] = "比上次进步了"
        with self.assertRaises(ValueError):
            validate(output, report)


class ProviderTests(unittest.TestCase):
    def test_deepseek_payload_excludes_identifiers_and_handles_json(self):
        import httpx
        requests = []
        def handle(request):
            requests.append(json.loads(request.content))
            return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {"content": '{"summary":"测试"}'}}]})
        actual_client = httpx.Client
        with patch("httpx.Client", side_effect=lambda **kwargs: actual_client(transport=httpx.MockTransport(handle), **kwargs)):
            result = generate(ProviderConfig("deepseek", "test", "SECRET"),
                              {"scope": "single_session", "mode": "simulation", "facts": [], "suggestions": [], "limitations": [], "goal": {}, "focus": "test", "display_values": {}, "participant_id": "PRIVATE", "visit_id": "PRIVATE", "raw_eeg": [1, 2]})
        self.assertEqual(result["summary"], "测试")
        body = json.dumps(requests)
        self.assertNotIn("PRIVATE", body)
        self.assertNotIn("SECRET", body)
        self.assertNotIn("raw_eeg", body)
        self.assertEqual(requests[0]["response_format"], {"type": "json_object"})


if __name__ == "__main__":
    unittest.main()
