"""Legacy live oracle and canonical replay parity; isolated runner only."""
import math
from pathlib import Path
import random
import sys
import types
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import signal_bot as bot
import strategy_engine as engine
from research.replay_live_engine import replay

H = engine.HOUR_MS
BASE = 1_735_689_600_000


def history(n=460):
    rng = random.Random(17)
    close, bars = 100.0, []
    for i in range(n):
        opened = close
        close *= 1 + (rng.choice([-.006, -.003, .001, .002, .004])
                      if i % 120 < 90 else rng.choice([-.04, -.01, .003]))
        bars.append({"open_time": BASE+i*H, "open": opened, "close": close,
                     "high": max(opened, close)*1.001,
                     "low": min(opened, close)*.999,
                     "volume": 1e7 if i % 29 == 0 else 100 + i % 7})
    return bars


def oracle():
    namespace = dict(vars(bot))
    source = (Path(__file__).parent / "fixtures" / "live_math_v0.py").read_text(encoding="utf-8")
    exec(compile(source, "live_math_v0.py", "exec"), namespace)
    return namespace


class EngineTests(unittest.TestCase):
    def test_effective_rules_provenance_and_legacy_unknown(self):
        self.assertEqual(bot.core_rules_for_research(), engine.CoreRules())
        data = bot._core_engine_provenance("S5")
        self.assertEqual(data["engine_config_hash"], engine.CoreRules().fingerprint())
        self.assertEqual(bot._core_engine_provenance("G1"), {})
        with patch.object(bot, "KLINE_LIMIT", 1):
            self.assertIsNone(bot._core_engine_provenance("S2")["engine_config_hash"])
        legacy = {"entry_ref": 100, "targets": {}, "status": "expired"}
        self.assertEqual(bot._price_target_public(legacy)["config_version"], "UNKNOWN")
        self.assertNotIn("config_version", legacy)

    def test_audit_refuses_historical_test_before_reading_data(self):
        from research.audit_live_parity import audit
        with self.assertRaisesRegex(ValueError, "do_not_reopen"):
            audit("nonexistent", ["BTCUSDT"], "2026-01-01", "2026-01-08")

    def test_random_and_flat_indicator_exact_legacy_parity(self):
        old = oracle()
        bars = history()
        for count in (0, 1, 14, 15, 98, 168, 249, 460):
            for values in ([b["close"] for b in bars[:count]], [1.0]*count):
                for period in (7, 14, 21):
                    a, b = old["calc_rsi"](values, period), engine.wilder_rsi(values, period)
                    self.assertEqual([None if math.isnan(x) else x for x in a],
                                     [None if math.isnan(x) else x for x in b])
            volumes = [b["volume"] for b in bars[:count]]
            for window in (1, 24, 168):
                a, b = old["calc_volume_zscore"](volumes, window), engine.log_volume_zscore(volumes, window)
                self.assertEqual([None if math.isnan(x) else x for x in a],
                                 [None if math.isnan(x) else x for x in b])
        self.assertEqual(engine.wilder_rsi([100]*20)[-1], 100)

    def test_divergence_and_threshold_edges(self):
        old = oracle()
        bars = history()
        closes, lows = [b["close"] for b in bars], [b["low"] for b in bars]
        rsi = engine.wilder_rsi(closes)
        for i in range(len(bars)):
            self.assertEqual(old["bullish_divergence"](closes, lows, rsi, i),
                             engine.bullish_divergence(lows, rsi, i))
        self.assertTrue(engine.volume_spike(3.0, 3.0))
        self.assertFalse(engine.volume_spike(math.nan, 3.0))
        self.assertTrue(engine.oversold(22.5, 22.5))
        self.assertTrue(engine.recent_volume_spike([3.] + [0.]*24, 24, 24, 3))
        self.assertFalse(engine.recent_volume_spike([3.] + [0.]*25, 25, 24, 3))
        self.assertTrue(engine.funding_squeeze([{"rate": -.0003}]*2, -.03, 2))
        self.assertFalse(engine.funding_squeeze([{"rate": -.0003}], -.03, 2))

    def test_state_exact_parity_first_scan_edges_and_cooldowns(self):
        old = oracle()
        ref = types.SimpleNamespace(prev_cond={}, last_fire={})
        actual = bot.ScanState()
        conditions = [True, True, False, True, False, True, False, True]
        hours = [0, 1, 2, 3, 4, 5, 15, 16]
        expected = [False, False, False, True, False, False, False, True]
        got = []
        for cond, hour in zip(conditions, hours):
            now = BASE/1000 + hour*3600
            a = old["should_fire"](ref, "S3", "BTCUSDT", cond, 12, now)
            b = actual.should_fire("S3", "BTCUSDT", cond, 12, now)
            self.assertEqual(a, b)
            self.assertEqual((ref.prev_cond, ref.last_fire), (actual.prev_cond, actual.last_fire))
            got.append(b)
        self.assertEqual(got, expected)

    def test_full_scan_and_replay_agree_including_funding_millisecond(self):
        bars = history()
        funding = [{"time": BASE + i*H + 9,
                    "rate": -.001 if i % 32 >= 16 else .001}
                   for i in range(0, len(bars)+1, 8)]
        scans = [BASE+i*H for i in range(98, len(bars)+1)]
        old = oracle()
        ref = types.SimpleNamespace(prev_cond={}, last_fire={})
        ref.should_fire = types.MethodType(old["should_fire"], ref)
        actual = bot.ScanState()
        ref_events, actual_events = [], []
        settings = {"S2_DERIVATIVES_SHADOW_ENABLED": False,
                    "DISABLED_STRATEGIES": set(), "EXTENDED_SET": set()}
        with patch.multiple(bot, **settings):
            old.update(settings)
            for now in scans:
                closed = [b for b in bars if b["open_time"]+H <= now][-249:]
                known = [r for r in funding if r["time"] <= now][-3:]
                mocks = {"fetch_klines": lambda *a, rows=closed, **k: rows,
                         "fetch_funding": lambda *a, rows=known, **k: rows,
                         "fetch_futures_price": lambda *a: 100.0,
                         "market_regime_snapshot": lambda: {"label": "UNKNOWN"}}
                old.update(mocks)
                with patch.multiple(bot, **mocks), patch.object(bot.time, "time", return_value=now/1000):
                    before = old["scan_symbol"]("BTCUSDT", ref)
                    after = bot.scan_symbol("BTCUSDT", actual)
                self.assertEqual(before, after)
                self.assertEqual(ref.prev_cond, actual.prev_cond)
                self.assertEqual(ref.last_fire, actual.last_fire)
                ref_events.extend(before)
                actual_events.extend(after)
        replayed = replay(bars, funding, scans, symbol="BTCUSDT", universe="core30",
                          rules=engine.CoreRules())
        def simplify(event):
            from datetime import datetime
            stamp = event.get("bar_time_ms")
            if stamp is None:
                stamp = round(datetime.fromisoformat(event["bar_time"]).timestamp()*1000)
            return event["strategy"], stamp
        self.assertEqual([simplify(e) for e in actual_events],
                         [simplify(e) for e in replayed["events"]])
        self.assertTrue(any(e["strategy"] == "S2" for e in ref_events))
        self.assertTrue(any(e["strategy"] == "S3" for e in ref_events))
        self.assertTrue(any(e["strategy"].startswith("S1") for e in ref_events))

    def test_future_data_cannot_change_past_replay(self):
        bars = history(350)
        scans = [BASE+i*H for i in range(98, 290)]
        args = dict(symbol="BTCUSDT", universe="core30", rules=engine.CoreRules())
        short = replay(bars[:289], [], scans, **args)
        future = replay(bars, [{"time": BASE+300*H, "rate": -.1}], scans, **args)
        self.assertEqual(short, future)
        # Millisecond settlement at hh:00:00.009 is unknown at hh:00:00.000.
        fr = [{"time": BASE+100*H, "rate": .001},
              {"time": BASE+108*H, "rate": -.001},
              {"time": BASE+116*H+9, "rate": -.001}]
        out = replay(bars, fr, [BASE+108*H, BASE+116*H, BASE+116*H+9], **args)
        s2 = [e for e in out["events"] if e["strategy"] == "S2"]
        self.assertEqual(len(s2), 1)
        self.assertEqual(s2[0]["decision_time_ms"], BASE+116*H+9)

    def test_window_seed_doji_gap_and_config(self):
        rules, bars = engine.CoreRules(), history(310)
        f = engine.closed_window_features(bars, rules)
        tail = bars[-249:]
        self.assertEqual(f["rsi"], engine.wilder_rsi([b["close"] for b in tail])[-1])
        doji = [dict(b) for b in bars]
        doji[-1]["open"] = doji[-1]["close"]
        doji[-1]["volume"] = 1e20
        f = engine.closed_window_features(doji, rules)
        self.assertTrue(f["s3_spike"])
        self.assertFalse(f["green_bar"])
        with self.assertRaisesRegex(ValueError, "noncontiguous"):
            engine.closed_window_features(bars[:-10]+bars[-9:], rules)
        self.assertNotEqual(rules.fingerprint(), engine.CoreRules(oversold=23).fingerprint())
        with self.assertRaises(ValueError):
            engine.CoreRules(kline_limit=10)

    def test_extended_disabled_and_observe_keep_policy(self):
        bars = history()
        scans = [BASE+i*H for i in range(98, len(bars)+1)]
        args = dict(symbol="BTCUSDT", universe="observe", rules=engine.CoreRules())
        out = replay(bars, [], scans, observe=True, **args)
        self.assertTrue(out["events"])
        self.assertTrue(all(e["strategy"] in ("S5", "S6") for e in out["events"]))
        off = replay(bars, [], scans, disabled=("S1", "S2", "S3"), **args)
        self.assertFalse(off["events"])


if __name__ == "__main__":
    unittest.main()
