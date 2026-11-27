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
        text = bot._telegram_signal_text(g1(atr14_1h_pct=4.0, oi_change_1h_pct=8.123,
                                            global_long_short_ratio=0.5291,
                                            global_short_account_pct=65.4))
        self.assertIn(f"🎯 <b>Hedef:</b> {bot._fmt_price(102.0)} (+%2)", text)
        self.assertIn(f"🛑 <b>Stop:</b> {bot._fmt_price(94.0)} (−%6.0) · kazanç/risk 0.33", text)
        self.assertIn("🔥 <b>OI artışı (1s):</b> +%8.1 · <b>Short hesap oranı:</b> %65.4", text)
        self.assertIn("⏱️ <b>Süre sınırı:</b> ", text)
        self.assertIn("(~4 saat)", text)
        order = [text.index(x) for x in ("Giriş fiyatı", "Hedef", "Stop", "OI artışı",
                                         "Süre sınırı", "Son 5")]
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
        self.assertIn("💰 <b>Giriş fiyatı:</b>", fresh)
        self.assertNotIn("⚠️", fresh)
        stale = bot._telegram_signal_text(g1(entry_quote={"exchange_time_ms": now_ms - 60_000, "spread_bps": 2.0}))
        self.assertIn("Teslim gecikti", stale)
        late = bot._telegram_signal_text(g1(notification_delay_minutes=12.0))
        self.assertIn("12 dakika sonra geldi", late)
        missing = bot._telegram_signal_text(g1(price_target_measurement_version=bot.g1_entry.MEASUREMENT))
        self.assertIn("Giriş fiyatı (eski)", missing)
        self.assertIn("Taze kotasyon alınamadı", missing)

    def test_market_line_variants(self):
        self.assertNotIn("🔥", bot._telegram_signal_text(g1()))
        for bad in (None, True, "8"):
            self.assertNotIn("🔥", bot._telegram_signal_text(g1(oi_change_1h_pct=bad)), bad)
        falling = bot._telegram_signal_text(g1(oi_change_1h_pct=-0.46))
        self.assertIn("🔥 <b>OI değişimi (1s):</b> −%0.5", falling)
        ratio_only = bot._telegram_signal_text(g1(global_long_short_ratio=0.8123,
                                                  global_short_account_pct=None))
        self.assertIn("🔥 <b>Long/short:</b> 0.81", ratio_only)

    def test_g2_card_shows_oi(self):
        text = bot._telegram_signal_text({
            "strategy": "G2", "symbol": "BBBUSDT", "direction": "LONG", "observe": True,
            "price": 5.0, "planned_entry_at": "2026-11-27T10:00:00+00:00",
            "horizon_hours": 24, "oi_change_1h_pct": 1.874})
        self.assertIn("🔥 <b>OI artışı (1s):</b> +%1.9", text)
        self.assertNotIn("Short hesap", text)
        order = [text.index(x) for x in ("Referans fiyat", "OI artışı", "Giriş zamanı")]
        self.assertEqual(order, sorted(order))

    def test_strategy_without_market_fields_unchanged(self):
        text = bot._telegram_signal_text({"strategy": "S1", "symbol": "CCCUSDT",
                                          "direction": "LONG", "price": 1.0,
                                          "horizon_hours": 24})
        self.assertNotIn("🔥", text)

    def test_dashboard_detail_row(self):
        rows = dict(bot._signal_detail_rows(g1(atr14_1h_pct=4.0)))
        self.assertEqual(rows["ATR14 1s"], "%4.00; referans stop 1.5×ATR = %6.0")


if __name__ == "__main__":
    unittest.main()
