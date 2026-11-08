"""G1 target filter (g1-target-filter-v1): does an entry-known feature pick the target?

Frozen by research/PREREG_G1_TARGET_FILTER_2026-11-08.md. Local archive plus public
Binance USD-M klines for the live cohort; no keys, Telegram, bot import or orders.
Missing ATR, feature or path is `unknown`, never a win or a loss.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import random
import re
import statistics as st
import sys
import time
import urllib.parse
import urllib.request

VERSION = "g1-target-filter-v1"
MINUTE, HOUR = 60_000, 3_600_000
ROOT = Path(__file__).resolve().parent
DEFAULT_DIR = ROOT / "data" / "historical-universe-2026-10-05"
DEFAULT_CACHE = ROOT / "data" / "g1-target-filter" / "klines"
PREREG = ROOT / "PREREG_G1_TARGET_FILTER_2026-11-08.md"
FUTURES = "https://fapi.binance.com/fapi/v1/klines"


def utc_ms(*args):
    return int(datetime(*args, tzinfo=timezone.utc).timestamp() * 1000)


DISCOVERY_END = utc_ms(2025, 7, 1)
HOLDOUT_END = utc_ms(2026, 8, 31)
TARGETS = (2.0, 3.0, 5.0, 10.0, None)
CARD = 2.0
FEATURES = ("return_24h", "rank", "volume_ratio", "last_hour_return", "dist_24h_high")
STOP_ATR = 1.5
MIN_BUCKET_EVENTS, MIN_BUCKET_DAYS = 200, 60


def contiguous(bars, step):
    return all(b[0] - a[0] == step for a, b in zip(bars, bars[1:]))


def path_result(path, target, stop_pct, order="conservative"):
    """Gross % for a LONG entered at path[0] open; same-bar ambiguity follows `order`."""
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


def bar_features(bars):
    """ATR, last-hour return and distance from the 24h high from closed hourly bars."""
    window = bars[-24:]
    if len(window) != 24 or not contiguous(window, HOUR):
        return None
    tail = bars[-15:]
    trs = [max(b[2] - b[3], abs(b[2] - a[4]), abs(b[3] - a[4])) for a, b in zip(tail, tail[1:])]
    close = window[-1][4]
    if close <= 0 or window[-1][1] <= 0:
        return None
    return {"atr": st.fmean(trs) / close * 100,
            "last_hour_return": (close / window[-1][1] - 1) * 100,
            "dist_24h_high": (close / max(b[2] for b in window) - 1) * 100}


def score(event, path, atr, costs=(20, 40), order="conservative"):
    stop = STOP_ATR * atr
    gross = {t: path_result(path, t, stop, order) for t in TARGETS}
    return {f"R{bps}": {t: (g - bps / 100) / stop for t, g in gross.items()} for bps in costs}


def load_archive(directory, order="conservative"):
    """Scored archive records plus the unknown count; uses the frozen event file only."""
    import pandas as pd
    raw = (directory / "g1_events.json").read_bytes()
    events = [e for e in json.loads(raw) if e["decision_ms"] < HOLDOUT_END]
    by_symbol = {}
    for e in events:
        by_symbol.setdefault(e["symbol"], []).append(e)
    records, unknown = [], 0
    for symbol, rows in sorted(by_symbol.items()):
        df = pd.read_parquet(directory / "1h" / f"{symbol}.parquet").sort_values("open_time")
        bars = [(int(t), float(o), float(h), float(l), float(c)) for t, o, h, l, c in
                df[["open_time", "open", "high", "low", "close"]].itertuples(index=False)]
        for e in rows:
            i = e["entry_index"]
            path = bars[i:i+4]
            feats = bar_features(bars[max(0, i-24):i]) if 0 <= i <= len(bars) else None
            if (feats is None or len(path) != 4 or path[0][0] != e["entry_time"]
                    or not contiguous(path, HOUR) or feats["atr"] <= 0):
                unknown += 1
                continue
            record = {"symbol": symbol, "decision_ms": e["decision_ms"], "return_24h": e["return_24h"] * 100,
                      "rank": e["rank"], "volume_ratio": e["volume_ratio"], **feats}
            record.update(score(e, path, feats["atr"], order=order))
            records.append(record)
    return records, unknown, hashlib.sha256(raw).hexdigest()


def tercile_cuts(values):
    data = sorted(values)
    return data[int(len(data) * 1 / 3)], data[int(len(data) * 2 / 3)]


def bucket(value, cuts):
    return 0 if value < cuts[0] else 1 if value < cuts[1] else 2


def day(record):
    return record["decision_ms"] // 86_400_000


def mean_r(rows, target, cost="R20"):
    return st.fmean(r[cost][target] for r in rows)


def select_policy(train, cost="R20"):
    """Mechanical discovery choice from the pre-registration; no outcome from later periods."""
    fixed = {t: mean_r(train, t, cost) for t in TARGETS}
    best_fixed = max(TARGETS, key=lambda t: (fixed[t], t is not None, t or 0))
    candidates = {}
    for feature in FEATURES:
        cuts = tercile_cuts(r[feature] for r in train)
        groups = {k: [r for r in train if bucket(r[feature], cuts) == k] for k in range(3)}
        if any(len(g) < MIN_BUCKET_EVENTS or len({day(r) for r in g}) < MIN_BUCKET_DAYS
               for g in groups.values()):
            candidates[feature] = {"eligible": False}
            continue
        mapping, stats = {}, {}
        for k, group in groups.items():
            means = {t: mean_r(group, t, cost) for t in TARGETS}
            mapping[k] = max(TARGETS, key=lambda t: (means[t], t is not None, t or 0))
            stats[k] = {"n": len(group), "means": {str(t): means[t] for t in TARGETS}}
        value = st.fmean(r[cost][mapping[bucket(r[feature], cuts)]] for r in train)
        candidates[feature] = {"eligible": True, "cuts": list(cuts), "mapping": mapping,
                               "value": value, "buckets": stats}
    eligible = [f for f in FEATURES if candidates[f]["eligible"]]
    chosen = max(eligible, key=lambda f: (candidates[f]["value"], -FEATURES.index(f))) if eligible else None
    return {"fixed": {str(t): fixed[t] for t in TARGETS}, "best_fixed": best_fixed,
            "feature": chosen, "candidates": candidates}


def apply_policy(records, policy, cost="R20", skip=False):
    """Per-event R of the frozen policy; a skipped bucket earns 0."""
    choice = policy["candidates"][policy["feature"]]
    out = []
    for r in records:
        k = bucket(r[policy["feature"]], choice["cuts"])
        target = choice["mapping"][k]
        if skip and choice["buckets"][k]["means"][str(target)] <= 0:
            out.append(0.0)
        else:
            out.append(r[cost][target])
    return out


def week_key(record):
    iso = datetime.fromtimestamp(record["decision_ms"] / 1000, timezone.utc).isocalendar()
    return iso[0], iso[1]


def block_ci(records, values, rounds=4000):
    by_week = {}
    for r, v in zip(records, values):
        by_week.setdefault(week_key(r), []).append(v)
    weeks = list(by_week)
    if len(weeks) < 2:
        return None, None
    rng = random.Random(0)
    means = sorted(st.fmean([v for w in (rng.choice(weeks) for _ in weeks) for v in by_week[w]])
                   for _ in range(rounds))
    return means[int(.025 * rounds)], means[int(.975 * rounds) - 1]


def evaluate(records, policy, cost="R20"):
    adaptive = apply_policy(records, policy, cost)
    skipped = apply_policy(records, policy, cost, skip=True)
    card = [r[cost][CARD] for r in records]
    best = [r[cost][policy["best_fixed"]] for r in records]
    vs_card = [a - b for a, b in zip(adaptive, card)]
    vs_best = [a - b for a, b in zip(adaptive, best)]
    return {"n": len(records), "adaptive_mean_R": st.fmean(adaptive), "adaptive_ci": block_ci(records, adaptive),
            "skip_mean_R": st.fmean(skipped), "card_mean_R": st.fmean(card), "best_fixed_mean_R": st.fmean(best),
            "vs_card": st.fmean(vs_card), "vs_card_ci": block_ci(records, vs_card),
            "vs_best": st.fmean(vs_best), "vs_best_ci": block_ci(records, vs_best)}


def decide(holdout, live):
    passed = (holdout["vs_card_ci"][0] is not None and holdout["vs_card_ci"][0] > 0
              and holdout["vs_best_ci"][0] is not None and holdout["vs_best_ci"][0] > 0)
    if not passed:
        return "NOT_SUPPORTED"
    return "SUPPORTED" if live and live["vs_card"] > 0 and live["vs_best"] > 0 else "PARTIAL"


class Klines:
    """Public USD-M klines with an on-disk cache; `get` is injectable for tests."""
    def __init__(self, cache, get=None):
        self.cache, self.get, self.requests = Path(cache), get or self._http, 0

    def _http(self, params):
        url = f"{FUTURES}?{urllib.parse.urlencode(params)}"
        for attempt in range(4):
            try:
                with urllib.request.urlopen(url, timeout=20) as response:
                    return json.loads(response.read())
            except Exception:
                if attempt == 3:
                    raise
                time.sleep(1 + attempt)

    def fetch(self, name, params):
        path = self.cache / name
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        rows = self.get(params)
        self.requests += 1
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(rows), encoding="utf-8")
        return rows

    def bars(self, symbol, interval, name, **params):
        rows = self.fetch(f"{interval}/{name}.json", {"symbol": symbol, "interval": interval, **params})
        return [(int(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[4])) for r in rows]


def number(text):
    found = re.search(r"[-+]?\d+(?:\.\d+)?", str(text or "").replace(",", "."))
    return float(found.group()) if found else None


def iso_ms(value):
    return int(datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp() * 1000)


def load_live_events(paths):
    """G1 events from dashboard data.json snapshots; a later snapshot wins for each event."""
    events = {}
    for path in paths:
        for s in json.loads(Path(path).read_text(encoding="utf-8")).get("signals", []):
            if s.get("strategy") != "G1":
                continue
            detail = {k: v for k, v in (s.get("detail") or [])}
            seen = s.get("delivered_at") or s.get("notified_at")
            if not seen:
                continue
            events[(s["symbol"], s["t"])] = {
                "symbol": s["symbol"], "decision_ms": iso_ms(s["t"]) + HOUR,
                "entry_ms": (iso_ms(seen) // MINUTE + 1) * MINUTE,
                "rank": number(detail.get("24s yükselen sırası")),
                "return_24h": number(detail.get("Kapanmış mum 24s getirisi")),
                "volume_ratio": number(detail.get("1s hacim / önceki 24s medyan"))}
    return [e for _, e in sorted(events.items(), key=lambda kv: kv[1]["decision_ms"])
            if e["decision_ms"] >= HOLDOUT_END]


def load_live(paths, klines):
    records, unknown = [], 0
    for e in load_live_events(paths):
        name = f"{e['symbol']}_{e['entry_ms']}"
        minutes = klines.bars(e["symbol"], "1m", name, startTime=e["entry_ms"], limit=240)
        hours = klines.bars(e["symbol"], "1h", f"{e['symbol']}_{e['decision_ms']}",
                            endTime=e["decision_ms"] - 1, limit=24)
        feats = bar_features(hours)
        if (feats is None or feats["atr"] <= 0 or len(minutes) != 240 or minutes[0][0] != e["entry_ms"]
                or not contiguous(minutes, MINUTE) or None in (e["rank"], e["return_24h"], e["volume_ratio"])):
            unknown += 1
            continue
        record = {**e, **feats}
        record.update(score(e, minutes, feats["atr"]))
        records.append(record)
    return records, unknown


def render(out):
    lines = [f"prereg sha256: {out['prereg_sha256']}", f"dönemler: {out['counts']}"]
    p = out["policy"]
    lines.append(f"keşif sabit hedefler (ort R): {p['fixed']} · en iyi sabit: {p['best_fixed']}")
    for f in FEATURES:
        c = p["candidates"][f]
        if not c["eligible"]:
            lines.append(f"  {f}: uygun değil")
            continue
        info = " | ".join(f"kova{k}→{c['mapping'][k]} n={c['buckets'][k]['n']}" for k in range(3))
        lines.append(f"  {f}: sınırlar {c['cuts'][0]:.3g}/{c['cuts'][1]:.3g} · politika {c['value']:+.4f}R · {info}")
    lines.append(f"seçilen özellik: {p['feature']}")
    for label, row in out["results"].items():
        if row is None:
            lines.append(f"[{label}] olay yok")
            continue
        fmt = lambda ci: "[—]" if ci[0] is None else f"[{ci[0]:+.3f}, {ci[1]:+.3f}]"
        lines.append(f"[{label}] n={row['n']} adaptive {row['adaptive_mean_R']:+.3f}R {fmt(row['adaptive_ci'])} · "
                     f"skip {row['skip_mean_R']:+.3f}R · kart {row['card_mean_R']:+.3f}R · en iyi sabit {row['best_fixed_mean_R']:+.3f}R\n"
                     f"    adaptive−kart {row['vs_card']:+.3f}R {fmt(row['vs_card_ci'])} · adaptive−en iyi sabit {row['vs_best']:+.3f}R {fmt(row['vs_best_ci'])}")
    lines.append(f"KARAR: {out['decision']}")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dir", type=Path, default=DEFAULT_DIR)
    parser.add_argument("--live", nargs="*", type=Path, default=[], help="Dashboard data.json snapshots")
    parser.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    records, unknown, events_sha = load_archive(args.dir)
    train = [r for r in records if r["decision_ms"] < DISCOVERY_END]
    holdout = [r for r in records if r["decision_ms"] >= DISCOVERY_END]
    policy = select_policy(train)
    klines = Klines(args.cache)
    live, live_unknown = load_live(args.live, klines) if args.live else ([], 0)
    optimistic, _, _ = load_archive(args.dir, order="optimistic")
    opt_holdout = [r for r in optimistic if r["decision_ms"] >= DISCOVERY_END]
    results = {"keşif (seçim verisi)": evaluate(train, policy),
               "ayrılmış · muhafazakâr · 20bp": evaluate(holdout, policy),
               "ayrılmış · muhafazakâr · 40bp": evaluate(holdout, policy, "R40"),
               "ayrılmış · iyimser sıra · 20bp": evaluate(opt_holdout, policy),
               "canlı · 1dk · 20bp": evaluate(live, policy) if live else None}
    out = {"version": VERSION, "prereg_sha256": hashlib.sha256(PREREG.read_bytes()).hexdigest(),
           "events_sha256": events_sha, "counts": {"keşif": len(train), "ayrılmış": len(holdout), "canlı": len(live),
                                                  "unknown_arşiv": unknown, "unknown_canlı": live_unknown},
           "policy": policy, "results": results,
           "decision": decide(results["ayrılmış · muhafazakâr · 20bp"], results["canlı · 1dk · 20bp"])}
    print(render(out))
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(out, ensure_ascii=False, indent=2, allow_nan=False, default=str), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
