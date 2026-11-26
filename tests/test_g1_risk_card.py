"""G1 card risk reference lines — offline, no Telegram."""
import time
import unittest

import signal_bot as bot


def g1(**extra):
    return {"strategy": "G1", "symbol": "AAAUSDT", "direction": "LONG",
            "strength": "RESEARCH", "confidence": "GOZLEM", "price": 100.0,
            "horizon_hours": 4, "note": "gölge araştırma", "observe": True, **extra}


class G1RiskCardTests(unittest.TestCase):
    def test_atr_stop_size_and_deadline_are_shown(self):
        text = bot._telegram_signal_text(g1(atr14_1h_pct=4.0))
        self.assertIn("Referans stop (1.5×ATR):", text)
        self.assertIn(f"Referans stop (1.5×ATR):</b> {bot._fmt_price(94.0)} ·", text)
        self.assertIn("girişin %6.0 altı", text)
        for removed in ("USDT risk", "Tasfiye fiyatı", "brüt fiyat ölçümü"):
            self.assertNotIn(removed, text)
        self.assertIn("süre sınırı:</b> ~4 saat · ≈ ", text)
        self.assertLess(text.index("Kişisel fiyat takibi"), text.index("Referans stop"))

    def test_missing_or_invalid_atr_hides_risk_lines(self):
        for atr in (None, 0, -1, 80.0):
            text = bot._telegram_signal_text(g1(atr14_1h_pct=atr))
            self.assertNotIn("Referans stop", text, atr)
            self.assertNotIn("USDT risk", text, atr)

    def test_quote_details_only_when_stale(self):
        now_ms = time.time() * 1000
        fresh = bot._telegram_signal_text(g1(entry_quote={"exchange_time_ms": now_ms, "spread_bps": 2.0}))
        self.assertNotIn("Kotasyon:", fresh)
        self.assertNotIn("Teslim gecikti", fresh)
        self.assertNotIn("ilk kısmi dakika", fresh)
        stale = bot._telegram_signal_text(g1(entry_quote={"exchange_time_ms": now_ms - 60_000, "spread_bps": 2.0}))
        self.assertIn("Teslim gecikti", stale)

    def test_dashboard_detail_row(self):
        rows = dict(bot._signal_detail_rows(g1(atr14_1h_pct=4.0)))
        self.assertEqual(rows["ATR14 1s"], "%4.00; referans stop 1.5×ATR = %6.0")


if __name__ == "__main__":
    unittest.main()
