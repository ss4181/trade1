"""Explore the local forward OI archive without fitting a live strategy.

The output is diagnostic only.  It decomposes a fixed gainer/volume/OI/short-
crowd hypothesis so we can see which condition adds or removes edge.  Entry is
the next hourly archive snapshot and exit is four hours later; no current-row
or forward value is used as a feature.  Parameters must not be promoted from
this discovery output without a separately declared OOS start.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import statistics
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path


COST_BPS = 12.0
HORIZON_HOURS = 4
COOLDOWN_HOURS = 24
BOOTSTRAP_SAMPLES = 2000


def number(value) -> float | None:
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError, OverflowError):
        return None


def hour_key(value) -> int | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return int(parsed.astimezone(timezone.utc).timestamp() // 3600)
    except (TypeError, ValueError, OverflowError):
        return None


def load_rows(root: Path) -> tuple[dict[str, dict[int, dict]], dict]:
    """Keep the latest snapshot for each symbol/hour; tolerate legacy rows."""
    panel: dict[str, dict[int, dict]] = defaultdict(dict)
    stats = {"lines": 0, "accepted": 0, "malformed": 0, "duplicates": 0}
    for path in sorted(root.glob("market_archive_*.jsonl")):
        with path.open("r", encoding="utf-8") as stream:
            for line in stream:
                stats["lines"] += 1
                try:
                    row = json.loads(line)
                except ValueError:
                    stats["malformed"] += 1
                    continue
                if not isinstance(row, dict):
                    stats["malformed"] += 1
                    continue
                symbol = str(row.get("sym") or "").upper()
                hour = hour_key(row.get("t"))
                px, oi = number(row.get("perp_px")), number(row.get("oi"))
                if not symbol or hour is None or not px or px <= 0 \
                        or oi is None or oi <= 0:
                    continue
                normalized = {
                    "symbol": symbol, "hour": hour, "price": px, "oi": oi,
                    "ls": number(row.get("global_ls_ratio")),
                    "taker_ratio": number(row.get("taker_buy_sell_ratio")),
                    "taker_buy": number(row.get("taker_buy_vol")),
                    "taker_sell": number(row.get("taker_sell_vol")),
                    "funding": number(row.get("funding_rate_snapshot")),
                    "basis": number(row.get("basis")),
                    "raw_time": str(row.get("t")),
                }
                old = panel[symbol].get(hour)
                if old is not None:
                    stats["duplicates"] += 1
                    if normalized["raw_time"] <= old["raw_time"]:
                        continue
                panel[symbol][hour] = normalized
                stats["accepted"] += 1
    return dict(panel), stats


def build_features(panel: dict[str, dict[int, dict]]) -> list[dict]:
    rows = []
    for symbol, by_hour in panel.items():
        for hour, current in sorted(by_hour.items()):
            lag1, lag6, lag24 = (by_hour.get(hour - offset)
                                 for offset in (1, 6, 24))
            entry = by_hour.get(hour + 1)
            exit_row = by_hour.get(hour + 1 + HORIZON_HOURS)
            if not all((lag1, lag6, lag24)):
                continue
            prior_flow = []
            for offset in range(1, 25):
                old = by_hour.get(hour - offset)
                if old is None or old["taker_buy"] is None \
                        or old["taker_sell"] is None:
                    prior_flow = []
                    break
                prior_flow.append(old["taker_buy"] + old["taker_sell"])
            flow = (current["taker_buy"] + current["taker_sell"]
                    if current["taker_buy"] is not None
                    and current["taker_sell"] is not None else None)
            flow_median = statistics.median(prior_flow) if prior_flow else None
            volume_ratio = (flow / flow_median if flow is not None
                            and flow_median and flow_median > 0 else None)
            ret24 = current["price"] / lag24["price"] - 1
            oi1 = current["oi"] / lag1["oi"] - 1
            oi6 = current["oi"] / lag6["oi"] - 1
            funding_delta6 = (current["funding"] - lag6["funding"]
                              if current["funding"] is not None
                              and lag6["funding"] is not None else None)
            gross = (exit_row["price"] / entry["price"] - 1
                     if entry is not None and exit_row is not None else None)
            rows.append({
                **current, "return_24h": ret24, "oi_change_1h": oi1,
                "oi_change_6h": oi6, "volume_ratio": volume_ratio,
                "funding_delta_6h": funding_delta6,
                "entry_price": entry["price"] if entry else None,
                "exit_price": exit_row["price"] if exit_row else None,
                "gross_return": gross,
                "net_return": (gross - COST_BPS / 10_000
                               if gross is not None else None),
                "entry_hour": hour + 1, "exit_hour": hour + 1 + HORIZON_HOURS,
            })

    by_hour: dict[int, list[dict]] = defaultdict(list)
    for row in rows:
        by_hour[row["hour"]].append(row)
    for hour_rows in by_hour.values():
        ordered = sorted(hour_rows,
                         key=lambda row: (-row["return_24h"], row["symbol"]))
        for rank, row in enumerate(ordered, 1):
            row["rank_24h"] = rank
            row["cross_section_size"] = len(ordered)
    return rows


def conditions(row: dict) -> dict[str, bool]:
    base = row["rank_24h"] <= 10 and row["return_24h"] >= .05
    vol2 = row["volume_ratio"] is not None and row["volume_ratio"] >= 2
    oi_up = row["oi_change_1h"] > 0
    oi2 = row["oi_change_1h"] >= .02
    short = row["ls"] is not None and row["ls"] < 1
    funding_up = (row["funding_delta_6h"] is not None
                  and row["funding_delta_6h"] > 0)
    taker_buy = row["taker_ratio"] is not None and row["taker_ratio"] > 1
    return {
        "P0_top10_gainer5": base,
        "P1_plus_volume2x": base and vol2,
        "P2_plus_any_oi_up": base and vol2 and oi_up,
        "P3_plus_oi_2pct": base and vol2 and oi2,
        "P4_plus_short_majority": base and vol2 and oi2 and short,
        "P5_plus_funding_rise": base and vol2 and oi2 and short and funding_up,
        "Q1_squeeze_proxy_oi_down": (
            base and short and row["oi_change_1h"] <= -.02 and taker_buy),
    }


def independent_events(rows: list[dict], rule: str) -> list[dict]:
    selected = []
    last_by_symbol: dict[str, int] = {}
    for row in sorted(rows, key=lambda item: (item["hour"], item["symbol"])):
        if not conditions(row)[rule]:
            continue
        last = last_by_symbol.get(row["symbol"])
        if last is not None and row["hour"] - last < COOLDOWN_HOURS:
            continue
        selected.append(row)
        last_by_symbol[row["symbol"]] = row["hour"]
    return selected


def percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * q
    lo, hi = math.floor(position), math.ceil(position)
    if lo == hi:
        return ordered[lo]
    return ordered[lo] * (hi - position) + ordered[hi] * (position - lo)


def bootstrap_nonpositive(events: list[dict]) -> float | None:
    by_day: dict[str, list[float]] = defaultdict(list)
    for row in events:
        day = datetime.fromtimestamp(
            row["entry_hour"] * 3600, tz=timezone.utc).date().isoformat()
        by_day[day].append(row["net_return"])
    daily = [statistics.mean(values) for values in by_day.values()]
    if len(daily) < 2:
        return None
    rng = random.Random(20260831)
    nonpositive = 0
    for _ in range(BOOTSTRAP_SAMPLES):
        sample = [rng.choice(daily) for _ in daily]
        nonpositive += statistics.mean(sample) <= 0
    return nonpositive / BOOTSTRAP_SAMPLES


def summarize(events: list[dict]) -> dict:
    matured = [row for row in events if row["net_return"] is not None]
    values = [row["net_return"] * 100 for row in matured]
    days = {datetime.fromtimestamp(row["entry_hour"] * 3600,
                                   tz=timezone.utc).date().isoformat()
            for row in matured}
    return {
        "n_total": len(events), "n": len(values),
        "n_pending": len(events) - len(matured),
        "independent_days": len(days),
        "mean_net_pct": round(statistics.mean(values), 4) if values else None,
        "median_net_pct": round(statistics.median(values), 4) if values else None,
        "win_rate_pct": round(sum(value > 0 for value in values) / len(values)
                              * 100, 1) if values else None,
        "q10_net_pct": (round(percentile(values, .10), 4) if values else None),
        "q90_net_pct": (round(percentile(values, .90), 4) if values else None),
        "bootstrap_p_mean_nonpositive": (
            round(bootstrap_nonpositive(matured), 4) if len(days) >= 2 else None),
        "sample_warning": "small_sample" if len(values) < 30 else "",
    }


def analyze(root: Path) -> dict:
    panel, ingest = load_rows(root)
    features = build_features(panel)
    rule_names = list(conditions(features[0]).keys()) if features else [
        "P0_top10_gainer5", "P1_plus_volume2x", "P2_plus_any_oi_up",
        "P3_plus_oi_2pct", "P4_plus_short_majority",
        "P5_plus_funding_rise", "Q1_squeeze_proxy_oi_down",
    ]
    results = {rule: summarize(independent_events(features, rule))
               for rule in rule_names}
    hours = sorted({row["hour"] for row in features})
    return {
        "schema_version": "forward-oi-discovery-v1",
        "mode": "EXPLORATORY_NOT_OOS",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "data": {
            **ingest, "symbols": len(panel), "feature_rows": len(features),
            "first_feature_utc": (datetime.fromtimestamp(
                hours[0] * 3600, tz=timezone.utc).isoformat() if hours else None),
            "last_feature_utc": (datetime.fromtimestamp(
                hours[-1] * 3600, tz=timezone.utc).isoformat() if hours else None),
        },
        "method": {
            "ranking": "same-hour cross-sectional 24h perp return",
            "volume": "current 5m taker buy+sell / previous 24 hourly median",
            "entry": "next available exact-hour perp snapshot",
            "exit": f"entry+{HORIZON_HOURS}h exact-hour perp snapshot",
            "round_trip_cost_bps": COST_BPS,
            "cooldown_hours_per_symbol": COOLDOWN_HOURS,
            "bootstrap_unit": "UTC event day",
        },
        "rules": results,
        "limitations": [
            "Only about one month of discovery data; no reliability claim.",
            "Snapshot prices are not executable bid/ask fills.",
            "Funding cash flows and slippage are not modeled.",
            "Liquidation filter is unavailable until the repaired stream collects events.",
            "Do not choose a winner from this table and call it OOS.",
        ],
    }


def print_report(report: dict) -> None:
    data = report["data"]
    print("FORWARD OI KESIF ANALIZI — OOS DEGIL / ESİK SECME RAPORU DEGIL")
    print(f"veri: {data['accepted']} kabul, {data['symbols']} sembol, "
          f"{data['feature_rows']} olgun ozellik satiri")
    print(f"donem: {data['first_feature_utc']} -> {data['last_feature_utc']}")
    print("giris: sonraki saat snapshot; cikis: +4s; maliyet: 12bp; cooldown: 24s")
    print("rule                         N pen gun  ort%    med%    WR%    q10%    q90%    p<=0")
    for rule, stats in report["rules"].items():
        def shown(key, width=7):
            value = stats[key]
            return f"{'—' if value is None else value:>{width}}"
        print(f"{rule:<28} {stats['n']:>3} {stats['n_pending']:>3} "
              f"{stats['independent_days']:>3} "
              f"{shown('mean_net_pct')} {shown('median_net_pct')} "
              f"{shown('win_rate_pct', 6)} {shown('q10_net_pct')} "
              f"{shown('q90_net_pct')} {shown('bootstrap_p_mean_nonpositive', 6)}"
              f" {'KÜÇÜK' if stats['sample_warning'] else ''}")
    print("KARAR: yalniz kesif/bottleneck analizi. 90 gun freeze kapisindan once "
          "strateji, guven orani veya canli emir uretilmez.")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dir", default=".", help="archive directory")
    parser.add_argument("--json", action="store_true", help="print JSON")
    args = parser.parse_args()
    report = analyze(Path(args.dir))
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print_report(report)


if __name__ == "__main__":
    main()
