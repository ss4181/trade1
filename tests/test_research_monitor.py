"""Weekly forward-research readiness monitor tests."""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import research_monitor as monitor


class ResearchMonitorTests(unittest.TestCase):
    def _archive(self, root: Path, *, days: int = 91,
                 missing_funding: bool = False) -> tuple[datetime, datetime]:
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        now = start + timedelta(days=days)
        market = root / "market_archive_2026-01.jsonl"
        with market.open("w", encoding="utf-8") as stream:
            for hour in range(days * 24 + 1):
                stamp = start + timedelta(hours=hour)
                row = {
                    "schema_version": "market-context-v2",
                    "t": stamp.isoformat(timespec="minutes"),
                    "sym": "BTCUSDT", "oi": 100 + hour,
                    "perp_px": 50000, "basis": 0.001,
                    "global_ls_ratio": 0.9,
                    "taker_buy_sell_ratio": 1.1,
                    "funding_rate_snapshot": (
                        (-0.0001 if hour == 0 else None)
                        if missing_funding else -0.0001),
                }
                stream.write(json.dumps(row) + "\n")
        liquidation = root / "liquidation_archive_2026-01.jsonl"
        with liquidation.open("w", encoding="utf-8") as stream:
            for day in range(30):
                stamp = start + timedelta(days=day)
                stream.write(json.dumps({
                    "record_type": "stream_status", "status": "heartbeat",
                    "at_utc": stamp.isoformat(),
                }) + "\n")
                stream.write(json.dumps({
                    "record_type": "force_order", "event_id": f"e{day}",
                    "received_at_utc": stamp.isoformat(),
                }) + "\n")
        shadow = root / "shadow_events_2026-01.jsonl"
        shadow.write_text("\n".join(json.dumps(row) for row in [
            {"kind": "G1_EVENT", "recorded_at": start.isoformat()},
            {"kind": "S2_DERIV_SHADOW", "recorded_at": start.isoformat(),
             "oi_short_build_complete": True,
             "oi_short_build_candidate": True,
             "funding_ls_divergence_candidate": False},
        ]) + "\n", encoding="utf-8")
        return start, now

    def test_90_day_quality_gate_becomes_interim_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _start, now = self._archive(root)
            report = monitor.build_research_readiness(root, now=now)
        self.assertEqual(report["phase"], "INTERIM_REVIEW_DUE")
        self.assertTrue(report["quality_ready"])
        self.assertEqual(report["market"]["hour_coverage_pct"], 100.0)
        self.assertEqual(report["liquidations"]["observed_days"], 30)
        self.assertEqual(report["liquidations"]["event_days"], 30)
        self.assertEqual(report["shadow"]["g1_events"], 1)
        self.assertEqual(report["shadow"]["s2_derivatives_events"], 1)
        self.assertEqual(report["shadow"]["s2_oi_short_build_complete"], 1)
        self.assertEqual(report["shadow"]["s2_oi_short_build_candidates"], 1)

    def test_missing_required_field_blocks_freeze(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _start, now = self._archive(root, missing_funding=True)
            report = monitor.build_research_readiness(root, now=now)
        self.assertEqual(report["phase"], "DATA_QUALITY_BLOCKED")
        self.assertFalse(report["quality_ready"])
        self.assertFalse(
            report["quality_checks"]["funding_completeness_80pct"])

    def test_declared_oos_start_controls_formal_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _start, now = self._archive(root)
            collecting = monitor.build_research_readiness(
                root, now=now, oos_start_utc=(now - timedelta(days=30)).isoformat())
            ready = monitor.build_research_readiness(
                root, now=now, oos_start_utc=(now - timedelta(days=90)).isoformat())
        self.assertEqual(collecting["phase"], "OOS_COLLECTING")
        self.assertEqual(ready["phase"], "FORMAL_REVIEW_DUE")

    def test_weekly_slot_waits_for_configured_instant(self):
        monday = datetime(2026, 8, 31, tzinfo=timezone.utc)
        self.assertIsNone(monitor.weekly_slot(monday + timedelta(hours=5)))
        self.assertEqual(monitor.weekly_slot(monday + timedelta(hours=6)),
                         "2026-W36")
        self.assertEqual(monitor.weekly_slot(monday + timedelta(days=2)),
                         "2026-W36")

    def test_empty_archive_is_safe_and_message_has_no_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = monitor.build_research_readiness(
                tmp, now=datetime(2026, 8, 31, tzinfo=timezone.utc))
            report["source_label"] = "Termux / tablet"
            message = monitor.format_research_readiness(report)
        self.assertEqual(report["phase"], "NO_DATA")
        self.assertIn("VERI YOK", message)
        self.assertIn("Kaynak:</b> Termux / tablet", message)
        self.assertNotIn(tmp, message)

    def test_legacy_market_rows_are_not_lost(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "market_archive_2026-07.jsonl").write_text(json.dumps({
                "t": "2026-07-01T00:00+00:00", "sym": "BTCUSDT",
                "oi": 123, "perp_px": 50000,
            }) + "\n", encoding="utf-8")
            report = monitor.build_research_readiness(
                root, now=datetime(2026, 7, 1, 1, tzinfo=timezone.utc))
        self.assertEqual(report["market"]["rows"], 1)
        self.assertEqual(report["market"]["symbols"], 1)

    def test_heartbeats_without_events_do_not_pass_liquidation_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _start, now = self._archive(root)
            path = root / "liquidation_archive_2026-01.jsonl"
            rows = [json.loads(line) for line in path.read_text(
                encoding="utf-8").splitlines()]
            path.write_text("\n".join(json.dumps(row) for row in rows
                                      if row["record_type"] == "stream_status")
                            + "\n", encoding="utf-8")
            report = monitor.build_research_readiness(root, now=now)
        self.assertFalse(report["quality_ready"])
        self.assertEqual(report["liquidations"]["event_days"], 0)
        self.assertTrue(report["liquidations"]["stream_suspect"])
        self.assertEqual(report["phase"], "WAITING_FOR_LIQUIDATION_EVENTS")
        self.assertIsNone(report["next_review_utc"])


if __name__ == "__main__":
    unittest.main()
