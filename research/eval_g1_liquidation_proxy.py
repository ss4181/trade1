"""G1 + gerçekleşmiş USD-M likidasyon yoğunluğu/fiyat-kümesi keşif testi.

Bu araç canlı stratejiyi değiştirmez. Binance ``!forceOrder@arr`` arşivi bir
gelecek liquidation heatmap'i değildir; yalnız gerçekleşmiş ve 1000 ms içinde
sembol başına en son force-order snapshot'larını içerir. Ayrıntılı ön kayıt:
``research/PREREG_G1_LIQUIDATION_PROXY.md``.
"""

from __future__ import annotations

import argparse
import bisect
import hashlib
import json
import math
import random
import re
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
REVIEW_VERSION = "g1-liquidation-proxy-v2-causal-audit"


def number(value) -> float | None:
    if isinstance(value, bool):
        return None
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


def _jsonl(root: Path, pattern: str, sources: list | None = None):
    for path in sorted(root.glob(pattern)):
        if path.is_symlink():
            raise ValueError("unsafe_source_symlink")
        before = path.stat()
        digest, size = hashlib.sha256(), 0
        with path.open("rb") as stream:
            for line_number, raw in enumerate(stream, 1):
                digest.update(raw)
                size += len(raw)
                try:
                    row = json.loads(raw)
                except (ValueError, UnicodeDecodeError):
                    yield None, path.name, line_number
                    continue
                yield row if isinstance(row, dict) else None, path.name, line_number
        after = path.stat()
        if sources is not None:
            sources.append({"name": path.name, "bytes": size,
                            "sha256": digest.hexdigest(),
                            "stable": (before.st_size == after.st_size == size
                                       and before.st_mtime_ns == after.st_mtime_ns),
                            "mtime_ns": after.st_mtime_ns})


def load_g1_events(root: Path, sources: list | None = None) -> tuple[list[dict], dict]:
    """Load only actual edge-triggered G1 events; never infer extra signals."""
    events: dict[tuple[str, int], dict] = {}
    stats = {"lines": 0, "accepted": 0, "malformed": 0, "duplicates": 0}
    for row, _name, _line in _jsonl(root, "shadow_events_*.jsonl", sources):
        stats["lines"] += 1
        if row is None:
            stats["malformed"] += 1
            continue
        if row.get("kind") != "G1_EVENT" and row.get("strategy") != "G1":
            continue
        symbol = str(row.get("performance_symbol") or row.get("symbol") or "").upper()
        bar_open = time_ms(row.get("bar_time"))
        if not re.fullmatch(r"[^\W_]{2,30}", symbol) or bar_open is None or bar_open % 3_600_000:
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
            "measurement_version": str(row.get("price_target_measurement_version") or "legacy"),
            "universe": str(row.get("universe") or "legacy_unspecified"),
            "feature_cutoff_ms": (hour + 1) * 3_600_000,
        }
        stats["accepted"] += 1
    return sorted(events.values(), key=lambda row: (row["entry_time_ms"],
                                                     row["symbol"])), stats


def load_liquidation_archive(root: Path, symbols: set | None = None,
                             sources: list | None = None,
                             cutoff_ms: int | None = None) -> tuple[dict, dict]:
    """Normalize force orders and global heartbeat coverage without zero fill."""
    by_symbol: dict[str, list[dict]] = defaultdict(list)
    heartbeat_bins: set[int] = set()
    disconnected_bins: set[int] = set()
    seen_ids: set[str] = set()
    stats = {"lines": 0, "events": 0, "statuses": 0, "malformed": 0,
             "duplicates": 0, "missing_receive_time": 0,
             "future_rows": 0, "first_event_ms": None, "last_event_ms": None}
    event_days, status_days = set(), set()
    for row, _name, _line in _jsonl(root, "liquidation_archive_*.jsonl", sources):
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
            if cutoff_ms is not None and stamp > cutoff_ms:
                stats["future_rows"] += 1
                continue
            if str(row.get("status")) in {"connected", "heartbeat"}:
                heartbeat_bins.add(stamp // 300_000)
                status_days.add(datetime.fromtimestamp(
                    stamp / 1000, tz=timezone.utc).date().isoformat())
            elif str(row.get("status")) in {"error", "disconnected", "stopped"}:
                disconnected_bins.add(stamp // 300_000)
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
        received = time_ms(row.get("received_at_ms"))
        if (not symbol or stamp is None or price is None or price <= 0
                or notional is None or notional < 0
                or side not in {"SHORT_LIQUIDATION", "LONG_LIQUIDATION"}):
            stats["malformed"] += 1
            continue
        if cutoff_ms is not None and (stamp > cutoff_ms or (received is not None and received > cutoff_ms)):
            stats["future_rows"] += 1
            continue
        if event_id:
            seen_ids.add(event_id)
        if received is None or received < stamp:
            stats["missing_receive_time"] += 1
            received = None
        if symbols is None or symbol in symbols:
            by_symbol[symbol].append({"t": stamp, "price": price,
                                      "notional": notional, "side": side,
                                      "received_at_ms": received})
        stats["first_event_ms"] = min(stamp, stats["first_event_ms"] or stamp)
        stats["last_event_ms"] = max(stamp, stats["last_event_ms"] or stamp)
        event_days.add(datetime.fromtimestamp(
            stamp / 1000, tz=timezone.utc).date().isoformat())
        stats["events"] += 1
    for rows in by_symbol.values():
        rows.sort(key=lambda row: row["t"])
    return {
        "by_symbol": dict(by_symbol),
        "times": {symbol: [row["t"] for row in rows]
                  for symbol, rows in by_symbol.items()},
        "heartbeat_bins": sorted(heartbeat_bins - disconnected_bins),
    }, {**stats, "event_days": len(event_days),
        "status_days": len(status_days)}


def _slice_rows(archive: dict, symbol: str, start_ms: int,
                end_ms: int, known_before_ms: int | None = None) -> list[dict]:
    times = archive["times"].get(symbol, [])
    rows = archive["by_symbol"].get(symbol, [])
    lo, hi = bisect.bisect_left(times, start_ms), bisect.bisect_left(times, end_ms)
    cutoff = end_ms if known_before_ms is None else known_before_ms
    return [row for row in rows[lo:hi]
            if row.get("received_at_ms") is not None and row["received_at_ms"] < cutoff]


def _covered_bins(archive: dict, start_ms: int, end_ms: int) -> list[int]:
    bins = archive["heartbeat_bins"]
    lo = bisect.bisect_left(bins, start_ms // 300_000)
    hi = bisect.bisect_left(bins, math.ceil(end_ms / 300_000))
    return bins[lo:hi]


def _unknown_receipt(archive, symbol, start_ms, end_ms):
    times = archive["times"].get(symbol, [])
    rows = archive["by_symbol"].get(symbol, [])
    lo, hi = bisect.bisect_left(times, start_ms), bisect.bisect_left(times, end_ms)
    return any(r.get("received_at_ms") is None for r in rows[lo:hi])


def percentile_rank(history: list[float], value: float) -> float | None:
    if not history:
        return None
    return 100.0 * sum(item <= value for item in history) / len(history)


def liquidation_features(event: dict, archive: dict) -> dict:
    """Compute point-in-time LQ1/LQ2 features using rows strictly before entry."""
    entry_ms = int(event.get("feature_cutoff_ms", event["entry_time_ms"]))
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
    # One heartbeat in an hour does not justify filling its other 55 minutes
    # with zeros. Only all twelve observed 5m bins make a comparable hour.
    counts = defaultdict(int)
    for bin_ in set(covered):
        counts[bin_ // 12] += 1
    covered_hours = sorted(hour for hour, count in counts.items() if count == 12)
    historical_rows = _slice_rows(archive, symbol, history_start, history_end,
                                  known_before_ms=entry_ms)
    short_by_hour: dict[int, float] = defaultdict(float)
    for row in historical_rows:
        if row["side"] == "SHORT_LIQUIDATION":
            short_by_hour[row["t"] // 3_600_000] += row["notional"]
    history_values = [short_by_hour.get(hour, 0.0) for hour in covered_hours]
    history_days = len({datetime.fromtimestamp(
        hour * 3600, tz=timezone.utc).date().isoformat()
                        for hour in covered_hours})
    recent_covered = (len(set(_covered_bins(archive, entry_ms - 3_600_000, entry_ms))) == 12
                      and not _unknown_receipt(archive, symbol, entry_ms - 3_600_000, entry_ms))
    burst_available = (recent_covered and len(covered_hours) >= MIN_HISTORY_HOURS
                       and history_days >= BURST_HISTORY_DAYS
                       and not _unknown_receipt(archive, symbol, history_start, history_end))
    burst_pct = percentile_rank(history_values, short_1h) if burst_available else None
    lq1 = (short_1h > 0 and burst_pct >= BURST_PERCENTILE_MIN) if burst_available else None

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
    ratio = up_total / down_total if down_total > 0 else None
    zone_available = (coverage_pct >= MIN_ZONE_COVERAGE_PCT
                      and not _unknown_receipt(archive, symbol, zone_start, entry_ms))
    lq2 = ((up_total > 0 and (down_total == 0 or ratio >= UP_DOWN_RATIO_MIN))
           if zone_available else None)
    return {
        "short_liq_usd_1h": short_1h if recent_covered else None,
        "long_liq_usd_1h": long_1h if recent_covered else None,
        "lq1_available": burst_available, "lq2_available": zone_available,
        "recent_hour_covered": recent_covered,
        "burst_history_hours": len(covered_hours),
        "burst_history_days": history_days,
        "short_burst_percentile": burst_pct, "lq1_short_burst": lq1,
        "zone_coverage_pct": coverage_pct,
        "up_zone_usd_24h": up_total if zone_available else None,
        "down_zone_usd_24h": down_total if zone_available else None,
        "up_down_zone_ratio": ratio if zone_available else None,
        "up_zone_price": zone_price if zone_available else None,
        "up_only_zone": bool(up_total > 0 and down_total == 0) if zone_available else None,
        "up_zone_distance_pct": (dominant_bucket * ZONE_BIN_PCT
                                 if dominant_bucket is not None and zone_available else None),
        "lq2_up_zone": lq2,
    }


def source_integrity(root: Path, sources: list, manifest_raw: bytes | None,
                     now: datetime) -> dict:
    """Hash the bytes actually parsed; never expose arbitrary manifest fields."""
    reasons = []
    actual = sorted(p.name for pattern in ("shadow_events_*.jsonl", "liquidation_archive_*.jsonl")
                    for p in root.glob(pattern))
    if actual != sorted(r["name"] for r in sources):
        reasons.append("source_file_set_changed")
    for row in sources:
        info = (root / row["name"]).stat()
        if (not row["stable"] or info.st_size != row["bytes"]
                or info.st_mtime_ns != row["mtime_ns"]):
            reasons.append("source_changed:" + row["name"])
    path = root / "backup_manifest.json"
    current = path.read_bytes() if path.is_file() else None
    if current != manifest_raw:
        reasons.append("manifest_changed")
    age_hours = None
    if manifest_raw is not None:
        try:
            manifest = json.loads(manifest_raw)
            if manifest["schema_version"] != "trade1-backup-v1":
                raise ValueError("wrong_schema")
            stamp = datetime.fromisoformat(manifest["created_at_utc"])
            if stamp.tzinfo is None:
                raise ValueError("timezone_missing")
            age_hours = (now - stamp).total_seconds() / 3600
            if not 0 <= age_hours <= 36:
                reasons.append("backup_stale_or_future")
            for row in sources:
                expected = manifest["files"].get(row["name"], {})
                if (expected.get("sha256") != row["sha256"]
                        or expected.get("bytes") != row["bytes"]):
                    reasons.append("manifest_mismatch:" + row["name"])
        except (KeyError, TypeError, ValueError, AttributeError):
            reasons.append("manifest_invalid")
    return {"ok": not reasons, "issues": reasons,
            "manifest_present": manifest_raw is not None,
            "manifest_age_hours": round(age_hours, 2) if age_hours is not None else None,
            "scope": "only_g1_and_liquidation_inputs_not_full_backup",
            "sources": [{k: v for k, v in row.items() if k != "mtime_ns"} for row in sources]}


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


def _cohort_key(row: dict) -> tuple[str, str, str]:
    return row["config_version"], row["measurement_version"], row["universe"]


def run(root: Path, cache_dir: Path, *, workers: int = 4,
        allow_download: bool = False,
        now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None or not root.is_dir():
        raise ValueError("valid_archive_and_utc_time_required")
    manifest_path = root / "backup_manifest.json"
    manifest_raw = manifest_path.read_bytes() if manifest_path.is_file() else None
    sources = []
    events, event_stats = load_g1_events(root, sources)
    archive, liquidation_stats = load_liquidation_archive(
        root, symbols={r["symbol"] for r in events}, sources=sources,
        cutoff_ms=int(now.timestamp() * 1000))
    integrity = source_integrity(root, sources, manifest_raw, now)
    matured = [event for event in events if event["entry_time_ms"]
               + HORIZON_HOURS * 3_600_000 <= int(now.timestamp() * 1000)]
    features = { (event["symbol"], event["hour"]):
                 liquidation_features(event, archive) for event in matured }
    input_groups = defaultdict(list)
    for event in events:
        input_groups[_cohort_key(event)].append(event)
    input_cohorts = []
    for key, rows in sorted(input_groups.items()):
        known = [features[(row["symbol"], row["hour"])] for row in rows
                 if (row["symbol"], row["hour"]) in features]
        input_cohorts.append({
            "config_version": key[0], "measurement_version": key[1], "universe": key[2],
            "n_events": len(rows), "n_matured": len(known),
            "lq1_available": sum(r["lq1_available"] for r in known),
            "lq2_available": sum(r["lq2_available"] for r in known)})
    # Yalnız dondurulmuş 4 saatlik pencerenin dokunduğu günleri indir. Ortak
    # yardımcıdaki varsayılan 24 saat burada gereksiz ağ/disk kullanırdı.
    first_liq, last_liq = liquidation_stats["first_event_ms"], liquidation_stats["last_event_ms"]
    span_days = ((last_liq - first_liq) / 86_400_000
                 if first_liq is not None and last_liq is not None else 0.0)
    gate_checks = {"span_90_days": span_days >= 90,
                   "liquidation_30_event_days": liquidation_stats["event_days"] >= 30,
                   "mature_g1_30_events": len(matured) >= 30,
                   "source_integrity": integrity["ok"],
                   "parse_quality": event_stats["malformed"] == 0 and liquidation_stats["malformed"] == 0}
    inputs_ready = all(gate_checks.values())
    # No price downloads, return calculations or success rates before the
    # preregistered discovery gate. Readiness counts are not profitability.
    jobs = sorted({
        (str(event.get("contract") or event["symbol"]).upper(), day)
        for event in matured for day in event_days(event, HORIZON_HOURS)
    }) if inputs_ready else []
    daily, download = load_jobs(
        VisionKlineStore(cache_dir, allow_download=allow_download), jobs,
        workers=workers, quiet=True) if jobs else ({}, {
            "requested": 0, "cached": 0, "downloaded": 0,
            "missing": 0, "errors": 0, "reasons": {}})
    # A sync may replace files while features/prices are being prepared. The
    # hashes describe the parsed snapshot, but a changing source is not ready.
    integrity = source_integrity(root, sources, manifest_raw, now)
    gate_checks["source_integrity"] = integrity["ok"]
    inputs_ready = inputs_ready and integrity["ok"]
    evaluated, unavailable = [], defaultdict(int)
    for event in matured if inputs_ready else []:
        bars, reason = window_for_event(event, daily, HORIZON_HOURS)
        if reason:
            unavailable[reason] += 1
            continue
        evaluated.append(evaluate_event(
            event, features[(event["symbol"], event["hour"])], bars))
    ready = inputs_ready and len(evaluated) >= 30
    grouped = defaultdict(list)
    for row in evaluated:
        grouped[_cohort_key(row)].append(row)
    cohorts = []
    for key, rows in sorted(grouped.items()):
        # Never pool legacy ticker references and v3 fresh-ask cohorts.
        if len(rows) < 30 or not ready:
            cohorts.append({"config_version": key[0], "measurement_version": key[1],
                            "universe": key[2], "n": len(rows), "rules": {},
                            "withheld": "cohort_or_total_sample_below_30"})
            continue
        rule_rows = {rule: [row for row in rows if _matches(rule, row)] for rule in RULES}
        cohorts.append({"config_version": key[0], "measurement_version": key[1],
                        "universe": key[2], "n": len(rows),
                        "rules": {r: summarize(v) for r, v in rule_rows.items()},
                        "matched_baselines": {
                            "LQ1": summarize([r for r in rows if r["lq1_available"]]),
                            "LQ2": summarize([r for r in rows if r["lq2_available"]]),
                            "LQ1_AND_LQ2": summarize([r for r in rows if r["lq1_available"] and r["lq2_available"]])}})
    ready = ready and any(c["rules"] for c in cohorts)
    return {
        "schema_version": REVIEW_VERSION,
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
                      "input_gate_checks": gate_checks,
                      "success_rates_withheld": not any(c["rules"] for c in cohorts),
                      "earliest_span_review_utc": (datetime.fromtimestamp(
                          first_liq / 1000, tz=timezone.utc) + timedelta(days=90)).isoformat()
                      if first_liq else None,
                      "liquidation_span_days": round(span_days, 1),
                      "liquidation_event_days": liquidation_stats["event_days"],
                      "g1_events": len(events), "g1_matured": len(matured),
                      "g1_evaluated": len(evaluated)},
        "feature_coverage": {
            "lq1_available": sum(r["lq1_available"] for r in features.values()),
            "lq2_available": sum(r["lq2_available"] for r in features.values()),
            "lq1_matched": sum(r["lq1_short_burst"] is True for r in features.values()),
            "lq2_matched": sum(r["lq2_up_zone"] is True for r in features.values())},
        "source_integrity": integrity,
        "prereg_sha256": hashlib.sha256((Path(__file__).parent / "PREREG_G1_LIQUIDATION_PROXY.md").read_bytes()).hexdigest()
            if (Path(__file__).parent / "PREREG_G1_LIQUIDATION_PROXY.md").is_file() else None,
        "live_rules_changed": False, "oos_evaluated": False,
        "funding_cost_status": "not_modeled",
        "measurement": "next_hour_reference_not_notification_fill_or_live_trade",
        "event_stats": event_stats, "liquidation_stats": liquidation_stats,
        "input_cohorts": input_cohorts,
        "download": download, "unavailable": dict(unavailable), "cohorts": cohorts,
        "rules": cohorts[0]["rules"] if len(cohorts) == 1 else {},
    }


def _fmt(value, digits: int = 2, suffix: str = "") -> str:
    return "—" if value is None else f"{value:.{digits}f}{suffix}"


def format_report(report: dict) -> str:
    ready = report["readiness"]
    lines = [
        "G1 + GERCEKLESMIS LIKIDASYON PROXY TESTI — KESIF / OOS DEGIL",
        "forceOrder = gerçekleşmiş snapshot; CoinGlass heatmap veya bekleyen bölge değil",
        (f"veri: {ready['g1_events']} G1 olay · {ready['g1_matured']} süresi dolmuş · "
         f"{ready['g1_evaluated']} getirisi ölçülen · "
         f"{ready['liquidation_span_days']} takvim günü kapsam · "
         f"{ready['liquidation_event_days']} gerçek olay günü"),
        "giriş: sonraki 1s açılışı · çıkış: +4s kapanış · maliyet: 12bp",
        "",
        ("rule                     N gün  ort%   med%   WR%   q10%   q90%  "
         "TP2%  TP3%  MFE%   MAE%  zone%  p<=0"),
    ]
    if ready.get("success_rates_withheld"):
        lines = lines[:-2]
        lines += ["Başarı/getiri tablosu kapalı: ön-kayıt veya veri bütünlüğü koşulları eksik.",
                  "Özellik kapsamı: " + json.dumps(report["feature_coverage"], ensure_ascii=False)]
    for cohort in report.get("cohorts", []):
        lines.append(f"Kohort: {cohort['config_version']} / {cohort['measurement_version']} / {cohort['universe']}")
        if not cohort["rules"]:
            lines.append(f"N={cohort['n']}: kohort tablosu kapalı")
        for rule, row in cohort["rules"].items():
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
    if report["source_integrity"]["issues"]:
        lines.append("Girdi sorunları: " + ", ".join(report["source_integrity"]["issues"]))
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
    parser.add_argument("--download", action="store_true", help="Enable downloads only AFTER the review input gates pass")
    parser.add_argument("--no-download", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--output", type=Path, help="Optional NEW private JSON report outside the source archive")
    args = parser.parse_args()
    if args.output and (args.output.exists() or args.output.resolve().is_relative_to(Path(args.dir).resolve())):
        parser.error("output must be new and outside the source archive")
    try:
        report = run(Path(args.dir), Path(args.cache_dir), workers=args.workers,
                     allow_download=args.download and not args.no_download)
    except (OSError, ValueError, TypeError):
        print('{"error":"g1_liquidation_input_audit_failed"}')
        return 1
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as stream:
            json.dump(report, stream, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True, allow_nan=False)
          if args.json else format_report(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
