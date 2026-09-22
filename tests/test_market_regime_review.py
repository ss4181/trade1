"""Numerical/clock regression checks for the offline regime research adapter."""
import sys
from pathlib import Path
import unittest

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from research.market_regime_review import (DAY, HOUR, CoreRules, block_interval,
    daily_table, features_fast, labels, return_grid, touch_grid,
    validate_adapter)
from strategy_engine import closed_window_features


def raw_daily(closes):
    start = 1704067200000
    return {"rows": [[start+i*DAY, str(c), str(c), str(c), str(c), "1",
                       start+(i+1)*DAY-1] for i, c in enumerate(closes)]}


class RegimeReviewTests(unittest.TestCase):
    def test_warmup_and_regime_states(self):
        for values, expected in [(np.arange(100., 340.), "BULL"),
                                 (np.arange(340., 100., -1), "BEAR"),
                                 (np.full(240, 100.), "TRANSITION")]:
            frame = daily_table(raw_daily(values))
            self.assertEqual(frame.regime.iloc[218], "UNKNOWN")
            self.assertEqual(frame.regime.iloc[-1], expected)

    def test_asof_boundary_and_stale(self):
        frame = daily_table(raw_daily(np.arange(100., 340.)))
        at = int(frame.available_ms.iloc[-1])
        first, _ = labels(frame, [at-1, at, at+DAY-1, at+DAY])
        self.assertEqual(first[-1], "UNKNOWN")
        old = frame.copy()
        old.loc[old.index[-1], ["regime", "subtype"]] = "BEAR"
        got, _ = labels(old, [at-1, at])
        self.assertEqual(got.tolist(), ["BULL", "BEAR"])

    def test_reject_gap_and_duplicate(self):
        for delta in (DAY, -DAY):
            raw = raw_daily(np.arange(100., 340.))
            raw["rows"][100][0] += delta
            with self.assertRaises(ValueError):
                daily_table(raw)

    def test_fast_window_parity_all_windows(self):
        rng = np.random.default_rng(123)
        close = 100*np.exp(np.cumsum(rng.normal(0, .015, 340)))
        op = np.r_[close[0], close[:-1]]
        volume = np.exp(rng.normal(10, 2, len(close)))
        frame = pd.DataFrame({"open_time": np.arange(len(close))*HOUR,
            "open": op, "close": close, "low": np.minimum(op, close)*.99,
            "high": np.maximum(op, close)*1.01, "volume": volume, "valid": True})
        rules = CoreRules()
        fast = features_fast(frame, rules)
        self.assertGreater(validate_adapter(frame, fast, rules), 0)
        bars = frame.drop(columns="valid").to_dict("records")
        for row in fast.itertuples(index=False):
            expected = closed_window_features(bars[row.i-248:row.i+1], rules)
            for name in ("s1", "s3_spike", "s4", "green_bar"):
                self.assertEqual(bool(getattr(row, name)), expected[name])
            self.assertAlmostEqual(row.rsi, expected["rsi"], places=9)
            self.assertAlmostEqual(row.volume_logz, expected["volume_logz"], places=9)

    def test_time_exit_next_open_horizon_and_gap(self):
        frame = pd.DataFrame({"open_time": (np.arange(8)+500000)*HOUR,
                              "open": np.full(8, 100.), "close": np.arange(101.,109.),
                              "valid": True})
        got = return_grid(frame, 4)
        self.assertAlmostEqual(got.iloc[0], 3.88)
        self.assertTrue(np.isnan(got.iloc[-3]))
        frame.loc[2, "valid"] = False
        self.assertTrue(np.isnan(return_grid(frame, 4).iloc[0]))

    def test_touch_grid_uses_entry_bar_and_rejects_future_gap(self):
        frame = pd.DataFrame({
            "open_time": (np.arange(5)+500000)*HOUR,
            "open": [100., 100., 100., 100., 100.],
            "high": [102., 101., 103., 100., 100.],
            "low": [99., 99., 99., 99., 99.],
            "close": [100., 100., 100., 100., 100.],
            "valid": True,
        })
        got = touch_grid(frame, 3)
        self.assertTrue(bool(got.tp2_touch.iloc[0]))
        self.assertTrue(bool(got.tp3_touch.iloc[0]))
        self.assertTrue(np.isnan(got.tp3_touch.iloc[3]))
        frame.loc[2, "valid"] = False
        self.assertTrue(np.isnan(touch_grid(frame, 3).tp2_touch.iloc[0]))

    def test_no_interval_for_one_cluster(self):
        frame = pd.DataFrame({"time_ms": [100*DAY]*100})
        self.assertIsNone(block_interval(frame, np.ones(100)))
        frame = pd.DataFrame({"time_ms": np.arange(50)*DAY})
        self.assertEqual(block_interval(frame, np.ones(50)), [1., 1.])


if __name__ == "__main__":
    unittest.main()
