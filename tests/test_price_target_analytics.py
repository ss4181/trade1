"""Price-target path analytics and state migration tests."""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

import signal_bot as bot


class PriceTargetAnalyticsTests(unittest.TestCase):
    def setUp(self):
        self.old_state = bot.PRICE_TARGET_STATE
        self.old_file = bot.PRICE_TARGET_STATE_FILE
        self.old_levels = bot.PRICE_TARGET_LEVELS_PCT
        self.old_signal_log = bot.SIGNAL_LOG
        self.tmp = tempfile.TemporaryDirectory()
        bot.PRICE_TARGET_STATE_FILE = Path(self.tmp.name) / "targets.json"
        bot.PRICE_TARGET_STATE = bot._empty_price_target_state()
        bot.PRICE_TARGET_LEVELS_PCT = (2.0, 3.0, 5.0, 10.0)

    def tearDown(self):
        bot.PRICE_TARGET_STATE = self.old_state
        bot.PRICE_TARGET_STATE_FILE = self.old_file
        bot.PRICE_TARGET_LEVELS_PCT = self.old_levels
        bot.SIGNAL_LOG = self.old_signal_log
        self.tmp.cleanup()

    @staticmethod
    def record(event_id="a" * 32):
        return {
            "event_id": event_id, "strategy": "S3", "symbol": "BTCUSDT",
            "direction": "LONG", "price": 100.0, "horizon_hours": 4,
            "notified_at": "2026-08-01T12:01:00+00:00",
            "push_allowed": True, "performance_market": "spot",
        }

    def test_active_hits_do_not_inflate_matured_rate(self):
        record = self.record()
        bot._register_price_targets(record)
        event = bot.PRICE_TARGET_STATE["events"][record["event_id"]]
        start = event["next_start_ms"]
        bot._apply_price_target_bars(event, [{
            "open_time": start, "high": 103.2, "low": 98.5,
            "close_time": start + 299_999,
        }], start + 300_000)
        active = bot.price_target_summary()["S3"]["2"]
        self.assertEqual(active["resolved"], 0)
        self.assertEqual(active["pending_hit"], 1)
        event["status"] = "expired"
        mature = bot.price_target_summary()["S3"]["2"]
        self.assertEqual(mature["hit_rate_pct"], 100.0)
        self.assertEqual(mature["median_adverse_before_hit_pct"], -1.5)
        self.assertEqual(mature["median_minutes_to_hit_upper"], 5.0)
        path = bot.price_path_summary()["S3"]
        self.assertEqual(path["median_mfe_pct"], 3.2)
        self.assertEqual(path["median_mae_pct"], -1.5)

    def test_v1_state_replays_all_levels_without_delayed_alert(self):
        record = self.record()
        bot._register_price_targets(record)
        event = bot.PRICE_TARGET_STATE["events"][record["event_id"]]
        start = event["next_start_ms"]
        event["targets"] = {
            "2": {"price": 102.0, "hit_at": "old"},
            "3": {"price": 103.0, "hit_at": "old"},
        }
        event["next_start_ms"] = start + 300_000
        event["status"] = "completed"
        bot.PRICE_TARGET_STATE["schema_version"] = 1
        changed = bot._ensure_price_target_state_schema()
        self.assertGreater(changed, 0)
        event = bot.PRICE_TARGET_STATE["events"][record["event_id"]]
        self.assertEqual(set(event["targets"]), {"2", "3", "5", "10"})
        self.assertEqual(event["status"], "active")
        hits = bot._apply_price_target_bars(event, [{
            "open_time": start, "high": 111.0, "low": 98.0,
            "close_time": start + 299_999,
        }], start + 300_000)
        self.assertEqual(hits, [], "gecmis replay Telegram alarmi uretmemeli")

    def test_only_configured_2_and_3_levels_notify(self):
        event = {
            "strategy": "S3", "symbol": "BTCUSDT", "direction": "LONG",
            "entry_ref": 100.0, "max_adverse_pct": -1.0,
            "targets": {
                "2": {"price": 102.0}, "3": {"price": 103.0},
                "5": {"price": 105.0}, "10": {"price": 110.0},
            },
        }
        sent = []
        with mock.patch.object(bot, "ENABLE_TELEGRAM", True), \
                mock.patch.object(bot, "PRICE_TARGET_NOTIFY", True), \
                mock.patch.object(bot, "PRICE_TARGET_NOTIFY_LEVELS_PCT", (2.0, 3.0)), \
                mock.patch.object(bot, "TELEGRAM_SUBSCRIBERS", ["1"]), \
                mock.patch.object(bot, "_telegram_send_text",
                                  side_effect=lambda text, **_kw:
                                  sent.append(text) or True):
            bot._send_price_target_alert(event, ["5", "10"])
            self.assertEqual(sent, [])
            bot._send_price_target_alert(event, ["2", "5"])
        self.assertEqual(len(sent), 1)
        self.assertIn("+%2", sent[0])
        self.assertNotIn("+%5", sent[0])

    def test_log_backfill_replays_history_silently(self):
        notified = datetime.now(timezone.utc) - timedelta(hours=1)
        record = self.record("b" * 32)
        record["notified_at"] = notified.isoformat()
        log_path = Path(self.tmp.name) / "signals.log"
        log_path.write_text(json.dumps(record) + "\n", encoding="utf-8")
        bot.SIGNAL_LOG = str(log_path)

        self.assertEqual(bot._backfill_price_targets_from_signal_log(), 1)
        event = bot.PRICE_TARGET_STATE["events"][record["event_id"]]
        start = event["next_start_ms"]
        self.assertGreater(event["replay_silent_before_ms"], start)
        hits = bot._apply_price_target_bars(event, [{
            "open_time": start, "high": 111.0, "low": 99.0,
            "close_time": start + 299_999,
        }], start + 300_000)
        self.assertEqual(hits, [], "log backfill gecikmis alarm uretmemeli")

    def test_dashboard_template_has_requested_filters(self):
        page = bot.dashboard_html("./data.json")
        for marker in ("Benim başarı kriterim", 'id="fSearch"',
                       'id="fTarget"', "TP2/3/5/10", "MFE / MAE"):
            self.assertIn(marker, page)
        self.assertNotIn("{{DATA_URL}}", page)


if __name__ == "__main__":
    unittest.main()
