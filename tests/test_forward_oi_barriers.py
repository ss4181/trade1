"""Five-minute forward OI barrier diagnostics tests."""

from __future__ import annotations

import csv
import io
import unittest
import zipfile

from research.eval_forward_oi_barriers import (
    BAR_MS,
    break_even_win_rate,
    entry_time_ms,
    event_days,
    parse_kline_zip,
    simulate_long,
    summarize_outcomes,
    window_for_event,
)


def bar(opened, o=100.0, h=100.5, low=99.5, close=100.0):
    return {"open_time_ms": opened, "open": o, "high": h,
            "low": low, "close": close}


class ForwardOIBarrierTests(unittest.TestCase):
    def setUp(self):
        self.event = {
            "symbol": "AAAUSDT", "contract": "1000AAAUSDT",
            "hour": 30, "entry_hour": 31,
        }
        self.start = entry_time_ms(self.event)

    def test_entry_and_days_match_next_exact_hour(self):
        self.assertEqual(self.start, 31 * 3600 * 1000)
        crossing = {**self.event, "entry_hour": 23}
        self.assertEqual(len(event_days(crossing, 24)), 2)

    def test_target_stop_timeout_and_same_bar_policy(self):
        target = [bar(self.start + i * BAR_MS) for i in range(12)]
        target[3] = bar(self.start + 3 * BAR_MS, h=102.1, low=99.7)
        result = simulate_long(target, 2, 1.5)
        self.assertEqual(result["outcome"], "TARGET")
        self.assertAlmostEqual(result["net_return_pct"], 1.88, places=6)

        stopped = [bar(self.start + i * BAR_MS) for i in range(12)]
        stopped[2] = bar(self.start + 2 * BAR_MS, h=100.2, low=98.4)
        self.assertEqual(simulate_long(stopped, 2, 1.5)["outcome"], "STOP")

        ambiguous = [bar(self.start, h=102.2, low=98.4)]
        amb = simulate_long(ambiguous, 2, 1.5)
        self.assertEqual(amb["outcome"], "AMBIGUOUS_AS_STOP")
        self.assertAlmostEqual(amb["net_return_pct"], -1.62, places=6)

        timeout = [bar(self.start + i * BAR_MS, close=100.4)
                   for i in range(12)]
        self.assertEqual(simulate_long(timeout, 2, 1.5)["outcome"], "TIMEOUT")

    def test_window_requires_every_five_minute_bar(self):
        day = "1970-01-02"
        bars = [bar(self.start + i * BAR_MS) for i in range(48)]
        daily = {("1000AAAUSDT", day): bars}
        window, reason = window_for_event(self.event, daily, 4)
        self.assertEqual(len(window), 48)
        self.assertIsNone(reason)
        daily[("1000AAAUSDT", day)] = bars[:-1]
        window, reason = window_for_event(self.event, daily, 4)
        self.assertEqual(window, [])
        self.assertEqual(reason, "missing_5m_bars:1")

    def test_summary_keeps_ambiguity_bounds_and_missing(self):
        rows = [
            {"available": True, "outcome": "TARGET", "net_return_pct": 1.88,
             "entry_time_ms": self.start, "minutes_to_exit": 20,
             "mae_pct": -0.2},
            {"available": True, "outcome": "AMBIGUOUS_AS_STOP",
             "net_return_pct": -1.62, "entry_time_ms": self.start + 86_400_000,
             "minutes_to_exit": 10, "mae_pct": -1.6},
            {"available": False, "unavailable_reason": "missing"},
        ]
        summary = summarize_outcomes(rows, 3)
        self.assertEqual(summary["n"], 2)
        self.assertEqual(summary["n_unavailable"], 1)
        self.assertEqual(summary["target_first_pct_lower"], 50.0)
        self.assertEqual(summary["target_first_pct_upper"], 100.0)
        self.assertEqual(summary["ambiguous_count"], 1)

    def test_zip_parser_handles_header_and_deduplicates(self):
        stream = io.StringIO()
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(["open_time", "open", "high", "low", "close",
                         "volume", "close_time"])
        writer.writerow([self.start, 100, 102, 99, 101, 10,
                         self.start + BAR_MS - 1])
        writer.writerow([self.start, 100, 103, 98, 102, 11,
                         self.start + BAR_MS - 1])
        raw = io.BytesIO()
        with zipfile.ZipFile(raw, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("AAAUSDT-5m.csv", stream.getvalue())
        parsed = parse_kline_zip(raw.getvalue())
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0]["high"], 103.0)

    def test_break_even_includes_round_trip_cost(self):
        self.assertAlmostEqual(break_even_win_rate(2, 1.5), 46.2857, places=3)


if __name__ == "__main__":
    unittest.main()
