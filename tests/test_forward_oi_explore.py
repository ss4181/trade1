"""Forward OI discovery diagnostics tests."""

from __future__ import annotations

import unittest

from research.explore_forward_oi import (
    COST_BPS,
    build_features,
    conditions,
    independent_events,
    summarize,
)


class ForwardOIExploreTests(unittest.TestCase):
    def _panel(self):
        rows = {}
        for hour in range(41):
            rows[hour] = {
                "symbol": "AAAUSDT", "hour": hour,
                "price": 100.0, "oi": 100.0, "ls": 0.8,
                "taker_ratio": 1.2, "taker_buy": 60.0,
                "taker_sell": 40.0, "funding": -0.001,
                "basis": 0.001, "raw_time": f"{hour:03d}",
            }
        rows[30].update({
            "price": 106.0, "oi": 103.0, "taker_buy": 200.0,
            "taker_sell": 100.0, "funding": 0.001,
        })
        rows[31]["price"] = 107.0       # next snapshot is the entry
        rows[35]["price"] = 110.0       # entry + 4h is the exit
        return {"AAAUSDT": rows}

    def test_features_use_lags_and_next_snapshot_entry(self):
        features = build_features(self._panel())
        row = next(item for item in features if item["hour"] == 30)
        self.assertAlmostEqual(row["return_24h"], .06)
        self.assertAlmostEqual(row["oi_change_1h"], .03)
        self.assertAlmostEqual(row["volume_ratio"], 3.0)
        self.assertEqual(row["entry_price"], 107.0)
        self.assertEqual(row["exit_price"], 110.0)
        self.assertAlmostEqual(
            row["net_return"], 110 / 107 - 1 - COST_BPS / 10_000)

    def test_fixed_filter_ladder_and_summary(self):
        features = build_features(self._panel())
        row = next(item for item in features if item["hour"] == 30)
        flags = conditions(row)
        self.assertTrue(flags["P0_top10_gainer5"])
        self.assertTrue(flags["P4_plus_short_majority"])
        self.assertTrue(flags["P5_plus_funding_rise"])
        events = independent_events(features, "P5_plus_funding_rise")
        self.assertEqual([event["hour"] for event in events], [30])
        summary = summarize(events)
        self.assertEqual(summary["n"], 1)
        self.assertEqual(summary["n_pending"], 0)
        self.assertEqual(summary["sample_warning"], "small_sample")

    def test_pending_outcomes_do_not_change_same_hour_rank(self):
        panel = self._panel()
        panel["ZZZUSDT"] = {
            hour: {**row, "symbol": "ZZZUSDT", "price": (
                120.0 if hour == 40 else 100.0)}
            for hour, row in self._panel()["AAAUSDT"].items()
        }
        features = build_features(panel)
        pending = next(item for item in features
                       if item["symbol"] == "ZZZUSDT" and item["hour"] == 40)
        self.assertEqual(pending["rank_24h"], 1)
        self.assertIsNone(pending["net_return"])


if __name__ == "__main__":
    unittest.main()
