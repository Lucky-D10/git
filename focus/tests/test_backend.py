import sqlite3
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace
import unittest

from backend.engine import Engine
from backend.service import BackendService, DeviceFrame
from settings import Config


def config(directory, **overrides):
    values = dict(mode="simulation", players=2, data_timeout=.2,
                  countdown_seconds=.1, storage_path=str(Path(directory) / "focus.sqlite3"))
    values.update(overrides)
    return Config(**values)


def normal(engine, lane, seq, raw=80, t=None):
    t = engine.now if t is None else t
    return engine.feed(lane, {"raw": raw, "sequence": seq, "received": t,
                              "generation": 0, "connected": True, "worn": True, "state": "normal"})


class EngineTests(unittest.TestCase):
    def test_status_only_baseline_updates_do_not_create_fresh_samples(self):
        c = config(tempfile.mkdtemp(), calibration_timeout=2)
        e = Engine(c, "status-baseline", "training")
        status = {"kind": "status", "connected": True, "worn": True,
                  "state": "baseline", "reason": "awaiting_new_frame",
                  "calibration_progress": .25, "device_baseline": 50}
        e.feed(1, status)
        e.advance(1)
        e.feed(1, {**status, "calibration_progress": .5})
        lane = e.snapshot()["players"][0]
        self.assertEqual(lane["calibration_progress"], .5)
        self.assertEqual(lane["calibration_since"], 0)
        self.assertFalse(lane["valid"])
        self.assertEqual(lane["sample_count"], 0)
        self.assertIsNone(lane["sequence"])
        self.assertFalse(e.intent("start", "status-baseline"))
        e.advance(2)
        self.assertEqual(e.snapshot()["players"][0]["reason"], "calibration_timeout")
        e.feed(1, {**status, "state": "off", "worn": False})
        e.advance(3)
        e.feed(1, status)
        self.assertEqual(e.snapshot()["players"][0]["calibration_since"], 3)

    def test_snapshot_exposes_session_thresholds_for_display(self):
        c = config(tempfile.mkdtemp(), start_threshold=25, high_focus_threshold=80)
        e = Engine(c, "display-thresholds", "training", references=[10, 90])
        self.assertEqual(e.snapshot()["attention_thresholds"], [25, 80])
        self.assertEqual([p["reference"] for p in e.snapshot()["players"]], [10, 90])

    def test_race_boost_tracks_threshold_hold_and_interruptions(self):
        c = config(tempfile.mkdtemp(), data_timeout=20, reward_seconds=2,
                   high_focus_threshold=75)
        e = Engine(c, "boost", "racing", distance=1000)
        normal(e, 1, 1, 75); normal(e, 2, 1, 60)
        e.intent("start", "boost"); e.advance(.1)
        first, second = e.snapshot()["players"]
        self.assertTrue(first["boost_active"])
        self.assertEqual(first["boost_progress"], 0)
        self.assertGreater(second["power"], 0)
        self.assertFalse(second["boost_active"])
        e.advance(1.1)
        self.assertAlmostEqual(e.snapshot()["players"][0]["boost_progress"], .5)
        e.advance(3.1)
        self.assertEqual(e.snapshot()["players"][0]["boost_progress"], 1)
        normal(e, 1, 2, 74)
        self.assertFalse(e.snapshot()["players"][0]["boost_active"])
        self.assertEqual(e.snapshot()["players"][0]["boost_progress"], 0)
        normal(e, 1, 3, 100)
        self.assertFalse(e.snapshot()["players"][0]["boost_active"], "smoothed value must also qualify")
        e.advance(4.1); normal(e, 1, 4, 100)
        self.assertTrue(e.snapshot()["players"][0]["boost_active"])
        self.assertEqual(e.snapshot()["players"][0]["boost_progress"], 0)
        e.advance(4.6)
        self.assertAlmostEqual(e.snapshot()["players"][0]["boost_progress"], .25)
        e.intent("pause", "boost")
        self.assertFalse(e.snapshot()["players"][0]["boost_active"])
        e.intent("resume", "boost"); e.advance(4.7)
        self.assertEqual(e.snapshot()["players"][0]["boost_progress"], 0)
        e.advance(25)
        self.assertFalse(e.snapshot()["players"][0]["boost_active"])

    def test_start_pause_resume_and_stale_session_intent_are_headless(self):
        c = config(tempfile.mkdtemp())
        e = Engine(c, "s1", "training", duration=2)
        normal(e, 1, 1); normal(e, 2, 1)
        self.assertFalse(e.intent("start", "old"))
        self.assertTrue(e.intent("start", "s1"))
        e.advance(.1)
        self.assertEqual(e.state, "running")
        e.advance(.2)
        running = e.elapsed
        self.assertTrue(e.intent("pause", "s1"))
        e.advance(10)
        self.assertAlmostEqual(e.elapsed, running)
        normal(e, 1, 2, t=e.now); normal(e, 2, 2, t=e.now)
        self.assertTrue(e.intent("resume", "s1"))

    def test_duplicate_does_not_extend_freshness_and_missing_reason_is_preserved(self):
        c = config(tempfile.mkdtemp())
        e = Engine(c, "s", "training")
        normal(e, 1, 1, t=0)
        e.advance(.19)
        self.assertFalse(normal(e, 1, 1, t=.19))
        self.assertEqual(e.lanes[0].reason, "valid")
        self.assertIn("duplicate", [row.get("reason") for row in e.events])
        e.advance(.21)
        self.assertEqual(e.lanes[0].reason, "stale")
        e.feed(2, {"raw": None, "sequence": 1, "received": e.now, "generation": 0,
                   "connected": True, "worn": True, "state": "normal"})
        self.assertEqual(e.lanes[1].reason, "missing_attention")

    def test_formal_all_signal_loss_aborts_and_emergency_blocks_late_callback(self):
        c = config(tempfile.mkdtemp(), session_kind="formal")
        e = Engine(c, "s", "training")
        normal(e, 1, 1); normal(e, 2, 1); e.intent("start", "s"); e.advance(.1)
        e.intent("emergency", "s")
        self.assertEqual(e.safety, "emergency_locked")
        self.assertFalse(normal(e, 2, 2, t=e.now))
        self.assertEqual(e.lanes[1].power, 0)

    def test_samples_are_lane_specific_and_statistics_need_two_samples(self):
        c = config(tempfile.mkdtemp())
        e = Engine(c, "s", "training")
        normal(e, 1, 1); normal(e, 2, 1); e.intent("start", "s"); e.advance(.1)
        normal(e, 1, 2, 90, e.now); normal(e, 2, 2, 50, e.now); e.advance(.2)
        players = e.snapshot()["players"]
        self.assertIsNone(players[0]["average"])  # only samples received after run count
        normal(e, 1, 3, 80, e.now); e.advance(.25)
        self.assertIsNotNone(e.snapshot()["players"][0]["average"])
        self.assertIsNone(e.snapshot()["players"][1]["average"])


class StorageTests(unittest.TestCase):
    def test_service_persists_without_blocking_and_marks_terminal_session(self):
        with tempfile.TemporaryDirectory() as directory:
            c = config(directory)
            service = BackendService(c, "training", duration=.1)
            service.start()
            service.submit_frame(DeviceFrame(1, 80, 1, connected=True, worn=True, state="normal"))
            service.submit_frame(DeviceFrame(2, 80, 1, connected=True, worn=True, state="normal"))
            service.submit_intent("start")
            time.sleep(.3)
            service.stop()
            self.assertIsNone(service.store.error)
            self.assertTrue(service.snapshot()["saved"])
            db = sqlite3.connect(c.storage_path)
            try:
                self.assertEqual(db.execute("SELECT COUNT(*) FROM sessions").fetchone()[0], 1)
                self.assertGreater(db.execute("SELECT COUNT(*) FROM events").fetchone()[0], 0)
                self.assertEqual(db.execute("SELECT COUNT(*) FROM configs").fetchone()[0], 1)
            finally:
                db.close()

            from backend.replay import replay_session
            replayed = replay_session(c.storage_path, service.session_id)
            self.assertTrue(replayed["matched"])

    def test_unfinished_sessions_are_recovered_as_interrupted(self):
        with tempfile.TemporaryDirectory() as directory:
            c = config(directory)
            path = Path(c.storage_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            with sqlite3.connect(path) as db:
                from backend.storage import SCHEMA
                db.executescript(SCHEMA)
                db.execute("INSERT INTO sessions(id,mode,activity,started_utc,status,complete) VALUES('old','simulation','training','now','running',0)")
                db.commit()
            store = __import__("backend.storage", fromlist=["Store"]).Store(c)
            store.close()
            db = sqlite3.connect(path)
            try:
                self.assertEqual(db.execute("SELECT status,end_reason FROM sessions WHERE id='old'").fetchone(), ("aborted", "process_restart"))
            finally:
                db.close()


if __name__ == "__main__":
    unittest.main()
