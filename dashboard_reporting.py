"""Read-only dashboard projections. Never fetch prices or send notifications."""
import json
from pathlib import Path


def market_name(value):
    return {"usd_m_perp": "um_perp", "usdm": "um_perp"}.get(value, value)


def bracket_summary(events):
    counts = dict(hit=0, missed=0, pending=0, unavailable=0, ambiguous=0)
    for event in events.values():
        if event.get("measurement_version") != "g2-scheduled-bracket-v1":
            continue
        status = (event.get("g2_bracket") or {}).get("status")
        key = ("hit" if status == "TP" else "missed" if status in
               ("SL", "AMBIGUOUS_SL", "TIMEOUT") else
               "pending" if status == "PENDING" else "unavailable")
        counts[key] += 1
        counts["ambiguous"] += status == "AMBIGUOUS_SL"
    resolved = counts["hit"] + counts["missed"]
    return {**counts, "resolved": resolved,
            "hit_rate_pct": round(counts["hit"] / resolved * 100, 1) if resolved else None,
            "sample_warning": resolved < 30,
            "measurement": "scheduled_binance_TP3_before_SL2"}


def live_regime_summary(records, events):
    """Frozen regime at signal time; missing metadata never uses today's regime.

    Matured cohorts only, including losses. Missing/untracked outcomes stay
    visible. G2 bracket outcomes cannot supply unrestricted TP2/TP3 touches.
    """
    grouped = {}
    unique = {r.get("event_id"): r for r in records if r.get("event_id")}
    for eid, record in unique.items():
        if record.get("delivery_confirmed") is not True:
            continue
        strategy = record.get("strategy", "UNKNOWN")
        if strategy.startswith("TEST") or strategy == "DL1":
            continue
        event = events.get(eid) or {}
        keys = ("universe", "config_version", "direction", "engine_config_hash")
        identity = {k: record.get(k) or event.get(k) or "UNKNOWN" for k in keys}
        identity.update(strategy=strategy,
                        market=market_name(record.get("performance_market") or event.get("market") or "UNKNOWN"),
                        regime=record.get("market_regime") or "UNKNOWN",
                        subtype=record.get("market_regime_subtype") or "UNKNOWN",
                        regime_version=record.get("market_regime_version") or "UNKNOWN")
        key = tuple(identity.values())
        row = grouped.setdefault(key, {**identity, "n": 0,
             **{f"tp{x}": dict(hit=0, missed=0, pending=0, unavailable=0) for x in (2, 3)}})
        row["n"] += 1
        for level in (2, 3):
            target = (event.get("targets") or {}).get(str(level))
            if strategy == "G2" or event.get("measurement_version") != "signal-reference-touch-v1" or target is None:
                outcome = "unavailable"
            elif event.get("status") == "expired":
                outcome = "hit" if target.get("hit_at") else "missed"
            elif event.get("status") == "active":
                outcome = "pending"
            else:
                outcome = "unavailable"
            row[f"tp{level}"][outcome] += 1
    for row in grouped.values():
        for level in (2, 3):
            counts = row[f"tp{level}"]
            counts["resolved"] = counts["hit"] + counts["missed"]
            counts["hit_rate_pct"] = (round(100 * counts["hit"] / counts["resolved"], 1)
                                      if counts["resolved"] else None)
    return {"measurement": "delivered_reference_touch_strategy_horizon",
            "rows": sorted(grouped.values(), key=lambda r: tuple(str(v) for v in
                           (r["strategy"], r["subtype"], r["universe"], r["config_version"])))}


def historical_regime_report(root):
    """Small versioned research summary, not the private price archive."""
    folder = Path(root) / "research" / "results"
    paths = sorted(folder.glob("regime_eventual_touch_*.json"), reverse=True)
    for path in paths:
        try:
            report = json.loads(path.read_text(encoding="utf-8"))
            if report.get("version") != "eventual-touch-observed-v1" or not isinstance(report.get("summaries"), list):
                continue
            return {"available": True, "report_file": path.name,
                    **{k: report.get(k) for k in ("version", "measurement", "n", "summaries",
                         "unavailable_strategies", "caveats", "events_sha256")}}
        except (OSError, ValueError, TypeError):
            continue
    return {"available": False, "reason": "research_report_missing_or_invalid", "summaries": []}
