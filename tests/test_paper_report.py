import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from contextlib import redirect_stdout

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from research.evaluate_paper_signals import evaluate_records, main, utc_ms
from research.paper_inputs import build_candle_manifest, verify_candle_manifest, load_outbox_records
from notification_delivery import DeliveryOutbox
from qc_export import canonical_event_id
from datetime import datetime, timezone, timedelta

BASE = 1_735_689_600_000
M = 300_000


def signal(strategy="S3"):
    market = "um_perp" if strategy == "S2" else "spot"
    return {"strategy": strategy, "symbol": "BTCUSDT", "direction": "LONG",
            "performance_market": market, "performance_symbol": "BTCUSDT",
            "bar_time": "2024-12-31T23:00:00+00:00", "price": 999.,
            "delivered_at": "2025-01-01T00:00:00+00:00", "delivery_confirmed": True,
            "universe": "core30", "config_version": "v1", "engine_config_hash": "h1",
            "horizon_hours": 72 if strategy == "S2" else 24 if strategy == "S1" else 4}


def candle(market="spot", high=103):
    return {"market": market, "symbol": "BTCUSDT", "open_time": BASE+M,
            "open": 100., "high": high, "low": 99., "close": 101.}


class PaperReportTests(unittest.TestCase):
    def test_canonical_identity_quarantines_wrong_ids_and_bad_types(self):
        good = signal()
        good["event_id"] = canonical_event_id(good)
        records = [good, dict(good), dict(good, event_id="a"*32), dict(good, event_id="b"*32),
                   dict(good, strategy=["S3"]), dict(good, universe={"secret": "PRIVATE"}),
                   dict(signal("S2"), performance_symbol=["BTCUSDT"])]
        report = evaluate_records(records, [candle()], as_of_ms=BASE+100*M)
        self.assertEqual(len(report["records"]), 1)
        self.assertEqual(report["summary"]["cohorts"][0]["n_measured"], 1)
        self.assertEqual(report["rejected_counts"], {"duplicate_delivery": 1,
            "event_id_mismatch": 2, "unsupported_strategy_or_symbol": 1,
            "invalid_provenance_field": 1, "invalid_contract": 1})
        self.assertEqual(report, evaluate_records(list(reversed(records)), [candle()], as_of_ms=BASE+100*M))
        self.assertNotIn("PRIVATE", json.dumps(report))
        with self.assertRaises(ValueError):
            evaluate_records([], [], as_of_ms=BASE, latency_ms=1)

    def test_log_and_partial_retry_outbox_are_merged_without_private_fields(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            sig = signal()
            sig.update(delivery_confirmed=False, token="PRIVATE_TOKEN", note="PRIVATE_MESSAGE")
            sig["event_id"] = canonical_event_id(sig)
            initial = datetime(2025, 1, 1, tzinfo=timezone.utc)
            outbox = DeliveryOutbox(root/"outbox.json")
            outbox.enqueue(sig, ["PRIVATE_CHAT_A", "PRIVATE_CHAT_B"], now=initial)
            outbox.deliver(sig["event_id"], lambda *args: False, now=initial)
            delivered = initial+timedelta(minutes=1)
            with patch("notification_delivery.utcnow", return_value=delivered):
                outbox.deliver(sig["event_id"], lambda cid, record: cid == "PRIVATE_CHAT_A", now=delivered)
            source, data, manifest, output = (root/n for n in ("signals.jsonl", "candles.jsonl", "manifest.json", "result.json"))
            source.write_text(json.dumps(sig)+"\n", encoding="utf-8")
            data.write_text(json.dumps(candle())+"\n", encoding="utf-8")
            manifest.write_text(json.dumps(build_candle_manifest(data, source="synthetic", captured_at="2025-01-02T00:00:00Z")), encoding="utf-8")
            originals = {p: p.read_bytes() for p in (source, data, manifest, outbox.path)}
            args = ["evaluate", "--signals-log", str(source), "--delivery-outbox", str(outbox.path),
                    "--candles-jsonl", str(data), "--candles-manifest", str(manifest),
                    "--as-of", "2025-01-02T00:00:00Z", "--output", str(output)]
            with patch.object(sys, "argv", args), redirect_stdout(io.StringIO()):
                main()
            report = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(len(report["records"]), 1)
            self.assertEqual(report["records"][0]["observed_at_ms"], BASE+60_000)
            self.assertEqual(report["records"][0]["outcome"]["status"], "measured")
            self.assertEqual(report["input_provenance"]["candles"]["status"], "checksum_and_inventory_verified")
            self.assertNotIn("PRIVATE", output.read_text(encoding="utf-8"))
            for p, original in originals.items():
                self.assertEqual(p.read_bytes(), original)
            rows, counts = load_outbox_records(outbox.path, as_of_ms=BASE)
            self.assertEqual(rows, [])
            self.assertEqual(counts["delivered_after_cutoff"], 1)
            # A missing log row still leaves the confirmed event in the snapshot.
            rows, _ = load_outbox_records(outbox.path, as_of_ms=BASE+100*M)
            self.assertEqual(evaluate_records(rows, [candle()], as_of_ms=BASE+100*M)["records"][0]["outcome"]["status"], "measured")

    def test_manifest_binds_bytes_coverage_and_closed_market_bars(self):
        with tempfile.TemporaryDirectory() as folder:
            data, path = Path(folder)/"candles.jsonl", Path(folder)/"manifest.json"
            data.write_text(json.dumps(candle())+"\n"+json.dumps(dict(candle(), open_time=BASE+3*M))+"\n", encoding="utf-8")
            manifest = build_candle_manifest(data, source="binance_spot_klines", captured_at="2025-01-01T00:20:00Z")
            self.assertEqual(manifest["series"][0]["missing_bars"], 1)
            path.write_text(json.dumps(manifest), encoding="utf-8")
            self.assertEqual(verify_candle_manifest(path, data)["sha256"], manifest["sha256"])
            with self.assertRaisesRegex(ValueError, "unclosed"):
                build_candle_manifest(data, source="synthetic", captured_at="2025-01-01T00:01:00Z")
            with self.assertRaisesRegex(ValueError, "market_mismatch"):
                build_candle_manifest(data, source="binance_um_klines", captured_at="2025-01-02T00:00:00Z")
            data.write_text(data.read_text(encoding="utf-8")+"\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "manifest_mismatch"):
                verify_candle_manifest(path, data)

    def test_corrupt_outbox_does_not_leak_payload_or_guess_delivery(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/"outbox.json"
            path.write_text('{"PRIVATE_SECRET": "not an outbox"}', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "^invalid_delivery_snapshot$"):
                load_outbox_records(path, as_of_ms=BASE)

    def test_all_core_markets_earliest_delivery_not_best_price(self):
        records = [signal("S1"), signal("S2"), signal("S3")]
        late = dict(records[-1], delivered_at="2025-01-01T00:05:00+00:00")
        records.append(late)
        report = evaluate_records(records, [candle(), candle("um_perp")], as_of_ms=BASE+100*M)
        self.assertEqual(len(report["records"]), 3)
        self.assertEqual(report["rejected_counts"]["duplicate_delivery"], 1)
        for record in report["records"]:
            self.assertEqual(record["outcome"]["entry_price"], 100)
            self.assertEqual(record["outcome"]["entry_time_ms"], BASE+M)
            self.assertEqual(record["outcome"]["status"], "measured")
        s2 = next(r for r in report["records"] if r["strategy"] == "S2")
        self.assertIsNone(s2["outcome"]["net_return_pct"])
        self.assertEqual(report, evaluate_records(list(reversed(records)), [candle(), candle("um_perp")],
                                                 as_of_ms=BASE+100*M))

    def test_no_proxy_contract_guess_or_legacy_delivery_fabrication(self):
        s2 = signal("S2")
        del s2["performance_symbol"]
        legacy = signal("S1")
        del legacy["delivery_confirmed"]
        report = evaluate_records([s2, legacy], [candle()], as_of_ms=BASE+100*M)
        reasons = {r["outcome"]["reason"] for r in report["records"]}
        self.assertEqual(reasons, {"contract_mismatch", "delivery_not_confirmed"})

    def test_conflicting_identity_bad_json_secrets_and_manual_cli(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source, data, output = root/"signals.jsonl", root/"candles.jsonl", root/"result.json"
            r = signal()
            r["token"] = "PRIVATE_TEST_SECRET"
            source.write_text(json.dumps(r)+"\ninvalid-json PRIVATE_TEST_SECRET\n", encoding="utf-8")
            data.write_text(json.dumps(candle())+"\n", encoding="utf-8")
            before = source.read_bytes()
            args = ["evaluate", "--signals-log", str(source), "--candles-jsonl", str(data),
                    "--as-of", "2025-01-02T00:00:00Z", "--output", str(output)]
            with patch.object(sys, "argv", args), redirect_stdout(io.StringIO()):
                main()
            report = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(report["malformed_rows"]["signals"], 1)
            self.assertNotIn("PRIVATE_TEST_SECRET", output.read_text(encoding="utf-8"))
            self.assertEqual(source.read_bytes(), before)
            self.assertEqual(report["records"][0]["outcome"]["status"], "measured")
        a, b = signal(), signal()
        b["config_version"] = "v2"
        report = evaluate_records([a, b], [], as_of_ms=BASE+100*M)
        self.assertFalse(report["records"])
        self.assertEqual(report["rejected_counts"]["conflicting_event_provenance"], 2)
        repeated = [a, dict(a), b, dict(b)]
        first = evaluate_records(repeated, [], as_of_ms=BASE+100*M)
        last = evaluate_records(list(reversed(repeated)), [], as_of_ms=BASE+100*M)
        self.assertEqual(first, last)
        self.assertEqual(first["rejected_counts"], {"conflicting_event_provenance": 4})

    def test_tp_wins_are_not_defined_by_stale_reference_or_missing_market(self):
        r = signal()
        out = evaluate_records([r], [candle(high=100.5)], as_of_ms=BASE+M+1)
        self.assertEqual(out["records"][0]["outcome"]["status"], "pending")
        del r["performance_market"]
        out = evaluate_records([r], [candle()], as_of_ms=BASE+100*M)
        self.assertFalse(out["records"])
        with self.assertRaisesRegex(ValueError, "timezone_required"):
            utc_ms("2025-01-01")
        before_close = signal()
        before_close["delivered_at"] = "2024-12-31T23:05:00+00:00"
        out = evaluate_records([before_close], [], as_of_ms=BASE+100*M)
        self.assertEqual(out["rejected_counts"]["invalid_signal_or_delivery_time"], 1)
        out = evaluate_records([], [{"market": "spot", "symbol": ["bad"]}], as_of_ms=BASE)
        self.assertEqual(out["rejected_counts"]["invalid_candle_symbol"], 1)


if __name__ == "__main__":
    unittest.main()
