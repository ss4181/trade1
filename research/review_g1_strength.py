"""Read-only G1 strength-score forward report (g1-strength-v1).

Frozen by research/PREREG_G1_STRENGTH_2026-11-26.md. No network, tuning, bot import,
Telegram or orders. Until the readiness gate passes only counts are shown.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path
import random
import statistics as st
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from g1_entry import EXIT_VERSION
from g1_strength import VERSION

PREREG = Path(__file__).with_name("PREREG_G1_STRENGTH_2026-11-26.md")
GATE = {"events": 150, "days": 40, "weeks": 8, "per_group": 40}
COST_BPS = 20
GROUPS = ("low", "mid", "high")


def _num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def record(strength, shadow):
    """One usable (score, R, tp_hit, day) row, or None."""
    if not (isinstance(strength, dict) and strength.get("version") == VERSION
            and _num(strength.get("score"))):
        return None
    if not (isinstance(shadow, dict) and shadow.get("version") == EXIT_VERSION
            and shadow.get("status") == "complete" and shadow.get("complete") is True
            and _num(shadow.get("stop_pct")) and shadow["stop_pct"] > 0
            and _num(shadow.get("entry_time_ms"))):
        return None
    plan = (shadow.get("plans") or {}).get("tp2") or {}
    if not _num(plan.get("gross_pct")):
        return None
    return {"score": float(strength["score"]),
            "R": (plan["gross_pct"] - COST_BPS / 100) / shadow["stop_pct"],
            "tp_hit": plan.get("status") == "TP",
            "day": datetime.fromtimestamp(shadow["entry_time_ms"] / 1000, timezone.utc).date()}


def assign_groups(rows):
    """Tertile cut points from the score distribution only (never outcomes)."""
    scores = sorted(r["score"] for r in rows)
    n = len(scores)
    cuts = (scores[n // 3], scores[2 * n // 3]) if n >= 3 else (math.inf, math.inf)
    for r in rows:
        r["group"] = "low" if r["score"] < cuts[0] else "mid" if r["score"] < cuts[1] else "high"
    return list(cuts)


def _day_ci(by_day, stat, rounds=2000):
    days = list(by_day)
    rng = random.Random(0)
    vals = sorted(stat([x for d in (rng.choice(days) for _ in days) for x in by_day[d]])
                  for _ in range(rounds))
    return vals[int(.025 * rounds)], vals[int(.975 * rounds) - 1]


def _diff_stat(sample):
    hi = [r["R"] for r in sample if r["group"] == "high"]
    lo = [r["R"] for r in sample if r["group"] == "low"]
    return (st.mean(hi) - st.mean(lo)) if hi and lo else 0.0


def summarize(pairs):
    rows = [r for r in (record(s, x) for s, x in pairs) if r]
    days = {r["day"] for r in rows}
    weeks = {d - timedelta(days=d.weekday()) for d in days}
    cuts = assign_groups(rows)
    counts = {g: sum(1 for r in rows if r["group"] == g) for g in GROUPS}
    ready = (len(rows) >= GATE["events"] and len(days) >= GATE["days"]
             and len(weeks) >= GATE["weeks"] and min(counts.values()) >= GATE["per_group"])
    report = {"version": VERSION, "research_only": True, "complete_events": len(rows),
              "event_days": len(days), "calendar_weeks": len(weeks), "group_counts": counts,
              "gate": GATE, "ready": ready, "groups": None, "high_minus_low": None,
              "decision": "NOT_READY"}
    if not ready:
        return report
    report["score_cuts"] = cuts
    groups = {}
    for g in GROUPS:
        sel = [r for r in rows if r["group"] == g]
        by_day = {}
        for r in sel:
            by_day.setdefault(r["day"], []).append(r["R"])
        groups[g] = {"n": len(sel), "mean_R": st.mean(r["R"] for r in sel),
                     "tp_before_stop_pct": sum(r["tp_hit"] for r in sel) / len(sel) * 100,
                     "mean_R_day_ci95": list(_day_ci(by_day, st.mean))}
    by_day = {}
    for r in rows:
        by_day.setdefault(r["day"], []).append(r)
    low, high = _day_ci(by_day, _diff_stat)
    diff = groups["high"]["mean_R"] - groups["low"]["mean_R"]
    relative = low > 0
    absolute = relative and groups["high"]["mean_R"] > 0 and groups["high"]["mean_R_day_ci95"][0] > 0
    report.update(groups=groups, high_minus_low={"mean_R_diff": diff, "day_block_ci95": [low, high]},
                  decision=("SUPPORTED_ABSOLUTE" if absolute else "SUPPORTED_RELATIVE" if relative
                            else "NO_DIFFERENCE_SHOWN"))
    return report


def render_text(report):
    c = report["group_counts"]
    lines = [f"G1 güç puanı ({report['version']}) — ileri test, emir/öneri değil",
             f"Tamamlanan olay {report['complete_events']}/{report['gate']['events']} · "
             f"gün {report['event_days']}/{report['gate']['days']} · "
             f"hafta {report['calendar_weeks']}/{report['gate']['weeks']} · "
             f"grup alt/orta/üst {c['low']}/{c['mid']}/{c['high']} (her biri ≥{report['gate']['per_group']})"]
    if not report["ready"]:
        lines.append("HAZIR DEĞİL: kapı geçilmeden grup sonuçları gösterilmez (ön kayıt).")
        return "\n".join(lines)
    names = {"low": "alt", "mid": "orta", "high": "üst"}
    for g in GROUPS:
        row = report["groups"][g]
        lo, hi = row["mean_R_day_ci95"]
        lines.append(f"{names[g]:4s} n={row['n']} ort {row['mean_R']:+.3f}R [{lo:+.3f}, {hi:+.3f}] · "
                     f"+%2 stoptan önce %{row['tp_before_stop_pct']:.0f}")
    d = report["high_minus_low"]
    lines.append(f"üst − alt: {d['mean_R_diff']:+.3f}R [{d['day_block_ci95'][0]:+.3f}, "
                 f"{d['day_block_ci95'][1]:+.3f}] → {report['decision']}")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--state", type=Path,
                        default=Path(__file__).resolve().parents[1] / ".price_target_state.json")
    source.add_argument("--data-json", type=Path, help="Public dashboard data.json (last 400 events only)")
    parser.add_argument("--format", choices=("json", "text"), default="text")
    args = parser.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    path = args.data_json or args.state
    if not path.exists():
        report = summarize([])
        report["input_status"] = "input_missing"
    else:
        data = json.loads(path.read_bytes())
        if args.data_json:
            pts = [s.get("price_target") or {} for s in data.get("signals", [])
                   if s.get("strategy") == "G1"]
            pairs = [(p.get("g1_strength"), p.get("exit_shadow")) for p in pts]
        else:
            pairs = [(e.get("g1_strength"), e.get("exit_shadow"))
                     for e in (data.get("events") or {}).values() if e.get("strategy") == "G1"]
        report = summarize(pairs)
    report["prereg_sha256"] = hashlib.sha256(PREREG.read_bytes()).hexdigest()
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str)
          if args.format == "json" else render_text(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
