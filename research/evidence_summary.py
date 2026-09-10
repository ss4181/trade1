"""Cohort-safe descriptive evidence, never a confidence label or promotion rule.

Input rows wrap paper_execution outcomes with event/cohort metadata. No fills,
balances or personal data are read. Old/missing provenance is kept visible in
an UNKNOWN cohort, not assigned today's settings retrospectively.
"""
from __future__ import annotations

from collections import Counter, defaultdict
import math
import random
import statistics

COHORT_FIELDS = ("strategy", "direction", "performance_market", "universe",
                 "config_version", "engine_config_hash", "evidence_source",
                 "measurement_version", "execution_spec_hash")
DAY_MS = 86_400_000


def _quantile(values, p):
    values = sorted(values)
    x = (len(values) - 1) * p
    lo = int(x)
    return values[lo] + (values[min(lo + 1, len(values) - 1)] - values[lo]) * (x - lo)


def block_mean_interval(observations, *, iterations=2000, block_days=7, seed=0):
    """Circular calendar-day blocks; all simultaneous symbols stay together.

    observations: (UTC epoch day, net percentage). Missing days stay empty. This
    is a dependence-aware descriptive interval, NOT P(strategy succeeds), an
    OOS test or a multiple-testing correction. No interval for small samples.
    """
    if type(block_days) is not int or block_days < 1 or iterations < 100:
        raise ValueError("invalid_bootstrap_spec")
    if len(observations) < 30:
        return None
    first, last = min(d for d, _ in observations), max(d for d, _ in observations)
    size = last - first + 1
    if size < 4 * block_days:
        return None
    daily = [[0.0, 0] for _ in range(size)]
    for day, value in observations:
        if not math.isfinite(value):
            raise ValueError("invalid_return")
        daily[day - first][0] += value
        daily[day - first][1] += 1
    rng, means = random.Random(seed), []
    for _ in range(iterations):
        total = count = sampled = 0
        while sampled < size:
            start = rng.randrange(size)
            for offset in range(min(block_days, size - sampled)):
                value, n = daily[(start + offset) % size]
                total += value
                count += n
                sampled += 1
        if count:
            means.append(total / count)
    if len(means) < iterations * 0.9:
        return None
    return {"low_pct": _quantile(means, .025), "high_pct": _quantile(means, .975),
            "method": "circular_calendar_day_block_bootstrap_95pct",
            "block_days": block_days, "iterations": iterations, "seed": seed}


def summarize(records, *, bootstrap_iterations=2000):
    grouped, rejected, conflicted = defaultdict(dict), Counter(), set()
    for record in records:
        if not isinstance(record, dict) or not isinstance(record.get("outcome"), dict):
            rejected["invalid_record"] += 1
            continue
        out = record["outcome"]
        merged = {**record, **{k: out.get(k) for k in (
            "performance_market", "measurement_version", "execution_spec_hash")}}
        key = tuple(str(merged.get(k) or "UNKNOWN") for k in COHORT_FIELDS)
        event_id, stamp = record.get("event_id"), record.get("observed_at_ms")
        if not isinstance(event_id, str) or not event_id or type(stamp) is not int or stamp < 0:
            rejected["missing_event_id_or_time"] += 1
            continue
        if out.get("status") not in ("measured", "pending", "unavailable"):
            rejected["invalid_status"] += 1
            continue
        # Whitelist: never propagate tokens, chat IDs, freeform messages or raw rows.
        item = {"observed_at_ms": stamp, "status": out["status"],
                "net": out.get("net_return_pct"), "ex_funding": out.get("net_ex_funding_return_pct"),
                "tp_low": out.get("tp_before_sl_lower"), "tp_high": out.get("tp_before_sl_upper")}
        if any(v is not None and (type(v) not in (int, float) or not math.isfinite(v))
               for v in (item["net"], item["ex_funding"])):
            rejected["invalid_return"] += 1
            continue
        if item["status"] == "measured" and (
                type(item["tp_low"]) is not bool or type(item["tp_high"]) is not bool
                or item["tp_low"] > item["tp_high"] or item["ex_funding"] is None):
            rejected["invalid_measured_outcome"] += 1
            continue
        # A contradictory revision is not resolved by picking a nicer outcome.
        if (key, event_id) in conflicted:
            rejected["conflicting_duplicate"] += 1
            continue
        previous = grouped[key].get(event_id)
        if previous is not None and previous != item:
            del grouped[key][event_id]
            conflicted.add((key, event_id))
            rejected["conflicting_duplicate"] += 2
        elif previous is None:
            grouped[key][event_id] = item
        else:
            rejected["exact_duplicate"] += 1
    summaries = []
    for key, indexed in sorted(grouped.items()):
        if not indexed:
            continue
        # Stable event order makes bootstrap and floating-point sums deterministic.
        rows = [indexed[event_id] for event_id in sorted(indexed)]
        measured = [r for r in rows if r["status"] == "measured"]
        net = [r["net"] for r in measured if r["net"] is not None]
        ex = [r["ex_funding"] for r in measured if r["ex_funding"] is not None]
        observations = [(r["observed_at_ms"] // DAY_MS, r["net"])
                        for r in measured if r["net"] is not None]
        cohort = dict(zip(COHORT_FIELDS, key))
        warnings = []
        if "UNKNOWN" in key:
            warnings.append("legacy_or_missing_provenance")
        if len(measured) < 30:
            warnings.append("small_sample")
        days = len({r["observed_at_ms"] // DAY_MS for r in measured})
        if days < 30:
            warnings.append("few_event_days")
        if len(net) != len(measured):
            warnings.append("full_net_unavailable_funding_not_modeled")
        if len(measured) != len(rows):
            warnings.append("pending_or_missing_outcomes_not_losses_or_wins")
        interval = block_mean_interval(observations, iterations=bootstrap_iterations)
        def pct(n, d):
            return n / d * 100 if d else None
        summaries.append({
            **cohort, "n_total": len(rows), "n_measured": len(measured),
            "n_pending": sum(r["status"] == "pending" for r in rows),
            "n_unavailable": sum(r["status"] == "unavailable" for r in rows),
            "n_full_net": len(net), "event_days": days,
            "tp_before_sl_lower_pct": pct(sum(r["tp_low"] for r in measured), len(measured)),
            "tp_before_sl_upper_pct": pct(sum(r["tp_high"] for r in measured), len(measured)),
            "mean_net_pct": statistics.mean(net) if net else None,
            "median_net_pct": statistics.median(net) if net else None,
            "net_win_rate_pct": pct(sum(v > 0 for v in net), len(net)),
            "q10_net_pct": _quantile(net, .1) if net else None,
            "q90_net_pct": _quantile(net, .9) if net else None,
            "mean_net_ex_funding_pct": statistics.mean(ex) if ex else None,
            "mean_net_interval": interval, "warnings": warnings,
        })
    return {"schema_version": "cohort-evidence-v1", "cohorts": summaries,
            "rejected_counts": dict(sorted(rejected.items())),
            "interpretation": "Descriptive only; no calibrated confidence, OOS claim or promotion."}
