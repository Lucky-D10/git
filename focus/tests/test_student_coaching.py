import copy
import unittest

from analytics.coaching import coaching
from ai.validator import ValidationError, validate


def record(**overrides):
    m = dict(valid_seconds=60., coverage=1., active_seconds=60., reference=50., target_ratio=.6,
             best_streak=8., weighted_average=62., iqr=15., target_bouts=2,
             segments=[dict(average=v, coverage=1.) for v in (60., 62., 65.)])
    m.update(overrides)
    facts = [{"id": f, "text": f} for f in ("quality", "target", "level", "segments")]
    return {"scope": "single_session", "facts": facts, **coaching(m, True, facts)}


def output(report):
    return {"summary": "从这次的片段出发", "observations": [
        {"evidence_id": "target", "text": "本轮达标率为{达标率}，最长连续达标{连续达标}，可以把它作为下轮起点。"},
        {"evidence_id": "segments", "text": "前段读数{前段读数}，后段读数{后段读数}，可以看看各段的不同。"}],
        "goal_id": report["goal"]["id"], "recommendation_ids": [s["id"] for s in report["suggestions"][:2]],
        "encouragement": "先试一个小变化，按自己的节奏继续。"}


class CoachingTests(unittest.TestCase):
    def test_diagnostics_identify_field_without_echoing_generated_text(self):
        r = record()
        v = output(r)
        v["encouragement"] = "你一定会提高成绩"
        with self.assertRaises(ValidationError) as error:
            validate(v, r)
        self.assertEqual(str(error.exception), "unsupported_claim")
        self.assertEqual(error.exception.field, "encouragement")
        self.assertEqual(error.exception.rule, "unanchored_number_or_restricted_wording")
        self.assertNotIn(v["encouragement"], str(error.exception))

    def test_patterns_choose_different_goals_and_methods(self):
        ordinary = record()
        low = record(target_ratio=.1, best_streak=0)
        late = record(segments=[dict(average=v, coverage=1.) for v in (80., 65., 50.)])
        variable = record(iqr=32., target_bouts=5)
        high = record(target_ratio=.9)
        self.assertEqual([r["focus"] for r in (ordinary, low, late, variable, high)],
                         ["small_step", "first_steps", "finish_routine", "steady_routine", "repeat_success"])
        self.assertEqual(low["goal"]["target"], 1)
        self.assertEqual(high["goal"]["target"], high["goal"]["baseline"])
        self.assertEqual(late["suggestions"][1]["id"], "return_later")
        self.assertEqual(variable["suggestions"][1]["id"], "ignore_fluctuation")
        self.assertEqual(ordinary["goal"]["target"], 9)
        self.assertNotIn("已经有", low["encouragement"])

    def test_goal_is_bounded_and_missing_segments_are_not_interpreted(self):
        r = record(active_seconds=10., best_streak=9.8)
        self.assertLessEqual(r["goal"]["target"], 10)
        m = dict(valid_seconds=30., coverage=1., active_seconds=30., reference=50., target_ratio=.6,
                 best_streak=8., weighted_average=62., iqr=15., target_bouts=2,
                 segments=[dict(average=None, coverage=0.)]*3)
        facts = [{"id": f} for f in ("quality", "target", "level")]
        r = coaching(m, True, facts)
        self.assertEqual(r["focus"], "small_step")
        self.assertNotIn("segments", r["display_values"])
        r = coaching(m, False, [{"id": "quality"}])
        self.assertIsNone(r["goal"]["target"])
        self.assertEqual(r["goal"]["evidence_ids"], ["quality"])

    def test_placeholders_resolve_from_their_own_evidence(self):
        r = record()
        result = validate(output(r), r)
        self.assertIn("60.0%", result["observations"][0]["text"])
        self.assertIn("8.0 秒", result["observations"][0]["text"])
        self.assertNotIn("{", result["observations"][0]["text"])
        self.assertNotIn("goal", result)  # AI cannot overwrite local goals.

    def test_invented_numbers_goals_labels_and_wrong_evidence_are_rejected(self):
        r = record()
        cases = []
        for text in ("你的达标率是99%", "最长连续达标一百秒", "本轮有{不存在的数据}",
                     "后段为{后段读数}", "你很聪明，比别人更强", "你不够努力", "你比上次进步了",
                     "说明开头到结束都跟住了页面提示", "你从头到尾都保持了稳定"):
            v = output(r)
            v["observations"][0]["text"] = text
            cases.append(v)
        v = output(r); v["goal_id"] = "train_harder"; cases.append(v)
        v = output(r); v["recommendation_ids"] = ["invented", "choose_cue"]; cases.append(v)
        v = output(r); v["encouragement"] = "你一定会提高成绩"; cases.append(v)
        for v in cases:
            with self.subTest(value=v), self.assertRaises(ValueError):
                validate(v, r)

    def test_generic_output_and_repeated_evidence_are_rejected(self):
        r = record()
        v = output(r)
        for obs in v["observations"]:
            obs["text"] = "可以继续尝试。"
        with self.assertRaises(ValueError):
            validate(v, r)
        v = output(r); v["observations"][1] = copy.deepcopy(v["observations"][0])
        with self.assertRaises(ValueError):
            validate(v, r)


if __name__ == "__main__":
    unittest.main()
