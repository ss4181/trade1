import math
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from paper_execution import ExecutionSpec, evaluate_path, simple_return_pct, log_price_return_to_simple_pct

M = 300_000
BASE = 1_735_689_600_000


def bars():
    return [{"open_time": BASE+(i+1)*M, "open": 100., "high": 100.5,
             "low": 99.5, "close": 100.} for i in range(12)]


class PaperTests(unittest.TestCase):
    def run_path(self, data=None, **kwargs):
        params = dict(delivered_at_ms=BASE, delivery_confirmed=True, market="spot",
                      candle_market="spot", symbol="BTCUSDT", candle_symbol="BTCUSDT",
                      spec=ExecutionSpec(horizon_hours=1), as_of_ms=BASE+13*M)
        params.update(kwargs)
        return evaluate_path(bars() if data is None else data, **params)

    def test_reference_price_is_never_entry_and_timeout_is_exact(self):
        data = bars()
        data[0].update(open=100.2, high=100.5)
        data[-1]["close"] = 100.3
        out = self.run_path(data)
        self.assertEqual(out["entry_time_ms"], BASE+M)
        self.assertEqual(out["entry_price"], 100.2)
        self.assertEqual(out["exit_window_end_ms"], BASE+13*M)
        self.assertEqual(out["exit_reason"], "timeout")
        self.assertAlmostEqual(out["gross_return_pct"], (100.3/100.2-1)*100)
        self.assertAlmostEqual(out["net_return_pct"], out["gross_return_pct"]-.12)

    def test_same_bar_uncertainty_stop_first(self):
        data = bars()
        data[0].update(high=104, low=97)
        out = self.run_path(data)
        self.assertEqual(out["exit_reason"], "stop")
        self.assertTrue(out["same_bar_ambiguous"])
        self.assertFalse(out["tp_before_sl_lower"])
        self.assertTrue(out["tp_before_sl_upper"])
        self.assertAlmostEqual(out["net_return_pct"], -1.62)

    def test_target_can_win_before_later_stop(self):
        data = bars()
        data[0]["high"] = 102.1
        data[1]["low"] = 80
        out = self.run_path(data)
        self.assertEqual(out["exit_reason"], "target")
        self.assertAlmostEqual(out["net_return_pct"], 1.88)
        self.assertEqual(out, self.run_path(data[:1]))  # no post-exit candles needed

    def test_opening_gap_stop_is_not_a_guaranteed_price(self):
        data = bars()
        data[1].update(open=96, low=95, high=103, close=100)
        out = self.run_path(data)
        self.assertEqual(out["exit_reason"], "stop_gap")
        self.assertFalse(out["same_bar_ambiguous"])
        self.assertAlmostEqual(out["net_return_pct"], -4.12)
        data[1].update(open=103, low=95, high=104, close=100)
        out = self.run_path(data)
        self.assertEqual(out["exit_reason"], "target_gap")
        self.assertAlmostEqual(out["net_return_pct"], 1.88)

    def test_pending_gaps_duplicates_and_no_future_candle_leak(self):
        data = bars()
        data[0]["high"] = 110
        self.assertEqual(self.run_path(data, as_of_ms=BASE+M+1)["status"], "pending")
        self.assertEqual(self.run_path(bars()[1:])["reason"], "missing_required_candle")
        self.assertEqual(self.run_path(bars()+[dict(bars()[0])])["status"], "measured")
        conflict = dict(bars()[0], close=100.1)
        self.assertEqual(self.run_path(bars()+[conflict])["reason"], "conflicting_candle")

    def test_delivery_latency_contract_and_funding_fail_closed(self):
        self.assertEqual(self.run_path(delivery_confirmed=False)["reason"], "delivery_not_confirmed")
        self.assertEqual(self.run_path(candle_market="um_perp")["reason"], "market_mismatch_or_unsupported")
        self.assertEqual(self.run_path(candle_symbol="1000BTCUSDT")["reason"], "contract_mismatch")
        out = self.run_path(market="um_perp", candle_market="um_perp")
        self.assertIsNone(out["net_return_pct"])
        self.assertEqual(out["funding_status"], "not_modeled")
        self.assertAlmostEqual(out["net_ex_funding_return_pct"], -.12)
        out = self.run_path(spec=ExecutionSpec(horizon_hours=1, latency_ms=M))
        self.assertEqual(out["entry_time_ms"], BASE+2*M)
        self.assertEqual(out["status"], "pending")

    def test_only_pre_exit_candle_conflicts_invalidate_event(self):
        first = dict(bars()[0], high=103)
        later = bars()[1]
        conflict = dict(later, close=100.1)
        expected = self.run_path([first])
        self.assertEqual(expected, self.run_path([first, later, conflict]))
        self.assertEqual(expected, self.run_path([conflict, later, first]))
        self.assertEqual(expected, self.run_path([first, dict(later, open_time=BASE+100*M+1)]))
        self.assertEqual(self.run_path([first, dict(first, close=100.1)])["reason"], "conflicting_candle")
        self.assertEqual(self.run_path([dict(first, open_time=first["open_time"]+1)])["reason"], "invalid_candle_timestamp")
        self.assertEqual(self.run_path([None])["reason"], "invalid_candle_timestamp")

    def test_short_simple_not_inverse_return_and_invalid_prices(self):
        self.assertAlmostEqual(simple_return_pct(100, 90, "SHORT"), 10)
        self.assertAlmostEqual(log_price_return_to_simple_pct(math.log(.9), "SHORT"), 10)
        self.assertAlmostEqual(log_price_return_to_simple_pct(math.log(1.5)), 50)
        data = bars()
        data[0]["low"] = 97
        out = self.run_path(data, market="um_perp", candle_market="um_perp", direction="SHORT")
        self.assertEqual(out["exit_reason"], "target")
        self.assertAlmostEqual(out["gross_return_pct"], 2)
        self.assertEqual(self.run_path(direction="SHORT")["reason"], "spot_borrow_not_modeled")
        data[0]["open"] = float("nan")
        self.assertEqual(self.run_path(data)["reason"], "invalid_ohlc")
        with self.assertRaises(ValueError):
            ExecutionSpec(target_pct=float("nan"))


if __name__ == "__main__":
    unittest.main()
