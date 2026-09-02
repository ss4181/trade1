"""Haftalık araştırma Telegram tesliminin süreç/arşiv güvenlik testleri."""

from __future__ import annotations

import unittest
from unittest.mock import patch

import signal_bot as bot


def report(rows: int, source: str = "Termux / tablet") -> dict:
    return {
        "source_label": source,
        "market": {"rows": rows},
    }


class ResearchWeeklyDeliveryTests(unittest.TestCase):
    def setUp(self) -> None:
        bot._last_research_summary_week = None

    def tearDown(self) -> None:
        bot._last_research_summary_week = None

    def test_empty_archive_sends_diagnostic_instead_of_zero_report(self) -> None:
        sent, saved = [], []
        with patch.object(bot, "RESEARCH_WEEKLY_SUMMARY_ENABLED", True), \
                patch.object(bot, "RESEARCH_WEEKLY_REQUIRE_DATA", True), \
                patch.object(bot, "ENABLE_TELEGRAM", True), \
                patch.object(bot, "research_weekly_slot", return_value="2026-W36"), \
                patch.object(bot, "_saved_research_week", return_value=None), \
                patch.object(bot, "research_readiness_report",
                             return_value=report(0, "Render / bulut")), \
                patch.object(bot, "format_research_readiness",
                             side_effect=AssertionError("normal rapor çağrılmamalı")), \
                patch.object(bot, "_telegram_send_text",
                             side_effect=lambda text, **_kw: sent.append(text) or True), \
                patch.object(bot, "_save_research_week",
                             side_effect=lambda slot: saved.append(slot)):
            bot._maybe_weekly_research_summary()
        self.assertEqual(saved, ["2026-W36"])
        self.assertIn("ARŞİVİ BULUNAMADI", sent[0])
        self.assertIn("Render / bulut", sent[0])
        self.assertNotIn("0 toplam", sent[0])

    def test_nonempty_archive_uses_regular_report(self) -> None:
        sent = []
        with patch.object(bot, "RESEARCH_WEEKLY_SUMMARY_ENABLED", True), \
                patch.object(bot, "RESEARCH_WEEKLY_REQUIRE_DATA", True), \
                patch.object(bot, "ENABLE_TELEGRAM", True), \
                patch.object(bot, "research_weekly_slot", return_value="2026-W37"), \
                patch.object(bot, "_saved_research_week", return_value=None), \
                patch.object(bot, "research_readiness_report",
                             return_value=report(100)), \
                patch.object(bot, "format_research_readiness",
                             return_value="NORMAL RAPOR"), \
                patch.object(bot, "_telegram_send_text",
                             side_effect=lambda text, **_kw: sent.append(text) or True), \
                patch.object(bot, "_save_research_week"):
            bot._last_research_summary_week = None
            bot._maybe_weekly_research_summary()
        self.assertEqual(sent, ["NORMAL RAPOR"])


if __name__ == "__main__":
    unittest.main()
