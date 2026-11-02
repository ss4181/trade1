"""G1 card risk reference lines — offline, no Telegram."""
import unittest

import g1_entry
import signal_bot as bot


def g1(**extra):
    return {"strategy": "G1", "symbol": "AAAUSDT", "direction": "LONG",
            "strength": "RESEARCH", "confidence": "GOZLEM", "price": 100.0,
            "horizon_hours": 4, "note": "gölge araştırma", "observe": True, **extra}


class G1RiskCardTests(unittest.TestCase):
    def test_atr_stop_size_and_deadline_are_shown(self):
        text = bot._telegram_signal_text(g1(atr14_1h_pct=4.0))
        stop_pct = g1_entry.REFERENCE_STOP_ATR_MULT * 4.0
        self.assertIn("Referans stop (1.5×ATR):", text)
        self.assertIn(f"Referans stop (1.5×ATR):</b> {bot._fmt_price(94.0)} ·", text)
        self.assertIn("girişin %6.0 altı", text)
        self.assertIn(f"her 1 USDT risk ≈ {100 / stop_pct:.1f} USDT pozisyon", text)
        self.assertIn("Tasfiye fiyatı stopun altında", text)
        self.assertIn("süre sınırı:</b> ~4 saat · ≈ ", text)
        self.assertLess(text.index("Kişisel fiyat takibi"), text.index("Referans stop"))

    def test_missing_or_invalid_atr_hides_risk_lines(self):
        for atr in (None, 0, -1, 80.0):
            text = bot._telegram_signal_text(g1(atr14_1h_pct=atr))
            self.assertNotIn("Referans stop", text, atr)
            self.assertNotIn("USDT risk", text, atr)

    def test_dashboard_detail_row(self):
        rows = dict(bot._signal_detail_rows(g1(atr14_1h_pct=4.0)))
        self.assertEqual(rows["ATR14 1s"], "%4.00; referans stop 1.5×ATR = %6.0")


if __name__ == "__main__":
    unittest.main()
