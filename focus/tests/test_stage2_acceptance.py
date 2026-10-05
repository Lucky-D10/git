"""Behavioral acceptance: fake-clock controls, real SQLite, injected failures."""
from contextlib import closing
from dataclasses import replace
import json
from pathlib import Path
import sqlite3
import tempfile
import time
import unittest
from unittest.mock import patch

import EEG
from backend.engine import Engine
from backend.hardware import MotorOutput
from backend.replay import replay_session
from backend.service import BackendService, DeviceFrame
from backend.storage import Store, export_session
from settings import Config
from sample_gate import SnapshotGate
from types import SimpleNamespace


def feed(e, lane, seq, raw=80, **changes):
    frame = dict(raw=raw, sequence=seq, received=e.now, generation=0,
                 connected=True, worn=True, state="normal")
    frame.update(changes)
    return e.feed(lane, frame)


def running(kind="experience", players=2, activity="training", **changes):
    c = Config(mode="simulation", players=players, session_kind=kind, countdown_seconds=.1, **changes)
    e = Engine(c, "test", activity, distance=.5)
    for lane in range(1,players+1):
        feed(e,lane,1)
    e.intent("start","test")
    e.advance(.1)
    return e


class TimeAndPolicyTests(unittest.TestCase):
    def test_elapsed_and_power_integral_ignore_display_refresh_rate(self):
        regular, stalled = running(activity="racing"), running(activity="racing")
        regular.distance = stalled.distance = 100
        for tick in range(11, 201):
            regular.advance(tick / 100)
        stalled.advance(2)
        for name in ("valid_seconds", "target_seconds", "best_streak", "position"):
            self.assertAlmostEqual(getattr(regular.lanes[0],name), getattr(stalled.lanes[0],name), places=8)
        self.assertAlmostEqual(stalled.lanes[0].valid_seconds,1.4)
        self.assertEqual(stalled.lanes[0].power,0)
        self.assertAlmostEqual(stalled.elapsed,1.9)

    def test_duration_ratio_is_time_weighted_and_pause_excluded(self):
        e=running(players=1)
        feed(e,1,2,90)
        e.advance(.3)
        feed(e,1,3,30)
        e.advance(.4)
        self.assertTrue(e.intent("pause","test"))
        e.advance(4)
        self.assertAlmostEqual(e.elapsed,.3)
        self.assertAlmostEqual(e.snapshot()["players"][0]["stable_ratio"],200/3)
        self.assertEqual(e.lanes[0].power,0)
        feed(e,1,4,90)
        self.assertTrue(e.intent("resume","test"))
        e.advance(4.1)
        self.assertEqual(e.lanes[0].streak,0)

    def test_countdown_disconnect_requires_new_start_and_both_lanes(self):
        c=Config(mode="simulation",countdown_seconds=1)
        e=Engine(c,"test")
        feed(e,1,1)
        self.assertFalse(e.intent("start","test"))
        feed(e,2,1)
        self.assertTrue(e.intent("start","test"))
        self.assertFalse(e.intent("start","test"))
        e.advance(.5)
        e.feed(1,dict(kind="status",connected=False,reason="not_connected"))
        self.assertEqual(e.state,"preparing")
        e.advance(1)
        self.assertEqual(e.elapsed,0)

    def test_formal_loss_aborts_but_experience_keeps_other_lane_running(self):
        e=running(kind="formal")
        e.feed(1,dict(kind="status",connected=False,reason="not_connected"))
        self.assertEqual(e.state,"running")
        self.assertEqual(e.lanes[0].power,0)
        self.assertGreater(e.lanes[1].power,0)
        e.feed(2,dict(kind="status",connected=False,reason="not_connected"))
        self.assertEqual(e.state,"aborted")
        self.assertFalse(e.intent("resume","test"))

    def test_virtual_winner_and_tie_are_backend_results(self):
        e=running(activity="racing",data_timeout=5)
        feed(e,1,2,100); feed(e,2,2,10)
        e.advance(2)
        self.assertEqual(e.result,"player_1")
        self.assertEqual(e.lanes[0].position,e.distance)
        self.assertLess(e.lanes[0].finish_time,1)
        self.assertEqual(e.lanes[1].position,0)
        tie=running(activity="racing",data_timeout=5)
        tie.advance(2)
        self.assertEqual(tie.result,"tie")

    def test_missing_zero_nonfinite_out_of_order_have_separate_reasons(self):
        e=running(players=1)
        for seq,(value,reason) in enumerate(((None,"missing_attention"),(0,"sdk_zero_unverified"),(float('nan'),"nonfinite_or_nonnumeric"),(101,"out_of_range")),2):
            feed(e,1,seq,value)
            self.assertEqual(e.lanes[0].reason,reason)
            self.assertEqual(e.lanes[0].power,0)
        self.assertFalse(feed(e,1,1,80))
        self.assertEqual(e.events[-1]["reason"],"out_of_order")
        verified=running(players=1,zero_is_valid=True)
        feed(verified,1,2,0)
        self.assertTrue(verified.lanes[0].valid)
        self.assertEqual(verified.lanes[0].power,0)

    def test_unworn_and_worn_stale_are_distinct(self):
        e=running(players=1)
        feed(e,1,2,80,worn=False)
        self.assertEqual(e.lanes[0].reason,"not_worn")
        self.assertTrue(e.lanes[0].connected)
        feed(e,1,3,80)
        e.advance(2)
        self.assertEqual(e.lanes[0].reason,"stale")
        self.assertTrue(e.lanes[0].worn)
        self.assertTrue(e.lanes[0].connected)

    def test_unknown_sdk_identity_and_order_cannot_refresh_data(self):
        gate=SnapshotGate()
        gate.accept(SimpleNamespace(attention=80),"normal")
        self.assertFalse(gate.new_sample)
        self.assertEqual(gate.reason,"unverified_identity")
        gate.accept(SimpleNamespace(seq=10,updated_at=1),"normal")
        self.assertTrue(gate.new_sample)
        gate.accept(SimpleNamespace(seq=10,updated_at=2),"normal")
        self.assertFalse(gate.new_sample)
        gate.accept(SimpleNamespace(seq=9,updated_at=3),"normal")
        self.assertEqual(gate.reason,"out_of_order")


class ServiceAcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.now=[0.]
        self.config=Config(mode="simulation",storage_path=str(Path(self.folder.name)/"test.sqlite3"),countdown_seconds=.1)
        self.outputs=[]
        self.service=BackendService(self.config, duration=1,clock=lambda:self.now[0],output=lambda s:self.outputs.append(s))
        self.addCleanup(self.service.stop)

    def tick(self,t):
        self.now[0]=t
        self.service.step(t)

    def ready(self):
        for lane in (1,2):
            self.service.submit_frame(DeviceFrame(lane,80,1,0,0,True,True,"normal"))
        self.service.submit_intent("start")
        self.tick(0)
        self.tick(.1)

    def test_complete_record_replays_and_csv_is_timestamped_long_format(self):
        self.ready()
        for lane in (1,2):
            self.service.submit_frame(DeviceFrame(lane,90,2,.2,0,True,True,"normal"))
        self.tick(.2)
        self.tick(1.2)
        self.service.stop()
        result=replay_session(self.config.storage_path,self.service.session_id)
        self.assertTrue(result["matched"])
        self.assertTrue(result["record_complete"])
        self.assertTrue(self.service.snapshot()["saved"])
        paths=export_session(self.config.storage_path,self.service.session_id,self.folder.name)
        self.assertIn("lane,device,utc,t,source_t,sequence",paths[1].read_text(encoding="utf-8-sig"))
        self.assertNotIn("player_1_attention",paths[1].read_text(encoding="utf-8-sig"))

    def test_end_during_running_is_journaled_and_replayable(self):
        self.ready()
        self.tick(.4)
        self.service.stop()
        self.assertTrue(replay_session(self.config.storage_path,self.service.session_id)["matched"])

    def test_terminal_snapshot_is_saved_without_repeated_checkpoint_writes(self):
        self.ready(); self.tick(1.2)
        ordinal=self.service.ordinal
        for t in (2,3,4): self.tick(t)
        self.assertEqual(self.service.ordinal,ordinal)

    def test_old_session_intent_and_samples_cannot_start_new_session(self):
        self.ready(); self.tick(1.2)
        old=self.service.session_id
        self.service.submit_intent("prepare",session_id=old,duration=2)
        self.tick(2)
        self.assertNotEqual(self.service.session_id,old)
        self.service.submit_intent("start",session_id=old)
        self.service.submit_frame(dict(lane=1,raw=90,sequence=99,received=1.5),absolute=True)
        self.tick(2.1)
        self.assertEqual(self.service.snapshot()["state"],"preparing")
        self.assertFalse(self.service.engine.lanes[0].valid)

    def test_record_failure_latches_fault_and_never_claims_saved(self):
        self.ready()
        with patch.object(self.service.store,"health",return_value={"healthy":False,"error":"disk full","warning":None,"lag_seconds":0}):
            self.tick(.2)
            s=self.service.snapshot()
            self.assertEqual(s["safety"],"fault_locked")
            self.assertFalse(s["saved"])
            self.assertTrue(s["record_incomplete"])
            self.assertEqual(self.outputs[-1]["players"][0]["power"],0)
        self.service.submit_intent("reset",confirmed=True)
        self.tick(.3)
        self.assertEqual(self.service.engine.safety,"fault_locked")

    def test_sqlite_failure_exposed_and_recovery_does_not_enable_outputs(self):
        self.ready()
        with patch.object(Store,"_write",side_effect=sqlite3.OperationalError("disk full")):
            self.tick(.3)
            deadline=time.monotonic()+2
            while self.service.store.error is None and time.monotonic()<deadline:
                time.sleep(.01)
            self.assertIn("disk full",self.service.store.error)
            self.tick(.4)
            self.assertEqual(self.service.engine.safety,"fault_locked")

    def test_sqlite_owner_lock_prevents_recovery_of_a_live_session(self):
        with self.assertRaisesRegex(RuntimeError,"数据库"):
            Store(self.config)

    def test_slow_sqlite_commit_does_not_block_control_step(self):
        self.ready()
        original = Store._write
        entered = []

        def slow_write(store, db, batch):
            entered.append(True)
            time.sleep(.25)
            return original(store, db, batch)

        with patch.object(Store, "_write", slow_write):
            started = time.perf_counter()
            self.tick(.5)
            elapsed = time.perf_counter() - started
            self.assertLess(elapsed, .1)
            self.assertAlmostEqual(self.service.engine.now, .5)
            deadline = time.monotonic() + 1
            while not entered and time.monotonic() < deadline:
                time.sleep(.01)
            self.assertTrue(entered)

    def test_tampered_checkpoint_is_rejected_by_read_only_replay(self):
        self.ready()
        self.tick(1.2)
        self.service.stop()
        with sqlite3.connect(self.config.storage_path) as db:
            row = db.execute("SELECT ordinal,payload FROM journal WHERE session_id=? AND kind='checkpoint' ORDER BY ordinal LIMIT 1",
                             (self.service.session_id,)).fetchone()
            payload = json.loads(row[1])
            payload["state"] = "tampered"
            db.execute("UPDATE journal SET payload=? WHERE session_id=? AND ordinal=?",
                       (json.dumps(payload), self.service.session_id, row[0]))
            db.commit()
        with self.assertRaises(AssertionError):
            replay_session(self.config.storage_path, self.service.session_id)


class MotorBoundaryTests(unittest.TestCase):
    def test_backend_stall_is_locked_by_independent_watchdog(self):
        now=[0.]
        motor=EEG.MotorController(lambda:now[0])
        config=Config(mode="simulation")
        state={"state":"running","safety":"allowed","players":[{"power":.8},{"power":.7}]}
        with patch.multiple(EEG,controller=motor,running=True,_gpio_fault=False), patch.object(EEG,"_write_outputs"):
            output=MotorOutput(EEG,config)
            self.assertIsNone(output(state))
            now[0]=config.command_timeout+.01
            self.assertEqual(motor.update(),(0,0))
            self.assertIsNotNone(output(state))
            self.assertFalse(motor.enabled)


if __name__ == "__main__":
    unittest.main()
