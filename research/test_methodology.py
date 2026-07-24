"""Research metodolojisi icin hizli, veri-dosyasi gerektirmeyen kontroller."""

import unittest

import numpy as np
import pandas as pd

import eval_final
from common import (
    HORIZONS,
    TRAIN_END,
    baseline_stats,
    bootstrap_pvalue,
    collect_event_returns,
    split_mask,
)


def _panel(index, value=1.0):
    data = {}
    for h in HORIZONS:
        data[f"fwd_{h}"] = np.full(len(index), value, dtype=float)
        data[f"fwdn_{h}"] = np.full(len(index), value, dtype=float)
    return {"X": pd.DataFrame(data, index=index)}


class SplitPurgeTests(unittest.TestCase):
    def test_train_mask_purges_only_horizon_crossing_rows(self):
        times = pd.DatetimeIndex([
            TRAIN_END - pd.Timedelta(hours=5),
            TRAIN_END - pd.Timedelta(hours=4),
            TRAIN_END - pd.Timedelta(hours=1),
            TRAIN_END,
        ])

        self.assertEqual(split_mask(times, "train").tolist(),
                         [True, True, True, False])
        self.assertEqual(split_mask(times, "train", 4).tolist(),
                         [True, False, False, False])
        self.assertEqual(split_mask(times, "test", 72).tolist(),
                         [False, False, False, True])

    def test_collection_keeps_event_but_masks_each_horizon(self):
        times = pd.DatetimeIndex([
            TRAIN_END - pd.Timedelta(hours=5),
            TRAIN_END - pd.Timedelta(hours=4),
            TRAIN_END - pd.Timedelta(hours=1),
        ])
        panel = _panel(times)
        events = {"X": (times, np.ones(len(times)))}

        ev = collect_event_returns(panel, events, "train")

        self.assertEqual(len(ev), 3)
        self.assertEqual(ev["fwd_1"].notna().tolist(), [True, True, False])
        self.assertEqual(ev["fwd_4"].notna().tolist(), [True, False, False])

    def test_baseline_uses_same_horizon_purge(self):
        times = pd.date_range(
            TRAIN_END - pd.Timedelta(hours=5), TRAIN_END,
            freq="h", inclusive="left",
        )
        panel = _panel(times)
        panel["X"]["fwd_4"] = np.arange(1, len(times) + 1, dtype=float)

        stats = baseline_stats(panel, "train")

        # Yalniz TRAIN_END-5h satirinin 4h getirisi train icinde biter.
        self.assertEqual(stats["X"].loc[4, "mean_fwd"], 1.0)


class BootstrapTests(unittest.TestCase):
    def test_plus_one_prevents_zero_pvalue(self):
        times = pd.date_range("2025-01-01", periods=4, freq="h", tz="UTC")
        panel = _panel(times, value=0.0)
        ev = pd.DataFrame({
            "sym": ["X"],
            "t": [times[0]],
            "dir": [1],
            "fwdn_1": [10.0],
        })

        pvalue = bootstrap_pvalue(panel, ev, 1, "all", n_iter=9, seed=1)

        self.assertEqual(pvalue, 0.1)

    def test_bootstrap_rejects_non_positive_iteration_count(self):
        with self.assertRaises(ValueError):
            bootstrap_pvalue({}, pd.DataFrame(), 1, "all", n_iter=0)


class CanonicalConfigTests(unittest.TestCase):
    def test_s3_matches_live_configuration(self):
        self.assertEqual(eval_final.S3_DIRECTION, "bar_up")
        self.assertTrue(eval_final.S3_LOG)
        self.assertEqual(eval_final.S3_Z, 3.0)
        self.assertEqual(eval_final.PRIMARY_H["S3"], 4)


if __name__ == "__main__":
    unittest.main()
