"""Thirty-day Forward OI Telegram scheduler tests (offline)."""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

import signal_bot as bot


RULES = (
    "P0_top10_gainer5", "P1_plus_volume2x", "P2_plus_any_oi_up",
    "P3_plus_oi_2pct", "P4_plus_short_majority",
    "P5_plus_funding_rise", "Q1_squeeze_proxy_oi_down",
)


def fake_report() -> dict:
    summary = {
        "n": 42, "n_unavailable": 1, "independent_days": 31,
        "target_first_pct_lower": 40.5, "stop_first_pct": 50.0,
        "mean_net_pct": 0.1234, "median_net_pct": -1.62,
        "bootstrap_p_mean_nonpositive": 0.2, "sample_warning": "",
    }
    return {
        "generated_at_utc": "2026-09-30T12:00:00+00:00",
        "data": {
            "accepted": 123456, "symbols": 135, "feature_rows": 98765,
            "feature_first_utc": "2026-07-21T14:00:00+00:00",
            "feature_last_utc": "2026-09-30T11:00:00+00:00",
            "download": {"requested": 900, "cached": 850,
                         "downloaded": 45, "missing": 5, "errors": 0},
            "token": "SHOULD_NEVER_APPEAR",
        },
        "rules": {
            name: {"tp2_sl1.5_4h": dict(summary),
                   "tp3_sl1.5_4h": dict(summary)}
            for name in RULES
        },
    }


class ImmediateThread:
    def __init__(self, target, **_kwargs):
        self.target = target

    def start(self):
        self.target()


class ForwardOIPeriodicReportTests(unittest.TestCase):
    def test_formatter_is_compact_complete_and_secret_free(self):
        text = bot.format_forward_oi_30d_report(fake_report())
        self.assertLessEqual(len(text), 4000)
        for code in ("P0", "P1", "P2", "P3", "P4", "P5", "Q1"):
            self.assertIn(code, text)
        self.assertIn("birikimli", text.lower())
        self.assertIn("OOS", text)
        self.assertNotIn("SHOULD_NEVER_APPEAR", text)

    def test_first_check_schedules_30_days_without_running(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "state.json"
            now = datetime(2026, 8, 31, 12, tzinfo=timezone.utc)
            with mock.patch.object(bot, "FORWARD_OI_REPORT_STATE_FILE", state_path), \
                    mock.patch.object(bot, "FORWARD_OI_REPORT_INTERVAL_DAYS", 30), \
                    mock.patch.object(bot, "FORWARD_OI_30D_REPORT_ENABLED", True), \
                    mock.patch.object(bot, "ENABLE_TELEGRAM", True), \
                    mock.patch.object(bot, "ARCHIVE_MARKET_DATA", True), \
                    mock.patch.object(bot, "_start_forward_oi_30d_report_worker") as start:
                self.assertFalse(bot._maybe_forward_oi_30d_report(now))
                start.assert_not_called()
                state = json.loads(state_path.read_text(encoding="utf-8"))
                due = datetime.fromisoformat(state["next_due_at_utc"])
                self.assertEqual(due, now + timedelta(days=30))
                self.assertFalse(
                    bot._maybe_forward_oi_30d_report(now + timedelta(days=29)))
                self.assertTrue(
                    bot._maybe_forward_oi_30d_report(now + timedelta(days=30)))
                start.assert_called_once()

    def test_due_worker_sends_and_persists_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "state.json"
            now = datetime(2026, 9, 30, 12, tzinfo=timezone.utc)
            state_path.write_text(json.dumps({
                "schema_version": "forward-oi-periodic-report-v1",
                "activated_at_utc": (now - timedelta(days=30)).isoformat(),
                "next_due_at_utc": now.isoformat(),
                "last_status": "scheduled",
            }), encoding="utf-8")
            delivered = []
            with mock.patch.object(bot, "FORWARD_OI_REPORT_STATE_FILE", state_path), \
                    mock.patch.object(bot, "FORWARD_OI_REPORT_INTERVAL_DAYS", 30), \
                    mock.patch.object(bot, "_generate_forward_oi_30d_report",
                                      return_value=fake_report()), \
                    mock.patch.object(bot, "_telegram_send_text",
                                      side_effect=lambda text, **_kw:
                                      delivered.append(text) or True), \
                    mock.patch.object(bot.threading, "Thread", ImmediateThread):
                self.assertTrue(bot._start_forward_oi_30d_report_worker(now))
            state = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(state["last_status"], "sent")
            self.assertIn("last_sent_at_utc", state)
            self.assertEqual(len(delivered), 1)

    def test_failed_report_retries_in_24_hours_without_escaping(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "state.json"
            now = datetime(2026, 9, 30, 12, tzinfo=timezone.utc)
            state_path.write_text(json.dumps({
                "activated_at_utc": (now - timedelta(days=30)).isoformat(),
                "next_due_at_utc": now.isoformat(), "last_status": "scheduled",
            }), encoding="utf-8")
            with mock.patch.object(bot, "FORWARD_OI_REPORT_STATE_FILE", state_path), \
                    mock.patch.object(bot, "_generate_forward_oi_30d_report",
                                      side_effect=RuntimeError("temporary")), \
                    mock.patch.object(bot, "_telegram_send_text", return_value=True), \
                    mock.patch.object(bot.threading, "Thread", ImmediateThread):
                self.assertTrue(bot._start_forward_oi_30d_report_worker(now))
            state = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(state["last_status"], "error")
            due = datetime.fromisoformat(state["next_due_at_utc"])
            completed = datetime.fromisoformat(state["last_completed_at_utc"])
            self.assertAlmostEqual((due - completed).total_seconds(), 86400, delta=2)

    def test_stale_running_claim_is_retryable_after_restart(self):
        now = datetime(2026, 9, 30, 12, tzinfo=timezone.utc)
        state = {
            "last_status": "running",
            "last_started_at_utc": (now - timedelta(hours=7)).isoformat(),
            "next_due_at_utc": (now + timedelta(days=29)).isoformat(),
        }
        self.assertTrue(bot._forward_oi_report_due(state, now))


if __name__ == "__main__":
    unittest.main()
