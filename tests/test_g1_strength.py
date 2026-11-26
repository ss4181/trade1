"""G1 strength score (g1-strength-v1): formula, card line, forward report gate. Offline."""
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "research")]
import g1_strength  # noqa: E402
import review_g1_strength as review  # noqa: E402
from g1_entry import EXIT_VERSION  # noqa: E402


def sig(**kw):
    base = {"rank_24h": 1, "volume_ratio": 8.0, "oi_change_1h_pct": 8.0,
            "global_short_account_pct": 65.0}
    return {**base, **kw}


class ScoreTests(unittest.TestCase):
    def test_bounds(self):
        self.assertEqual(g1_strength.score(sig())["score"], 100.0)
        low = g1_strength.score(sig(rank_24h=10, volume_ratio=2.0, oi_change_1h_pct=2.0,
                                    global_short_account_pct=50.0))
        self.assertEqual(low["score"], 2.5)  # only rank 10 -> 0.1
        self.assertEqual(g1_strength.score(sig(volume_ratio=50))["parts"]["volume"], 1.0)

    def test_log_midpoint_and_linear_short(self):
        r = g1_strength.score(sig(volume_ratio=4.0, oi_change_1h_pct=4.0,
                                  global_short_account_pct=57.5))
        self.assertAlmostEqual(r["parts"]["volume"], 0.5)
        self.assertAlmostEqual(r["parts"]["oi"], 0.5)
        self.assertAlmostEqual(r["parts"]["short"], 0.5)
        self.assertEqual(r["version"], "g1-strength-v1")

    def test_missing_or_invalid_fields_give_none(self):
        for bad in ({"rank_24h": None}, {"volume_ratio": float("nan")}, {"rank_24h": 11},
                    {"global_short_account_pct": True}, {"oi_change_1h_pct": "3"}):
            self.assertIsNone(g1_strength.score(sig(**bad)), bad)


class CardTests(unittest.TestCase):
    def test_card_shows_score_only_when_present(self):
        import signal_bot as bot
        base = {"strategy": "G1", "symbol": "AAAUSDT", "direction": "LONG", "price": 100.0,
                "horizon_hours": 4, "observe": True, "atr14_1h_pct": 4.0,
                "price_target": {"targets": [{"level_pct": 2, "price": 102.0}]}}
        text = bot._telegram_signal_text({**base, "g1_strength": g1_strength.score(sig())})
        self.assertIn("💪 <b>Güç:</b> 100/100 · test ediliyor, filtre değil", text)
        self.assertLess(text.index("Stop:"), text.index("Güç:"))
        self.assertNotIn("Güç:", bot._telegram_signal_text({**base, "g1_strength": None}))

    def test_score_is_copied_to_minute_target_event(self):
        import signal_bot as bot
        src = Path(bot.__file__).read_text(encoding="utf-8")
        self.assertIn('"g1_strength"):', src)
        self.assertIn('"g1_strength": event.get("g1_strength")', src)


def shadow(day, gross, stop=3.0, status="TP"):
    t = datetime(2027, 1, 1, tzinfo=timezone.utc) + timedelta(days=day)
    return {"version": EXIT_VERSION, "status": "complete", "complete": True, "stop_pct": stop,
            "entry_time_ms": int(t.timestamp() * 1000),
            "plans": {"tp2": {"gross_pct": gross, "status": status}}}


def strength(score):
    return {"version": g1_strength.VERSION, "score": score}


class ReportTests(unittest.TestCase):
    def test_gate_hides_groups(self):
        pairs = [(strength(i), shadow(i % 30, 2.0)) for i in range(100)]
        rep = review.summarize(pairs)
        self.assertFalse(rep["ready"])
        self.assertIsNone(rep["groups"])
        self.assertIn("HAZIR DEĞİL", review.render_text(rep))

    def test_unusable_rows_ignored(self):
        bad = [(None, shadow(1, 2.0)), (strength(50), {**shadow(1, 2.0), "complete": False}),
               ({"version": "other", "score": 1}, shadow(1, 2.0)), (strength(50), None)]
        self.assertEqual(review.summarize(bad)["complete_events"], 0)

    def test_clear_difference_supported_and_no_difference(self):
        pairs = []
        for i in range(180):
            day, score = i % 60, float(i)  # tertiles: <60 low, 60-119 mid, >=120 high
            gross = 2.0 if score >= 120 else -3.0 if score < 60 else 0.0
            pairs.append((strength(score), shadow(day, gross, status="TP" if gross > 0 else "SL")))
        rep = review.summarize(pairs)
        self.assertTrue(rep["ready"])
        self.assertEqual(rep["decision"], "SUPPORTED_ABSOLUTE")
        self.assertGreater(rep["high_minus_low"]["day_block_ci95"][0], 0)
        self.assertEqual(rep["groups"]["high"]["tp_before_stop_pct"], 100)
        flat = [(strength(i % 100), shadow(i % 60, 2.0 if i % 2 else -3.0)) for i in range(180)]
        self.assertEqual(review.summarize(flat)["decision"], "NO_DIFFERENCE_SHOWN")


if __name__ == "__main__":
    unittest.main()
