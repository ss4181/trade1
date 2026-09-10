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
