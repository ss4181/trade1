"""Read-only G1 exit-plan report (g1-exit-shadow-v1). No network, tuning, bot import or credentials."""
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
from g1_entry import EXIT_PLANS, EXIT_VERSION

PREREG = Path(__file__).with_name("PREREG_G1_EXIT_SHADOW_2026-11-02.md")
GATE = {"events": 30, "days": 20, "weeks": 4}
COSTS = (20, 40)


def _num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def _usable(shadow):
    return (isinstance(shadow, dict) and shadow.get("version") == EXIT_VERSION
            and shadow.get("status") == "complete" and shadow.get("complete") is True
            and _num(shadow.get("stop_pct")) and _num(shadow.get("entry_time_ms"))
            and all(_num((shadow.get("plans") or {}).get(k, {}).get("gross_pct")) for k in EXIT_PLANS))


def _ci(diffs_by_day, rounds=2000):
    days = list(diffs_by_day)
    rng = random.Random(0)
    means = []
    for _ in range(rounds):
        sample = [v for d in (rng.choice(days) for _ in days) for v in diffs_by_day[d]]
        means.append(st.mean(sample))
    means.sort()
    return means[int(.025*rounds)], means[int(.975*rounds)-1]


def summarize(shadows):
    shadows = [s for s in shadows if isinstance(s, dict) and s.get("version") == EXIT_VERSION]
    status = {}
    for s in shadows:
        key = s.get("status") if s.get("status") != "unavailable" else f"unavailable:{s.get('reason')}"
        if s.get("status") == "complete" and s.get("complete") is not True:
            key = "complete_with_gap"
        status[key] = status.get(key, 0) + 1
    done = [s for s in shadows if _usable(s)]
    day = lambda s: datetime.fromtimestamp(s["entry_time_ms"]/1000, timezone.utc).date()
    days = {day(s) for s in done}
    weeks = {d - timedelta(days=d.weekday()) for d in days}
    ready = len(done) >= GATE["events"] and len(days) >= GATE["days"] and len(weeks) >= GATE["weeks"]
    report = {"version": EXIT_VERSION, "research_only": True, "status_counts": status,
              "complete_events": len(done), "event_days": len(days), "calendar_weeks": len(weeks),
              "gate": GATE, "ready": ready, "plans": None, "paired_vs_tp2_net40": None}
    if not ready:
        return report
    plans = {}
    for key in EXIT_PLANS:
        gross = [s["plans"][key]["gross_pct"] for s in done]
        r = [g / s["stop_pct"] for g, s in zip(gross, done)]
        row = {"n": len(gross), "mean_R": st.mean(r), "worst_pct": min(gross),
               "status": {}}
        for s in done:
            label = s["plans"][key].get("status")
            row["status"][label] = row["status"].get(label, 0) + 1
        for bps in COSTS:
            net = [g - bps/100 for g in gross]
            row[f"net{bps}_mean_pct"] = st.mean(net)
            row[f"net{bps}_median_pct"] = st.median(net)
            row[f"net{bps}_win_pct"] = sum(1 for x in net if x > 0) / len(net) * 100
        plans[key] = row
    paired = {}
    for key in EXIT_PLANS:
        if key == "tp2":
            continue
        by_day = {}
        for s in done:
            by_day.setdefault(day(s), []).append(s["plans"][key]["gross_pct"] - s["plans"]["tp2"]["gross_pct"])
        diffs = [v for vals in by_day.values() for v in vals]
        low, high = _ci(by_day)
        paired[key] = {"mean_diff_pct": st.mean(diffs), "day_block_ci95": [low, high],
                       "verdict": ("better_than_tp2" if low > 0 else "worse_than_tp2" if high < 0
                                   else "no_difference_shown")}
    report.update(plans=plans, paired_vs_tp2_net40=paired)
    return report


def render_text(report):
    lines = [f"G1 çıkış gölgesi ({report['version']}) — araştırma, emir/öneri değil",
             f"Tamamlanan olay {report['complete_events']}/{report['gate']['events']} · "
             f"olay günü {report['event_days']}/{report['gate']['days']} · "
             f"hafta {report['calendar_weeks']}/{report['gate']['weeks']}",
             "Durumlar: " + (", ".join(f"{k}={v}" for k, v in sorted(report["status_counts"].items())) or "henüz olay yok")]
    if not report["ready"]:
        lines.append("HAZIR DEĞİL: kapı geçilmeden plan sıralaması gösterilmez (ön kayıt).")
        return "\n".join(lines)
    for key, row in report["plans"].items():
        lines.append(f"{key:10s} net40 ort %{row['net40_mean_pct']:+.2f} medyan %{row['net40_median_pct']:+.2f} "
                     f"kazanma %{row['net40_win_pct']:.0f} · ort {row['mean_R']:+.3f}R · en kötü %{row['worst_pct']:+.1f}")
    for key, row in report["paired_vs_tp2_net40"].items():
        low, high = row["day_block_ci95"]
        lines.append(f"{key} − tp2: %{row['mean_diff_pct']:+.2f} [%{low:+.2f}, %{high:+.2f}] → {row['verdict']}")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--state", type=Path,
                        default=Path(__file__).resolve().parents[1]/".price_target_state.json")
    source.add_argument("--data-json", type=Path, help="Public dashboard data.json (last 400 events only)")
    parser.add_argument("--format", choices=("json", "text"), default="text")
    args = parser.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    try:
        path = args.data_json or args.state
        if not path.exists():
            report = summarize([])
            report["input_status"] = "input_missing"
        else:
            raw = path.read_bytes()
            data = json.loads(raw)
            if args.data_json:
                shadows = [(s.get("price_target") or {}).get("exit_shadow")
                           for s in data.get("signals", []) if isinstance(s, dict) and s.get("strategy") == "G1"]
            else:
                shadows = [e.get("exit_shadow") for e in data["events"].values()
                           if isinstance(e, dict) and e.get("strategy") == "G1"]
            report = summarize(shadows)
            report["input_sha256"] = hashlib.sha256(raw).hexdigest()
        report["prereg_sha256"] = hashlib.sha256(PREREG.read_bytes()).hexdigest()
        print(render_text(report) if args.format == "text"
              else json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False, default=str))
        return 0
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        # Never echo records, local paths or secrets.
        print("Rapor okunamadı: dosya biçimini kontrol edin.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
