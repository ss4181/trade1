"""S2 long/short ön-kayıtlı araştırmasının nedensellik testleri."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from research import s2_long_short_common as study
from research import eval_s2_derivatives_v2 as derivatives


class S2LongShortTests(unittest.TestCase):
    def test_event_generation_preserves_persistence_and_edge_trigger(self):
        times = pd.date_range("2025-01-01", periods=6, freq="8h", tz="UTC")
        frame = pd.DataFrame({
            "calc_time": [int(stamp.timestamp() * 1000) for stamp in times],
            "last_funding_rate": [-.0001, -.0003, -.0004,
                                  -.0005, -.0001, -.0004],
        })
        events = study.build_events({"AAAUSDT": frame})
        self.assertEqual(len(events), 1)
        self.assertEqual(events.iloc[0]["event_time"], times[2])
        self.assertEqual(events.iloc[0]["direction"], 1)

    def test_long_short_alignment_is_strictly_before_event(self):
        event_time = pd.Timestamp("2025-01-01T08:00:00Z")
        events = pd.DataFrame({
            "symbol": ["AAAUSDT"], "event_time": [event_time],
            "direction": [1],
        })
        metrics = pd.DataFrame({
            "create_time": [event_time - pd.Timedelta(minutes=5), event_time,
                            event_time + pd.Timedelta(minutes=5)],
            "count_long_short_ratio": [.8, .7, .6],
        })
        result = study.attach_long_short(events, {"AAAUSDT": metrics})
        self.assertEqual(result.iloc[0]["long_short_ratio"], .8)
        self.assertEqual(result.iloc[0]["metric_age_minutes"], 5)

    def test_metric_older_than_tolerance_is_not_used(self):
        event_time = pd.Timestamp("2025-01-01T08:00:00Z")
        events = pd.DataFrame({
            "symbol": ["AAAUSDT"], "event_time": [event_time],
            "direction": [1],
        })
        metrics = pd.DataFrame({
            "create_time": [event_time - pd.Timedelta(minutes=20)],
            "count_long_short_ratio": [.8],
        })
        result = study.attach_long_short(events, {"AAAUSDT": metrics})
        self.assertTrue(np.isnan(result.iloc[0]["long_short_ratio"]))

    def test_entry_and_exit_match_frozen_timing(self):
        event_time = pd.Timestamp("2025-01-01T08:00:00Z")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "um").mkdir()
            times = pd.date_range(event_time, periods=74, freq="h", tz="UTC")
            bars = pd.DataFrame({
                "open_time": [int(stamp.timestamp() * 1000)
                              for stamp in times],
                "open": np.arange(100.0, 174.0),
                "close": np.arange(100.5, 174.5),
            })
            bars.to_parquet(root / "um" / "AAAUSDT.parquet", index=False)
            events = pd.DataFrame({
                "symbol": ["AAAUSDT"], "event_time": [event_time],
                "direction": [1], "long_short_ratio": [.8],
            })
            result = study.attach_outcomes(events, root).iloc[0]
        self.assertEqual(result["entry_price"], 101.0)
        self.assertEqual(result["exit_price"], 172.5)
        expected = np.log(172.5 / 101.0) * 100
        self.assertAlmostEqual(result["gross_return_pct"], expected)
        self.assertAlmostEqual(result["net_return_pct"],
                               expected - study.ROUND_TRIP_COST_PCT)

    def test_small_sample_cannot_pass_gate(self):
        filtered = {
            "n": 13, "days": 13, "symbols": 6, "mean_net_pct": 2.6,
            "median_net_pct": .1, "win_rate": .54, "q10_net_pct": -9,
            "top5_share": .92,
        }
        rejected = {"median_net_pct": .9, "q10_net_pct": -9.2}
        passed, reasons = study.decision(
            "train", .97, filtered, rejected, 1.0, .35)
        self.assertFalse(passed)
        self.assertTrue(any("N=13" in reason for reason in reasons))
        self.assertTrue(any("p-değeri" in reason for reason in reasons))

    def test_derivatives_features_use_only_strictly_prior_rows(self):
        event_time = pd.Timestamp("2025-01-02T08:00:00Z")
        events = pd.DataFrame({
            "symbol": ["AAAUSDT"], "event_time": [event_time],
            "direction": [1],
        })
        metrics = pd.DataFrame({
            "create_time": [
                event_time - pd.Timedelta(hours=8, minutes=5),
                event_time - pd.Timedelta(hours=8),
                event_time - pd.Timedelta(minutes=5), event_time,
            ],
            "sum_open_interest": [100, 999, 120, 999],
            "count_long_short_ratio": [.8, 9, .9, 9],
            "sum_toptrader_long_short_ratio": [.6, 9, .7, 9],
        })
        funding_times = [event_time - pd.Timedelta(hours=8), event_time]
        funding = pd.DataFrame({
            "calc_time": [int(stamp.timestamp() * 1000)
                          for stamp in funding_times],
            "last_funding_rate": [-.0003, -.0004],
        })
        row = study.attach_derivatives_features(
            events, {"AAAUSDT": metrics}, {"AAAUSDT": funding}).iloc[0]
        self.assertAlmostEqual(row["oi_change_8h"], .2)
        self.assertAlmostEqual(row["global_ls_change_8h"], .125)
        self.assertEqual(row["top_position_ls"], .7)
        self.assertAlmostEqual(row["funding_delta"], -.0001)

    def test_frozen_candidate_conditions(self):
        rows = pd.DataFrame({
            "oi_change_8h": [.1, -.1],
            "top_position_ls": [.8, .8],
            "funding_delta": [-.0001, .0001],
            "global_ls_change_8h": [.05, .05],
        })
        complete, selected = derivatives.candidate_masks(
            rows, "OI_SHORT_BUILD")
        self.assertEqual(complete.tolist(), [True, True])
        self.assertEqual(selected.tolist(), [True, False])
        _, divergence = derivatives.candidate_masks(
            rows, "FUNDING_LS_DIVERGENCE")
        self.assertEqual(divergence.tolist(), [True, False])


if __name__ == "__main__":
    unittest.main()
