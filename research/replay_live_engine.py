"""Offline core replay using the live engine, not the legacy vectorized model.

No bot import/network, no parameter search, no performance/OOS selection. The
caller must supply scan times and point-in-time universe membership. Uniform
hourly scans are an idealized experiment, NOT evidence of actual notification.
"""
from __future__ import annotations

from bisect import bisect_right
from collections import Counter
from dataclasses import asdict
import hashlib
import json
import math
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from strategy_engine import (CoreRules, ENGINE_VERSION, HOUR_MS,
                             closed_window_features, funding_squeeze, should_fire)


def replay(candles, funding, scan_times_ms, *, symbol, universe, rules,
           extended=False, observe=False, disabled=()):
    """One symbol, one constant membership interval, empty initial state.

    Warm up from pre-evaluation scans; slice emitted events afterwards. At a
    membership/restart boundary either reproduce state explicitly in a future
    adapter or label the limitation. S2 event time retains settlement millis;
    decision time is separately recorded. Funding is NOT rounded into the past.
    """
    if not symbol or not universe or not isinstance(rules, CoreRules):
        raise ValueError("explicit_symbol_universe_rules_required")
    disabled = frozenset(disabled)
    if not disabled <= {"S1", "S2", "S3"}:
        raise ValueError("unknown_disabled_strategy")
    scans = list(scan_times_ms)
    if any(type(t) is not int or t < 0 for t in scans) or any(
            b <= a for a, b in zip(scans, scans[1:])):
        raise ValueError("scan_times_must_increase")
    by_time = {}
    for bar in candles:
        stamp = bar["open_time"]
        if type(stamp) is not int or stamp % HOUR_MS:
            raise ValueError("invalid_hourly_timestamp")
        if stamp in by_time and by_time[stamp] != bar:
            raise ValueError("conflicting_candle")
        by_time[stamp] = bar
    bars = [by_time[t] for t in sorted(by_time)]
    closes_at = [b["open_time"] + HOUR_MS for b in bars]
    fr_by_time = {}
    for row in funding:
        stamp, rate = row["time"], row["rate"]
        if type(stamp) is not int or stamp < 0 or not math.isfinite(rate):
            raise ValueError("invalid_funding")
        if stamp in fr_by_time and fr_by_time[stamp]["rate"] != rate:
            raise ValueError("conflicting_funding")
        fr_by_time[stamp] = {"time": stamp, "rate": rate}
    fr_times = sorted(fr_by_time)
    fr = [fr_by_time[t] for t in fr_times]
    prev, last, events = {}, {}, []
    skipped = Counter()
    cached_end, features = -1, None
    extended = extended or observe
    rules_hash = rules.fingerprint()

    def emit(strategy, stamp, now, horizon, market, price):
        key = f"{strategy}|{symbol}|{stamp}|{rules_hash}|{universe}"
        events.append({
            "replay_event_key": hashlib.sha256(key.encode()).hexdigest(),
            "strategy": strategy, "symbol": symbol, "direction": "LONG",
            "universe": universe, "engine_version": ENGINE_VERSION,
            "engine_config_hash": rules_hash, "bar_time_ms": stamp,
            "decision_time_ms": now, "signal_price": price,
            "performance_market": market, "horizon_hours": horizon,
            "source": "offline_replay_not_delivery",
        })

    for now in scans:
        end = bisect_right(closes_at, now)
        if end != cached_end:
            cached_end = end
            try:
                features = closed_window_features(
                    bars[max(0, end - rules.kline_limit + 1):end], rules)
            except ValueError:
                features = None
        if features is None:
            skipped["warmup_or_invalid_hourly_window"] += 1
            continue
        # Missing latest expected bar is a data gap, never silently a stale scan.
        if features["bar_time_ms"] != (now // HOUR_MS - 1) * HOUR_MS:
            skipped["latest_closed_bar_missing"] += 1
            continue

        def fire(strategy, cond, cooldown):
            return should_fire(prev, last, strategy, symbol, cond, cooldown,
                               now / 1000)

        if "S1" not in disabled and fire("S1", features["s1"], rules.s1_cooldown_hours):
            name = "S1+S4" if features["s4"] else "S1"
            if observe:
                name = {"S1+S4": "S5", "S1": "S6"}[name]
            emit(name, features["bar_time_ms"], now, 24, "spot", features["signal_price"])
        if (not extended and "S3" not in disabled
                and fire("S3", features["s3_spike"], rules.s3_cooldown_hours)
                and features["green_bar"]):
            emit("S3", features["bar_time_ms"], now, 4, "spot", features["signal_price"])
        if not extended and "S2" not in disabled:
            pos = bisect_right(fr_times, now)
            known = fr[max(0, pos - rules.funding_persistence):pos]
            if len(known) < rules.funding_persistence:
                skipped["funding_unavailable"] += 1
            elif fire("S2", funding_squeeze(known, rules.funding_threshold_pct,
                                           rules.funding_persistence), rules.s2_cooldown_hours):
                # Spot close is never a fake perp execution price.
                emit("S2", known[-1]["time"], now, 72, "um_perp", None)
    return {"engine_version": ENGINE_VERSION, "engine_config_hash": rules_hash,
            "rules": asdict(rules), "events": events,
            "scan_count": len(scans), "skipped": dict(sorted(skipped.items())),
            "limitations": ["idealized_data_availability_no_network_latency",
                            "caller_supplied_membership_not_current_survivors",
                            "empty_initial_state_no_delivery_or_fill_evidence",
                            "funding_source_completeness_must_be_audited_separately"],
            "interpretation": "Parity replay only; not an OOS or profitability claim."}
