"""G1 ATR split on the historical archive (g1-atr-split-hist-v1).

Frozen by research/PREREG_G1_ATR_SPLIT_2026-11-03.md. Reads local archive files
only: no network, Telegram, bot import or orders. Missing bars are `unknown`,
never a win or a loss.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import random
import statistics as st
import sys

VERSION = "g1-atr-split-hist-v1"
HOUR = 3_600_000
CUTOFF_MS = int(datetime(2026, 8, 31, tzinfo=timezone.utc).timestamp() * 1000)
THRESHOLD = 6.0
PLANS = {"card": (2.0, 1.5), "tp3": (3.0, 1.5), "no_target": (None, 2.0)}
PERIODS = ("older_history", "previously_seen", "recent_control")
ROOT = Path(__file__).resolve().parent
DEFAULT_DIR = ROOT / "data" / "historical-universe-2026-10-05"
PREREG = ROOT / "PREREG_G1_ATR_SPLIT_2026-11-03.md"


def atr_pct(bars, i):
    """Mean of 14 true ranges over bars i-15..i-1, as % of bar i-1 close."""
    window = bars[i-15:i]
    if i < 15 or len(window) != 15 or any(b[0] - a[0] != HOUR for a, b in zip(window, window[1:])):
        return None
    trs = [max(b[2] - b[3], abs(b[2] - a[4]), abs(b[3] - a[4])) for a, b in zip(window, window[1:])]
    close = window[-1][4]
    return st.fmean(trs) / close * 100 if close > 0 else None


def path_gross(bars, i, target, stop_pct, order="conservative"):
    """Gross % for a LONG entered at bars[i] open, 4 hourly bars, fixed stop/target."""
    path = bars[i:i+4]
    if len(path) != 4 or any(b[0] - a[0] != HOUR for a, b in zip(path, path[1:])):
        return None
    entry = path[0][1]
    stop = entry * (1 - stop_pct / 100)
    goal = entry * (1 + target / 100) if target else None
    for _, o, h, l, _c in path:
        if o <= stop:
            return (o / entry - 1) * 100
        if goal and o >= goal:
            return target
        hit_stop, hit_goal = l <= stop, bool(goal) and h >= goal
        if hit_stop and (not hit_goal or order == "conservative"):
            return -stop_pct
        if hit_goal:
            return target
    return (path[-1][4] / entry - 1) * 100


def evaluate(events, load_bars, cost_bps=20, order="conservative"):
    """One record per eligible event; unknown ATR/path is counted, not scored."""
    records, unknown = [], 0
    by_symbol = defaultdict(list)
    for event in events:
        if event.get("decision_ms", CUTOFF_MS) < CUTOFF_MS and event.get("partition") in PERIODS:
            by_symbol[event["symbol"]].append(event)
    for symbol, rows in sorted(by_symbol.items()):
        bars = load_bars(symbol)
        for event in rows:
            i = event["entry_index"]
            if not 0 <= i < len(bars) or bars[i][0] != event["entry_time"]:
                unknown += 1
                continue
            atr = atr_pct(bars, i)
            if atr is None:
                unknown += 1
                continue
            result = {"period": event["partition"], "decision_ms": event["decision_ms"],
                      "symbol": symbol, "atr": atr, "high_atr": atr >= THRESHOLD}
            for name, (target, mult) in PLANS.items():
                gross = path_gross(bars, i, target, mult * atr, order)
                result[name] = None if gross is None else (gross - cost_bps / 100) / (mult * atr)
            if all(result[name] is None for name in PLANS):
                unknown += 1
                continue
            records.append(result)
    return records, unknown


def week_ci(records, plan, rounds=4000):
    by_week = defaultdict(list)
    for r in records:
        if r[plan] is not None:
            d = datetime.fromtimestamp(r["decision_ms"] / 1000, timezone.utc).isocalendar()
            by_week[(d[0], d[1])].append(r[plan])
    weeks = list(by_week)
    if not weeks:
        return None, None
    rng = random.Random(0)
    means = sorted(st.fmean([v for w in (rng.choice(weeks) for _ in weeks) for v in by_week[w]])
                   for _ in range(rounds))
    return means[int(.025 * rounds)], means[int(.975 * rounds) - 1]


def cell(values):
    values = [v for v in values if v is not None]
    if not values:
        return {"n": 0, "mean_R": None, "win_pct": None}
    return {"n": len(values), "mean_R": st.fmean(values),
            "win_pct": sum(1 for v in values if v > 0) / len(values) * 100}


def summarize(records, unknown=0):
    plans = {}
    for plan in PLANS:
        periods = {p: {g: cell(r[plan] for r in records if r["period"] == p and r["high_atr"] == (g == "high"))
                       for g in ("high", "low")} for p in PERIODS}
        high = [r for r in records if r["high_atr"]]
        low, high_ci = cell(r[plan] for r in records if not r["high_atr"]), week_ci(high, plan)
        quart = sorted(r["atr"] for r in records if r[plan] is not None)
        cuts = [quart[int(len(quart) * q)] for q in (.25, .5, .75)] if quart else []
        quartiles = [cell(r[plan] for r in records if r[plan] is not None
                          and (k == 0 or r["atr"] >= cuts[k-1]) and (k == 3 or r["atr"] < cuts[k]))
                     for k in range(4)] if cuts else []
        plans[plan] = {"by_period": periods, "high_pooled": {**cell(r[plan] for r in high),
                       "week_ci95": high_ci}, "low_pooled": low,
                       "atr_quartile_cuts": cuts, "atr_quartiles": quartiles}
    card = plans["card"]
    relative = all(card["by_period"][p]["high"]["n"] and card["by_period"][p]["low"]["n"]
                   and card["by_period"][p]["high"]["mean_R"] > card["by_period"][p]["low"]["mean_R"]
                   for p in PERIODS)
    low_ci = card["high_pooled"]["week_ci95"][0]
    absolute = (card["high_pooled"]["mean_R"] or 0) > 0 and low_ci is not None and low_ci > 0
    decision = "SUPPORTED" if relative and absolute else "PARTIAL" if relative else "NOT_SUPPORTED"
    return {"version": VERSION, "decision": decision, "relative_all_periods": relative,
            "absolute_high_atr": absolute, "events_scored": len(records), "events_unknown": unknown,
            "plans": plans}


def render(report, title):
    lines = [f"== {title} ==", f"karar: {report['decision']} · puanlanan olay {report['events_scored']} · unknown {report['events_unknown']}"]
    for plan, row in report["plans"].items():
        hp, lp = row["high_pooled"], row["low_pooled"]
        ci = row["high_pooled"]["week_ci95"]
        lines.append(f"[{plan}] ATR>=6: n={hp['n']} ortR={hp['mean_R']:+.3f} kazanma=%{hp['win_pct']:.0f} "
                     f"CI[{ci[0]:+.3f},{ci[1]:+.3f}] | ATR<6: n={lp['n']} ortR={lp['mean_R']:+.3f} kazanma=%{lp['win_pct']:.0f}")
        for p in PERIODS:
            h, l = row["by_period"][p]["high"], row["by_period"][p]["low"]
            fmt = lambda c: "—" if not c["n"] else f"n={c['n']} {c['mean_R']:+.3f}R %{c['win_pct']:.0f}"
            lines.append(f"    {p:16s} ATR>=6 {fmt(h)} | ATR<6 {fmt(l)}")
        lines.append("    ATR çeyrekleri " + " · ".join(
            f"{c['mean_R']:+.3f}R" for c in row["atr_quartiles"] if c["n"]) +
            f" (sınırlar %{', %'.join(f'{x:.2f}' for x in row['atr_quartile_cuts'])})")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dir", type=Path, default=DEFAULT_DIR)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    import pandas as pd
    raw = (args.dir / "g1_events.json").read_bytes()
    events = json.loads(raw)
    cache = {}

    def load_bars(symbol):
        if symbol not in cache:
            df = pd.read_parquet(args.dir / "1h" / f"{symbol}.parquet").sort_values("open_time")
            cache[symbol] = [(int(t), float(o), float(h), float(l), float(c)) for t, o, h, l, c in
                             df[["open_time", "open", "high", "low", "close"]].itertuples(index=False)]
        return cache[symbol]

    out = {"prereg_sha256": hashlib.sha256(PREREG.read_bytes()).hexdigest(),
           "events_sha256": hashlib.sha256(raw).hexdigest(), "runs": {}}
    for label, cost, order in (("birincil · muhafazakâr · 20bp", 20, "conservative"),
                               ("duyarlılık · muhafazakâr · 40bp", 40, "conservative"),
                               ("sınır · iyimser sıra · 20bp", 20, "optimistic")):
        records, unknown = evaluate(events, load_bars, cost, order)
        report = summarize(records, unknown)
        out["runs"][label] = report
        print(render(report, label), "\n")
    if args.output:
        args.output.write_text(json.dumps(out, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    print("prereg sha256", out["prereg_sha256"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
