from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).parent.parent))

from derivatives_archive import (
    ArchiveIgnoredEvent,
    ArchivePayloadError,
    DEFAULT_STREAM_URL,
    ForceOrderArchiveWorker,
    MonthlyJsonlArchive,
    normalize_force_order,
    summarize_archive,
)


def payload(*, side: str = "SELL", event_ms: int = 1_720_000_000_123) -> dict:
    return {
        "e": "forceOrder",
        "E": event_ms,
        "o": {
            "s": "BTCUSDT",
            "S": side,
            "o": "LIMIT",
            "f": "IOC",
            "q": "2.000",
            "p": "100.0",
            "ap": "101.0",
            "X": "FILLED",
            "l": "1.5",
            "z": "1.5",
            "T": event_ms - 5,
        },
    }


class NormalizeTests(unittest.TestCase):
    def test_normalizes_side_notional_and_deterministic_id(self) -> None:
        first = normalize_force_order(payload(), received_at_ms=1_720_000_001_000)
        second = normalize_force_order(payload(), received_at_ms=1_720_000_009_000)
        self.assertEqual(first["event_id"], second["event_id"])
        self.assertEqual(first["liquidation_side"], "LONG_LIQUIDATION")
        self.assertEqual(first["estimated_notional_usd"], "151.50")
        self.assertEqual(first["capture_semantics"],
                         "latest_per_symbol_per_1000ms_snapshot")
        self.assertEqual(first["raw_event"], payload())

        short = normalize_force_order(payload(side="BUY"))
        self.assertEqual(short["liquidation_side"], "SHORT_LIQUIDATION")

    def test_rejects_non_force_order_and_invalid_numeric_data(self) -> None:
        with self.assertRaises(ArchivePayloadError):
            normalize_force_order({"e": "trade"})
        broken = payload()
        broken["o"]["q"] = "NaN"
        with self.assertRaises(ArchivePayloadError):
            normalize_force_order(broken)

    def test_new_market_path_and_merged_stream_usdm_filter(self) -> None:
        self.assertEqual(
            DEFAULT_STREAM_URL,
            "wss://fstream.binance.com/market/ws/!forceOrder@arr")
        usdm = payload()
        usdm.update({"st": 1, "ps": "BTCUSDT"})
        record = normalize_force_order(usdm)
        self.assertEqual(record["market_segment"], "USD_M")
        self.assertEqual(record["binance_symbol_type"], 1)
        coinm = payload()
        coinm["st"] = 2
        with self.assertRaises(ArchiveIgnoredEvent):
            normalize_force_order(coinm)


class WriterTests(unittest.TestCase):
    def test_duplicate_is_suppressed_across_restart(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            record = normalize_force_order(payload())
            first = MonthlyJsonlArchive(directory)
            self.assertTrue(first.append(record))
            self.assertFalse(first.append(record))

            restarted = MonthlyJsonlArchive(directory)
            self.assertFalse(restarted.append(record))
            path = next(Path(directory).glob("liquidation_archive_*.jsonl"))
            rows = [json.loads(line) for line in path.read_text(
                encoding="utf-8").splitlines()]
            self.assertEqual(len(rows), 1)

    def test_lifecycle_records_and_summary_are_safe(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            writer = MonthlyJsonlArchive(directory)
            writer.append_status(
                "error", at_ms=1_720_000_000_000,
                detail="https://user:pass@example.test/?token=secret-value")
            writer.append(normalize_force_order(payload()))
            summary = summarize_archive(directory)
            self.assertEqual(summary["events"], 1)
            self.assertEqual(summary["status_records"], 1)
            all_text = "\n".join(
                path.read_text(encoding="utf-8")
                for path in Path(directory).glob("*.jsonl"))
            self.assertNotIn("pass@", all_text)
            self.assertNotIn("secret-value", all_text)
            self.assertIn("[REDACTED]", all_text)


class WorkerTests(unittest.TestCase):
    def test_message_errors_do_not_escape_or_stop_worker_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            worker = ForceOrderArchiveWorker(directory)
            worker._on_message(None, json.dumps(payload()))
            coinm = payload()
            coinm["st"] = 2
            worker._on_message(None, json.dumps(coinm))
            worker._on_message(None, "not-json")
            status = worker.snapshot()
            self.assertEqual(status["events_written"], 1)
            self.assertEqual(status["parse_errors"], 1)
            self.assertEqual(status["non_usdm_ignored"], 1)
            self.assertIn("ArchivePayloadError", status["last_error"])
            self.assertEqual(summarize_archive(directory)["events"], 1)


if __name__ == "__main__":
    unittest.main()
