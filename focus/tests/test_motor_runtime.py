"""Regression tests exercise the production policy and both GUI control callbacks."""
import importlib.util
import unittest
from collections import deque
from pathlib import Path
from unittest.mock import MagicMock, patch

import EEG
from EEG import AttentionReward, TrainingMetrics
COMMAND_TIMEOUT = EEG.COMMAND_TIMEOUT
DATA_TIMEOUT = EEG.DATA_TIMEOUT


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).resolve().parents[1] / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module






class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.now = 100.0
        self.controller = EEG.MotorController(lambda: self.now)
        for name, value in (("controller", self.controller), ("running", True),
                            ("_gpio_fault", False), ("motor_enabled", False),
                            ("_samples", [EEG.AttentionSample(80, self.now, True, 1)] * 2)):
            context = patch.object(EEG, name, value)
            context.start()
            self.addCleanup(context.stop)
        context = patch.object(EEG.time, "monotonic", lambda: self.now)
        context.start()
        self.addCleanup(context.stop)
        context = patch.object(EEG, "_write_outputs")
        self.write = context.start()
        self.addCleanup(context.stop)

    def tick(self, seconds=.05, refresh=True):
        self.now += seconds
        if refresh:
            for i in (1, 2):
                EEG._publish(i, EEG.AttentionSample(80, self.now, True, 0))
        return EEG._motor_tick(self.now, seconds)

    def test_valid_data_and_heartbeat_run_past_old_cutoff(self):
        self.assertTrue(EEG.enable_motors(True))
        for _ in range(80):
            EEG.set_race_speeds(8, 9)
            duties = self.tick()
        self.assertTrue(EEG.motor_status()[0])
        self.assertGreater(duties[1], duties[0])
        self.assertGreater(duties[0], 0)

    def test_fresh_eeg_cannot_keep_dead_ui_alive(self):
        EEG.enable_motors(True)
        EEG.set_race_speeds(8, 8)
        self.tick()
        self.assertEqual(self.tick(COMMAND_TIMEOUT + .01), (0, 0))
        self.assertFalse(EEG.motor_status()[0])
        EEG.set_race_speeds(9, 9)  # Recovery requires explicit re-enable.
        self.assertEqual(self.tick(), (0, 0))

    def test_one_invalid_lane_stops_only_that_lane_with_heartbeat(self):
        EEG.enable_motors(True)
        EEG.set_race_speeds(9, 9)
        self.tick()
        EEG._publish(1, EEG.AttentionSample(None, self.now, False, 0))
        duties = self.tick(refresh=False)
        self.assertEqual(duties[0], 0)
        self.assertGreater(duties[1], 0)
        self.assertTrue(EEG.motor_status()[0])
        self.assertTrue(EEG.enable_motors(True))
        self.assertEqual(self.tick(), (0, 0))  # No old command after re-enable.

    def test_stale_data_zeros_both_tracks_without_pausing_controller(self):
        EEG.enable_motors(True)
        for _ in range(40):
            EEG.set_race_speeds(8, 8)
            result = self.tick(refresh=False)
        self.assertEqual(result, (0, 0))
        self.assertFalse(EEG.device_has_recent_data(1, max_age=10))
        self.assertTrue(EEG.motor_status()[0])

    def test_ramp_limits_increases_and_zero_is_immediate(self):
        EEG.enable_motors(True)
        EEG.set_race_speeds(10, 10)
        self.assertAlmostEqual(self.tick()[0], 1.25)
        EEG.set_race_speeds(0, 0)
        self.assertEqual(self.tick(), (0, 0))

    def test_emergency_writes_zero_and_blocks_late_commands(self):
        EEG.enable_motors(True)
        EEG.set_race_speeds(10, 10)
        self.tick()
        EEG.emergency_stop()
        self.write.assert_called_with(0, 0)
        EEG.set_race_speeds(10, 10)
        self.assertEqual(self.tick(), (0, 0))

    def test_nan_commands_are_zero(self):
        EEG.enable_motors(True)
        EEG.set_race_speeds(float("nan"), float("inf"))
        self.assertEqual(self.tick(), (0, 0))

    def test_snapshot_sequence_survives_parser_restart(self):
        EEG._publish(1, EEG.AttentionSample(70, self.now, True, 1))
        first = EEG.get_samples()[0].sequence
        EEG._publish(1, EEG.AttentionSample(70, self.now, True, 1))
        self.assertGreater(EEG.get_samples()[0].sequence, first)

    def test_failed_output_worker_cannot_be_rearmed(self):
        EEG.enable_motors(True)
        with patch.object(EEG, "_stop") as stop, patch.object(EEG, "_motor_tick", side_effect=RuntimeError("worker failed")):
            stop.is_set.return_value = False
            with self.assertLogs("EEGSystem", level="ERROR"):
                EEG.f2()
        self.assertTrue(EEG._gpio_fault)
        self.assertFalse(EEG.enable_motors(True))


class GPIOFailureTests(unittest.TestCase):
    def test_driver_exception_lowers_stby_and_latches_fault(self):
        gpio, first, second = MagicMock(), MagicMock(), MagicMock()
        gpio.LOW, gpio.HIGH = 0, 1
        second.ChangeDutyCycle.side_effect = OSError("driver error")
        controller = EEG.MotorController()
        controller.enable(True)
        with patch.multiple(EEG, GPIO=gpio, pwm_1=first, pwm_2=second,
                            gpio_initialized=True, simulation_mode=False,
                            controller=controller, _gpio_fault=False, motor_enabled=True):
            with self.assertLogs("EEGSystem", level="ERROR"):
                with EEG.motor_lock:
                    EEG._write_outputs(30, 40)
            self.assertTrue(EEG._gpio_fault)
            self.assertFalse(EEG.motor_enabled)
            self.assertFalse(controller.enabled)
            gpio.output.assert_called_with(EEG.STBY, gpio.LOW)

    def test_disabled_api_does_not_initialize_gpio(self):
        with patch.object(EEG, "gpio_initialized", False), patch.object(EEG, "GPIO") as gpio:
            EEG.emergency_stop()
        gpio.setup.assert_not_called()
        gpio.PWM.assert_not_called()


class ConnectionTests(unittest.TestCase):
    def test_real_mode_never_silently_falls_back_to_random_data(self):
        with patch.object(EEG, "running", False), patch.object(EEG, "hardware_available", False), patch.object(EEG, "simulation_mode", False):
            with self.assertRaises(RuntimeError):
                EEG.start()


