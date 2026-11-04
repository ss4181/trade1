"""S1+S4 automatic-execution replay at account level (s1s4-account-replay-v1).

Replays every S1+S4 detection as if a bot had bought spot at the first full
minute after detection and sold after 24 hours, then compounds the results in
an account split into equal 1x slots. Prices come from public Binance spot
1m/1h klines (cached); no keys, Telegram, bot import or orders. Missing bars
are `unknown`, never a win or a loss.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import random
import statistics as st
import sys
import time
import urllib.parse
import urllib.request

VERSION = "s1s4-account-replay-v1"
MINUTE, HOUR = 60_000, 3_600_000
HORIZON_MIN = 24 * 60
STRATEGY = "S1+S4"
SPOT = "https://api.binance.com/api/v3/klines"
ROOT = Path(__file__).resolve().parent
DEFAULT_CACHE = ROOT / "data" / "s1s4-account-replay"
# Validated rule first; the others are descriptive comparisons only.
PLANS = {"time24": {}, "disaster15": {"disaster": 15.0},
         "card": {"target": 2.0, "atr_stop": 1.5}, "card4h": {"target": 2.0, "atr_stop": 1.5, "limit": 240}}


def ms(value):
    return int(datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp() * 1000)


def load_events(paths):
    """S1+S4 detections from signals.log/JSONL, dashboard data.json or all-execution events.jsonl.

    Deduplicated by (symbol, signal bar). Entry = first full minute after the
    detection record (delivery time is irrelevant to an automatic bot)."""
    events = {}
    for path in paths:
        text = Path(path).read_text(encoding="utf-8")
        try:
            data = json.loads(text)
            rows = data.get("signals", []) if isinstance(data, dict) else data
        except json.JSONDecodeError:
            rows = [json.loads(line) for line in text.splitlines() if line.strip()]
        for row in rows:
            if not isinstance(row, dict) or row.get("strategy") != STRATEGY:
                continue
            if row.get("market", "spot") != "spot" or row.get("performance_market", "spot") != "spot":
                continue
            if "anchor_ms" in row:  # all-execution archive: first applicable minute already fixed
                signal, entry = int(row["signal_ms"]), int(row["anchor_ms"])
            else:
                bar = row.get("t") or row.get("bar_time")
                if not bar:
                    continue
                signal = ms(bar)
                seen = row.get("notified_at") or row.get("detected_at")
                ref = ms(seen) if seen else signal + HOUR + 10_000
                entry = (ref // MINUTE + 1) * MINUTE
            key = (row["symbol"], signal)
            events.setdefault(key, {"symbol": row["symbol"], "signal_ms": signal, "entry_ms": entry,
                                    "universe": row.get("universe") or "UNKNOWN",
                                    "config_version": row.get("config_version") or "UNKNOWN"})
    return sorted(events.values(), key=lambda e: (e["entry_ms"], e["symbol"]))


class Klines:
    """Public spot klines with an on-disk cache; `get` is injectable for tests."""
    def __init__(self, cache_dir, get=None):
        self.cache = Path(cache_dir)
        self.get = get or self._http
        self.requests = 0

    def _http(self, params):
        url = f"{SPOT}?{urllib.parse.urlencode(params)}"
        for attempt in range(4):
            try:
                with urllib.request.urlopen(url, timeout=20) as response:
                    return json.loads(response.read())
            except Exception:
                if attempt == 3:
                    raise
                time.sleep(1 + attempt)

    def _cached(self, name, params):
        path = self.cache / name
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        rows = self.get(params)
        self.requests += 1
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(rows), encoding="utf-8")
        return rows

    def minutes(self, symbol, start):
        rows = []
        for offset, limit in ((0, 1000), (1000, HORIZON_MIN - 1000)):
            rows += self._cached(f"1m/{symbol}_{start + offset * MINUTE}.json",
                                 {"symbol": symbol, "interval": "1m",
                                  "startTime": start + offset * MINUTE, "limit": limit})
        return [(int(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[4])) for r in rows]

    def hours_before(self, symbol, end):
        rows = self._cached(f"1h/{symbol}_{end}.json",
                            {"symbol": symbol, "interval": "1h", "endTime": end - 1, "limit": 16})
        return [(float(r[2]), float(r[3]), float(r[4])) for r in rows if int(r[6]) < end]


def atr_pct(hours):
    if len(hours) < 15:
        return None
    window = hours[-15:]
    trs = [max(b[0] - b[1], abs(b[0] - a[2]), abs(b[1] - a[2])) for a, b in zip(window, window[1:])]
    return st.fmean(trs) / window[-1][2] * 100 if window[-1][2] > 0 else None


def outcome(bars, entry_ms, target=None, atr_stop=None, atr=None, disaster=None, limit=HORIZON_MIN):
    """Gross % and exit time for a LONG; same-bar stop/target ambiguity is stop-first."""
    path = [b for b in bars if entry_ms <= b[0] < entry_ms + limit * MINUTE]
    if (len(path) != limit or path[0][0] != entry_ms
            or any(b[0] - a[0] != MINUTE for a, b in zip(path, path[1:]))):
        return None
    if atr_stop and not atr:
        return None
    entry = path[0][1]
    stop_pct = atr_stop * atr if atr_stop else disaster
    stop = entry * (1 - stop_pct / 100) if stop_pct else None
    for t, o, h, l, _c in path:
        if stop and o <= stop:
            return (o / entry - 1) * 100, t + MINUTE
        if stop and l <= stop:
            return -stop_pct, t + MINUTE
        if target and h >= entry * (1 + target / 100):
            return target, t + MINUTE
    return (path[-1][4] / entry - 1) * 100, path[-1][0] + MINUTE


def account(trades, slots, cost_pct):
    """Equal 1x slots; a signal is skipped when every slot is busy. Returns n, return %, max drawdown %.

    trades = (entry_ms, symbol, exit_ms, gross). Same-minute signals are taken in
    symbol order, never by outcome, so a full account cannot pick its trades."""
    busy, taken = [], []
    for entry, _symbol, exit_ms, gross in sorted(trades, key=lambda t: (t[0], t[1])):
        busy = [x for x in busy if x > entry]
        if len(busy) >= slots:
            continue
        busy.append(exit_ms)
        taken.append((exit_ms, (gross - cost_pct) / slots))
    equity = peak = 100.0
    drawdown = 0.0
    for _, r in sorted(taken):
        equity *= 1 + r / 100
        peak = max(peak, equity)
        drawdown = min(drawdown, equity / peak - 1)
    return len(taken), equity - 100, drawdown * 100


def day_ci(rows, rounds=4000):
    by_day = {}
    for e, v in rows:
        by_day.setdefault(datetime.fromtimestamp(e["entry_ms"] / 1000, timezone.utc).date(), []).append(v)
    days = list(by_day)
    if len(days) < 2:
        return None, None
    rng = random.Random(0)
    means = sorted(st.fmean([v for d in (rng.choice(days) for _ in days) for v in by_day[d]]) for _ in range(rounds))
    return means[int(.025 * rounds)], means[int(.975 * rounds) - 1]


def evaluate(events, klines, cost_bps=20, slots=(1, 5, 10)):
    cost = cost_bps / 100
    scored, unknown = {name: [] for name in PLANS}, Counter()
    for e in events:
        bars = klines.minutes(e["symbol"], e["entry_ms"])
        atr = atr_pct(klines.hours_before(e["symbol"], e["entry_ms"]))
        for name, plan in PLANS.items():
            result = outcome(bars, e["entry_ms"], atr=atr, **plan)
            if result is None:
                unknown[name] += 1
            else:
                scored[name].append((e, result))
    report = {"version": VERSION, "events": len(events), "cost_bps": cost_bps,
              "event_days": len({datetime.fromtimestamp(e["entry_ms"] / 1000, timezone.utc).date() for e in events}),
              "unknown": dict(unknown), "plans": {}}
    for name, rows in scored.items():
        nets = [(e, g - cost) for e, (g, _) in rows]
        low, high = day_ci(nets)
        report["plans"][name] = {
            "n": len(nets), "win_pct": sum(1 for _, v in nets if v > 0) / len(nets) * 100 if nets else None,
            "mean_net_pct": st.fmean(v for _, v in nets) if nets else None,
            "median_net_pct": st.median(v for _, v in nets) if nets else None,
            "worst_net_pct": min(v for _, v in nets) if nets else None, "day_ci95": [low, high],
            "account": {str(k): dict(zip(("trades", "return_pct", "max_drawdown_pct"),
                                         account([(e["entry_ms"], e["symbol"], x, g) for e, (g, x) in rows], k, cost)))
                        for k in slots}}
    return report


def render(report, title):
    lines = [f"== {title} ==",
             f"olay {report['events']} · gün {report['event_days']} · maliyet {report['cost_bps']}bp · unknown {report['unknown'] or 0}"]
    for name, row in report["plans"].items():
        if not row["n"]:
            lines.append(f"  {name:10s} ölçülebilir olay yok")
            continue
        low, high = row["day_ci95"]
        ci = f"[%{low:+.2f}, %{high:+.2f}]" if low is not None else "[—]"
        acc = " · ".join(f"{k} slot %{a['return_pct']:+.1f}/düşüş %{a['max_drawdown_pct']:+.1f}"
                         for k, a in row["account"].items())
        lines.append(f"  {name:10s} n={row['n']} kazanma=%{row['win_pct']:.0f} ort=%{row['mean_net_pct']:+.2f} {ci} "
                     f"medyan=%{row['median_net_pct']:+.2f} en kötü=%{row['worst_net_pct']:+.1f} | {acc}")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--events", nargs="+", type=Path, required=True,
                        help="signals.log, data.json snapshots and/or all-execution events.jsonl")
    parser.add_argument("--since", help="ISO time; keep entries at or after it")
    parser.add_argument("--until", help="ISO time; keep entries before it")
    parser.add_argument("--cost-bps", type=float, default=20)
    parser.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--format", choices=("text", "json"), default="text")
    args = parser.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    events = load_events(args.events)
    if args.since:
        events = [e for e in events if e["entry_ms"] >= ms(args.since)]
    if args.until:
        events = [e for e in events if e["entry_ms"] < ms(args.until)]
    klines = Klines(args.cache)
    report = evaluate(events, klines, args.cost_bps)
    report.update(since=args.since, until=args.until, network_requests=klines.requests,
                  inputs_sha256={str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in args.events})
    title = f"S1+S4 otomatik yeniden oynatma {args.since or 'başlangıç'} → {args.until or 'son'}"
    print(render(report, title) if args.format == "text"
          else json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
