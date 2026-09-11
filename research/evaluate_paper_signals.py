"""Offline confirmed-notification -> paper outcome -> cohort report adapter.

Only explicit manual CLI output is written. No bot import, download, Telegram,
orders, state rewrite or threshold selection. Candles JSONL must label the exact
market and contract on each row; prices without market provenance are unusable.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from paper_execution import ExecutionSpec, evaluate_path
from qc_export import canonical_event_id
from research.evidence_summary import summarize
from research.paper_inputs import load_outbox_records, verify_candle_manifest, file_sha256

HORIZONS = {"S1": 24, "S1+S4": 24, "S2": 72, "S3": 4, "S5": 24, "S6": 24, "G1": 4}


def utc_ms(value):
    stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if stamp.tzinfo is None:
        raise ValueError("timezone_required")
    return int(stamp.astimezone(timezone.utc).timestamp()*1000)


def evaluate_records(records, candle_rows, *, as_of_ms, target_pct=2., cost_bps=12., latency_ms=0):
    """One fixed specification per run; never choose it from the output results.

    Duplicate deliveries use the earliest confirmed timestamp, regardless of how
    its hypothetical outcome looks. Conflicting event provenance is quarantined.
    Legacy unconfirmed events are counted as unavailable, not silently dropped.
    """
    if target_pct not in (2., 3.) or cost_bps not in (12., 24.):
        raise ValueError("only_preregistered_primary_or_sensitivity_specs")
    if type(latency_ms) is not int or latency_ms not in (0, 300_000):
        raise ValueError("only_preregistered_latency")
    if type(as_of_ms) is not int or as_of_ms < 0:
        raise ValueError("invalid_as_of")
    candles = defaultdict(list)
    rejected = Counter()
    for candle in candle_rows:
        if not isinstance(candle, dict) or candle.get("market") not in ("spot", "um_perp"):
            rejected["invalid_candle_market"] += 1
            continue
        if not isinstance(candle.get("symbol"), str) or not re.fullmatch(r"\w+USDT", candle["symbol"]):
            rejected["invalid_candle_symbol"] += 1
            continue
        candles[candle["market"], candle.get("symbol")].append(candle)
    candidates = defaultdict(list)
    for record in records:
        if not isinstance(record, dict):
            rejected["invalid_signal_record"] += 1
            continue
        strategy, symbol = record.get("strategy"), record.get("symbol")
        if not isinstance(strategy, str) or strategy not in HORIZONS or not isinstance(symbol, str) or not re.fullmatch(r"\w+USDT", symbol):
            rejected["unsupported_strategy_or_symbol"] += 1
            continue
        market = "um_perp" if strategy in ("S2", "G1") else "spot"
        if record.get("performance_market") != market or record.get("direction") != "LONG":
            rejected["market_or_direction_not_explicit"] += 1
            continue
        if type(record.get("horizon_hours")) is not int or record["horizon_hours"] != HORIZONS[strategy]:
            rejected["horizon_mismatch"] += 1
            continue
        if any(value is not None and (not isinstance(value, str) or
               not value.strip() or not re.fullmatch(r"[^\x00-\x1f\x7f]{1,128}", value))
               for value in (record.get(k) for k in
                             ("universe", "config_version", "engine_version", "engine_config_hash"))):
            rejected["invalid_provenance_field"] += 1
            continue
        contract = record.get("performance_symbol") if market == "um_perp" else symbol
        if contract is not None and (not isinstance(contract, str) or
                                    not re.fullmatch(r"\w+USDT", contract)):
            rejected["invalid_contract"] += 1
            continue
        try:
            bar_ms = utc_ms(record["bar_time"])
            confirmed = record.get("delivery_confirmed") is True
            delivered = utc_ms(record["delivered_at"]) if confirmed else bar_ms
            known_after = bar_ms + (3_600_000 if market == "spot" else 0)
            if confirmed and delivered < known_after or delivered > as_of_ms:
                raise ValueError("invalid_delivery_time")
        except (KeyError, TypeError, ValueError, OverflowError):
            rejected["invalid_signal_or_delivery_time"] += 1
            continue
        supplied_id = record.get("event_id")
        event_id = canonical_event_id(record)
        if supplied_id is not None and supplied_id != event_id:
            rejected["event_id_mismatch"] += 1
            continue
        # Use explicit perp contract. Never guess 1000-token multipliers.
        identity = (strategy, symbol, market, contract, record.get("universe"),
                    record.get("config_version"), record.get("engine_config_hash"),
                    record.get("engine_version"), bar_ms)
        candidates[event_id].append(dict(identity=identity, confirmed=confirmed, delivered=delivered))
    chosen = {}
    for event_id, items in candidates.items():
        # Count every conflicting row in the same category, independent of log order.
        if len({item["identity"] for item in items}) != 1:
            rejected["conflicting_event_provenance"] += len(items)
            continue
        if len(items) > 1:
            rejected["duplicate_delivery"] += len(items)-1
        chosen[event_id] = min(items, key=lambda item: (not item["confirmed"], item["delivered"]))
    measured = []
    for event_id, item in sorted(chosen.items()):
        strategy, symbol, market, contract, universe, config, engine, version, bar_ms = item["identity"]
        spec = ExecutionSpec(target_pct=target_pct, stop_pct=1.5,
                             horizon_hours=HORIZONS[strategy], latency_ms=latency_ms,
                             round_trip_cost_bps=cost_bps)
        out = evaluate_path(candles[market, contract], delivered_at_ms=item["delivered"],
                            delivery_confirmed=item["confirmed"], market=market,
                            candle_market=market, symbol=contract, candle_symbol=contract,
                            spec=spec, as_of_ms=as_of_ms)
        measured.append({"event_id": event_id, "symbol": symbol, "strategy": strategy,
                         "direction": "LONG", "universe": universe or "UNKNOWN",
                         "config_version": config or "UNKNOWN", "engine_config_hash": engine or "UNKNOWN",
                         "engine_version": version or "UNKNOWN", "bar_time_ms": bar_ms,
                         "observed_at_ms": item["delivered"],
                         "evidence_source": ("confirmed_delivery" if item["confirmed"]
                                             else "legacy_unverified_delivery"), "outcome": out})
    return {"schema_version": "paper-signals-report-v1", "as_of_ms": as_of_ms,
            "records": measured, "summary": summarize(measured),
            "rejected_counts": dict(sorted(rejected.items())),
            "interpretation": "Hypothetical notification outcomes, not actual trades or validated reliability."}


def read_jsonl(path):
    rows, malformed = [], 0
    with Path(path).open(encoding="utf-8") as stream:
        for line in stream:
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except (ValueError, TypeError):
                malformed += 1
    return rows, malformed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--signals-log", type=Path, required=True)
    parser.add_argument("--candles-jsonl", type=Path, required=True)
    parser.add_argument("--delivery-outbox", type=Path,
                        help="Optional private outbox snapshot; read only, never exported")
    parser.add_argument("--candles-manifest", type=Path,
                        help="Optional checksum/coverage manifest from research/paper_inputs.py")
    parser.add_argument("--as-of", required=True, help="Timezone-aware ISO UTC cutoff")
    parser.add_argument("--target-pct", type=float, choices=(2., 3.), default=2.)
    parser.add_argument("--cost-bps", type=float, choices=(12., 24.), default=12.)
    parser.add_argument("--latency-ms", type=int, choices=(0, 300_000), default=0)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    inputs = [args.signals_log, args.candles_jsonl, args.delivery_outbox, args.candles_manifest]
    if args.output.resolve() in [p.resolve() for p in inputs if p is not None]:
        parser.error("output_must_not_overwrite_inputs")
    signals, bad_signals = read_jsonl(args.signals_log)
    candles, bad_candles = read_jsonl(args.candles_jsonl)
    cutoff = utc_ms(args.as_of)
    outbox_rows, outbox_counts = (load_outbox_records(args.delivery_outbox, as_of_ms=cutoff)
                                 if args.delivery_outbox else ([], {}))
    candle_provenance = (verify_candle_manifest(args.candles_manifest, args.candles_jsonl)
                         if args.candles_manifest else {"status": "unverified",
                                                       "sha256": file_sha256(args.candles_jsonl)})
    log_count = len(signals)
    signals.extend(outbox_rows)
    report = evaluate_records(signals, candles, as_of_ms=cutoff,
                              target_pct=args.target_pct, cost_bps=args.cost_bps,
                              latency_ms=args.latency_ms)
    report["malformed_rows"] = {"signals": bad_signals, "candles": bad_candles}
    report["input_provenance"] = {
        "signals_sha256": file_sha256(args.signals_log),
        "delivery_sources": "log_and_outbox_snapshot" if args.delivery_outbox else "log_only_retry_coverage_unknown",
        "log_rows": log_count, "outbox": outbox_counts, "candles": candle_provenance,
        "limitations": ["snapshots_do_not_prove_complete_delivery_history",
                        "declared_source_and_checksum_are_not_independent_authentication",
                        "point_in_time_universe_not_verified", "forward_oos_not_validated"],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False)+"\n", encoding="utf-8")
    print(f"Paper observations: {len(report['records'])}; cohorts: {len(report['summary']['cohorts'])}")
    print("No orders or notifications sent; missing funding is not zero funding.")


if __name__ == "__main__":
    main()
