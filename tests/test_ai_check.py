import contextlib
import io
import unittest
from unittest.mock import patch

from ai.provider import ProviderConfig
from tools.check_ai import main


class AICheckTests(unittest.TestCase):
    def run_check(self, succeeds):
        calls = []

        def generate(config, report):
            calls.append(dict(report))
            return {
                "summary": "达标率99%" if len(calls) == 1 or not succeeds else "从这次的片段出发",
                "observations": [
                    {"evidence_id": "target", "text": "最长连续达标{连续达标}。"},
                    {"evidence_id": "quality", "text": "覆盖率{覆盖率}，可以一起看看记录。"}],
                "goal_id": report["goal"]["id"],
                "recommendation_ids": [s["id"] for s in report["suggestions"][:2]],
                "encouragement": "按自己的节奏尝试。"}

        output = io.StringIO()
        with patch("sys.argv", ["check_ai.py", "--live"]), \
                patch("ai.configuration.load_local_env"), \
                patch("ai.provider.ProviderConfig.from_env", return_value=ProviderConfig("deepseek", "test", "secret")), \
                patch("ai.provider.generate", side_effect=generate), contextlib.redirect_stdout(output):
            result = main()
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[1]["_validation_error"], "unsupported_claim")
        self.assertIn("field=summary", output.getvalue())
        self.assertNotIn("secret", output.getvalue())
        self.assertNotIn("99%", output.getvalue())
        return result

    def test_corrected_response_passes(self):
        self.assertEqual(self.run_check(True), 0)

    def test_repeated_invalid_response_stops_after_two_requests(self):
        self.assertEqual(self.run_check(False), 1)
