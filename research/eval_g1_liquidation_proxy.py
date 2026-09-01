"""G1 + gerçekleşmiş USD-M likidasyon yoğunluğu/fiyat-kümesi keşif testi.

Bu araç canlı stratejiyi değiştirmez. Binance ``!forceOrder@arr`` arşivi bir
gelecek liquidation heatmap'i değildir; yalnız gerçekleşmiş ve 1000 ms içinde
sembol başına en büyük force-order snapshot'larını içerir. Ayrıntılı ön kayıt:
``research/PREREG_G1_LIQUIDATION_PROXY.md``.
"""

from __future__ import annotations

import argparse
import bisect
import json
import math
import random
import statistics
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:  # package import in tests; direct tablet script execution
    from research.eval_forward_oi_barriers import (
        VisionKlineStore, event_days, load_jobs, simulate_long,
        window_for_event,
    )
except ModuleNotFoundError:  # pragma: no cover - tablet CLI path
    from eval_forward_oi_barriers import (  # type: ignore
        VisionKlineStore, event_days, load_jobs, simulate_long,
        window_for_event,
    )


COST_BPS = 12.0
HORIZON_HOURS = 4
ZONE_LOOKBACK_HOURS = 24
BURST_HISTORY_DAYS = 30
MIN_HISTORY_HOURS = 576             # 30 günün %80'i
MIN_ZONE_COVERAGE_PCT = 80.0
ZONE_BIN_PCT = 0.25
ZONE_MIN_DISTANCE_PCT = 0.25
ZONE_MAX_DISTANCE_PCT = 3.0
UP_DOWN_RATIO_MIN = 1.5
BURST_PERCENTILE_MIN = 95.0
BOOTSTRAP_SAMPLES = 2000
RULES = (
    "BASE_G1", "G1_LQ1_SHORT_BURST", "G1_LQ2_UP_ZONE",
    "G1_LQ1_AND_LQ2",
)


def number(value) -> float | None:
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError, OverflowError):
        return None


def time_ms(value) -> int | None:
    if value in (None, ""):
        return None
    numeric = number(value)
    if numeric is not None and not isinstance(value, str):
        if numeric >= 100_000_000_000_000:
            numeric /= 1000
        return int(numeric)
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return int(parsed.astimezone(timezone.utc).timestamp() * 1000)
    except (TypeError, ValueError, OverflowError):
        return None


def _jsonl(root: Path, pattern: str):
    for path in sorted(root.glob(pattern)):
        try:
            stream = path.open("r", encoding="utf-8")
        except OSError:
            continue
        with stream:
            for line_number, line in enumerate(stream, 1):
                try:
                    row = json.loads(line)
                except ValueError:
                    yield None, path.name, line_number
                    continue
                yield row if isinstance(row, dict) else None, path.name, line_number


def load_g1_events(root: Path) -> tuple[list[dict], dict]:
    """Load only actual edge-triggered G1 events; never infer extra signals."""
    events: dict[tuple[str, int], dict] = {}
    stats = {"lines": 0, "accepted": 0, "malformed": 0, "duplicates": 0}
    for row, _name, _line in _jsonl(root, "shadow_events_*.jsonl"):
        stats["lines"] += 1
        if row is None:
            stats["malformed"] += 1
            continue
        if row.get("kind") != "G1_EVENT" and row.get("strategy") != "G1":
            continue
        symbol = str(row.get("performance_symbol") or row.get("symbol") or "").upper()
        bar_open = time_ms(row.get("bar_time"))
        if not symbol or bar_open is None:
            stats["malformed"] += 1
            continue
        hour = bar_open // 3_600_000
        key = (symbol, hour)
        if key in events:
            stats["duplicates"] += 1
            continue
        condition_price = number(row.get("condition_price")) or number(row.get("price"))
        if condition_price is None or condition_price <= 0:
            stats["malformed"] += 1
            continue
        events[key] = {
            "symbol": symbol, "contract": symbol, "hour": hour,
            "entry_hour": hour + 1, "entry_time_ms": (hour + 1) * 3_600_000,
            "bar_time": row.get("bar_time"),
            "condition_price": condition_price,
            "notification_price": number(row.get("price")),
            "config_version": str(row.get("config_version") or "legacy"),
        }
        stats["accepted"] += 1
    return sorted(events.values(), key=lambda row: (row["entry_time_ms"],
                                                     row["symbol"])), stats


def load_liquidation_archive(root: Path) -> tuple[dict, dict]:
    """Normalize force orders and global heartbeat coverage without zero fill."""
    by_symbol: dict[str, list[dict]] = defaultdict(list)
    heartbeat_bins: set[int] = set()
    seen_ids: set[str] = set()
    stats = {"lines": 0, "events": 0, "statuses": 0, "malformed": 0,
             "duplicates": 0}
    event_days, status_days = set(), set()
    for row, _name, _line in _jsonl(root, "liquidation_archive_*.jsonl"):
        stats["lines"] += 1
        if row is None:
            stats["malformed"] += 1
            continue
        if row.get("record_type") == "stream_status":
            stamp = time_ms(row.get("at_ms") if row.get("at_ms") is not None
                            else row.get("at_utc"))
            if stamp is None:
                stats["malformed"] += 1
                continue
            if str(row.get("status")) in {"connected", "heartbeat"}:
                heartbeat_bins.add(stamp // 300_000)
                status_days.add(datetime.fromtimestamp(
                    stamp / 1000, tz=timezone.utc).date().isoformat())
            stats["statuses"] += 1
            continue
        if row.get("record_type") != "force_order":
            continue
        event_id = str(row.get("event_id") or "")
        if event_id and event_id in seen_ids:
            stats["duplicates"] += 1
            continue
        symbol = str(row.get("symbol") or "").upper()
        stamp = time_ms(row.get("transaction_time_ms"))
        price = number(row.get("average_price")) or number(row.get("order_price"))
        notional = number(row.get("estimated_notional_usd"))
        side = str(row.get("liquidation_side") or "")
        if (not symbol or stamp is None or price is None or price <= 0
                or notional is None or notional < 0
                or side not in {"SHORT_LIQUIDATION", "LONG_LIQUIDATION"}):
            stats["malformed"] += 1
            continue
        if event_id:
            seen_ids.add(event_id)
        by_symbol[symbol].append({"t": stamp, "price": price,
                                  "notional": notional, "side": side})
        event_days.add(datetime.fromtimestamp(
            stamp / 1000, tz=timezone.utc).date().isoformat())
        stats["events"] += 1
    for rows in by_symbol.values():
        rows.sort(key=lambda row: row["t"])
    return {
        "by_symbol": dict(by_symbol),
        "times": {symbol: [row["t"] for row in rows]
                  for symbol, rows in by_symbol.items()},
        "heartbeat_bins": sorted(heartbeat_bins),
    }, {**stats, "event_days": len(event_days),
        "status_days": len(status_days)}


def _slice_rows(archive: dict, symbol: str, start_ms: int,
                end_ms: int) -> list[dict]:
    times = archive["times"].get(symbol, [])
    rows = archive["by_symbol"].get(symbol, [])
    lo, hi = bisect.bisect_left(times, start_ms), bisect.bisect_left(times, end_ms)
    return rows[lo:hi]


def _covered_bins(archive: dict, start_ms: int, end_ms: int) -> list[int]:
    bins = archive["heartbeat_bins"]
    lo = bisect.bisect_left(bins, start_ms // 300_000)
    hi = bisect.bisect_left(bins, math.ceil(end_ms / 300_000))
    return bins[lo:hi]


def percentile_rank(history: list[float], value: float) -> float | None:
    if not history:
        return None
    return 100.0 * sum(item <= value for item in history) / len(history)


def liquidation_features(event: dict, archive: dict) -> dict:
    """Compute point-in-time LQ1/LQ2 features using rows strictly before entry."""
    entry_ms = int(event["entry_time_ms"])
    symbol = event["symbol"]
    base_price = float(event["condition_price"])
    recent = _slice_rows(archive, symbol, entry_ms - 3_600_000, entry_ms)
    short_1h = sum(row["notional"] for row in recent
                   if row["side"] == "SHORT_LIQUIDATION")
    long_1h = sum(row["notional"] for row in recent
                  if row["side"] == "LONG_LIQUIDATION")

    history_start = entry_ms - BURST_HISTORY_DAYS * 86_400_000
    history_end = entry_ms - 3_600_000
    covered = _covered_bins(archive, history_start, history_end)
    covered_hours = sorted({bin_ * 300_000 // 3_600_000 for bin_ in covered})
    historical_rows = _slice_rows(archive, symbol, history_start, history_end)
    short_by_hour: dict[int, float] = defaultdict(float)
    for row in historical_rows:
        if row["side"] == "SHORT_LIQUIDATION":
            short_by_hour[row["t"] // 3_600_000] += row["notional"]
    history_values = [short_by_hour.get(hour, 0.0) for hour in covered_hours]
    history_days = len({datetime.fromtimestamp(
        hour * 3600, tz=timezone.utc).date().isoformat()
                        for hour in covered_hours})
    burst_pct = (percentile_rank(history_values, short_1h)
                 if short_1h > 0 and len(covered_hours) >= MIN_HISTORY_HOURS
                 and history_days >= BURST_HISTORY_DAYS else None)
    lq1 = burst_pct is not None and burst_pct >= BURST_PERCENTILE_MIN

    zone_start = entry_ms - ZONE_LOOKBACK_HOURS * 3_600_000
    zone_rows = _slice_rows(archive, symbol, zone_start, entry_ms)
    zone_covered = _covered_bins(archive, zone_start, entry_ms)
    expected_bins = ZONE_LOOKBACK_HOURS * 12
    coverage_pct = min(100.0, len(set(zone_covered)) / expected_bins * 100)
    up_bins: dict[int, float] = defaultdict(float)
    down_bins: dict[int, float] = defaultdict(float)
    for row in zone_rows:
        relative = (row["price"] / base_price - 1) * 100
        bucket = int(round(relative / ZONE_BIN_PCT))
        center = bucket * ZONE_BIN_PCT
        if (row["side"] == "SHORT_LIQUIDATION"
                and ZONE_MIN_DISTANCE_PCT <= center <= ZONE_MAX_DISTANCE_PCT):
            up_bins[bucket] += row["notional"]
        elif (row["side"] == "LONG_LIQUIDATION"
              and -ZONE_MAX_DISTANCE_PCT <= center <= -ZONE_MIN_DISTANCE_PCT):
            down_bins[bucket] += row["notional"]
    up_total, down_total = sum(up_bins.values()), sum(down_bins.values())
    dominant_bucket = (max(up_bins, key=lambda key: (up_bins[key], -abs(key)))
                       if up_bins else None)
    zone_price = (base_price * (1 + dominant_bucket * ZONE_BIN_PCT / 100)
                  if dominant_bucket is not None else None)
    ratio = (up_total / down_total if down_total > 0
             else (math.inf if up_total > 0 else None))
    lq2 = (coverage_pct >= MIN_ZONE_COVERAGE_PCT and up_total > 0
           and ratio is not None and ratio >= UP_DOWN_RATIO_MIN)
    return {
        "short_liq_usd_1h": short_1h, "long_liq_usd_1h": long_1h,
        "burst_history_hours": len(covered_hours),
        "burst_history_days": history_days,
        "short_burst_percentile": burst_pct, "lq1_short_burst": lq1,
        "zone_coverage_pct": coverage_pct,
        "up_zone_usd_24h": up_total, "down_zone_usd_24h": down_total,
        "up_down_zone_ratio": ratio,
        "up_zone_price": zone_price,
        "up_zone_distance_pct": (dominant_bucket * ZONE_BIN_PCT
                                 if dominant_bucket is not None else None),
        "lq2_up_zone": lq2,
    }


def _zone_touch(bars: list[dict], zone_price: float | None) -> tuple[
        bool | None, int | None, str | None]:
    if zone_price is None or not bars:
        return None, None, "zone_unavailable"
    # Koşul fiyatına göre tanımlanan bölge, ölçüm girişi açılışında zaten
    # aşılmışsa bunu gelecekteki bir "dokunma" başarısı saymak look-ahead olmasa
    # da hipotezi yanlış ölçer. Ayrı unavailable nedeni olarak dışarı ver.
    if bars[0]["open"] >= zone_price:
        return None, None, "zone_already_reached_before_entry"
    for index, bar in enumerate(bars):
        if bar["high"] >= zone_price:
            return True, (index + 1) * 5, None
    return False, None, None


def evaluate_event(event: dict, features: dict, bars: list[dict]) -> dict:
    entry = bars[0]["open"]
    exit_price = bars[-1]["close"]
    gross = (exit_price / entry - 1) * 100
    mfe = (max(bar["high"] for bar in bars) / entry - 1) * 100
    mae = (min(bar["low"] for bar in bars) / entry - 1) * 100
    tp2 = simulate_long(bars, 2.0, 1.5, COST_BPS)
    tp3 = simulate_long(bars, 3.0, 1.5, COST_BPS)
    touched, minutes, touch_reason = _zone_touch(
        bars, features.get("up_zone_price"))
    return {**event, **features, "entry_price": entry,
            "exit_price": exit_price, "gross_return_pct": gross,
            "net_return_pct": gross - COST_BPS / 100,
            "mfe_pct": mfe, "mae_pct": mae,
            "tp2_before_sl15": tp2.get("outcome") == "TARGET",
            "tp3_before_sl15": tp3.get("outcome") == "TARGET",
            "zone_touched_4h": touched, "minutes_to_zone": minutes,
            "zone_touch_unavailable_reason": touch_reason}


def _quantile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    pos = (len(ordered) - 1) * q
    lo, hi = math.floor(pos), math.ceil(pos)
    if lo == hi:
        return ordered[lo]
    return ordered[lo] * (hi - pos) + ordered[hi] * (pos - lo)


def _bootstrap_p(rows: list[dict]) -> float | None:
    by_day: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        day = datetime.fromtimestamp(
            row["entry_time_ms"] / 1000, tz=timezone.utc).date().isoformat()
        by_day[day].append(row["net_return_pct"])
    daily = [statistics.mean(values) for values in by_day.values()]
    if len(daily) < 2:
        return None
    rng = random.Random(20260901)
    nonpositive = 0
    for _ in range(BOOTSTRAP_SAMPLES):
        sample = [rng.choice(daily) for _ in daily]
        nonpositive += statistics.mean(sample) <= 0
    return nonpositive / BOOTSTRAP_SAMPLES


def summarize(rows: list[dict]) -> dict:
    values = [row["net_return_pct"] for row in rows]
    zone_rows = [row for row in rows if row.get("zone_touched_4h") is not None]
    touched = [row for row in zone_rows if row["zone_touched_4h"]]
    times = [row["minutes_to_zone"] for row in touched
             if row.get("minutes_to_zone") is not None]
    n = len(rows)
    by_symbol: dict[str, int] = defaultdict(int)
    for row in rows:
        by_symbol[str(row["symbol"])] += 1
    return {
        "n": n,
        "symbol_count": len(by_symbol),
        "max_symbol_share_pct": (100 * max(by_symbol.values()) / n
                                 if n else None),
        "independent_days": len({datetime.fromtimestamp(
            row["entry_time_ms"] / 1000, tz=timezone.utc).date().isoformat()
                                 for row in rows}),
        "mean_net_pct": statistics.mean(values) if values else None,
        "median_net_pct": statistics.median(values) if values else None,
        "win_rate_pct": 100 * sum(value > 0 for value in values) / n if n else None,
        "q10_net_pct": _quantile(values, .10), "q90_net_pct": _quantile(values, .90),
        "median_mfe_pct": statistics.median(
            [row["mfe_pct"] for row in rows]) if rows else None,
        "median_mae_pct": statistics.median(
            [row["mae_pct"] for row in rows]) if rows else None,
        "tp2_before_sl15_pct": 100 * sum(row["tp2_before_sl15"] for row in rows) / n
        if n else None,
        "tp3_before_sl15_pct": 100 * sum(row["tp3_before_sl15"] for row in rows) / n
        if n else None,
        "zone_touch_pct": 100 * len(touched) / len(zone_rows) if zone_rows else None,
        "median_minutes_to_zone": statistics.median(times) if times else None,
        "bootstrap_p_mean_nonpositive": _bootstrap_p(rows),
        "sample_warning": "small_sample" if n < 30 else None,
    }


def _matches(rule: str, row: dict) -> bool:
    if rule == "BASE_G1":
        return True
    if rule == "G1_LQ1_SHORT_BURST":
        return bool(row.get("lq1_short_burst"))
    if rule == "G1_LQ2_UP_ZONE":
        return bool(row.get("lq2_up_zone"))
    if rule == "G1_LQ1_AND_LQ2":
        return bool(row.get("lq1_short_burst") and row.get("lq2_up_zone"))
    raise ValueError(rule)


def run(root: Path, cache_dir: Path, *, workers: int = 4,
        allow_download: bool = True,
        now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    events, event_stats = load_g1_events(root)
    archive, liquidation_stats = load_liquidation_archive(root)
    matured = [event for event in events if event["entry_time_ms"]
               + HORIZON_HOURS * 3_600_000 <= int(now.timestamp() * 1000)]
    features = { (event["symbol"], event["hour"]):
                 liquidation_features(event, archive) for event in matured }
    # Yalnız dondurulmuş 4 saatlik pencerenin dokunduğu günleri indir. Ortak
    # yardımcıdaki varsayılan 24 saat burada gereksiz ağ/disk kullanırdı.
    jobs = sorted({
        (str(event.get("contract") or event["symbol"]).upper(), day)
        for event in matured for day in event_days(event, HORIZON_HOURS)
    })
    daily, download = load_jobs(
        VisionKlineStore(cache_dir, allow_download=allow_download), jobs,
        workers=workers, quiet=True) if jobs else ({}, {
            "requested": 0, "cached": 0, "downloaded": 0,
            "missing": 0, "errors": 0, "reasons": {}})
    evaluated, unavailable = [], defaultdict(int)
    for event in matured:
        bars, reason = window_for_event(event, daily, HORIZON_HOURS)
        if reason:
            unavailable[reason] += 1
            continue
        evaluated.append(evaluate_event(
            event, features[(event["symbol"], event["hour"])], bars))
    rules = {rule: summarize([row for row in evaluated if _matches(rule, row)])
             for rule in RULES}
    first_liq = min((row["t"] for rows in archive["by_symbol"].values()
                     for row in rows), default=None)
    last_liq = max((row["t"] for rows in archive["by_symbol"].values()
                    for row in rows), default=None)
    span_days = ((last_liq - first_liq) / 86_400_000
                 if first_liq is not None and last_liq is not None else 0.0)
    ready = (span_days >= 90 and liquidation_stats["event_days"] >= 30
             and rules["BASE_G1"]["n"] >= 30)
    return {
        "schema_version": "g1-liquidation-proxy-v1",
        "generated_at_utc": now.isoformat(timespec="seconds"),
        "interpretation": "KESIF; gerçek liquidation heatmap veya canlı sinyal değil",
        "parameters": {
            "horizon_hours": HORIZON_HOURS, "cost_bps": COST_BPS,
            "zone_lookback_hours": ZONE_LOOKBACK_HOURS,
            "zone_bin_pct": ZONE_BIN_PCT,
            "zone_distance_pct": [ZONE_MIN_DISTANCE_PCT, ZONE_MAX_DISTANCE_PCT],
            "up_down_ratio_min": UP_DOWN_RATIO_MIN,
            "burst_history_days": BURST_HISTORY_DAYS,
            "burst_percentile_min": BURST_PERCENTILE_MIN,
        },
        "readiness": {"ready_for_discovery_review": ready,
                      "liquidation_span_days": round(span_days, 1),
                      "liquidation_event_days": liquidation_stats["event_days"],
                      "g1_events": len(events), "g1_matured": len(matured),
                      "g1_evaluated": len(evaluated)},
        "event_stats": event_stats, "liquidation_stats": liquidation_stats,
        "download": download, "unavailable": dict(unavailable), "rules": rules,
    }


def _fmt(value, digits: int = 2, suffix: str = "") -> str:
    return "—" if value is None else f"{value:.{digits}f}{suffix}"


def format_report(report: dict) -> str:
    ready = report["readiness"]
    lines = [
        "G1 + GERCEKLESMIS LIKIDASYON PROXY TESTI — KESIF / OOS DEGIL",
        "forceOrder = gerçekleşmiş snapshot; CoinGlass heatmap veya bekleyen bölge değil",
        (f"veri: {ready['g1_events']} G1 olay · {ready['g1_evaluated']} olgun/ölçülen · "
         f"{ready['liquidation_span_days']} takvim günü kapsam · "
         f"{ready['liquidation_event_days']} gerçek olay günü"),
        "giriş: sonraki 1s açılışı · çıkış: +4s kapanış · maliyet: 12bp",
        "",
        ("rule                     N gün  ort%   med%   WR%   q10%   q90%  "
         "TP2%  TP3%  MFE%   MAE%  zone%  p<=0"),
    ]
    for rule in RULES:
        row = report["rules"][rule]
        warning = " KUCUK" if row.get("sample_warning") else ""
        lines.append(
            f"{rule:<23} {row['n']:>3} {row['independent_days']:>3} "
            f"{_fmt(row['mean_net_pct']):>6} {_fmt(row['median_net_pct']):>6} "
            f"{_fmt(row['win_rate_pct'], 1):>5} {_fmt(row['q10_net_pct']):>7} "
            f"{_fmt(row['q90_net_pct']):>7} {_fmt(row['tp2_before_sl15_pct'], 1):>5} "
            f"{_fmt(row['tp3_before_sl15_pct'], 1):>5} "
            f"{_fmt(row['median_mfe_pct']):>6} {_fmt(row['median_mae_pct']):>6} "
            f"{_fmt(row['zone_touch_pct'], 1):>6} "
            f"{_fmt(row['bootstrap_p_mean_nonpositive'], 3):>5}{warning}")
    lines += ["", "KARAR: " + (
        "keşif inceleme kapısı hazır; sonuç seçimi yapmadan ön kayıt uygulanabilir."
        if ready["ready_for_discovery_review"] else
        "veri yetersiz; G1 değişmez, canlı filtre/güven oranı üretilmez."),
        "LQ1=önceki 1s short-likidasyon p95; LQ2=önceki 24s üst fiyat-kümesi proxy.",
        "Bu çıktı yatırım sinyali değildir ve bot emir açmaz."]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="G1 + gerçekleşmiş liquidation proxy keşif testi")
    parser.add_argument("--dir", default=".", help="arşivlerin bulunduğu klasör")
    parser.add_argument("--cache-dir", default="research/data/g1_liquidation_5m")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--no-download", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    report = run(Path(args.dir), Path(args.cache_dir), workers=args.workers,
                 allow_download=not args.no_download)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True)
          if args.json else format_report(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
