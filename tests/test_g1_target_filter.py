"""g1-target-filter-v1 mechanics on synthetic data — offline, no archive or network."""
import json
from pathlib import Path
import tempfile
import unittest

from research import eval_g1_target_filter as tf

H, M = tf.HOUR, tf.MINUTE
T0 = 1_700_000_000_000 // H * H


def hour_bars(n=24, close=100.0):
    return [(T0 + k*H, close, close + 1, close - 1, close) for k in range(n)]


def rec(day_index, feature, r_by_target):
    row = {"decision_ms": T0 + day_index * 86_400_000, "symbol": "A", "R20": dict(r_by_target), "R40": dict(r_by_target)}
    for name in tf.FEATURES:
        row[name] = feature
    return row


class TargetFilterTests(unittest.TestCase):
    def test_path_ordering_gap_and_timeout(self):
        both = [(T0, 100, 103, 90, 100)]
        self.assertEqual(tf.path_result(both, 2, 5), -5)
        self.assertEqual(tf.path_result(both, 2, 5, "optimistic"), 2)
        gap = [(T0, 100, 101, 99, 100), (T0 + H, 90, 91, 89, 90)]
        self.assertAlmostEqual(tf.path_result(gap, 2, 5), -10)
        flat = [(T0 + k*H, 100, 101, 99, 100 + k) for k in range(4)]
        self.assertAlmostEqual(tf.path_result(flat, None, 5), 3)

    def test_bar_features_require_24_contiguous_closed_bars(self):
        bars = hour_bars()
        bars[-1] = (bars[-1][0], 99.0, 105.0, 98.0, 102.0)
        feats = tf.bar_features(bars)
        self.assertAlmostEqual(feats["last_hour_return"], (102 / 99 - 1) * 100)
        self.assertAlmostEqual(feats["dist_24h_high"], (102 / 105 - 1) * 100)
        self.assertGreater(feats["atr"], 0)
        self.assertIsNone(tf.bar_features(bars[:23]))
        gap = bars[:10] + [(bars[10][0] + H,) + bars[10][1:]] + bars[11:]
        self.assertIsNone(tf.bar_features(gap))

    def test_selection_uses_only_training_cuts_and_maps_each_bucket(self):
        train = []
        for k in range(900):
            value = k % 3
            r = {t: -0.1 for t in tf.TARGETS}
            r[{0: 2.0, 1: 5.0, 2: None}[value]] = 0.3
            train.append(rec(k, float(value), r))
        policy = tf.select_policy(train)
        choice = policy["candidates"][policy["feature"]]
        self.assertTrue(choice["eligible"])
        self.assertEqual(choice["mapping"], {0: 2.0, 1: 5.0, 2: None})
        out = tf.evaluate(train, policy)
        self.assertAlmostEqual(out["adaptive_mean_R"], 0.3)
        self.assertGreater(out["vs_card"], 0)

    def test_small_buckets_are_ineligible(self):
        train = [rec(k, float(k % 3), {t: 0.1 for t in tf.TARGETS}) for k in range(60)]
        policy = tf.select_policy(train)
        self.assertIsNone(policy["feature"])

    def test_skip_policy_earns_zero_in_negative_buckets(self):
        train = []
        for k in range(900):
            value = k % 3
            base = -0.2 if value == 0 else 0.2
            train.append(rec(k, float(value), {t: base for t in tf.TARGETS}))
        policy = tf.select_policy(train)
        self.assertAlmostEqual(tf.evaluate(train, policy)["skip_mean_R"], 0.4 / 3)

    def test_decision_needs_holdout_ci_and_live_direction(self):
        good = {"vs_card_ci": (0.01, 0.2), "vs_best_ci": (0.02, 0.2), "vs_card": 0.1, "vs_best": 0.1}
        self.assertEqual(tf.decide(good, {"vs_card": 0.1, "vs_best": 0.05}), "SUPPORTED")
        self.assertEqual(tf.decide(good, {"vs_card": -0.1, "vs_best": 0.05}), "PARTIAL")
        self.assertEqual(tf.decide(good, None), "PARTIAL")
        weak = dict(good, vs_best_ci=(-0.01, 0.2))
        self.assertEqual(tf.decide(weak, {"vs_card": 0.1, "vs_best": 0.05}), "NOT_SUPPORTED")

    def test_live_loader_keeps_only_live_window_and_latest_snapshot(self):
        def signal(t, seen, rank):
            return {"strategy": "G1", "symbol": "AAAUSDT", "t": t, "notified_at": seen,
                    "detail": [["24s yükselen sırası", f"#{rank}"], ["Kapanmış mum 24s getirisi", "+7.607%"],
                               ["1s hacim / önceki 24s medyan", "8.836x"]]}
        with tempfile.TemporaryDirectory() as folder:
            first, second = Path(folder) / "a.json", Path(folder) / "b.json"
            first.write_text(json.dumps({"signals": [signal("2026-09-10T05:00:00+00:00", "2026-09-10T06:00:12+00:00", 3),
                                                     signal("2026-08-01T05:00:00+00:00", "2026-08-01T06:00:12+00:00", 1)]}))
            second.write_text(json.dumps({"signals": [signal("2026-09-10T05:00:00+00:00", "2026-09-10T06:00:12+00:00", 8)]}))
            events = tf.load_live_events([first, second])
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["rank"], 8)
        self.assertEqual(events[0]["entry_ms"], tf.iso_ms("2026-09-10T06:01:00+00:00"))
        self.assertAlmostEqual(events[0]["return_24h"], 7.607)
        self.assertAlmostEqual(events[0]["volume_ratio"], 8.836)


if __name__ == "__main__":
    unittest.main()
