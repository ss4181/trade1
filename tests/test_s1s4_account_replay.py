"""s1s4-account-replay-v1 mechanics — offline, injected klines, no network."""
import json
from pathlib import Path
import tempfile
import unittest

from research import replay_s1s4_account as replay

M, H = replay.MINUTE, replay.HOUR
T0 = 1_780_000_000_000 // H * H


class ReplayTests(unittest.TestCase):
    def test_load_events_from_all_sources_dedups_and_filters(self):
        with tempfile.TemporaryDirectory() as folder:
            dash = Path(folder) / "data.json"
            dash.write_text(json.dumps({"signals": [
                {"strategy": "S1+S4", "symbol": "AAAUSDT", "t": "2026-11-01T10:00:00+00:00",
                 "notified_at": "2026-11-01T11:00:09+00:00", "universe": "core30", "performance_market": "spot"},
                {"strategy": "S3", "symbol": "AAAUSDT", "t": "2026-11-01T10:00:00+00:00"}]}))
            log = Path(folder) / "signals.log"
            log.write_text("\n".join(json.dumps(r) for r in (
                {"strategy": "S1+S4", "symbol": "AAAUSDT", "bar_time": "2026-11-01T10:00:00+00:00",
                 "notified_at": "2026-11-01T11:00:30+00:00"},
                {"strategy": "S1+S4", "symbol": "BBBUSDT", "bar_time": "2026-11-02T10:00:00+00:00"})) + "\n")
            arch = Path(folder) / "events.jsonl"
            arch.write_text(json.dumps({"strategy": "S1+S4", "symbol": "CCCUSDT", "market": "spot",
                                        "signal_ms": T0, "anchor_ms": T0 + H + 5*M}) + "\n" +
                            json.dumps({"strategy": "S1+S4", "symbol": "DDDUSDT", "market": "um",
                                        "signal_ms": T0, "anchor_ms": T0 + H}) + "\n")
            events = replay.load_events([dash, log, arch])
        self.assertEqual([e["symbol"] for e in events], ["CCCUSDT", "AAAUSDT", "BBBUSDT"])
        by = {e["symbol"]: e for e in events}
        self.assertEqual(set(by), {"AAAUSDT", "BBBUSDT", "CCCUSDT"})
        self.assertEqual(by["AAAUSDT"]["entry_ms"], replay.ms("2026-11-01T11:01:00+00:00"))
        self.assertEqual(by["BBBUSDT"]["entry_ms"], replay.ms("2026-11-02T11:01:00+00:00"))
        self.assertEqual(by["CCCUSDT"]["entry_ms"], T0 + H + 5*M)

    def test_outcome_time_exit_disaster_gap_stop_first_and_unknown(self):
        flat = [(T0 + k*M, 100, 100.5, 99.5, 100 + (k == 1439) * 3) for k in range(1440)]
        self.assertAlmostEqual(replay.outcome(flat, T0)[0], 3.0)
        gap = list(flat)
        gap[10] = (T0 + 10*M, 80, 81, 79, 80)
        self.assertAlmostEqual(replay.outcome(gap, T0, disaster=15)[0], -20.0)
        both = list(flat)
        both[0] = (T0, 100, 103, 96, 100)
        self.assertAlmostEqual(replay.outcome(both, T0, target=2, atr_stop=1.5, atr=2)[0], -3.0)
        self.assertIsNone(replay.outcome(flat[:1439], T0))
        self.assertIsNone(replay.outcome(flat, T0, target=2, atr_stop=1.5, atr=None))
        self.assertEqual(len([b for b in flat if b[0] < T0 + 240*M]), 240)
        self.assertAlmostEqual(replay.outcome(flat, T0, target=2, atr_stop=1.5, atr=2, limit=240)[0], 0.0)

    def test_account_slots_skip_busy_signals_and_compound(self):
        trades = [(0, "A", 10, 10.2), (5, "A", 15, 10.2), (20, "A", 30, -9.8)]
        n, ret, dd = replay.account(trades, 1, 0.2)
        self.assertEqual(n, 2)
        self.assertAlmostEqual(ret, (1.10 * 0.90 - 1) * 100)
        self.assertAlmostEqual(dd, -10.0)
        n2, ret2, _ = replay.account(trades, 2, 0.2)
        self.assertEqual(n2, 3)
        self.assertAlmostEqual(ret2, (1.05 * 1.05 * 0.95 - 1) * 100)
        # Same-minute ties are taken by symbol, not by outcome.
        tie = [(0, "BBB", 10, 50.2), (0, "AAA", 10, -9.8)]
        self.assertAlmostEqual(replay.account(tie, 1, 0.2)[1], -10.0)

    def test_evaluate_uses_cache_and_counts_unknown(self):
        calls = []
        def get(params):
            calls.append(params)
            if params["interval"] == "1h":
                end = params["endTime"] + 1
                return [[end - (16-k)*H, 0, 102, 98, 100, 0, end - (15-k)*H - 1] for k in range(16)]
            start = params["startTime"]
            return [[start + k*M, 100, 101, 99, 100.5] for k in range(params["limit"])]
        events = [{"symbol": "AAAUSDT", "signal_ms": T0, "entry_ms": T0 + H + M,
                   "universe": "core30", "config_version": "x"}]
        with tempfile.TemporaryDirectory() as folder:
            klines = replay.Klines(folder, get)
            first = replay.evaluate(events, klines)
            again = replay.evaluate(events, replay.Klines(folder, lambda p: self.fail("network")))
        self.assertEqual(len(calls), 3)
        self.assertEqual(first, again)
        self.assertAlmostEqual(first["plans"]["time24"]["mean_net_pct"], 0.3)
        self.assertEqual(first["plans"]["card"]["n"], 1)
        self.assertEqual(first["unknown"], {})


if __name__ == "__main__":
    unittest.main()
