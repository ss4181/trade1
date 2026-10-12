"""Causal forward paths and paired reporting, using only synthetic candles."""
import copy
from datetime import datetime, timezone
import json
from pathlib import Path
import random
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import execution_shadow as e
from research.review_execution_shadow import summarize

T = 1_800_000_000_000
STEP = e.STEP


def iso(t):
    return datetime.fromtimestamp(t/1000, timezone.utc).isoformat()


def source(strategy="S1"):
    universe, market, hours = {"S1": ("extended59", "spot", 24),
                              "S3": ("core30", "spot", 4),
                              "G2": ("g2_fixed87_binance_signal_universe", "um_perp", 24)}[strategy]
    return dict(strategy=strategy, symbol="LDOUSDT" if strategy == "S1" else "BTCUSDT",
                direction="LONG", universe=universe, performance_market=market,
                performance_symbol="LDOUSDT" if strategy == "S1" else "BTCUSDT",
                config_version="synthetic-v1", engine_version="live-compatible-v1",
                engine_config_hash="b"*64, delivery_confirmed=True, push_allowed=True,
                delivered_at=iso(T+1000), planned_entry_at=iso(T+3_600_000),
                horizon_hours=hours, market_regime="BULL")


def event(strategy="S1"):
    return e.create_event(source(strategy), "a"*32, T, T+1000)


def bar(t, o=100, h=101, l=99, c=100):
    return dict(open_time=t, open=o, high=h, low=l, close=c, close_time=t+STEP-1)


class EngineTests(unittest.TestCase):
    def test_exact_boundary_strict_next_and_g2_scheduled(self):
        r = source(); r["delivered_at"] = iso(T)
        self.assertEqual(e.create_event(r, "a"*32, T, T)["anchor_ms"], T+STEP)
        g = event("G2")
        self.assertEqual(g["anchor_ms"], T+3_600_000)
        r = source("G2"); r["delivered_at"] = r["planned_entry_at"]
        self.assertIsNone(e.create_event(r, "a"*32, T, T+3_600_000))

    def test_no_legacy_suppressed_wrong_cohort_or_old_delivery(self):
        for changes in ({"delivered_at": iso(T-1)}, {"delivered_at": iso(T+2000)},
                        {"delivered_at": "2026-01-01T00:00:00"}, {"delivery_confirmed": False},
                        {"suppressed": True}, {"push_allowed": False}, {"direction": "SHORT"},
                        {"strategy": "S1+S4"}, {"universe": "core30"},
                        {"performance_market": "um_perp"}, {"engine_config_hash": None}):
            self.assertIsNone(e.create_event({**source(), **changes}, "a"*32, T, T+1000), changes)
        self.assertIsNone(e.create_event(source(), "a"*32, T, T+STEP+1001))

    def test_closed_contiguous_and_gap_recovery(self):
        x = event(); t = x["anchor_ms"]
        e.advance(x, [bar(t, h=110)], t+STEP-1)
        self.assertEqual(x["processed_bars"], 0)
        e.advance(x, [bar(t+STEP, h=110)], t+2*STEP)
        self.assertEqual(x["data_status"], "UNKNOWN")
        self.assertIsNone(x["plans"]["baseline"]["gross_pct"])
        e.advance(x, [bar(t), bar(t+STEP, h=110)], t+2*STEP)
        self.assertEqual(x["plans"]["baseline"]["status"], "TP")
        self.assertEqual(x["processed_bars"], 2)

    def test_conflicting_invalid_ohlc_and_future_extreme(self):
        for invalid in (bar(T+STEP, h=99), {**bar(T+STEP), "close_time": 0}):
            x = event(); t = x["anchor_ms"]
            e.advance(x, [invalid], t+STEP)
            self.assertEqual(x["data_status"], "UNKNOWN")
            self.assertEqual(x["next_start_ms"], t)
        x = event(); t = x["anchor_ms"]
        e.advance(x, [bar(t), bar(t, h=102)], t+STEP)
        self.assertEqual(x["data_reason"], "conflicting_bar")
        e.advance(x, [bar(t), bar(t+STEP, h=900)], t+STEP)
        self.assertEqual(x["plans"]["baseline"]["status"], "ACTIVE")

    def test_stop_first_gap_and_costs(self):
        x = event(); t = x["anchor_ms"]
        e.advance(x, [bar(t, h=108, l=96)], t+STEP)
        p = x["plans"]["distant"]
        self.assertEqual(p["status"], "AMBIGUOUS_STOP")
        self.assertAlmostEqual(p["net40_pct"], -3.4)
        x = event(); t = x["anchor_ms"]
        e.advance(x, [bar(t), bar(t+STEP, o=95, h=99, l=94, c=98)], t+2*STEP)
        self.assertEqual(x["plans"]["distant"]["status"], "STOP_GAP")
        self.assertAlmostEqual(x["plans"]["distant"]["gross_pct"], -5)

    def test_confirmation_uses_three_closed_bars_and_fourth_open(self):
        x = event("S3"); t = x["anchor_ms"]
        bars = [bar(t, c=100.2), bar(t+STEP, c=100.5),
                bar(t+2*STEP, h=102, l=99.5, c=101),
                bar(t+3*STEP, o=102, h=103, l=101, c=102)]
        e.advance(x, bars, t+3*STEP)
        self.assertFalse(x["plans"]["confirm15_trail"]["entered"])
        e.advance(x, bars, t+4*STEP)
        p = x["plans"]["confirm15_trail"]
        self.assertEqual(p["entry_price"], 102)
        self.assertEqual(p["entry_ms"], t+3*STEP)
        self.assertEqual(p["end_ms"], x["plans"]["baseline"]["end_ms"])

    def test_no_entry_zero_opportunity_and_not_trade(self):
        x = event("S3"); t = x["anchor_ms"]
        e.advance(x, [bar(t+i*STEP) for i in range(3)], t+3*STEP)
        p = x["plans"]["confirm15_trail"]
        self.assertEqual(p["status"], "NO_ENTRY")
        self.assertFalse(p["entered"])
        self.assertEqual(p["net40_pct"], 0)

    def test_partial_next_bar_trailing_and_funding_unknown(self):
        x = event("G2"); t = x["anchor_ms"]
        e.advance(x, [bar(t, h=107, l=99, c=105)], t+STEP)
        p = x["plans"]["partial_trail"]
        self.assertEqual(p["status"], "ACTIVE")
        self.assertEqual(p["remaining_fraction"], .5)
        self.assertEqual(p["stop_effective_ms"], t+STEP)
        self.assertEqual(x["plans"]["baseline"]["status"], "TP")
        e.advance(x, [bar(t+STEP, o=104, h=104.5, l=103, c=104)], t+2*STEP)
        p = x["plans"]["partial_trail"]
        self.assertEqual(p["status"], "TRAIL_STOP")
        self.assertAlmostEqual(p["gross_pct"], 3+.5*3.79)
        self.assertAlmostEqual(p["cost40_pct"], .4)
        self.assertIsNone(p["net40_pct"])
        self.assertAlmostEqual(sum(l["weight"] for l in p["legs"]), 1)
        self.assertEqual(x["status"], "active")

    def test_finished_outcome_immutable_but_full_path_continues(self):
        x = event(); t = x["anchor_ms"]
        e.advance(x, [bar(t, h=107)], t+STEP)
        gross = x["plans"]["distant"]["gross_pct"]
        e.advance(x, [], t+2*STEP)
        self.assertEqual(x["plans"]["distant"]["gross_pct"], gross)
        self.assertEqual(x["plans"]["distant"]["data_status"], "OK")
        self.assertEqual(x["plans"]["distant"]["full_window_data_status"], "UNKNOWN")
        e.advance(x, [bar(t+STEP, o=110, h=120, l=90, c=110)], t+2*STEP)
        self.assertAlmostEqual(x["plans"]["distant"]["full_window_mfe_pct"], 20)
        self.assertEqual(x["plans"]["distant"]["gross_pct"], gross)

    def test_full_horizon_timeout_incremental_equals_batch_and_replay_idempotent(self):
        x = event("S3"); t = x["anchor_ms"]
        bars = [bar(t+i*STEP) for i in range(48)]
        y = copy.deepcopy(x)
        for b in bars:
            e.advance(x, [b], b["open_time"]+STEP)
        e.advance(y, bars, y["end_ms"])
        self.assertEqual(x, y)
        self.assertEqual(x["status"], "complete")
        self.assertEqual(x["plans"]["baseline"]["status"], "TIMEOUT")
        previous = copy.deepcopy(x)
        e.advance(x, bars, x["end_ms"])
        self.assertEqual(x, previous)

    def test_public_whitelist_drops_nested_secrets(self):
        x = event(); x["token"] = "SECRET_SENTINEL"
        x["plans"]["baseline"]["recipients"] = ["SECRET_SENTINEL"]
        x["plans"]["baseline"]["entry_price"] = {"token": "SECRET_SENTINEL"}
        x["plans"]["fake_secret"] = {"token": "SECRET_SENTINEL"}
        public = e.public_event(x)
        self.assertNotIn("SECRET_SENTINEL", json.dumps(public))
        self.assertNotIn("_confirmation", public)

    def test_frozen_engine_matches_historical_simulate_on_complete_paths(self):
        # Independent existing engine is research-only and optional in a clean release.
        try:
            from research.all_execution_engine import simulate
        except ImportError:
            self.skipTest("historical scratchpad not installed")
        rng = random.Random(1503)
        for strategy in ("S1", "S3", "G2"):
            for sample in range(15):
                x = event(strategy); t = x["anchor_ms"]
                path = []; o = 100.
                for i in range((x["end_ms"]-t)//STEP):
                    c = o*(1+rng.uniform(-.025, .025))
                    h = max(o, c)*(1+rng.uniform(0, .025))
                    low = min(o, c)*(1-rng.uniform(0, .025))
                    path.append((o,h,low,c)); o = c
                e.advance(x, [bar(t+i*STEP,*b) for i,b in enumerate(path)], x["end_ms"])
                for p in x["plans"].values():
                    old = simulate(path,(p["entry_rule"],p["exit_rule"],p["tp_pct"],p["sl_pct"]))
                    self.assertEqual(p["status"],old["status"], (strategy,sample))
                    self.assertAlmostEqual(p["gross_pct"],old["gross_pct"],places=10)


class ReportTests(unittest.TestCase):
    def data(self, *events):
        return dict(study_version=e.VERSION,plan_hash=e.PLAN_HASH,activated_ms=T,
                    events={x["event_id"]:x for x in events})

    def test_pending_unknown_and_no_entry_are_separate(self):
        x = event("S3"); t = x["anchor_ms"]
        e.advance(x, [bar(t+i*STEP) for i in range(3)], t+3*STEP)
        e.advance(x, [], t+4*STEP)
        report = summarize(self.data(x),t+4*STEP)
        rows = {r["plan_id"]:r for r in report["cohorts"]}
        self.assertEqual(rows["baseline"]["n_unknown"],1)
        self.assertEqual(rows["confirm15_trail"]["n_no_entry"],1)
        self.assertEqual(rows["confirm15_trail"]["n_matured_entries"],0)
        self.assertEqual(rows["confirm15_trail"]["net40_per_opportunity_pct"]["mean"],0)

    def test_g2_has_no_full_net_and_cohorts_do_not_mix(self):
        x = event("G2"); t=x["anchor_ms"]
        e.advance(x, [bar(t,h=107)],t+STEP)
        y = copy.deepcopy(x); y["event_id"]="b"*32; y["regime"]="BEAR"
        report = summarize(self.data(x,y),t+STEP)
        self.assertEqual(len(report["cohorts"]),6)
        for r in report["cohorts"]:
            self.assertIsNone(r["net40_per_opportunity_pct"])
            self.assertFalse(r["auto_promote"])

    def test_report_deterministic_and_unknown_version_excluded(self):
        x=event(); data=self.data(x)
        self.assertEqual(summarize(data,T+1000),summarize(data,T+1000))
        x["study_version"]="old"
        report=summarize(self.data(x),T+1000)
        self.assertEqual(report["accepted_events"],0)


if __name__ == "__main__":
    unittest.main()
