import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import unittest

import replay
from sample_gate import SnapshotGate
from session import Rules, Session
from settings import Config, load


class StageOneTests(unittest.TestCase):
    def test_modes_are_explicit_and_configs_validate(self):
        hardware = load(Path("config/hardware.json"))
        simulation = load(Path("config/simulation.json"))
        self.assertEqual(hardware.mode, "hardware")
        self.assertEqual(simulation.mode, "simulation")
        with self.assertRaises(ValueError):
            Config(mode="other")
        with self.assertRaises(ValueError):
            Config(pwm_pins=(2, 11), direction_pins=(4, 3, 10, 17), standby_pin=17)

    def test_formal_dual_signal_loss_aborts_and_experience_continues(self):
        clock = [0.0]
        formal = Session(Config(mode="simulation", session_kind="formal"), lambda: clock[0])
        samples = [SimpleNamespace(valid=False), SimpleNamespace(valid=False)]
        self.assertFalse(formal.observe([SimpleNamespace(valid=True), SimpleNamespace(valid=True)]))
        self.assertTrue(formal.observe(samples))
        self.assertIn("session_aborted", [row["event"] for row in formal.events])
        experience = Session(Config(mode="simulation", session_kind="experience"), lambda: clock[0])
        self.assertFalse(experience.observe(samples))

    def test_snapshot_gate_rejects_duplicates_but_accepts_state_transition(self):
        gate = SnapshotGate()
        snap = SimpleNamespace(updated_at=10, seq=1)
        self.assertTrue(gate.accept(snap, "normal"))
        self.assertFalse(gate.accept(snap, "normal"))
        self.assertTrue(gate.accept(snap, "off"))

    def test_fixed_replay_is_repeatable_and_covers_required_scenarios(self):
        first, second = replay.run_all(), replay.run_all()
        self.assertEqual(first, second)
        self.assertTrue({"stable", "alternating", "single_loss", "double_loss", "baseline_timeout", "duplicate", "pause_resume", "emergency_late_callback"} <= set(first))
        self.assertEqual(first["duplicate"]["valid_samples"], [2, 2])

    def test_runtime_test_uses_current_entry_names(self):
        text = Path("tests/test_runtime.py").read_text(encoding="utf-8")
        self.assertIn("Focus Training.py", text)
        self.assertIn("Focus Racing.py", text)


if __name__ == "__main__":
    unittest.main()
