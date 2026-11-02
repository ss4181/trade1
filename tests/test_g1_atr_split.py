"""g1-atr-split-hist-v1 mechanics on synthetic hourly bars — offline."""
import unittest

from research import eval_g1_atr_split as split

H = split.HOUR


def bars(n=24, start=1_700_000_000_000 // H * H, step=0.25):
    return [(start + k*H, 100 + k*step, 100 + k*step, 100 + k*step, 100 + k*step) for k in range(n)]


class AtrSplitTests(unittest.TestCase):
    def test_atr_uses_15_closed_bars_before_entry_and_requires_contiguity(self):
        b = bars()
        self.assertAlmostEqual(split.atr_pct(b, 20), 0.25 / b[19][4] * 100)
        self.assertIsNone(split.atr_pct(b, 10))
        gap = b[:12] + [(b[12][0] + H,) + b[12][1:]] + b[13:]
        self.assertIsNone(split.atr_pct(gap, 20))

    def test_path_ordering_gap_and_timeout(self):
        t = 1_700_000_000_000 // H * H
        both = [(t, 100, 103, 90, 100), (t+H, 100, 100, 100, 100), (t+2*H, 100, 100, 100, 100), (t+3*H, 100, 100, 100, 101)]
        self.assertEqual(split.path_gross(both, 0, 2, 5, "conservative"), -5)
        self.assertEqual(split.path_gross(both, 0, 2, 5, "optimistic"), 2)
        gapdown = [(t, 100, 101, 99, 99), (t+H, 90, 91, 89, 90), (t+2*H, 90, 90, 90, 90), (t+3*H, 90, 90, 90, 90)]
        self.assertAlmostEqual(split.path_gross(gapdown, 0, 2, 5), -10)
        flat = [(t+k*H, 100, 101, 99, 100 + k) for k in range(4)]
        self.assertAlmostEqual(split.path_gross(flat, 0, None, 5), 3)
        self.assertIsNone(split.path_gross(flat[:3], 0, 2, 5))

    def test_cutoff_unknown_and_decision(self):
        b = bars(40)
        live = dict(symbol="A", partition="recent_control", decision_ms=split.CUTOFF_MS, entry_index=20, entry_time=b[20][0])
        wrong = dict(symbol="A", partition="older_history", decision_ms=1, entry_index=20, entry_time=b[21][0])
        records, unknown = split.evaluate([live, wrong], lambda s: b)
        self.assertEqual((records, unknown), ([], 1))
        rec = lambda p, high, r: {"period": p, "decision_ms": 1_700_000_000_000 + hash((p, high, r)) % 10**9,
                                  "symbol": "A", "atr": 8 if high else 3, "high_atr": high,
                                  "card": r, "tp3": r, "no_target": r}
        good = [rec(p, True, .3) for p in split.PERIODS for _ in range(5)] + \
               [rec(p, False, -.2) for p in split.PERIODS for _ in range(5)]
        self.assertEqual(split.summarize(good)["decision"], "SUPPORTED")
        relative_only = [rec(p, True, -.05) for p in split.PERIODS for _ in range(5)] + \
                        [rec(p, False, -.2) for p in split.PERIODS for _ in range(5)]
        self.assertEqual(split.summarize(relative_only)["decision"], "PARTIAL")
        flipped = good[:5] + [rec("older_history", False, .9)] * 5 + good[5:]
        self.assertEqual(split.summarize(flipped)["decision"], "NOT_SUPPORTED")


if __name__ == "__main__":
    unittest.main()
