import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from EEG import build_race_report, build_training_report, export_session_report, summarize_series
from EEG import draw_checkered_finish, draw_device_state_machine, draw_race_car, draw_two_lane_track


class SessionReportTests(unittest.TestCase):
    def test_series_summary_handles_empty_and_median(self):
        self.assertEqual(summarize_series([])["samples"], 0)
        summary = summarize_series([20, 80, 40, 60])
        self.assertEqual(summary["median"], 50)
        self.assertEqual(summary["minimum"], 20)
        self.assertEqual(summary["maximum"], 80)

    def test_training_report_preserves_measurement_boundary(self):
        metrics = [SimpleNamespace(stable_ratio=60, best_streak=3.2, valid_seconds=8),
                   SimpleNamespace(stable_ratio=40, best_streak=2.0, valid_seconds=7)]
        report = build_training_report([[50, 70], [30, 90]], [55, 60], metrics, 10, "模拟数据模式")
        self.assertEqual(report["type"], "focus_training")
        self.assertEqual(report["players"][0]["baseline"], 55)
        self.assertIn("软件估算", report["measurement_note"])

    def test_race_report_labels_virtual_measurements(self):
        players = [
            SimpleNamespace(focus_history=[50, 80], color="#f00", race_time=12.5, position=100, max_speed=8),
            SimpleNamespace(focus_history=[40, 70], color="#00f", race_time=0, position=95, max_speed=7),
        ]
        report = build_race_report(players, 12.5, 100, "模拟数据模式", "player_1")
        self.assertEqual(report["result"], "player_1")
        self.assertIn("虚拟进度", report["measurement_note"])

    def test_export_writes_utf8_json_and_aligned_csv(self):
        report = {"type": "focus_training", "players": []}
        with tempfile.TemporaryDirectory() as directory:
            json_path, csv_path = export_session_report(report, [[10, 20], [30]], directory)
            self.assertEqual(json.loads(Path(json_path).read_text(encoding="utf-8"))["type"], "focus_training")
            csv_text = Path(csv_path).read_text(encoding="utf-8-sig")
            self.assertIn("player_1_attention", csv_text)
            self.assertIn("2,20,", csv_text)
class FakeCanvas:
    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        if not name.startswith("create_"):
            raise AttributeError(name)
        def create(*args, **kwargs):
            self.calls.append((name, args, kwargs))
            return len(self.calls)
        return create


class VisualComponentTests(unittest.TestCase):
    def test_device_state_machine_draws_three_states_and_arrows(self):
        canvas = FakeCanvas()
        ids = draw_device_state_machine(canvas, 200, 40, "baseline")
        labels = [call[2].get("text") for call in canvas.calls if call[0] == "create_text"]
        self.assertEqual(len(ids), 8)
        self.assertEqual(labels, ["未佩戴", "采集基线", "输出专注度"])
        self.assertEqual(sum(call[0] == "create_line" for call in canvas.calls), 2)

    def test_shared_car_and_track_draw_without_ui_state(self):
        canvas = FakeCanvas()
        car_ids = draw_race_car(canvas, 100, 80, "#f00", state="finished")
        lanes = draw_two_lane_track(canvas, 20, 30, 300, 170, ("#f00", "#00f"))
        self.assertGreater(len(car_ids), 8)
        self.assertEqual(len(lanes), 2)
        self.assertLess(lanes[0], lanes[1])
        self.assertTrue(any(call[0] == "create_polygon" for call in canvas.calls))

    def test_finish_band_is_checkered(self):
        canvas = FakeCanvas()
        ids = draw_checkered_finish(canvas, 200, 20, 120)
        fills = [call[2].get("fill") for call in canvas.calls if call[0] == "create_rectangle"]
        self.assertGreater(len(ids), 10)
        self.assertIn("#F5F7FA", fills)
        self.assertIn("#111827", fills)


if __name__ == "__main__":
    unittest.main()
