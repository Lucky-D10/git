import json
from pathlib import Path
import tempfile
import unittest

from backend.service import BackendService, DeviceFrame
from settings import Config
from web.runtime import OperatorLease


class LeaseTests(unittest.TestCase):
    def test_only_one_operator_and_expiry_requires_reclaim(self):
        now = [0.0]
        lease = OperatorLease(timeout=2, clock=lambda: now[0])
        first = lease.claim()
        self.assertTrue(first)
        self.assertIsNone(lease.claim())
        self.assertTrue(lease.heartbeat(first))
        now[0] = 2.1
        self.assertFalse(lease.alive())
        second = lease.claim()
        self.assertTrue(second)
        self.assertNotEqual(first, second)


class WebContractTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.now = [0.0]
        self.lease = OperatorLease(timeout=2, clock=lambda: self.now[0])
        config = Config(mode="simulation", storage_path=str(Path(self.folder.name) / "web.sqlite3"),
                        countdown_seconds=.1, web_push_interval=.1, storage_max_lag_seconds=10)
        self.service = BackendService(config, duration=2, clock=lambda: self.now[0], operator=self.lease)
        self.addCleanup(self.service.stop)

    def frame(self, lane, sequence=1):
        return DeviceFrame(lane, 90, sequence, self.now[0], 0, True, True, "normal")

    def step(self, t):
        self.now[0] = t
        self.service.step(t)

    def test_action_receipt_is_idempotent_and_requires_operator(self):
        sid = self.service.session_id
        denied = self.service.request("denied", "start", sid, "wrong")
        self.step(0)
        self.assertFalse(denied.result()["ok"])
        token = self.lease.claim()
        for lane in (1, 2):
            self.service.submit_frame(self.frame(lane))
        first = self.service.request("start-1", "start", sid, token)
        self.step(0.01)
        result1 = first.result()
        retry = self.service.request("start-1", "start", sid, token)
        self.step(0.02)
        self.assertEqual(result1, retry.result())
        self.assertEqual(self.service.engine.state, "countdown")

    def test_operator_timeout_pauses_running_session(self):
        token = self.lease.claim()
        sid = self.service.session_id
        for lane in (1, 2):
            self.service.submit_frame(self.frame(lane))
        start = self.service.request("start-2", "start", sid, token)
        self.step(.01)
        self.assertTrue(start.result()["ok"])
        self.step(.2)
        self.assertEqual(self.service.engine.state, "running")
        self.now[0] = 2.1
        self.step(2.1)
        self.assertEqual(self.service.engine.state, "paused")
        self.assertEqual(self.service.engine.lanes[0].power, 0)

    def test_static_page_is_local_and_800x480_friendly(self):
        html = Path("web/static/index.html").read_text(encoding="utf-8")
        script = Path("web/static/app.js").read_text(encoding="utf-8")
        self.assertIn("/static/echarts.min.js", html)
        self.assertIn('type="module" src="/static/app.js"', html)
        self.assertIn("setOption", Path("web/static/js/charts.js").read_text(encoding="utf-8"))
        self.assertNotIn("http://", html + script)
        self.assertNotIn("https://", html + script)

    def test_emergency_bypasses_full_queue_and_cancels_queued_reset(self):
        from backend.replay import replay_session
        token = self.lease.claim()
        sid = self.service.session_id
        outputs = []
        self.service.output = lambda state: outputs.append(state)
        for lane in (1, 2):
            self.service.submit_frame(self.frame(lane))
        self.service.request("start", "start", sid, token)
        self.step(.01)
        self.step(.2)
        self.assertEqual(self.service.engine.state, "running")
        queued = [self.service.request(str(i), "reset", sid, token, confirmed=True) for i in range(32)]
        stop = self.service.request("urgent", "emergency", sid, token)
        self.service.submit_frame(self.frame(1, 2))
        outputs.clear()
        self.step(.25)
        self.assertTrue(stop.result()["ok"])
        self.assertEqual(self.service.engine.safety, "emergency_locked")
        self.assertTrue(all(f.result()["reason"] == "superseded_by_emergency" for f in queued))
        self.assertTrue(outputs)
        self.assertTrue(all(p["power"] == 0 for s in outputs for p in s["players"]))
        self.service.stop()
        self.assertTrue(replay_session(self.service.store.path, sid)["matched"])

    def test_unauthorized_emergency_cannot_fill_priority_queue(self):
        for i in range(16):
            result = self.service.request(str(i), "emergency", self.service.session_id, "wrong")
            self.assertEqual(result.result()["reason"], "operator_required")
        self.assertEqual(self.service.urgent.qsize(), 0)

    def test_new_operator_does_not_hide_expired_previous_operator(self):
        token = self.lease.claim()
        for lane in (1, 2):
            self.service.submit_frame(self.frame(lane))
        self.service.request("start", "start", self.service.session_id, token)
        self.step(.01)
        self.step(.2)
        self.now[0] = 2.01
        self.assertTrue(self.lease.claim())
        self.step(2.01)
        self.assertEqual(self.service.engine.state, "paused")

    def test_idempotency_conflict_and_cancelled_request_never_mutate(self):
        token = self.lease.claim()
        sid = self.service.session_id
        first = self.service.request("same", "prepare", sid, token, players=1)
        self.step(.1)
        self.assertTrue(first.result()["ok"])
        conflicting = self.service.request("same", "prepare", sid, token, players=2)
        self.step(.2)
        self.assertEqual(conflicting.result()["reason"], "idempotency_conflict")
        cancelled = self.service.request("cancel", "emergency", self.service.session_id, token)
        cancelled.cancel()
        self.step(.3)
        self.assertEqual(self.service.engine.safety, "inhibited")


if __name__ == "__main__":
    unittest.main()
