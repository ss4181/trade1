"""G1 Telegram card — only decision lines, warnings only when needed. Offline."""
import time
import unittest

import signal_bot as bot


def g1(**extra):
    return {"strategy": "G1", "symbol": "AAAUSDT", "direction": "LONG",
            "strength": "RESEARCH", "confidence": "GOZLEM", "price": 100.0,
            "horizon_hours": 4, "note": "gölge araştırma", "observe": True,
            "price_target": {"targets": [{"level_pct": 2, "price": 102.0}]}, **extra}


class G1RiskCardTests(unittest.TestCase):
    def test_decision_lines_in_order(self):
        text = bot._telegram_signal_text(g1(atr14_1h_pct=4.0))
        self.assertIn(f"🎯 <b>Hedef:</b> {bot._fmt_price(102.0)} (+%2)", text)
        self.assertIn(f"🛑 <b>Stop:</b> {bot._fmt_price(94.0)} (−%6.0) · kazanç/risk 0.33", text)
        self.assertIn("⏱️ <b>Süre sınırı:</b> ", text)
        self.assertIn("(~4 saat)", text)
        order = [text.index(x) for x in ("Fiyat", "Hedef", "Stop", "Süre sınırı", "Son 5")]
        self.assertEqual(order, sorted(order))
        for removed in ("USDT risk", "Tasfiye", "brüt fiyat", "Neden geldi", "Toplu hedef",
                        "Koşul mumu", "Bildirim gecikmesi", "Ölçüm girişi", "ATR14", "⚠️"):
            self.assertNotIn(removed, text)

    def test_missing_or_invalid_atr_hides_stop(self):
        for atr in (None, 0, -1, 80.0):
            text = bot._telegram_signal_text(g1(atr14_1h_pct=atr))
            self.assertNotIn("Stop:", text, atr)

    def test_quote_and_delay_warnings_only_when_needed(self):
        now_ms = time.time() * 1000
        fresh = bot._telegram_signal_text(g1(entry_quote={"exchange_time_ms": now_ms, "spread_bps": 2.0},
                                             notification_delay_minutes=0.1))
        self.assertIn("💰 <b>Giriş (ask):</b>", fresh)
        self.assertNotIn("⚠️", fresh)
        stale = bot._telegram_signal_text(g1(entry_quote={"exchange_time_ms": now_ms - 60_000, "spread_bps": 2.0}))
        self.assertIn("Teslim gecikti", stale)
        late = bot._telegram_signal_text(g1(notification_delay_minutes=12.0))
        self.assertIn("12 dakika sonra geldi", late)
        missing = bot._telegram_signal_text(g1(price_target_measurement_version=bot.g1_entry.MEASUREMENT))
        self.assertIn("Fiyat (eski referans)", missing)
        self.assertIn("Taze kotasyon alınamadı", missing)

    def test_dashboard_detail_row(self):
        rows = dict(bot._signal_detail_rows(g1(atr14_1h_pct=4.0)))
        self.assertEqual(rows["ATR14 1s"], "%4.00; referans stop 1.5×ATR = %6.0")


if __name__ == "__main__":
    unittest.main()
