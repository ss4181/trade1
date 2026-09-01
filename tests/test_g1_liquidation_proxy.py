"""G1 gerçekleşmiş-likidasyon proxy araştırmasının çevrimdışı testleri."""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

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
            {"t": before, "price": 102.0, "notional": 10_000.0,
             "side": "SHORT_LIQUIDATION"},
            {"t": before, "price": 99.0, "notional": 1_000.0,
             "side": "LONG_LIQUIDATION"},
            # Bu dev olay gelecektedir; test özelliğine sızmamalı.
            {"t": after, "price": 101.0, "notional": 1_000_000_000.0,
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
            int((history_start + timedelta(hours=i)).timestamp() // 300)
            for i in range(30 * 24)
        ]
        current = {"t": ms(self.entry - timedelta(minutes=30)), "price": 100.5,
                   "notional": 500_000.0, "side": "SHORT_LIQUIDATION"}
        archive = {"by_symbol": {"AAAUSDT": [current]},
                   "times": {"AAAUSDT": [current["t"]]},
                   "heartbeat_bins": heartbeat}
        features = proxy.liquidation_features(self.event, archive)
        self.assertTrue(features["lq1_short_burst"])
        self.assertEqual(features["short_burst_percentile"], 100.0)
        self.assertGreaterEqual(features["burst_history_hours"], 576)

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
