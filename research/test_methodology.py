"""Research metodolojisi icin hizli, veri-dosyasi gerektirmeyen kontroller."""

import unittest

import numpy as np
import pandas as pd

import eval_final
import eval_donchian_4h
import eval_delta_neutral_carry
import eval_cross_sectional_momentum
import eval_pump_short_squeeze
import eval_vwap_mr
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


class VwapCandidateTests(unittest.TestCase):
    @staticmethod
    def _trade_frame(*, signal_atr=10.0, entry_open=100.0,
                     second_z=0.0):
        index = pd.date_range("2025-01-01", periods=26, freq="h", tz="UTC")
        frame = pd.DataFrame({
            "open": np.full(26, 100.0),
            "low": np.full(26, 99.0),
            "close": np.full(26, 100.0),
            "vwap_z": np.full(26, -1.0),
            "atr14": np.full(26, signal_atr),
        }, index=index)
        frame.loc[index[1], "open"] = entry_open
        frame.loc[index[2], ["open", "low", "close", "vwap_z"]] = (
            101.0, 100.0, 102.0, second_z)
        return frame

    def test_entry_uses_next_bar_open_and_exit_uses_current_bar_close(self):
        frame = self._trade_frame()

        rows = eval_vwap_mr.trade_outcomes(
            "BTCUSDT", frame, pd.DatetimeIndex([frame.index[0]]), "train")

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["entry"], 100.0)
        self.assertEqual(rows[0]["exit"], 102.0)
        self.assertEqual(rows[0]["exit_t"], frame.index[2])
        self.assertEqual(rows[0]["reason"], "z_exit")
        self.assertAlmostEqual(rows[0]["net_pct"], 1.88)

    def test_gap_through_stop_uses_worse_next_bar_open(self):
        frame = self._trade_frame(signal_atr=1.0, entry_open=100.0,
                                  second_z=-1.0)
        frame.loc[frame.index[2], ["open", "low", "close"]] = (
            95.0, 94.0, 96.0)

        rows = eval_vwap_mr.trade_outcomes(
            "BTCUSDT", frame, pd.DatetimeIndex([frame.index[0]]), "train")

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["entry"], 100.0)
        self.assertEqual(rows[0]["exit"], 95.0)
        self.assertEqual(rows[0]["exit_t"], frame.index[2])
        self.assertEqual(rows[0]["reason"], "stop")


class DonchianCandidateTests(unittest.TestCase):
    @staticmethod
    def _bars(*, atr=20.0):
        index = pd.date_range("2025-01-01", periods=5, freq="4h", tz="UTC")
        return pd.DataFrame({
            "open": [90.0, 100.0, 82.0, 78.0, 79.0],
            "low": [88.0, 95.0, 79.0, 76.0, 77.0],
            "close": [92.0, 101.0, 80.0, 79.0, 80.0],
            "lower10": [70.0, 90.0, 90.0, 75.0, 75.0],
            "atr20": [atr] * 5,
            "entry_signal": [True, False, False, False, False],
        }, index=index)

    def test_entry_and_donchian_exit_execute_on_following_opens(self):
        bars = self._bars()

        rows, pending = eval_donchian_4h.simulate("BTCUSDT", bars, "train")

        self.assertEqual(pending, 0)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["signal_t"], bars.index[0])
        self.assertEqual(rows[0]["entry_t"], bars.index[1])
        self.assertEqual(rows[0]["entry"], 100.0)
        self.assertEqual(rows[0]["exit_t"], bars.index[3])
        self.assertEqual(rows[0]["exit"], 78.0)
        self.assertEqual(rows[0]["reason"], "donchian_exit")

    def test_gap_through_atr_stop_uses_worse_open(self):
        bars = self._bars(atr=5.0)
        bars.loc[bars.index[2], ["open", "low", "close", "lower10"]] = (
            85.0, 80.0, 84.0, 70.0)

        rows, _ = eval_donchian_4h.simulate("BTCUSDT", bars, "train")

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["stop"], 90.0)
        self.assertEqual(rows[0]["exit_t"], bars.index[2])
        self.assertEqual(rows[0]["exit"], 85.0)
        self.assertEqual(rows[0]["reason"], "atr_stop")


class DeltaNeutralCarryTests(unittest.TestCase):
    def test_funding_features_use_only_rates_known_at_each_settlement(self):
        start = pd.Timestamp("2025-01-01", tz="UTC")
        rows = [[int((start + pd.Timedelta(hours=h)).timestamp() * 1000), rate]
                for h, rate in ((0, .001), (8, .001), (16, .001), (24, -.001))]

        features = eval_delta_neutral_carry.funding_features(rows)

        self.assertTrue(pd.isna(features.iloc[1]["fund_apr72"]))
        self.assertAlmostEqual(features.iloc[2]["fund_apr72"], 36.5)
        self.assertTrue(bool(features.iloc[2]["last3_positive"]))
        self.assertFalse(bool(features.iloc[3]["last3_positive"]))

    def test_entry_is_next_hour_and_same_hour_funding_is_not_counted(self):
        index = pd.date_range("2025-01-01", periods=5, freq="h", tz="UTC")
        panel = pd.DataFrame(index=index)
        for leg, base in (("spot", 100.0), ("perp", 101.0)):
            panel[f"{leg}_open"] = base
            panel[f"{leg}_high"] = base * 1.001
            panel[f"{leg}_low"] = base * .999
            panel[f"{leg}_close"] = base
        panel["fund_rate"] = [0.001, 0.001, 0.001, np.nan, np.nan]
        panel["fund_apr72"] = 20.0
        panel["last2_nonpositive"] = False
        panel["basis_close"] = .01
        panel["entry_signal"] = [True, False, False, False, False]
        # t=2 kapanışında yakınsama görülür; çıkış t=3 açılışıdır.
        panel.loc[index[2], "basis_close"] = -0.01
        panel.loc[index[3]:, ["perp_open", "perp_high", "perp_low",
                              "perp_close"]] = 100.0

        rows, pending = eval_delta_neutral_carry.simulate(
            "BTCUSDT", panel, "train")

        self.assertEqual(pending, 0)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["signal_t"], index[0])
        self.assertEqual(rows[0]["entry_t"], index[1])
        self.assertEqual(rows[0]["exit_t"], index[3])
        # Giriş saati t=1 funding'i sayılmaz; yalnız t=2 settlement'i sayılır.
        self.assertAlmostEqual(rows[0]["funding_pct"], .001 * 101 / 201 * 100)
        self.assertEqual(rows[0]["reason"], "basis_converged")


class CrossSectionalMomentumTests(unittest.TestCase):
    def test_score_uses_old_closes_and_forward_return_uses_72h_open(self):
        index = pd.date_range(
            eval_cross_sectional_momentum.ANCHOR, periods=820, freq="h")
        raw = pd.DataFrame({
            "open_time": [int(t.timestamp() * 1000) for t in index],
            "open": np.full(len(index), 100.0),
            "close": np.full(len(index), 100.0),
        })
        # t=745 skorunun uçları t=0 ve t=720'dir. t sonrasındaki büyük hareket
        # skora girmemeli; yalnız forward return'e giriş/çıkış açılışları girer.
        raw.loc[720, "close"] = 200.0
        raw.loc[746:, "close"] = 1000.0
        raw.loc[745, "open"] = 100.0
        raw.loc[817, "open"] = 110.0

        frame = eval_cross_sectional_momentum.enrich(raw)
        t = index[745]

        self.assertEqual(frame.loc[t, "score"], 1.0)
        self.assertAlmostEqual(frame.loc[t, "forward_return"], .10)

    def test_cross_sectional_selection_is_ranked_and_weight_capped(self):
        index = pd.date_range(
            eval_cross_sectional_momentum.ANCHOR, periods=73, freq="h")
        panel = {}
        for rank in range(10):
            frame = pd.DataFrame(index=index, data={
                "open": 100.0,
                "score": float(10 - rank),
                "selection_vol": 0.01,
                "forward_return": 0.01,
            })
            if rank < 2:
                frame["forward_return"] = 0.10
            frame.loc[index[-1], "forward_return"] = np.nan
            panel[f"S{rank}"] = frame

        rows = eval_cross_sectional_momentum.portfolio_periods(
            panel, set(panel), "train")

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows.iloc[0]["n_selected"], 2)
        self.assertEqual(set(rows.iloc[0]["symbols"].split(",")), {"S0", "S1"})
        # Yalnız iki uygun varlık olduğundan %25+%25, kalan %50 nakittir.
        self.assertAlmostEqual(rows.iloc[0]["invested"], .50)
        self.assertAlmostEqual(rows.iloc[0]["gross_pct"], 5.0)


class PumpShortSqueezeTests(unittest.TestCase):
    def test_signal_uses_closed_pump_bar_metrics_and_settled_funding(self):
        index = pd.date_range("2025-01-01", periods=14, freq="h", tz="UTC")
        close = np.full(len(index), 100.0)
        close[6:] = 106.0
        perp = pd.DataFrame({
            "open_time": [int(t.timestamp() * 1000) for t in index],
            "open": close,
            "close": close,
        })
        metrics = pd.DataFrame({
            "create_time": index,
            "sum_open_interest": [100.0] * 6 + [90.0] * 8,
            "count_long_short_ratio": [1.0] * 6 + [.70] * 8,
            "sum_taker_long_short_vol_ratio": [1.0] * 6 + [1.50] * 8,
        })
        funding = [
            [int(index[0].timestamp() * 1000), -0.0002],
            # Pump barı index[6], kapanış/sinyal zamanı index[7].
            [int(index[7].timestamp() * 1000), 0.0],
        ]

        frame = eval_pump_short_squeeze.prepare(perp, metrics, funding)

        self.assertTrue(bool(frame.loc[index[6], "signal"]))
        self.assertAlmostEqual(frame.loc[index[6], "pump6"], .06)
        self.assertAlmostEqual(frame.loc[index[6], "oi_change_1h"], -.10)
        self.assertAlmostEqual(frame.loc[index[6], "funding_delta"], .0002)
        self.assertEqual(frame.loc[index[6], "funding_age_h"], 0.0)
        self.assertFalse(bool(frame.loc[index[5], "signal"]))


if __name__ == "__main__":
    unittest.main()
