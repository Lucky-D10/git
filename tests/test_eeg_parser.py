import unittest
from unittest.mock import patch
import EEG

from EEG import DeviceStateMachine, MotorController, _snapshot_sample, _speed_to_duty, normalize_device_state


class AttentionUsbTests(unittest.TestCase):
    def test_explicit_no_wear_overrides_stale_normal_state(self):
        snapshot = type("Snapshot", (), {"attention": 73, "state": "normal", "wear": False})()
        sample = _snapshot_sample(snapshot, 12.5)
        self.assertEqual(sample.attention, 73)
        self.assertFalse(sample.valid)
        self.assertEqual(sample.state, "off")

    def test_worn_normal_snapshot_outputs_attention(self):
        snapshot = type("Snapshot", (), {"attention": 73, "state": "normal", "wear": True})()
        sample = _snapshot_sample(snapshot, 12.5)
        self.assertTrue(sample.valid)
        self.assertEqual(sample.state, "normal")

    def test_normal_without_attention_is_not_output_state(self):
        snapshot = type("Snapshot", (), {"attention": None, "state": "normal", "wear": True})()
        sample = _snapshot_sample(snapshot, 12.5)
        self.assertFalse(sample.valid)
        self.assertEqual(sample.state, "baseline")

    def test_baseline_progress_overrides_temporary_attention_value(self):
        snapshot = type("Snapshot", (), {
            "attention": 64,
            "state": "normal",
            "wear": True,
            "baseline_progress": 0.01,
        })()
        sample = _snapshot_sample(snapshot, 12.5)
        self.assertFalse(sample.valid)
        self.assertEqual(sample.state, "baseline")

    def test_shared_feedback_contract_matches_state(self):
        baseline = _snapshot_sample(type("Snapshot", (), {
            "state": "baseline", "attention": 55, "baseline_progress": 0.2, "wear": True,
        })(), 12.5)
        baseline = baseline.__class__(baseline.attention, 12.5, baseline.valid, 1, baseline.state,
                                      baseline.baseline, baseline.baseline_progress, baseline.wear, baseline.battery_soc)
        with patch("EEG._samples", [baseline, baseline]), patch("EEG.time.monotonic", return_value=12.5):
            feedback = EEG.device_feedback(1)
        self.assertEqual(feedback["state"], "baseline")
        self.assertFalse(feedback["ready"])

    def test_baseline_state_does_not_drive_motor(self):
        snapshot = type("Snapshot", (), {"attention": 73, "state": "baseline", "baseline_progress": 0.4})()
        sample = _snapshot_sample(snapshot, 12.5)
        self.assertFalse(sample.valid)
        self.assertEqual(sample.state, "baseline")
        self.assertEqual(sample.baseline_progress, 0.4)

    def test_vendor_typo_is_normalized(self):
        self.assertEqual(normalize_device_state("normol"), "normal")
        self.assertEqual(normalize_device_state("OFF"), "off")

    def test_new_sdk_wear_lifecycle_is_used_for_state(self):
        device = type("Device", (), {
            "online": {"adapter": True, "headband_ble": True},
        })()
        baseline = type("Snapshot", (), {
            "wear": "baseline", "attention": 68, "calib_progress": 42,
            "calibrated": False,
        })()
        normal = type("Snapshot", (), {
            "wear": "normal", "attention": 82, "calib_progress": 100,
            "calibrated": True,
        })()
        off = type("Snapshot", (), {
            "wear": "off", "attention": 82, "calib_progress": 100,
            "calibrated": True,
        })()
        self.assertEqual(_snapshot_sample(baseline, 1, device).state, "baseline")
        self.assertFalse(_snapshot_sample(baseline, 1, device).valid)
        self.assertEqual(_snapshot_sample(normal, 2, device).state, "normal")
        self.assertTrue(_snapshot_sample(normal, 2, device).valid)
        self.assertEqual(_snapshot_sample(off, 3, device).state, "off")

    def test_new_sdk_online_dict_disconnects_stale_normal(self):
        snapshot = type("Snapshot", (), {"wear": "normal", "attention": 82})()
        device = type("Device", (), {
            "online": {"adapter": True, "headband_ble": False},
        })()
        sample = _snapshot_sample(snapshot, 1, device)
        self.assertEqual(sample.state, "off")
        self.assertFalse(sample.valid)

    def test_state_machine_transitions_and_times_out(self):
        machine = DeviceStateMachine(clock=lambda: 0.0)
        baseline = type("Snapshot", (), {"state": "baseline", "attention": None, "baseline_progress": 0.2})()
        normal = type("Snapshot", (), {"state": "normol", "attention": 82})()
        off = type("Snapshot", (), {"state": "off", "attention": None})()
        self.assertEqual(machine.update(baseline, 1).state, "baseline")
        self.assertFalse(machine.update(baseline, 2).valid)
        self.assertEqual(machine.update(normal, 3).state, "normal")
        self.assertTrue(machine.update(normal, 4).valid)
        self.assertEqual(machine.update(off, 5).state, "off")
        machine.update(normal, 6)
        timeout = machine.tick(6 + 1.5 + 0.01)
        self.assertEqual(timeout.state, "off")
        self.assertEqual(machine.transition_count, 5)

    def test_missing_or_out_of_range_attention_is_invalid(self):
        for value in (None, 0, 101):
            snapshot = type("Snapshot", (), {"attention": value})()
            self.assertFalse(_snapshot_sample(snapshot, 12.5).valid)


class MotorControllerTests(unittest.TestCase):
    def test_invalid_signal_stops_only_invalid_track_without_pausing(self):
        controller = MotorController()
        controller.enable(True)
        controller.command_speed(9, 9)
        duty_1, duty_2 = controller.update(0.1, valid=(False, True))
        self.assertEqual(duty_1, 0)
        self.assertGreater(duty_2, 0)
        self.assertTrue(controller.enabled)

    def test_both_invalid_signals_do_not_pause_the_session(self):
        controller = MotorController()
        controller.enable(True)
        controller.command_speed(9, 9)
        self.assertEqual(controller.update(0.1, valid=(False, False)), (0, 0))
        self.assertTrue(controller.enabled)

    def test_power_mapping_is_bounded_and_monotonic(self):
        low = _speed_to_duty(2)
        high = _speed_to_duty(10)
        self.assertGreater(high, low)
        self.assertGreaterEqual(low, 25)
        self.assertLessEqual(high, 50)


if __name__ == "__main__":
    unittest.main()
