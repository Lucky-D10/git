import contextlib
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ai.configuration import load_local_env
from ai.provider import ProviderConfig


class AIConfigurationTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = Path(folder.name) / ".env.deepseek"
        self.path.write_text('FOCUS_AI_PROVIDER=deepseek\nFOCUS_AI_MODEL="test-model"\n'
                             'DEEPSEEK_API_KEY=test-secret\nFOCUS_AI_ALLOW_SIMULATION=0\n', encoding="utf-8")
        self.env = patch.dict(os.environ, {}, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_main_entry_loads_ai_before_backend_even_from_another_directory(self):
        import app
        with patch("ai.configuration.LOCAL_ENV_FILE", self.path), \
                patch("app.environment", return_value={}), \
                patch("app.settings.configure"), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(app.main(["web", "--mode", "simulation", "--environment"]), 0)
        config = ProviderConfig.from_env()
        self.assertTrue(config.enabled)
        self.assertEqual(config.api_key, "test-secret")
        self.assertFalse(config.allow_simulation)

    def test_service_environment_including_explicit_disable_takes_priority(self):
        os.environ.update(FOCUS_AI_PROVIDER="disabled", DEEPSEEK_API_KEY="service-secret")
        load_local_env(self.path)
        self.assertFalse(ProviderConfig.from_env().enabled)
        self.assertEqual(os.environ["DEEPSEEK_API_KEY"], "service-secret")

    def test_invalid_file_does_not_partially_apply_or_expose_secret(self):
        self.path.write_text("DEEPSEEK_API_KEY=test-secret\nBAD_SECRET=test-secret", encoding="utf-8")
        with self.assertRaises(ValueError) as result:
            load_local_env(self.path)
        self.assertNotIn("test-secret", str(result.exception))
        self.assertNotIn("DEEPSEEK_API_KEY", os.environ)

    def test_missing_file_is_optional_but_explicit_check_requires_it(self):
        missing = self.path.parent / "missing"
        self.assertFalse(load_local_env(missing))
        with self.assertRaises(FileNotFoundError):
            load_local_env(missing, required=True)

    def test_explicit_check_can_load_service_file_without_changing_staff_pin(self):
        with self.path.open("a", encoding="utf-8") as target:
            target.write("FOCUS_STAFF_PIN=123456\n")
        os.environ.update(DEEPSEEK_API_KEY="old-secret", FOCUS_STAFF_PIN="654321")
        load_local_env(self.path, overwrite=True)
        self.assertEqual(os.environ["DEEPSEEK_API_KEY"], "test-secret")
        self.assertEqual(os.environ["FOCUS_STAFF_PIN"], "654321")
