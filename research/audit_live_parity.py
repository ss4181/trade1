"""TRAIN-only legacy/canonical event audit; no return evaluation or tuning.

python research/audit_live_parity.py --output research/data/parity_audit.json
Historical TEST (2026-01-01 onward) cannot be evaluated by this command.
"""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import re
import sys

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from strategy_engine import CoreRules, ENGINE_VERSION, HOUR_MS
from research.replay_live_engine import replay
from research.strategies import s1_events, s3_events

TRAIN_END = pd.Timestamp("2026-01-01", tz="UTC")


def audit(data_dir, symbols, start="2025-12-01", end="2025-12-08"):
    start, end = pd.Timestamp(start), pd.Timestamp(end)
    start = start.tz_localize("UTC") if start.tzinfo is None else start.tz_convert("UTC")
    end = end.tz_localize("UTC") if end.tzinfo is None else end.tz_convert("UTC")
    if not start < end <= TRAIN_END:
        raise ValueError("train_only_do_not_reopen_historical_test")
    if end - start > pd.Timedelta(days=31):
        raise ValueError("bounded_audit_max_31_days")
    if not symbols or any(not re.fullmatch(r"\w+USDT", s) for s in symbols):
        raise ValueError("invalid_symbol")
    rules = CoreRules()
    report = {"schema_version": "live-parity-audit-v1", "engine_version": ENGINE_VERSION,
              "engine_config_hash": rules.fingerprint(), "rules": asdict(rules),
              "start_utc": start.isoformat(), "end_utc_exclusive": end.isoformat(),
              "scan_model": "hourly_at_close_72h_state_warmup_no_latency",
              "selection": "fixed_symbols_and_dates_no_optimization",
              "results": [], "return_evaluation": False, "historical_test_evaluated": False,
              "input_read_scope": "full_parquet_columns_filtered_before_signal_calculation",
              "limitations": ["S1_S3_only_funding_not_audited_here",
                              "historical_membership_not_reconstructed",
                              "parity_is_not_profitability_or_OOS_validation"]}
    for symbol in symbols:
        path = Path(data_dir) / "spot" / (symbol + ".parquet")
        frame = pd.read_parquet(path, columns=["open_time", "open", "high", "low", "close", "volume"])
        # Slice BEFORE any signal computation. Do not calculate test statistics.
        frame = frame[frame.open_time < end.value//1_000_000].sort_values("open_time")
        frame = frame.set_index(pd.to_datetime(frame.open_time, unit="ms", utc=True))
        if frame.empty or frame.index.min() > start - pd.Timedelta(hours=322):
            raise ValueError("insufficient_pre_audit_warmup")
        panel = {symbol: frame}
        old_s1, _ = s1_events(panel, 101, rules.oversold)[symbol]
        old_s3_any, _ = s3_events(panel, rules.volume_threshold, use_log=True,
                                  direction="long")[symbol]
        old_s3_up, _ = s3_events(panel, rules.volume_threshold, use_log=True,
                                 direction="bar_up")[symbol]
        old = []
        for stamp in old_s1:
            confluence = any(pd.Timedelta(0) <= stamp - spike <= pd.Timedelta(hours=24)
                             for spike in old_s3_any)
            # Partition legacy family counts; an inclusive S1 benchmark is not
            # interchangeable with exclusive live S1-only statistics.
            old.append(("S1+S4" if confluence else "S1", int(stamp.value//1_000_000)))
        old.extend(("S3", int(t.value//1_000_000)) for t in old_s3_up)
        start_ms, end_ms = int(start.value//1_000_000), int(end.value//1_000_000)
        new = replay(frame.reset_index(drop=True).to_dict("records"), [],
                     range(start_ms-72*HOUR_MS, end_ms+1, HOUR_MS), symbol=symbol,
                     universe="core30_audit_fixed_membership", rules=rules, disabled=("S2",))
        old_set = {(s, t) for s, t in old if start_ms <= t < end_ms}
        new_set = {(e["strategy"], e["bar_time_ms"]) for e in new["events"]
                   if start_ms <= e["bar_time_ms"] < end_ms}
        report["results"].append({
            "symbol": symbol, "source_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "legacy_event_counts": dict(sorted(Counter(s for s, _ in old_set).items())),
            "canonical_event_counts": dict(sorted(Counter(s for s, _ in new_set).items())),
            "matched_events": len(old_set & new_set), "legacy_only_events": len(old_set-new_set),
            "canonical_only_events": len(new_set-old_set), "replay_skipped": new["skipped"],
        })
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", default="research/data")
    parser.add_argument("--symbols", nargs="+", default=["BTCUSDT", "ETHUSDT", "1INCHUSDT"])
    parser.add_argument("--start", default="2025-12-01")
    parser.add_argument("--end", default="2025-12-08")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = audit(args.data_dir, args.symbols, args.start, args.end)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False)+"\n",
                           encoding="utf-8")
    for result in report["results"]:
        print(f"{result['symbol']}: legacy={result['legacy_event_counts']} "
              f"canonical={result['canonical_event_counts']} "
              f"matched={result['matched_events']} "
              f"legacy_only={result['legacy_only_events']} "
              f"canonical_only={result['canonical_only_events']}")
    print("TRAIN-only event audit; thresholds unchanged, TEST not evaluated.")


if __name__ == "__main__":
    main()
