"""Research-only backfill, provenance, leakage and source-preservation tests."""
import csv
import hashlib
import io
import json
import tempfile
import unittest
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from research import prepare_archive_data as prep
from research.eval_forward_oi_barriers import VisionKlineStore


DAY = "2026-09-04"
START = prep.timestamp(DAY + "T00:00:00+00:00")


def zip_csv(rows):
    stream = io.StringIO()
    csv.writer(stream, lineterminator="\n").writerows(rows)
    raw = io.BytesIO()
    with zipfile.ZipFile(raw, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("data.csv", stream.getvalue())
    return raw.getvalue()


def metric_raw(extra=None):
    return zip_csv([
        ["create_time", "symbol", *prep.METRICS],
        [DAY + " 00:10:00", "BTCUSDT", 100, .9, .8, 1.2],
        [DAY + " 00:05:00", "BTCUSDT", 99, .7, .8, 1.1],
        *(extra or []),
    ])


class ArchivePreparationTests(unittest.TestCase):
    def test_metrics_sorted_and_no_future_or_stale_row(self):
        rows = prep.parse_zip(metric_raw(), "metrics", "BTCUSDT", DAY)
        self.assertEqual(rows[0]["timestamp"], START + 300_000)
        value, at = prep._metric_before(rows, START + 600_000, "sum_toptrader_long_short_ratio")
        self.assertEqual(value, .7)  # equal-time 00:10 row not available
        self.assertEqual(at, START + 300_000)
        self.assertEqual(prep._metric_before(rows, START + 26 * 60_000, "sum_toptrader_long_short_ratio"), (None, None))

    def test_conflicting_metric_duplicates_rejected(self):
        raw = metric_raw([[DAY + " 00:05:00", "BTCUSDT", 1000, .7, .8, 1.1]])
        with self.assertRaisesRegex(ValueError, "conflicting_duplicate"):
            prep.parse_zip(raw, "metrics", "BTCUSDT", DAY)

    def test_missing_ratio_not_zero(self):
        raw = zip_csv([["create_time", "symbol", *prep.METRICS],
                       [DAY + " 00:05:00", "BTCUSDT", 100, "", "NaN", 1]])
        rows = prep.parse_zip(raw, "metrics", "BTCUSDT", DAY)
        self.assertIsNone(rows[0]["sum_toptrader_long_short_ratio"])
        self.assertIsNone(rows[0]["count_long_short_ratio"])

    def test_bad_prices_symbol_time_and_duplicates_rejected(self):
        samples = [
            [START, 100, 90, 99, 100, 1, START + 299999],
            [START, 0, 102, 99, 100, 1, START + 299999],
            [START + 1, 100, 102, 99, 100, 1, START + 299999],
            [START - 300_000, 100, 102, 99, 100, 1, START - 1],
        ]
        for row in samples:
            with self.subTest(row=row), self.assertRaises(ValueError):
                prep.parse_zip(zip_csv([row]), "klines", "BTCUSDT", DAY)
        with self.assertRaisesRegex(ValueError, "wrong_symbol"):
            prep.parse_zip(metric_raw(), "metrics", "ETHUSDT", DAY)

    def test_official_checksum_provenance_and_cache(self):
        raw = metric_raw()
        name = f"BTCUSDT-metrics-{DAY}.zip"
        proof = f"{hashlib.sha256(raw).hexdigest()}  {name}\n".encode()
        calls = []
        def fetch(url):
            calls.append(url)
            return proof if url.endswith(".CHECKSUM") else raw
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = prep.PublicStore(root, True, fetch)
            first = store.load(("metrics", "BTCUSDT", DAY))
            second = store.load(("metrics", "BTCUSDT", DAY))
            self.assertEqual(first["status"], "downloaded")
            self.assertEqual(second["status"], "cached")
            self.assertEqual(first["rows"], second["rows"])
            self.assertEqual(first["retrieved_at_utc"], second["retrieved_at_utc"])
            self.assertEqual(len(calls), 2)
            next(root.rglob("*.CHECKSUM")).unlink()
            missing = prep.PublicStore(root, False, fetch).load(("metrics", "BTCUSDT", DAY))
            self.assertEqual(missing["status"], "missing")
            self.assertEqual(len(calls), 2)

    def test_missing_wrong_checksum_never_written(self):
        for proof in [None, b"0" * 64 + b"  wrong.zip", b"garbage"]:
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                store = prep.PublicStore(root, True, lambda url: proof if url.endswith(".CHECKSUM") else metric_raw())
                with self.assertRaises(ValueError):
                    store.load(("metrics", "BTCUSDT", DAY))
                self.assertFalse(list(root.rglob("*.zip")))

    def test_unicode_contract_preserved_and_url_encoded(self):
        symbol = "币安人生USDT"
        calls = []
        with tempfile.TemporaryDirectory() as tmp:
            result = prep.PublicStore(Path(tmp), True, lambda url: calls.append(url)).load(("metrics", symbol, DAY))
        self.assertEqual(result["status"], "missing")
        self.assertIn("%E5%B8%81", calls[0])
        self.assertTrue(prep.SYMBOL.fullmatch(symbol))
        raw = b"test"
        name = f"{symbol}-5m-{DAY}.zip"
        prep.PublicStore.verify(raw, f"{hashlib.sha256(raw).hexdigest()}  {name}".encode("utf-8"), name)

    def test_rest_excludes_unclosed_bar_and_labels_local_hash(self):
        rows = [[START + i * 300_000, "100", "102", "99", "101", "1", START + (i + 1) * 300_000 - 1]
                for i in range(3)]
        now = datetime.fromtimestamp((START + 600_000) / 1000, timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            result = prep.rest_price_fallback(("klines", "BTCUSDT", DAY), Path(tmp),
                                             lambda url: json.dumps(rows).encode(), now)
            self.assertEqual(len(result["rows"]), 2)
            self.assertEqual(result["integrity_source"], "local_response_sha256_not_publisher_checksum")
            self.assertEqual(len(list(Path(tmp).rglob("*.json"))), 2)
            cached = prep.rest_cached(("klines", "BTCUSDT", DAY), Path(tmp))
            self.assertEqual(cached["rows"], result["rows"])
            self.assertEqual(cached["status"], "rest_cached")
            raw_path = next(p for p in Path(tmp).rglob("*.json") if not p.name.endswith(".provenance.json"))
            raw_path.write_bytes(b"[]")
            self.assertIsNone(prep.rest_cached(("klines", "BTCUSDT", DAY), Path(tmp)))

    def test_rest_never_fills_old_or_future_day(self):
        now = datetime.fromtimestamp((START + 10 * prep.DAY) / 1000, timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            result = prep.rest_price_fallback(("klines", "BTCUSDT", DAY), Path(tmp),
                                             lambda url: self.fail("network not allowed"), now)
        self.assertEqual(result["status"], "missing")

    def test_old_kline_cache_needs_checksum_too(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "BTCUSDT" / f"BTCUSDT-5m-{DAY}.zip"
            path.parent.mkdir()
            path.write_bytes(zip_csv([[START, 100, 102, 99, 101, 1, START + 299999]]))
            self.assertEqual(VisionKlineStore(root, False).load_day("BTCUSDT", DAY)["status"], "missing")
            path.with_suffix(".zip.sha256").write_text(hashlib.sha256(path.read_bytes()).hexdigest())
            self.assertEqual(VisionKlineStore(root, False).load_day("BTCUSDT", DAY)["status"], "cached")

    def test_audit_counts_partial_rows_and_clock_gaps_separately(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rows = [{"t": prep.iso(START + h * prep.HOUR), "sym": "BTCUSDT",
                     **{f: (None if h == 3 and f == "oi" else 1) for f in prep.FIELDS}}
                    for h in (0, 1, 3)]
            (root / "market_archive_test.jsonl").write_text("\n".join(map(json.dumps, rows)))
            audit = prep.audit_market(root)
            self.assertEqual(audit["rows_in_research_period"], 3)
            self.assertEqual(audit["actually_complete_rows"], 2)
            self.assertEqual(audit["missing_hours"], 1)
            self.assertEqual(audit["missing_fields_in_period"]["oi"], 1)

    def test_recovery_not_a_signal_and_missing_price_stays_missing(self):
        event = {"symbol": "BTCUSDT", "event_time_ms": START + 600_000,
                 "top_position_ls_ratio": None, "oi_change_8h": .1}
        results = [{"job": ["metrics", "BTCUSDT", DAY], "rows": prep.parse_zip(metric_raw(), "metrics", "BTCUSDT", DAY)}]
        context = prep.prepare_context([], [event], results)
        row = context["s2_context"][0]
        self.assertTrue(row["missing_top_recovered"])
        self.assertEqual(row["archive_top_position_ls_ratio"], .7)
        self.assertEqual(row["classification"], "retrospective_backfill_not_forward")
        self.assertNotIn("confidence", row)
        self.assertNotIn("signal", row)
        self.assertFalse(context["price_windows"][0]["complete"])

    def test_s2_plan_72h_next_hour_and_lag_previous_day(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            event = {"kind": "S2_DERIV_SHADOW", "symbol": "BTCUSDT", "event_time_ms": START}
            (root / "shadow_events_test.jsonl").write_text(json.dumps(event))
            plan, _, _ = prep.build_plan(root)
            self.assertIn(["metrics", "BTCUSDT", "2026-09-03"], plan["jobs"])
            self.assertIn(["klines", "BTCUSDT", "2026-09-07"], plan["jobs"])
            self.assertNotIn(["klines", "BTCUSDT", "2026-09-08"], plan["jobs"])

    def test_source_unchanged_secret_not_read_and_deterministic_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, output = Path(tmp) / "source", Path(tmp) / "output"
            root.mkdir()
            (root / ".env").write_text("API_KEY=NEVER_PUBLISH_ME")
            row = {"sym": "BTCUSDT", "t": prep.iso(START), **dict.fromkeys(prep.FIELDS, 1), "api_key": "NEVER_PUBLISH_ME"}
            path = root / "market_archive_test.jsonl"
            path.write_text(json.dumps(row))
            original = path.read_bytes()
            with patch.object(prep, "fetch_public", side_effect=AssertionError("no_network")):
                a = prep.run(root, output, False)
                b = prep.run(root, output, False)
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(a["audit"], b["audit"])
            self.assertFalse(a["oos_evaluated"])
            self.assertNotIn("NEVER_PUBLISH_ME", (output / "preparation_report.json").read_text())
            self.assertEqual({p.name for p in root.iterdir()}, {".env", path.name})

    def test_output_cannot_overlap_archive_and_job_paths_validated(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for output in (root, root / "child", root.parent):
                with self.assertRaises(ValueError):
                    prep.run(root, output)
            with self.assertRaises(ValueError):
                prep.PublicStore(root).load(("metrics", "../BAD", DAY))


if __name__ == "__main__":
    unittest.main()
