import math
import unittest

from EEG import AttentionReward, TrainingMetrics, focus_to_power
from EEG import _speed_to_duty


class RewardTests(unittest.TestCase):
    def sustained(self, focus, seconds=6, hz=20):
        reward = AttentionReward()
        for i in range(int(seconds * hz)):
            reward.update(focus, True, 1 / hz, new_sample=i % hz == 0)
        return reward.state

    def test_higher_focus_has_advantage_at_equal_duration(self):
        values = [self.sustained(f).power for f in (21, 40, 60, 70, 80, 90, 100)]
        self.assertTrue(all(a < b for a, b in zip(values, values[1:])))
        self.assertAlmostEqual(values[-1], 1.0)

    def test_mapping_is_bounded_and_monotonic_for_same_streak(self):
        for streak in (0, 1, 3, 5, 100):
            values = [focus_to_power(f, True, streak) for f in range(101)]
            self.assertTrue(all(a <= b for a, b in zip(values, values[1:])))
            self.assertTrue(all(0 <= value <= 1 for value in values))

    def test_convex_base_rewards_high_focus_more(self):
        self.assertGreater(focus_to_power(90) - focus_to_power(80),
                           focus_to_power(40) - focus_to_power(30))

    def test_sustained_bonus_cannot_exceed_ten_percentage_points(self):
        for focus in (30, 60, 70, 80, 100):
            state = self.sustained(focus)
            self.assertGreaterEqual(state.bonus, 0)
            self.assertLessEqual(state.bonus, 0.10000001)
        self.assertGreater(self.sustained(80).power, focus_to_power(80))
        self.assertEqual(self.sustained(60).bonus, 0)

    def test_reward_does_not_depend_on_ui_refresh_rate(self):
        a = self.sustained(80, seconds=4, hz=20)
        b = self.sustained(80, seconds=4, hz=10)
        self.assertAlmostEqual(a.power, b.power)
        self.assertAlmostEqual(a.streak, b.streak)

    def test_ema_changes_only_on_new_samples(self):
        reward = AttentionReward()
        reward.update(30, True, 0.05)
        for _ in range(19):
            reward.update(30, True, 0.05, False)
        after = reward.update(90, True, 0.05, True)
        self.assertGreater(after.smoothed, 30)
        self.assertLess(after.smoothed, 90)
        held = reward.update(90, True, 0.05, False)
        self.assertEqual(after.smoothed, held.smoothed)

    def test_low_focus_stops_exactly_after_high_focus(self):
        reward = AttentionReward()
        for _ in range(100):
            reward.update(90, True, 0.05)
        state = reward.update(10, True, 0.05)
        self.assertEqual(state.power, 0)
        self.assertEqual(state.streak, 0)
        self.assertEqual(_speed_to_duty(state.power * 10), 0)

    def test_invalid_zero_nan_and_reset_clear_reward(self):
        for value, valid in ((90, False), (0, True), (math.nan, True), (math.inf, True)):
            reward = AttentionReward()
            for _ in range(100):
                reward.update(90, True, 0.05)
            self.assertEqual(reward.update(value, valid, 0.05).power, 0)
            self.assertEqual(reward.state.streak, 0)
        reward.reset()
        self.assertEqual(reward.state.power, 0)

    def test_baseline_is_only_a_training_metric(self):
        low, high = TrainingMetrics(30), TrainingMetrics(80)
        low.update(60, True, 0.2)
        high.update(60, True, 0.2)
        self.assertEqual(low.stable_ratio, 100)
        self.assertEqual(high.stable_ratio, 0)
        self.assertEqual(AttentionReward().update(60, True, 0.2).power,
                         focus_to_power(60))

    def test_metrics_count_elapsed_time_and_break_invalid_streaks(self):
        metrics = TrainingMetrics(50)
        for _ in range(20):
            metrics.update(80, True, 0.05)
        self.assertAlmostEqual(metrics.best_streak, 1.0)
        metrics.update(80, False, 0.2)
        self.assertEqual(metrics.current_streak, 0)
        self.assertAlmostEqual(metrics.valid_seconds, 1)
        for _ in range(20):
            metrics.update(30, True, 0.05)
        self.assertAlmostEqual(metrics.stable_ratio, 50)


if __name__ == "__main__":
    unittest.main()
