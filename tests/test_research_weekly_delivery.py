"""Offline report E2E: archive -> real HTML -> Telegram API stub -> durable ACK."""
from __future__ import annotations

from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

import signal_bot as bot
import research_report_delivery as delivery

REAL_THREAD = threading.Thread


class ImmediateThread:
    def __init__(self, target, **_kwargs):
        self.target = target

    def start(self):
        self.target()


class ResearchWeeklyDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.state_path = self.root / "weekly.json"
        self.now = datetime(2026, 10, 12, 12, tzinfo=timezone.utc)
        for name, value in {
            "RESEARCH_WEEKLY_SUMMARY_ENABLED": True, "RESEARCH_WEEKLY_REQUIRE_DATA": True,
            "ARCHIVE_MARKET_DATA": True, "ENABLE_TELEGRAM": True,
            "RESEARCH_MONITOR_STATE_FILE": self.state_path, "ARCHIVE_DIR": self.root,
            "RESEARCH_REPORT_SOURCE": "TABLET-ANA", "TELEGRAM_MIN_INTERVAL_SECONDS": 0,
            "TELEGRAM_BOT_TOKEN": "SYNTHETIC_SECRET", "TELEGRAM_CHAT_ID": "SYNTHETIC_CHAT",
        }.items():
            self.stack.enter_context(patch.object(bot, name, value))
        self.stack.enter_context(patch.object(bot.threading, "Thread", ImmediateThread))
        response = Mock()
        response.json.return_value = {"ok": True}
        self.post = self.stack.enter_context(patch.object(bot.requests, "post", return_value=response))
        self.stack.enter_context(patch.object(bot, "_note_notify"))

    def archive(self):
        row = dict(schema_version="market-context-v2", t=self.now.isoformat(),
                   sym="BTCUSDT", oi=100, perp_px=50000, basis=.001,
                   global_ls_ratio=.9, taker_buy_sell_ratio=1.1, funding_rate_snapshot=-.0001,
                   token="SYNTHETIC_SECRET")
        (self.root / "market_archive_2026-10.jsonl").write_text(json.dumps(row)+"\n", encoding="utf-8")

    def test_real_archive_html_and_api_ack_are_persisted_once(self):
        self.archive()
        self.assertTrue(bot._maybe_weekly_research_summary(self.now))
        message = self.post.call_args.kwargs["json"]["text"]
        self.assertIn("TABLET-ANA", message)
        self.assertIn("1 toplam", message)
        self.assertIn("Son arşiv kaydı", message)
        for private in ("SYNTHETIC_SECRET", "SYNTHETIC_CHAT", str(self.root)):
            self.assertNotIn(private, message)
        state = delivery.read_state(self.state_path)
        self.assertEqual(state["last_status"], "sent")
        self.assertEqual(state["archive_snapshot"]["rows"], 1)
        self.assertFalse(bot._maybe_weekly_research_summary(self.now + timedelta(hours=1)))
        self.assertEqual(self.post.call_count, 1)

    def test_empty_archive_sends_one_diagnostic_even_when_require_data_false(self):
        with patch.object(bot, "RESEARCH_WEEKLY_REQUIRE_DATA", False):
            self.assertTrue(bot._maybe_weekly_research_summary(self.now))
        self.assertIn("ARŞİVİ BULUNAMADI", self.post.call_args.kwargs["json"]["text"])
        self.assertEqual(delivery.read_state(self.state_path)["last_status"], "warning")
        self.assertFalse(bot._maybe_weekly_research_summary(self.now))

    def test_failed_api_ack_retries_after_one_hour_not_next_week(self):
        self.archive()
        self.post.return_value.json.return_value = {"ok": False}
        bot._maybe_weekly_research_summary(self.now)
        state = delivery.read_state(self.state_path)
        self.assertNotIn("last_week", state)
        self.assertNotIn("last_sent_at_utc", state)
        retry = delivery.utc_time(state["retry_at_utc"])
        self.assertFalse(bot._maybe_weekly_research_summary(retry - timedelta(seconds=1)))
        self.post.return_value.json.return_value = {"ok": True}
        self.assertTrue(bot._maybe_weekly_research_summary(retry))
        self.assertEqual(delivery.read_state(self.state_path)["last_status"], "sent")

    def test_legacy_success_and_stale_running_are_restart_safe(self):
        slot = bot.research_weekly_slot(self.now, 0, 6)
        delivery.write_state(self.state_path, {"last_week": slot})
        self.assertFalse(bot._maybe_weekly_research_summary(self.now))
        delivery.write_state(self.state_path, {
            "last_status": "running", "last_started_at_utc": (self.now-timedelta(hours=7)).isoformat()})
        self.assertTrue(bot._maybe_weekly_research_summary(self.now))

    def test_corrupt_state_and_failed_thread_start_do_not_escape(self):
        self.state_path.write_text("{bad", encoding="utf-8")
        self.assertFalse(bot._maybe_weekly_research_summary(self.now))
        self.post.assert_not_called()
        self.assertEqual(self.state_path.read_text(encoding="utf-8"), "{bad")
        delivery.write_state(self.state_path, {})
        with patch.object(bot.threading, "Thread", side_effect=RuntimeError("thread_start")):
            self.assertFalse(bot._maybe_weekly_research_summary(self.now))
        self.assertEqual(delivery.read_state(self.state_path)["last_status"], "error")
        self.assertFalse(bot._weekly_research_worker_lock.locked())

    def test_archive_disabled_process_cannot_send(self):
        with patch.object(bot, "ARCHIVE_MARKET_DATA", False):
            self.assertFalse(bot._maybe_weekly_research_summary(self.now))
        self.post.assert_not_called()

    def test_explicit_delivery_test_does_not_change_schedule(self):
        self.archive()
        delivery.write_state(self.state_path, {"last_week": "2026-W40"})
        before = self.state_path.read_bytes()
        self.assertTrue(bot.run_research_report_test("weekly"))
        self.assertIn("TEST", self.post.call_args.kwargs["json"]["text"])
        self.assertEqual(self.state_path.read_bytes(), before)

    def test_explicit_empty_archive_test_does_not_send(self):
        self.assertFalse(bot.run_research_report_test("weekly"))
        self.post.assert_not_called()

    def test_archive_reading_runs_off_caller_thread(self):
        started, release, finished = threading.Event(), threading.Event(), threading.Event()
        def read():
            started.set()
            release.wait(5)
            return {"market": {"rows": 0}, "source_label": "TABLET-ANA"}
        threads = []
        def create(**kwargs):
            target = kwargs.pop("target")
            def work():
                try:
                    target()
                finally:
                    finished.set()
            t = REAL_THREAD(target=work, **kwargs)
            threads.append(t)
            return t
        with patch.object(bot.threading, "Thread", side_effect=create), patch.object(bot, "research_readiness_report", side_effect=read):
            try:
                self.assertTrue(bot._maybe_weekly_research_summary(self.now))
                self.assertTrue(started.wait(3))
                self.assertFalse(finished.is_set())
                self.assertFalse(bot._maybe_weekly_research_summary(self.now))
            finally:
                release.set()
                for t in threads:
                    t.join(5)
            self.assertTrue(finished.is_set())

    def test_github_actions_source_identified_and_status_has_no_secret(self):
        with patch.dict(os.environ, {"GITHUB_ACTIONS": "true"}):
            self.assertEqual(bot._default_research_report_source(), "GitHub Actions / geçici bulut")
        delivery.write_state(self.state_path, {"last_error": "SYNTHETIC_SECRET", "token": "SYNTHETIC_SECRET"})
        with patch.object(bot, "FORWARD_OI_REPORT_STATE_FILE", self.root / "monthly.json"):
            text = json.dumps(bot.research_report_delivery_status())
        for private in ("SYNTHETIC_SECRET", "SYNTHETIC_CHAT", str(self.root)):
            self.assertNotIn(private, text)


if __name__ == "__main__":
    unittest.main()
