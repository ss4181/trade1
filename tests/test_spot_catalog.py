from contextlib import ExitStack
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from spot_catalog import SpotCatalog
from configure_scan_timing import configure
import signal_bot as bot


def catalog(vanry="BREAK"):
    return {"symbols": [{"symbol": "BTCUSDT", "status": "TRADING", "isSpotTradingAllowed": True},
                        {"symbol": "VANRYUSDT", "status": vanry, "isSpotTradingAllowed": True}]}


class CatalogTests(unittest.TestCase):
    def test_break_excluded_even_when_spot_permission_is_true_and_resumes(self):
        c = SpotCatalog()
        original = ["BTCUSDT", "VANRYUSDT"]
        self.assertTrue(c.refresh(lambda: catalog(), now=100))
        self.assertEqual(c.select(original), ["BTCUSDT"])
        self.assertEqual(original, ["BTCUSDT", "VANRYUSDT"])
        self.assertEqual(c.snapshot(original)["excluded"], {"VANRYUSDT": "BREAK"})
        self.assertTrue(c.refresh(lambda: catalog("TRADING"), now=3700))
        self.assertEqual(c.select(original), original)

    def test_bad_or_failed_refresh_retains_known_status_and_unknown_is_not_delisted(self):
        c = SpotCatalog()
        self.assertEqual(c.select(["NEW"]), ["NEW"])
        c.refresh(lambda: catalog(), now=100)
        for data in ({"symbols": []}, {"symbols": [{"symbol": "BTCUSDT"}]},
                     {"symbols": catalog()["symbols"] * 2}):
            self.assertFalse(c.refresh(lambda: data, now=200, force=True))
            self.assertFalse(c.eligible("VANRYUSDT"))
            self.assertEqual(c.checked_at, 100)
            self.assertTrue(c.last_error)
        def failed(): raise OSError()
        self.assertFalse(c.refresh(failed, now=300, force=True))
        self.assertFalse(c.eligible("VANRYUSDT"))

    def test_refresh_does_not_repeat_within_hour(self):
        c = SpotCatalog()
        fetch = Mock(return_value=catalog())
        c.refresh(fetch, now=100)
        c.refresh(fetch, now=200)
        fetch.assert_called_once()

    def test_unavailable_symbol_never_fetches_candles_or_changes_cooldowns(self):
        c = SpotCatalog()
        c.refresh(lambda: catalog(), now=100)
        state = Mock()
        with patch.object(bot, "SPOT_CATALOG", c), patch.object(bot, "fetch_klines") as fetch:
            self.assertEqual(bot.scan_symbol("VANRYUSDT", state), [])
        fetch.assert_not_called()
        state.should_fire.assert_not_called()

    def test_both_scan_paths_exclude_unavailable_without_hiding_real_errors(self):
        for parallel in (False, True):
            c = SpotCatalog()
            c.refresh(lambda: catalog(), now=100)
            called = []
            def scan(symbol, *a, **kw):
                called.append(symbol)
                if symbol == "BAD": raise bot.StaleCandleError("no latest candle")
                return []
            with self.subTest(parallel=parallel), ExitStack() as stack:
                values = {"SPOT_CATALOG": c, "SYMBOLS": ["BTCUSDT", "VANRYUSDT", "BAD"],
                          "OBSERVE_SYMBOLS": ["VANRYUSDT"], "OBSERVE_ENABLED": True,
                          "SCAN_STREAMING_ENABLED": parallel, "SCAN_WORKERS": 3,
                          "MAX_PUSH_PER_SCAN": 10000, "OBSERVE_MAX_PUSH_PER_SCAN": 10000}
                for key, value in values.items(): stack.enter_context(patch.object(bot, key, value))
                stack.enter_context(patch.object(bot, "scan_symbol", side_effect=scan))
                stack.enter_context(patch.object(bot.time, "sleep"))
                bot.scan_all(Mock())
                self.assertNotIn("VANRYUSDT", called)
                self.assertEqual(bot.LAST_SCAN_ATTEMPTED, 2)
                self.assertEqual(bot.LAST_SCAN_ERRORS, 1)

    def test_timing_config_preserves_other_settings_and_deduplicates(self):
        with tempfile.TemporaryDirectory() as folder:
            p = Path(folder)/".env"
            p.write_text("TELEGRAM_BOT_TOKEN=example\nSCAN_CLOSE_DELAY_SECONDS=10\n"
                         "export SCAN_CLOSE_DELAY_SECONDS=20\n# keep comment\n", encoding="utf-8")
            configure(p, 5)
            text = p.read_text(encoding="utf-8")
            self.assertIn("TELEGRAM_BOT_TOKEN=example\n", text)
            self.assertIn("# keep comment\n", text)
            self.assertEqual(text.count("SCAN_CLOSE_DELAY_SECONDS="), 1)
            self.assertIn("SCAN_CLOSE_DELAY_SECONDS=5\n", text)
            with self.assertRaises(ValueError): configure(p, 0)
            self.assertEqual(p.read_text(), text)


if __name__ == "__main__":
    unittest.main()
