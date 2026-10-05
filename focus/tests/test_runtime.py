"""Regression tests for the headless runtime and display adapter."""
import inspect
import unittest
from pathlib import Path
from unittest.mock import MagicMock
import importlib.util

from backend.ui import SessionPanel
from backend.service import BackendService
from settings import Config


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).resolve().parents[1] / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


curve = load("curve", "Focus Training.py")
race = load("race", "Focus Racing.py")


class RuntimeTests(unittest.TestCase):
    def test_both_pages_are_display_only_backend_adapters(self):
        self.assertTrue(issubclass(curve.CarAttentionMonitor, SessionPanel))
        self.assertTrue(issubclass(race.FocusRacingGame, SessionPanel))
        source = inspect.getsource(SessionPanel.refresh)
        for forbidden in ("enable_motors", "set_race_speeds", "advance(", "reward.update", "metric.update"):
            self.assertNotIn(forbidden, source)

    def test_old_session_id_is_carried_with_every_intent(self):
        view = SessionPanel.__new__(SessionPanel)
        view.backend = MagicMock()
        view.intent("start", "previous-session")
        view.backend.submit_intent.assert_called_once_with("start", session_id="previous-session")

    def test_service_constructor_has_no_tk_dependency(self):
        self.assertNotIn("tkinter", inspect.getsource(BackendService))

if __name__ == "__main__":
    unittest.main()
