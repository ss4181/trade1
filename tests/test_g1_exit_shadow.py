"""g1-exit-shadow-v1: frozen four-plan exits on 1m bars — offline, no orders."""
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import g1_entry as entry
import signal_bot as bot
from research.review_g1_exit_shadow import summarize

START = 1_793_000_000_000 // 60_000 * 60_000


def event(atr=2.0):
    # 1.5 x 2.0 ATR = 3% stop -> stop price 97 on a 100 entry.
    e = {"strategy": "G1", "direction": "LONG", "measurement_version": entry.MEASUREMENT,
         "tracking_start_ms": START}
    if atr is not None:
        e["atr14_1h_pct"] = atr
    return e


def bar(i, o, h, l, c):
    return {"open_time": START + i*60_000, "open": o, "high": h, "low": l, "close": c}


def plans(e):
    return e["exit_shadow"]["plans"]


class ExitShadowTests(unittest.TestCase):
    def test_missing_atr_or_entry_bar_is_unavailable_not_a_result(self):
        e = event(atr=None)
        entry.advance_exit_shadow(e, [bar(0, 100, 101, 99, 100)])
        self.assertEqual((e["exit_shadow"]["status"], e["exit_shadow"]["reason"]), ("unavailable", "atr_missing"))
        e = event()
        entry.advance_exit_shadow(e, [bar(1, 100, 101, 99, 100)])
        self.assertEqual(e["exit_shadow"]["reason"], "entry_bar_missing")
        self.assertEqual(summarize([e["exit_shadow"]])["complete_events"], 0)

    def test_tp2_half_breakeven_and_timeout(self):
        e = event()
        entry.advance_exit_shadow(e, [bar(0, 100, 102.5, 100.1, 102)])
        self.assertEqual((plans(e)["tp2"]["status"], plans(e)["tp2"]["gross_pct"]), ("TP", 2.0))
        self.assertEqual(plans(e)["half_tp2"]["status"], "active")
        entry.advance_exit_shadow(e, [bar(1, 101, 101.5, 99.9, 100.5)])
        self.assertEqual((plans(e)["half_tp2"]["status"], plans(e)["half_tp2"]["gross_pct"]), ("TP_BE", 1.0))
        entry.advance_exit_shadow(e, [bar(2, 100.5, 104, 100.2, 104)])
        entry.finish_exit_shadow(e)
        self.assertEqual(plans(e)["tp10"]["status"], "TIMEOUT")
        self.assertAlmostEqual(plans(e)["no_target"]["gross_pct"], 4.0)
        self.assertEqual(e["exit_shadow"]["status"], "complete")

    def test_same_bar_target_and_stop_is_stop_first(self):
        e = event()
        entry.advance_exit_shadow(e, [bar(0, 100, 111, 96, 100)])
        for key in entry.EXIT_PLANS:
            self.assertEqual(plans(e)[key]["status"], "AMBIGUOUS_SL" if key != "no_target" else "SL", key)
            self.assertAlmostEqual(plans(e)[key]["gross_pct"], -3.0)

    def test_gap_below_stop_fills_at_open(self):
        e = event()
        entry.advance_exit_shadow(e, [bar(0, 100, 100.5, 99, 99.5), bar(1, 95, 96, 94, 95)])
        self.assertEqual(plans(e)["no_target"]["status"], "SL_GAP")
        self.assertAlmostEqual(plans(e)["no_target"]["gross_pct"], -5.0)

    def test_half_target_bar_with_dip_below_entry_is_conservative(self):
        e = event()
        entry.advance_exit_shadow(e, [bar(0, 100, 102.5, 99.0, 101)])
        self.assertEqual((plans(e)["half_tp2"]["status"], plans(e)["half_tp2"]["gross_pct"]), ("TP_BE", 1.0))

    def test_half_target_then_timeout_averages_both_halves(self):
        e = event()
        entry.advance_exit_shadow(e, [bar(0, 100, 102.5, 100.1, 102), bar(1, 102, 106, 101, 106)])
        entry.finish_exit_shadow(e)
        self.assertEqual(plans(e)["half_tp2"]["status"], "TP_TIMEOUT")
        self.assertAlmostEqual(plans(e)["half_tp2"]["gross_pct"], 4.0)
        self.assertEqual(plans(e)["tp10"]["status"], "TIMEOUT")
        self.assertAlmostEqual(plans(e)["tp10"]["gross_pct"], 6.0)

    def test_gap_in_bars_is_excluded_from_report(self):
        e = event()
        entry.advance_exit_shadow(e, [bar(0, 100, 101, 99, 100), bar(2, 100, 101, 99, 100)])
        entry.finish_exit_shadow(e)
        self.assertFalse(e["exit_shadow"]["complete"])
        self.assertEqual(summarize([e["exit_shadow"]])["status_counts"], {"complete_with_gap": 1})

    def test_report_gate_and_paired_verdict(self):
        rows = []
        for i in range(30):
            e = event()
            e["tracking_start_ms"] = START + i * 86_400_000
            first = {"open_time": e["tracking_start_ms"], "open": 100, "high": 102.5, "low": 100.1, "close": 102}
            nxt = dict(first, open_time=first["open_time"] + 60_000, open=102, high=104, low=101.5, close=104)
            entry.advance_exit_shadow(e, [first, nxt])
            entry.finish_exit_shadow(e)
            rows.append(e["exit_shadow"])
        early = summarize(rows[:10])
        self.assertFalse(early["ready"])
        self.assertIsNone(early["plans"])
        report = summarize(rows)
        self.assertTrue(report["ready"])
        self.assertEqual(report["paired_vs_tp2_net40"]["no_target"]["verdict"], "better_than_tp2")
        self.assertAlmostEqual(report["plans"]["tp2"]["net40_mean_pct"], 1.6)
        self.assertAlmostEqual(report["plans"]["tp2"]["mean_R"], 2/3)

    def test_public_whitelist_and_bot_wiring(self):
        e = event()
        entry.advance_exit_shadow(e, [bar(0, 100, 101, 99, 100)])
        e["exit_shadow"]["secret"] = "PRIVATE_MARKER"
        e["exit_shadow"]["plans"]["tp2"]["token"] = "PRIVATE_MARKER"
        self.assertNotIn("PRIVATE_MARKER", json.dumps(entry.public_exit_shadow(e)))
        with tempfile.TemporaryDirectory() as folder, ExitStack() as stack:
            for name, value in {"PRICE_TARGET_STATE": bot._empty_price_target_state(),
                                "PRICE_TARGET_STATE_FILE": Path(folder)/"targets.json",
                                "PRICE_TARGET_LEVELS_PCT": (2., 3., 5., 10.),
                                "PRICE_TARGET_TRACKING_ENABLED": True}.items():
                stack.enter_context(patch.object(bot, name, value))
            now = datetime(2026, 11, 2, 12, 0, 11, tzinfo=timezone.utc)
            record = dict(event_id="x", strategy="G1", symbol="AAAUSDT", direction="LONG",
                          universe="all_active_usdm_perpetuals", price=100., horizon_hours=4,
                          performance_market="um_perp", config_version=entry.CONFIG_VERSION,
                          price_reference_status="fresh", price_target_measurement_version=entry.MEASUREMENT,
                          notified_at=now.isoformat(), delivered_at=(now+timedelta(seconds=1)).isoformat(),
                          delivery_confirmed=True, push_allowed=True, atr14_1h_pct=2.0,
                          entry_quote={"exchange_time_ms": int(now.timestamp()*1000)})
            self.assertIsNotNone(bot._register_price_targets(record))
            stored = bot.PRICE_TARGET_STATE["events"]["x"]
            self.assertEqual(stored["atr14_1h_pct"], 2.0)
            start = stored["tracking_start_ms"]
            entry.advance_exit_shadow(stored, [dict(open_time=start, open=100, high=102.5, low=99.5, close=102)])
            public = bot._price_target_public(stored)["exit_shadow"]
            self.assertEqual(public["plans"]["tp2"]["status"], "TP")
            self.assertAlmostEqual(public["stop_pct"], 3.0)


if __name__ == "__main__":
    unittest.main()
