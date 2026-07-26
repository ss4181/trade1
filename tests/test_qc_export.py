"""Olay-bazli QC export ve GitHub yayin davranisi (tamamen cevrimdisi)."""

from __future__ import annotations

import csv
import contextlib
import io
import json
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import requests

sys.path.insert(0, str(Path(__file__).parent.parent))
import signal_bot as bot
from qc_export import build_package, canonical_event_id, git_blob_sha
from qc_export import EVENT_FIELDS, OUTCOME_FIELDS, REJECTED_FIELDS, SUMMARY_FIELDS


NOW = datetime(2026, 7, 24, 12, tzinfo=timezone.utc)
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]


def event(
    strategy: str = "S1",
    symbol: str = "BTCUSDT",
    bar: datetime | None = None,
    event_id: str | None = None,
) -> dict:
    horizons = {"S1": 24, "S1+S4": 24, "S2": 72, "S3": 4}
    row = {
        "strategy": strategy,
        "symbol": symbol,
        "direction": "LONG",
        "bar_time": (bar or datetime(2026, 7, 20, 0, tzinfo=timezone.utc)
                     ).isoformat(),
        "price": 100,
        "horizon_hours": horizons.get(strategy, 24),
        "confidence": "YUKSEK",
        "strength": "NORMAL",
    }
    if event_id:
        row["event_id"] = event_id
    return row


def lines(*records: object) -> list[str]:
    return [json.dumps(row) if not isinstance(row, str) else row
            for row in records]


def loader_with_calls(calls: list[tuple[str, str, int, int]]):
    def load(market: str, symbol: str, start_ms: int, limit: int):
        calls.append((market, symbol, start_ms, limit))
        rows = []
        for offset in range(limit):
            rows.append({
                "open_time": start_ms + offset * 3_600_000,
                "open": 100 + offset,
                "close": 100.5 + offset,
            })
        source = ("perp;funding:not_modeled"
                  if market == "usd_m_perp" else "spot")
        return rows, source
    return load


def package(raw_lines, *, now=NOW, loader=None):
    return build_package(
        raw_lines,
        configured_symbols=SYMBOLS,
        core_symbols=["BTCUSDT", "ETHUSDT"],
        extended_symbols=["SOLUSDT"],
        config_version="cfg-test",
        confidence_rank={"DUSUK": 0, "ORTA": 1, "YUKSEK": 2},
        min_confidence="ORTA",
        now=now,
        round_trip_cost_bps=12,
        candle_loader=loader,
    )


def csv_rows(content: bytes) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(content.decode("utf-8"))))


class QCExportTests(unittest.TestCase):
    def test_duplicate_event_id_is_one_event(self):
        first = event(event_id="a" * 32)
        second = {**first, "price": 999}
        built = package(lines(first, second))
        accepted = csv_rows(built.files["qc/signal_events.csv"])
        rejected = csv_rows(built.files["qc/rejected_records.csv"])
        self.assertEqual(len(accepted), 1)
        self.assertEqual(rejected[0]["rejection_reason"],
                         "duplicate_event_id")

    def test_test_and_out_of_universe_are_rejected(self):
        built = package(lines(
            event(strategy="TEST"),
            event(symbol="X"),
            "{broken-json",
        ))
        self.assertEqual(built.accepted_count, 0)
        reasons = {row["rejection_reason"] for row in
                   csv_rows(built.files["qc/rejected_records.csv"])}
        self.assertEqual(
            reasons,
            {"test_strategy", "symbol_not_in_configured_universe",
             "malformed_json"},
        )

    def test_pending_and_matured_are_distinct(self):
        calls = []
        matured = event(event_id="a" * 32)
        pending = event(
            strategy="S3", event_id="b" * 32,
            bar=NOW - timedelta(hours=2))
        built = package(lines(matured, pending),
                        loader=loader_with_calls(calls))
        outcomes = {row["event_id"]: row for row in
                    csv_rows(built.files["qc/signal_outcomes.csv"])}
        self.assertEqual(outcomes["a" * 32]["outcome_status"], "matured")
        self.assertEqual(outcomes["b" * 32]["outcome_status"], "pending")

    def test_strategy_market_routing(self):
        calls = []
        built = package(
            lines(event("S1"), event("S2"), event("S3")),
            loader=loader_with_calls(calls),
        )
        outcomes = csv_rows(built.files["qc/signal_outcomes.csv"])
        markets = {row["strategy"]: row["performance_market"]
                   for row in outcomes}
        self.assertEqual(markets["S1"], "spot")
        self.assertEqual(markets["S3"], "spot")
        self.assertEqual(markets["S2"], "usd_m_perp")
        self.assertIn("funding:not_modeled",
                      next(row["outcome_source"] for row in outcomes
                           if row["strategy"] == "S2"))

    def test_entry_and_exit_timing(self):
        calls = []
        row = event("S3")
        bar = datetime.fromisoformat(row["bar_time"])
        built = package(lines(row), loader=loader_with_calls(calls))
        outcome = csv_rows(built.files["qc/signal_outcomes.csv"])[0]
        self.assertEqual(
            outcome["entry_time_utc"],
            (bar + timedelta(hours=1)).isoformat(
                timespec="seconds").replace("+00:00", "Z"),
        )
        self.assertEqual(
            outcome["exit_time_utc"],
            (bar + timedelta(hours=5)).isoformat(
                timespec="seconds").replace("+00:00", "Z"),
        )
        self.assertEqual(float(outcome["entry_price"]), 101)
        self.assertEqual(float(outcome["exit_price"]), 104.5)

    def test_csv_generation_is_deterministic(self):
        raw = lines(event("S1"), event("S3"))
        one = package(raw, loader=loader_with_calls([]))
        two = package(raw, loader=loader_with_calls([]))
        for path in one.files:
            if path.endswith(".csv"):
                self.assertEqual(one.files[path], two.files[path], path)

    def test_exact_headers_summary_warning_and_manifest_hashes(self):
        built = package(lines(event()), loader=loader_with_calls([]))
        expected = {
            "qc/signal_events.csv": EVENT_FIELDS,
            "qc/signal_outcomes.csv": OUTCOME_FIELDS,
            "qc/strategy_summary.csv": SUMMARY_FIELDS,
            "qc/rejected_records.csv": REJECTED_FIELDS,
        }
        for path, fields in expected.items():
            header = built.files[path].decode("utf-8").splitlines()[0]
            self.assertEqual(header.split(","), fields)
        summary = csv_rows(built.files["qc/strategy_summary.csv"])[0]
        self.assertEqual(summary["sample_warning"], "small_sample")
        manifest = json.loads(built.files["qc/manifest.json"])
        for path in expected:
            self.assertIn(path, manifest["files"])
            self.assertEqual(len(manifest["files"][path]["sha256"]), 64)

    def test_secret_values_never_enter_outputs(self):
        row = {
            **event(),
            "api_key": "TOP_SECRET_VALUE",
            "token": "ANOTHER_SECRET",
            "event_id": "TOP_SECRET_VALUE",
            "config_version": "cfg-TOP_SECRET_VALUE",
            "source": "TOP_SECRET_VALUE",
            "confidence": "TOP_SECRET_VALUE",
            "strength": "TOP_SECRET_VALUE",
            "suppression_reason": "TOP_SECRET_VALUE",
        }
        built = package(lines(row, "TOP_SECRET_VALUE {not json"))
        joined = b"\n".join(built.files.values())
        self.assertNotIn(b"TOP_SECRET_VALUE", joined)
        self.assertNotIn(b"ANOTHER_SECRET", joined)

    def test_event_id_matches_bot(self):
        """signals.log <-> QC capraz eslestirmesinin sartı: iki tarafin olay
        kimligi ayni algoritmayi (32 hex) uretmeli. qc_export 32-hex olmayan
        kimlikleri reddedip yeniden hesapladigi icin bu esitlik zorunludur."""
        cases = [
            {"strategy": "S1", "symbol": "BTCUSDT", "direction": "LONG",
             "bar_time": "2026-07-20T12:00:00+00:00", "horizon_hours": 24},
            {"strategy": "S1+S4", "symbol": "pepeusdt", "direction": "long",
             "bar_time": "2026-07-20T12:00:00Z", "horizon_hours": 24},
            {"strategy": "S2", "symbol": "REUSDT", "direction": "LONG",
             "bar_time": "2026-07-20T08:00:00+00:00", "horizon_hours": 72},
        ]
        for case in cases:
            bot_id = bot._signal_event_id(case)
            qc_id = canonical_event_id(case)
            self.assertEqual(bot_id, qc_id, case)
            self.assertEqual(len(bot_id), 32)
            self.assertTrue(all(c in "0123456789abcdef" for c in bot_id))

    # NOT (2026-07-26 denetimi): asagidaki uc test, qc_export'un signal_bot'a
    # KABLOLANMIS oldugu eski yamayi varsayar. "Reliability hardening" surumu
    # kendi olay-kimligi/teslimat-kaydi sistemini getirdigi icin QC entegrasyonu
    # bilerek BAGLANMADI (qc_export bagimsiz arac olarak durur; signals.log'u
    # cevrimdisi isler). Kancalar eklenirse bu testler otomatik aktiflesir.
    _HOOKS = all(hasattr(bot, n) for n in
                 ("build_qc_export_package", "_publish_qc_package",
                  "PUBLISH_QC_ENABLED"))

    @unittest.skipUnless(_HOOKS, "signal_bot QC kancalari bagli degil")
    def test_unchanged_csv_is_not_uploaded(self):
        built = package(lines(event()), loader=loader_with_calls([]))
        puts = []

        def sha(path):
            return git_blob_sha(built.files[path])

        with patch.object(bot, "build_qc_export_package",
                          return_value=built), \
             patch.object(bot, "_gh_get_sha", side_effect=sha), \
             patch.object(bot, "_gh_put_file",
                          side_effect=lambda *args: puts.append(args)):
            self.assertFalse(bot._publish_qc_package())
        self.assertEqual(puts, [])

    @unittest.skipUnless(_HOOKS, "signal_bot QC kancalari bagli degil")
    def test_github_error_is_contained(self):
        old_enabled = bot.PUBLISH_ENABLED
        old_qc = bot.PUBLISH_QC_ENABLED
        old_last = bot._last_publish
        try:
            bot.PUBLISH_ENABLED = False
            bot.PUBLISH_QC_ENABLED = True
            bot._last_publish = 0
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr), \
                 patch.object(bot, "_gh_ensure_branch",
                              side_effect=requests.ConnectionError(
                                  "simulated token=SECRET")):
                bot.publish_to_github(force=True)  # exception must not escape
            self.assertNotIn("SECRET", stderr.getvalue())
        finally:
            bot.PUBLISH_ENABLED = old_enabled
            bot.PUBLISH_QC_ENABLED = old_qc
            bot._last_publish = old_last

    @unittest.skipUnless(_HOOKS, "signal_bot QC kancalari bagli degil")
    def test_automatic_publish_creates_no_local_csv(self):
        built = package(lines(event()), loader=loader_with_calls([]))
        root = Path(bot.__file__).parent
        before = {path.resolve() for path in root.rglob("*.csv")}
        with patch.object(bot, "build_qc_export_package",
                          return_value=built), \
             patch.object(bot, "_gh_get_sha", return_value=None), \
             patch.object(bot, "_gh_put_file", return_value="new-sha"):
            bot._publish_qc_package()
        after = {path.resolve() for path in root.rglob("*.csv")}
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
