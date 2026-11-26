"""G1 gerçekleşmiş-likidasyon proxy araştırmasının çevrimdışı testleri."""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from research import eval_g1_liquidation_proxy as proxy


def ms(value: datetime) -> int:
    return int(value.timestamp() * 1000)


def bar(opened: datetime, open_: float, high: float, low: float,
        close: float) -> dict:
    return {"open_time_ms": ms(opened), "open": open_, "high": high,
            "low": low, "close": close}


class G1LiquidationProxyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.entry = datetime(2026, 9, 1, 12, tzinfo=timezone.utc)
        self.event = {
            "symbol": "AAAUSDT", "contract": "AAAUSDT",
            "hour": int(self.entry.timestamp() // 3600) - 1,
            "entry_hour": int(self.entry.timestamp() // 3600),
            "entry_time_ms": ms(self.entry), "condition_price": 100.0,
        }

    def test_event_loader_deduplicates_and_preserves_two_prices(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            row = {
                "kind": "G1_EVENT", "strategy": "G1", "symbol": "AAAUSDT",
                "bar_time": "2026-09-01T11:00:00+00:00",
                "condition_price": 100.0, "price": 98.5,
            }
            path = root / "shadow_events_2026-09.jsonl"
            path.write_text("\n".join(json.dumps(row) for _ in range(2)) + "\n",
                            encoding="utf-8")
            events, stats = proxy.load_g1_events(root)
        self.assertEqual(len(events), 1)
        self.assertEqual(stats["duplicates"], 1)
        self.assertEqual(events[0]["condition_price"], 100.0)
        self.assertEqual(events[0]["notification_price"], 98.5)
        self.assertEqual(events[0]["entry_time_ms"], ms(self.entry))

    def test_zone_feature_uses_only_information_before_entry(self) -> None:
        heartbeat = [
            int((self.entry - timedelta(hours=24) + timedelta(minutes=5 * i)
                 ).timestamp() // 300)
            for i in range(288)
        ]
        before = ms(self.entry - timedelta(minutes=30))
        after = ms(self.entry + timedelta(minutes=1))
        rows = [
            {"t": before, "received_at_ms": before + 1, "price": 102.0, "notional": 10_000.0,
             "side": "SHORT_LIQUIDATION"},
            {"t": before, "received_at_ms": before + 1, "price": 99.0, "notional": 1_000.0,
             "side": "LONG_LIQUIDATION"},
            # Bu dev olay gelecektedir; test özelliğine sızmamalı.
            {"t": after, "received_at_ms": after + 1, "price": 101.0, "notional": 1_000_000_000.0,
             "side": "SHORT_LIQUIDATION"},
        ]
        archive = {"by_symbol": {"AAAUSDT": rows},
                   "times": {"AAAUSDT": [row["t"] for row in rows]},
                   "heartbeat_bins": heartbeat}
        features = proxy.liquidation_features(self.event, archive)
        self.assertTrue(features["lq2_up_zone"])
        self.assertEqual(features["up_zone_usd_24h"], 10_000.0)
        self.assertEqual(features["down_zone_usd_24h"], 1_000.0)
        self.assertAlmostEqual(features["up_zone_price"], 102.0)

    def test_burst_requires_covered_30_day_history(self) -> None:
        history_start = self.entry - timedelta(days=30)
        heartbeat = [
            int((history_start + timedelta(minutes=5 * i)).timestamp() // 300)
            for i in range(30 * 24 * 12)
        ]
        current = {"t": ms(self.entry - timedelta(minutes=30)), "price": 100.5,
                   "received_at_ms": ms(self.entry - timedelta(minutes=29)),
                   "notional": 500_000.0, "side": "SHORT_LIQUIDATION"}
        archive = {"by_symbol": {"AAAUSDT": [current]},
                   "times": {"AAAUSDT": [current["t"]]},
                   "heartbeat_bins": heartbeat}
        features = proxy.liquidation_features(self.event, archive)
        self.assertTrue(features["lq1_short_burst"])
        self.assertEqual(features["short_burst_percentile"], 100.0)
        self.assertGreaterEqual(features["burst_history_hours"], 576)

    def test_late_receipt_cannot_leak_despite_old_exchange_timestamp(self):
        t = ms(self.entry - timedelta(minutes=30))
        row = {"t": t, "received_at_ms": ms(self.entry + timedelta(seconds=1)),
               "price": 102, "notional": 1e9, "side": "SHORT_LIQUIDATION"}
        archive = {"by_symbol": {"AAAUSDT": [row]}, "times": {"AAAUSDT": [t]},
                   "heartbeat_bins": list(range(ms(self.entry)//300000 - 288, ms(self.entry)//300000))}
        features = proxy.liquidation_features(self.event, archive)
        self.assertEqual(features["up_zone_usd_24h"], 0)
        self.assertFalse(features["lq2_up_zone"])
        row["received_at_ms"] = None
        features = proxy.liquidation_features(self.event, archive)
        self.assertIsNone(features["lq2_up_zone"])
        self.assertIsNone(features["up_zone_usd_24h"])

    def test_sparse_heartbeat_not_a_full_hour_and_missing_stays_unknown(self):
        archive = {"by_symbol": {}, "times": {}, "heartbeat_bins": [
            ms(self.entry)//300000 - 12 * i for i in range(1, 30 * 24 + 1)]}
        features = proxy.liquidation_features(self.event, archive)
        self.assertEqual(features["burst_history_hours"], 0)
        self.assertIsNone(features["lq1_short_burst"])
        self.assertIsNone(features["lq2_up_zone"])
        self.assertIsNone(features["short_liq_usd_1h"])
        json.dumps(features, allow_nan=False)

    def test_no_down_zone_has_no_json_infinity(self):
        t = ms(self.entry - timedelta(minutes=30))
        row = {"t": t, "received_at_ms": t + 1, "price": 102,
               "notional": 1000, "side": "SHORT_LIQUIDATION"}
        archive = {"by_symbol": {"AAAUSDT": [row]}, "times": {"AAAUSDT": [t]},
                   "heartbeat_bins": list(range(ms(self.entry)//300000 - 288, ms(self.entry)//300000))}
        features = proxy.liquidation_features(self.event, archive)
        self.assertTrue(features["lq2_up_zone"])
        self.assertTrue(features["up_only_zone"])
        self.assertIsNone(features["up_down_zone_ratio"])
        json.dumps(features, allow_nan=False)

    def test_disconnection_invalidates_same_heartbeat_bin(self):
        t = ms(self.entry)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "liquidation_archive_2026-09.jsonl"
            rows = [{"record_type": "stream_status", "at_ms": t + i,
                     "status": status} for i, status in enumerate(("connected", "disconnected"))]
            path.write_text("\n".join(map(json.dumps, rows)), encoding="utf-8")
            archive, stats = proxy.load_liquidation_archive(Path(tmp))
        self.assertEqual(archive["heartbeat_bins"], [])
        self.assertEqual(stats["statuses"], 2)

    def test_gate_prevents_even_cached_returns_and_downloads(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            row = {"kind": "G1_EVENT", "symbol": "AAAUSDT",
                   "bar_time": "2026-09-01T11:00:00+00:00", "condition_price": 100}
            (root / "shadow_events_test.jsonl").write_text(json.dumps(row))
            with patch.object(proxy, "load_jobs", side_effect=AssertionError("gate closed")), \
                    patch.object(proxy, "evaluate_event", side_effect=AssertionError("no return calculation")):
                result = proxy.run(root, root / "cache", allow_download=True,
                                   now=self.entry + timedelta(hours=5))
        self.assertEqual(result["rules"], {})
        self.assertEqual(result["download"]["requested"], 0)
        self.assertTrue(result["readiness"]["success_rates_withheld"])
        self.assertNotIn("WR%", proxy.format_report(result))

    def test_bad_manifest_and_secret_fields_never_escape(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            row = {"kind": "G1_EVENT", "symbol": "AAAUSDT",
                   "bar_time": "2026-09-01T11:00:00+00:00", "condition_price": 100,
                   "api_key": "PRIVATE_NEVER_EXPORT"}
            (root / "shadow_events_test.jsonl").write_text(json.dumps(row))
            (root / "backup_manifest.json").write_text(json.dumps({
                "schema_version": "trade1-backup-v1", "created_at_utc": self.entry.isoformat(),
                "files": {}, "secret": "PRIVATE_NEVER_EXPORT"}))
            before = {p.name: p.read_bytes() for p in root.iterdir()}
            report = proxy.run(root, root / "cache", now=self.entry + timedelta(hours=5))
            self.assertFalse(report["source_integrity"]["ok"])
            self.assertNotIn("PRIVATE_NEVER_EXPORT", json.dumps(report))
            self.assertEqual(before, {p.name: p.read_bytes() for p in root.iterdir()})

    def _ready_fixture(self, old_count, new_count):
        events = [{**self.event, "symbol": f"COIN{i}USDT", "universe": "fixed",
                   "config_version": "old" if i < old_count else "fresh-ask",
                   "measurement_version": "5m" if i < old_count else "1m"}
                  for i in range(old_count + new_count)]
        stats = {"events": 1000, "statuses": 1000, "malformed": 0,
                 "first_event_ms": ms(self.entry - timedelta(days=91)),
                 "last_event_ms": ms(self.entry), "event_days": 92}
        archive = {"by_symbol": {}, "times": {}, "heartbeat_bins": []}
        bars = [bar(self.entry + timedelta(minutes=5*i), 100, 101, 99, 100)
                for i in range(48)]
        return events, stats, archive, bars

    def test_input_and_result_cohorts_never_pool_old_and_fresh_ask(self):
        for old_count, new_count, ready in ((20, 20, False), (30, 15, True)):
            with self.subTest(old=old_count), tempfile.TemporaryDirectory() as tmp:
                events, stats, archive, bars = self._ready_fixture(old_count, new_count)
                with patch.object(proxy, "load_g1_events", return_value=(events, {"malformed": 0})), \
                        patch.object(proxy, "load_liquidation_archive", return_value=(archive, stats)), \
                        patch.object(proxy, "load_jobs", return_value=({}, {"requested": 0})), \
                        patch.object(proxy, "window_for_event", return_value=(bars, None)):
                    report = proxy.run(Path(tmp), Path(tmp)/"cache", now=self.entry + timedelta(hours=5))
                self.assertEqual(report["readiness"]["ready_for_discovery_review"], ready)
                self.assertEqual(report["rules"], {})
                self.assertEqual(len(report["input_cohorts"]), 2)
                cohorts = {c["config_version"]: c for c in report["cohorts"]}
                self.assertEqual(cohorts["fresh-ask"]["n"], new_count)
                self.assertEqual(cohorts["fresh-ask"]["rules"], {})
                if ready:
                    self.assertEqual(cohorts["old"]["rules"]["BASE_G1"]["n"], old_count)
                    self.assertEqual(cohorts["old"]["matched_baselines"]["LQ1"]["n"], 0)

    def test_sync_during_preparation_blocks_return_calculation(self):
        events, stats, archive, _bars = self._ready_fixture(30, 0)
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(proxy, "load_g1_events", return_value=(events, {"malformed": 0})), \
                patch.object(proxy, "load_liquidation_archive", return_value=(archive, stats)), \
                patch.object(proxy, "load_jobs", return_value=({}, {"requested": 0})), \
                patch.object(proxy, "source_integrity", side_effect=[
                    {"ok": True, "issues": []}, {"ok": False, "issues": ["source_changed"]}]), \
                patch.object(proxy, "evaluate_event", side_effect=AssertionError("unstable input")):
            report = proxy.run(Path(tmp), Path(tmp)/"cache", now=self.entry + timedelta(hours=5))
        self.assertFalse(report["readiness"]["input_gate_checks"]["source_integrity"])
        self.assertEqual(report["readiness"]["g1_evaluated"], 0)

    def test_source_replaced_after_read_is_not_trusted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "shadow_events_test.jsonl"
            path.write_text('{}\n', encoding="utf-8")
            sources = []
            list(proxy._jsonl(root, "shadow_events_*.jsonl", sources))
            path.write_text('{}\n{}\n', encoding="utf-8")
            integrity = proxy.source_integrity(root, sources, None, self.entry)
        self.assertFalse(integrity["ok"])
        self.assertIn("source_changed:shadow_events_test.jsonl", integrity["issues"])

    def test_entry_is_next_hour_open_and_zone_touch_is_causal(self) -> None:
        bars = []
        for index in range(48):
            opened = self.entry + timedelta(minutes=5 * index)
            bars.append(bar(opened, 101.0, 101.5, 100.5, 101.2))
        bars[2]["high"] = 102.1
        features = {"up_zone_price": 102.0, "lq1_short_burst": False,
                    "lq2_up_zone": True}
        result = proxy.evaluate_event(self.event, features, bars)
        self.assertEqual(result["entry_price"], 101.0)
        self.assertTrue(result["zone_touched_4h"])
        self.assertEqual(result["minutes_to_zone"], 15)

        already_crossed = proxy.evaluate_event(
            self.event, {**features, "up_zone_price": 100.5}, bars)
        self.assertIsNone(already_crossed["zone_touched_4h"])
        self.assertEqual(already_crossed["zone_touch_unavailable_reason"],
                         "zone_already_reached_before_entry")

    def test_empty_archive_is_safe_and_does_not_create_cache(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cache = root / "cache"
            report = proxy.run(root, cache, allow_download=False,
                               now=self.entry + timedelta(hours=5))
            self.assertFalse(report["readiness"]["ready_for_discovery_review"])
            self.assertEqual(report["readiness"]["g1_events"], 0)
            self.assertFalse(cache.exists())


if __name__ == "__main__":
    unittest.main()
