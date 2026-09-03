"""G1/DL1 gölge deney çekirdeği — tamamen çevrimdışı."""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import shadow_experiments as shadow


class Response:
    def __init__(self, payload, status=200):
        self.payload = payload
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self.payload


def klines(now: datetime) -> list[list]:
    end_open = now.replace(minute=0, second=0, microsecond=0) - timedelta(hours=1)
    start = end_open - timedelta(hours=24)
    rows = []
    for index in range(25):
        opened = start + timedelta(hours=index)
        close = 100.0 + index * 0.25       # 100 -> 106 = +%6
        volume = 250.0 if index == 24 else 100.0
        rows.append([
            int(opened.timestamp() * 1000), close, close, close, close, 1.0,
            int((opened + timedelta(hours=1)).timestamp() * 1000) - 1,
            volume,
        ])
    # Henüz kapanmamış bar aşırı değer taşısa da hesaplamaya girmemeli.
    rows.append([int((end_open + timedelta(hours=1)).timestamp() * 1000),
                 999, 999, 999, 999, 1,
                 int((end_open + timedelta(hours=2)).timestamp() * 1000) - 1,
                 999999])
    return rows


class ShadowExperimentTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 8, 31, 12, 30, tzinfo=timezone.utc)
        cutoff = int((self.now.replace(minute=0, second=0, microsecond=0)
                      ).timestamp() * 1000) - 1
        self.oi = [
            {"timestamp": cutoff - 3_600_000, "sumOpenInterest": "100"},
            {"timestamp": cutoff, "sumOpenInterest": "103"},
        ]
        self.ls = [{"timestamp": cutoff, "longShortRatio": "0.80",
                    "longAccount": "0.4444", "shortAccount": "0.5556"}]

    def test_g1_uses_only_closed_data_and_requires_all_conditions(self):
        result = shadow.evaluate_g1_snapshot(
            klines(self.now), self.oi, self.ls, 1, 6.0,
            int(self.now.timestamp() * 1000))
        self.assertTrue(result["condition"])
        self.assertAlmostEqual(result["return_24h"], .06, places=6)
        self.assertAlmostEqual(result["volume_ratio"], 2.5)
        self.assertAlmostEqual(result["oi_change_1h"], .03)
        crowded_long = [{**self.ls[0], "longShortRatio": "1.01"}]
        failed = shadow.evaluate_g1_snapshot(
            klines(self.now), self.oi, crowded_long, 1, 6.0,
            int(self.now.timestamp() * 1000))
        self.assertFalse(failed["condition"])

    def test_s2_derivatives_shadow_is_causal_and_silent(self):
        event = datetime(2026, 9, 1, 16, tzinfo=timezone.utc)
        event_ms = int(event.timestamp() * 1000)
        lag_ms = event_ms - 8 * 3_600_000
        oi = [
            {"timestamp": lag_ms - 300_000, "sumOpenInterest": "100"},
            {"timestamp": lag_ms, "sumOpenInterest": "999"},
            {"timestamp": event_ms - 300_000, "sumOpenInterest": "120"},
            {"timestamp": event_ms, "sumOpenInterest": "999"},
        ]
        global_ls = [
            {"timestamp": lag_ms - 300_000, "longShortRatio": "0.80"},
            {"timestamp": event_ms - 300_000, "longShortRatio": "0.90"},
        ]
        top = [{"timestamp": event_ms - 300_000,
                "longShortRatio": "0.70"}]
        funding = [
            {"time": lag_ms, "rate": -0.0003},
            {"time": event_ms, "rate": -0.0004},
        ]
        result = shadow.evaluate_s2_derivatives_snapshot(
            oi, top, global_ls, funding, event_ms)
        self.assertAlmostEqual(result["oi_change_8h"], .2)
        self.assertAlmostEqual(result["global_ls_change_8h"], .125)
        self.assertTrue(result["oi_short_build_candidate"])
        self.assertTrue(result["funding_ls_divergence_candidate"])

        requested = {}

        def futures_get(path, params=None):
            requested[path] = dict(params or {})
            if path.endswith("openInterestHist"):
                return Response(oi)
            if path.endswith("globalLongShortAccountRatio"):
                return Response(global_ls)
            if path.endswith("topLongShortPositionRatio"):
                return Response(top)
            raise AssertionError(path)

        with tempfile.TemporaryDirectory() as tmp:
            row = shadow.capture_s2_derivatives_shadow(
                futures_get, "AAAUSDT", "AAAUSDT", funding, Path(tmp),
                now=event + timedelta(minutes=4))
            lines = list(Path(tmp).glob("shadow_events_*.jsonl"))
            self.assertEqual(len(lines), 1)
            saved = json.loads(lines[0].read_text(encoding="utf-8"))
        self.assertEqual(row["push_allowed"], False)
        self.assertEqual(saved["kind"], "S2_DERIV_SHADOW")
        self.assertEqual(saved["event_id"], f"S2-DERIV|AAAUSDT|{event_ms}")
        for params in requested.values():
            self.assertLess(params["endTime"], event_ms)
        self.assertLessEqual(
            requested["/futures/data/openInterestHist"]["startTime"],
            lag_ms - 300_000)

    def test_s2_derivatives_missing_top_position_is_recorded_not_raised(self):
        event = datetime(2026, 9, 1, 16, tzinfo=timezone.utc)
        event_ms = int(event.timestamp() * 1000)
        lag_ms = event_ms - 8 * 3_600_000
        oi = [
            {"timestamp": lag_ms - 300_000, "sumOpenInterest": "100"},
            {"timestamp": event_ms - 300_000, "sumOpenInterest": "120"},
        ]
        global_ls = [
            {"timestamp": lag_ms - 300_000, "longShortRatio": "0.80"},
            {"timestamp": event_ms - 300_000, "longShortRatio": "0.90"},
        ]
        funding = [
            {"time": lag_ms, "rate": -0.0003},
            {"time": event_ms, "rate": -0.0004},
        ]

        def futures_get(path, params=None):
            if path.endswith("openInterestHist"):
                return Response(oi)
            if path.endswith("globalLongShortAccountRatio"):
                return Response(global_ls)
            if path.endswith("topLongShortPositionRatio"):
                return Response({}, status=401)
            raise AssertionError(path)

        with tempfile.TemporaryDirectory() as tmp:
            row = shadow.capture_s2_derivatives_shadow(
                futures_get, "AAAUSDT", "AAAUSDT", funding, Path(tmp),
                now=event + timedelta(minutes=4))
            summary = shadow.summarize_archive(Path(tmp))
        self.assertFalse(row["oi_short_build_complete"])
        self.assertIsNone(row["oi_short_build_candidate"])
        self.assertTrue(row["funding_ls_divergence_complete"])
        self.assertIn("topLongShortPositionRatio:RuntimeError",
                      row["unavailable_reason"])
        self.assertEqual(summary["s2_derivatives_events"], 1)
        self.assertEqual(summary["s2_oi_short_build_complete"], 0)
        self.assertEqual(summary["s2_funding_ls_divergence_candidates"], 1)

    def test_g1_same_closed_hour_is_deduplicated(self):
        calls = []

        def futures_get(path, params=None):
            calls.append(path)
            if path.endswith("exchangeInfo"):
                return Response({"symbols": [{"symbol": "AAAUSDT",
                    "contractType": "PERPETUAL", "status": "TRADING",
                    "quoteAsset": "USDT"}]})
            if path.endswith("ticker/24hr"):
                return Response([{"symbol": "AAAUSDT",
                                  "priceChangePercent": "6",
                                  "lastPrice": "104.25"}])
            if path.endswith("klines"):
                return Response(klines(self.now))
            if path.endswith("openInterestHist"):
                return Response(self.oi)
            if path.endswith("globalLongShortAccountRatio"):
                return Response(self.ls)
            raise AssertionError(path)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = shadow.scan_g1(futures_get, root / "state.json", root,
                                   now=self.now)
            before = len(calls)
            second = shadow.scan_g1(futures_get, root / "state.json", root,
                                    now=self.now)
            self.assertEqual([row["strategy"] for row in first], ["G1"])
            self.assertEqual(first[0]["price"], 104.25)
            self.assertEqual(first[0]["condition_price"], 106.0)
            self.assertEqual(first[0]["price_source"],
                             "usdm_24h_ticker_last_at_scan")
            self.assertEqual(first[0]["measurement_entry_time_utc"],
                             "2026-08-31T12:00:00+00:00")
            self.assertEqual(first[0]["notification_delay_minutes"], 30.0)
            self.assertEqual(second, [])
            self.assertEqual(len(calls), before)
            events = list(root.glob("shadow_events_*.jsonl"))
            self.assertEqual(len(events), 1)
            self.assertEqual(len(events[0].read_text().splitlines()), 1)

    def test_only_full_token_delist_is_accepted(self):
        self.assertEqual(shadow.title_tokens(
            "Notice of Removal of Spot Trading Pairs - 2026-09-03"), [])
        self.assertEqual(shadow.title_tokens(
            "Binance Will Delist AAA, BBB on 2026-09-03"), ["AAA", "BBB"])
        article = {"code": "abc", "title":
                   "Binance Will Delist AAA on 2026-09-03",
                   "releaseDate": int(self.now.timestamp() * 1000)}
        body = {"node": "root", "child": [{"node": "text", "text":
            "We will delist and cease trading on all spot trading pairs for "
            "the following tokens at 2026-09-03 03:00 (UTC)."}]}
        parsed = shadow.parse_delist_detail(
            article, {"data": {"body": json.dumps(body)}})
        self.assertEqual(parsed["tokens"], ["AAA"])
        self.assertEqual(parsed["delist_at"], "2026-09-03T03:00:00+00:00")

    def test_dl1_first_run_notifies_only_active_full_delist_once(self):
        article = {"code": "abc", "title":
                   "Binance Will Delist AAA on 2026-09-03",
                   "releaseDate": int((self.now - timedelta(hours=1)
                                       ).timestamp() * 1000)}
        pair_notice = {"code": "pair", "title":
                       "Notice of Removal of Spot Trading Pairs - 2026-09-03",
                       "releaseDate": article["releaseDate"]}
        body = {"node": "root", "child": [{"node": "text", "text":
            "Binance will delist and cease trading on all spot trading pairs "
            "at 2026-09-03 03:00 (UTC)."}]}

        def http_get(url, params=None, timeout=None):
            if url == shadow.BINANCE_DELIST_LIST:
                return Response({"data": {"catalogs": [{
                    "articles": [article, pair_notice]}]}})
            if url == shadow.BINANCE_DELIST_DETAIL:
                return Response({"data": {"body": json.dumps(body)}})
            if url == shadow.BYBIT_TICKER:
                return Response({"result": {"list": []}})
            if url == shadow.OKX_TICKER:
                return Response({"data": []})
            raise AssertionError(url)

        def spot_get(path, params=None):
            self.assertEqual(params["symbol"], "AAAUSDT")
            return Response({"lastPrice": "2", "bidPrice": "1.99",
                             "askPrice": "2.01", "quoteVolume": "1000",
                             "priceChangePercent": "5"})

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = shadow.poll_dl1(http_get, spot_get, root / "state.json",
                                    root, now=self.now)
            second = shadow.poll_dl1(http_get, spot_get, root / "state.json",
                                     root, now=self.now + timedelta(minutes=5))
            self.assertEqual(len(first), 1)
            self.assertEqual(first[0]["strategy"], "DL1")
            self.assertEqual(first[0]["direction"], "EVENT")
            self.assertTrue(first[0]["performance_excluded"])
            self.assertEqual(second, [])
            payload = "".join(path.read_text() for path in root.glob("shadow_*.jsonl"))
            self.assertNotIn("TOKEN", payload)
            self.assertNotIn("API_KEY", payload)


if __name__ == "__main__":
    unittest.main()
