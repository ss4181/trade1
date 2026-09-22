import unittest
from unittest.mock import patch

import market_regime
import signal_bot as bot


def rows(values, start=1704067200000):
    return [[start + i * market_regime.DAY_MS, str(v), str(v), str(v), str(v), "1",
             start + (i + 1) * market_regime.DAY_MS - 1] for i, v in enumerate(values)]


class MarketRegimeTests(unittest.TestCase):
    def test_bull_subtypes_and_closed_boundary(self):
        values = list(range(100, 300)) + list(range(300, 500))
        snap = market_regime.compute_snapshot(rows(values),
                                              as_of_ms=rows(values)[-1][6] + 1)
        self.assertEqual(snap["label"], "BULL")
        self.assertEqual(snap["subtype"], "bull_moderate")
        open_row = rows(values) + [[rows(values)[-1][0] + market_regime.DAY_MS,
                                    "500", "500", "500", "500", "1", 9999999999999]]
        same = market_regime.compute_snapshot(open_row,
                                              as_of_ms=rows(values)[-1][6] + 1)
        self.assertEqual(same["data_close_at"], snap["data_close_at"])

    def test_transition_and_validation(self):
        flat = rows([100.] * 240)
        snap = market_regime.compute_snapshot(flat, as_of_ms=flat[-1][6] + 1)
        self.assertEqual(snap["label"], "TRANSITION")
        bad = rows([100.] * 240)
        bad[10][0] += market_regime.DAY_MS
        with self.assertRaises(ValueError):
            market_regime.compute_snapshot(bad)
        stale = market_regime.compute_snapshot(
            rows([100.] * 240), as_of_ms=rows([100.] * 240)[-1][6] + 3 * market_regime.DAY_MS)
        self.assertEqual(stale["label"], "UNKNOWN")
        self.assertFalse(stale["fresh"])

    def test_menu_and_read_only_command_card(self):
        self.assertEqual(bot.MENU_BUTTONS["🌐 Piyasa"], "/piyasa")
        sent = []
        with patch.object(bot, "_telegram_send_text",
                          side_effect=lambda text, **kwargs: sent.append(text)):
            with patch.object(bot, "market_regime_snapshot", return_value={
                    "label": "BULL", "subtype": "bull_moderate",
                    "btc_close": 100, "sma200": 90, "distance_pct": 11.11,
                    "slope20_pct": 1.2, "momentum30_pct": 5.0,
                    "data_close_at": "2026-09-21T23:59:59+00:00"}):
                bot.handle_telegram_command("/piyasa", str(bot.TELEGRAM_CHAT_ID))
        self.assertTrue(sent)
        self.assertIn("BOĞA", sent[-1])
        self.assertIn("ılımlı yükseliş", sent[-1])


if __name__ == "__main__":
    unittest.main()
