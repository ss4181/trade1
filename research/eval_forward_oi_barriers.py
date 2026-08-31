"""Five-minute first-touch diagnostics for forward OI discovery events.

This module does not fit or activate a strategy.  It reuses the frozen P0-P5
and Q1 event definitions from ``explore_forward_oi.py``, downloads only the
official Binance USD-M 5m daily kline files needed around those events, and
measures whether a long take-profit or stop is touched first.  Results remain
discovery data until the separately declared OOS protocol is completed.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import random
import statistics
import sys
import time
import zipfile
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

try:  # package import in tests; script import on the tablet
    from research.explore_forward_oi import (
        COST_BPS,
        build_features,
        conditions,
        independent_events,
        load_rows,
        percentile,
    )
except ModuleNotFoundError:  # pragma: no cover - exercised by tablet CLI
    from explore_forward_oi import (  # type: ignore
        COST_BPS,
        build_features,
        conditions,
        independent_events,
        load_rows,
        percentile,
    )


VISION_BASE = "https://data.binance.vision/data/futures/um/daily/klines"
INTERVAL = "5m"
BAR_MS = 5 * 60 * 1000
TARGETS_PCT = (2.0, 3.0)
STOPS_PCT = (1.0, 1.5, 2.0)
HORIZONS_HOURS = (4, 12, 24)
PRIMARY_STOP_PCT = 1.5
BOOTSTRAP_SAMPLES = 2000
DEFAULT_WORKERS = 6


def _finite(value) -> float | None:
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError, OverflowError):
        return None


def epoch_ms(value) -> int | None:
    """Parse Binance millisecond timestamps and tolerate microseconds."""
    parsed = _finite(value)
    if parsed is None or parsed < 0:
        return None
    if parsed >= 100_000_000_000_000:
        parsed /= 1000
    return int(parsed)


def parse_kline_zip(raw: bytes) -> list[dict]:
    archive = zipfile.ZipFile(io.BytesIO(raw))
    if archive.testzip() is not None:
        raise zipfile.BadZipFile("ZIP CRC dogrulamasi basarisiz")
    members = [name for name in archive.namelist()
               if name.lower().endswith(".csv") and not name.endswith("/")]
    if len(members) != 1:
        raise ValueError("kline ZIP tam olarak bir CSV icermeli")
    bars: dict[int, dict] = {}
    with archive.open(members[0]) as binary:
        stream = io.TextIOWrapper(binary, encoding="utf-8-sig", newline="")
        for row in csv.reader(stream):
            if len(row) < 7:
                continue
            opened = epoch_ms(row[0])
            prices = [_finite(value) for value in row[1:5]]
            if opened is None or any(value is None or value <= 0
                                     for value in prices):
                continue  # also skips an optional header row
            bars[opened] = {
                "open_time_ms": opened,
                "open": prices[0], "high": prices[1],
                "low": prices[2], "close": prices[3],
            }
    return [bars[key] for key in sorted(bars)]


def _download(url: str, retries: int = 4) -> bytes | None:
    for attempt in range(retries):
        try:
            response = requests.get(url, timeout=45)
            if response.status_code == 404:
                return None
            response.raise_for_status()
            return response.content
        except requests.RequestException:
            if attempt == retries - 1:
                raise
            time.sleep(2 ** attempt)
    return None


class VisionKlineStore:
    """Checksum-verified on-disk cache for manual research downloads."""

    def __init__(self, cache_dir: Path, allow_download: bool = True):
        self.cache_dir = cache_dir
        self.allow_download = allow_download

    @staticmethod
    def url(contract: str, day: str) -> str:
        name = f"{contract}-{INTERVAL}-{day}.zip"
        return f"{VISION_BASE}/{contract}/{INTERVAL}/{name}"

    def load_day(self, contract: str, day: str) -> dict:
        folder = self.cache_dir / contract
        path = folder / f"{contract}-{INTERVAL}-{day}.zip"
        digest_path = path.with_suffix(path.suffix + ".sha256")
        if path.exists():
            raw = path.read_bytes()
            expected = (digest_path.read_text(encoding="ascii").strip().lower()
                        if digest_path.exists() else "")
            actual = hashlib.sha256(raw).hexdigest()
            if expected and expected != actual:
                raw = b""  # corrupt cache is replaced, never analyzed
            if raw:
                try:
                    return {"status": "cached", "bars": parse_kline_zip(raw)}
                except (ValueError, OSError, zipfile.BadZipFile):
                    raw = b""
        if not self.allow_download:
            return {"status": "missing", "bars": [],
                    "reason": "cache_missing_download_disabled"}

        url = self.url(contract, day)
        raw = _download(url)
        if raw is None:
            return {"status": "missing", "bars": [],
                    "reason": "official_daily_file_not_available"}
        checksum_raw = _download(url + ".CHECKSUM")
        if checksum_raw is None:
            return {"status": "error", "bars": [],
                    "reason": "official_checksum_not_available"}
        expected = checksum_raw.decode("utf-8", errors="strict").split()[0].lower()
        actual = hashlib.sha256(raw).hexdigest()
        if len(expected) != 64 or expected != actual:
            return {"status": "error", "bars": [],
                    "reason": "sha256_mismatch"}
        bars = parse_kline_zip(raw)
        folder.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        digest_path.write_text(expected + "\n", encoding="ascii")
        return {"status": "downloaded", "bars": bars}


def event_key(event: dict) -> tuple[str, int]:
    return str(event["symbol"]), int(event["hour"])


def entry_time_ms(event: dict) -> int:
    # Deliberately matches the hourly discovery analyzer.  The archive worker
    # takes time to visit every symbol, so an earlier 5m entry could look ahead.
    return int(event["entry_hour"]) * 3600 * 1000


def event_days(event: dict, horizon_hours: int = 24) -> list[str]:
    start = datetime.fromtimestamp(entry_time_ms(event) / 1000, tz=timezone.utc)
    end = start + timedelta(hours=horizon_hours) - timedelta(milliseconds=1)
    days = []
    cursor = start.date()
    while cursor <= end.date():
        days.append(cursor.isoformat())
        cursor += timedelta(days=1)
    return days


def required_jobs(events_by_rule: dict[str, list[dict]]) -> list[tuple[str, str]]:
    jobs = set()
    seen = set()
    for events in events_by_rule.values():
        for event in events:
            key = event_key(event)
            if key in seen:
                continue
            seen.add(key)
            contract = str(event.get("contract") or event["symbol"]).upper()
            for day in event_days(event):
                jobs.add((contract, day))
    return sorted(jobs)


def load_jobs(store: VisionKlineStore, jobs: list[tuple[str, str]],
              workers: int = DEFAULT_WORKERS, quiet: bool = False) -> tuple[dict, dict]:
    data = {}
    stats = {"requested": len(jobs), "cached": 0, "downloaded": 0,
             "missing": 0, "errors": 0, "reasons": {}}
    workers = max(1, min(int(workers), 12))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(store.load_day, *job): job for job in jobs}
        for done, future in enumerate(as_completed(futures), 1):
            job = futures[future]
            try:
                result = future.result()
            except Exception as exc:  # missing data is reported, never fabricated
                result = {"status": "error", "bars": [],
                          "reason": f"{type(exc).__name__}"}
            data[job] = result["bars"]
            status = result["status"]
            if status == "error":
                stats["errors"] += 1
            else:
                stats[status] += 1
            reason = result.get("reason")
            if reason:
                stats["reasons"][reason] = stats["reasons"].get(reason, 0) + 1
            if not quiet and (done % 25 == 0 or done == len(jobs)):
                print(f"5m veri: {done}/{len(jobs)} gun", file=sys.stderr,
                      flush=True)
    return data, stats


def window_for_event(event: dict, daily: dict,
                     horizon_hours: int) -> tuple[list[dict], str | None]:
    contract = str(event.get("contract") or event["symbol"]).upper()
    by_time = {}
    for day in event_days(event, horizon_hours):
        for bar in daily.get((contract, day), []):
            by_time[bar["open_time_ms"]] = bar
    start = entry_time_ms(event)
    expected = [start + offset * BAR_MS
                for offset in range(horizon_hours * 12)]
    missing = [stamp for stamp in expected if stamp not in by_time]
    if missing:
        return [], f"missing_5m_bars:{len(missing)}"
    return [by_time[stamp] for stamp in expected], None


def simulate_long(bars: list[dict], target_pct: float,
                  stop_pct: float, cost_bps: float = COST_BPS) -> dict:
    if not bars:
        return {"available": False, "unavailable_reason": "no_bars"}
    entry = bars[0]["open"]
    target = entry * (1 + target_pct / 100)
    stop = entry * (1 - stop_pct / 100)
    mfe_pct, mae_pct = 0.0, 0.0
    outcome, fill, exit_index = "TIMEOUT", bars[-1]["close"], len(bars) - 1
    for index, bar in enumerate(bars):
        if index > 0 and bar["open"] <= stop:
            mae_pct = min(mae_pct, (bar["open"] / entry - 1) * 100)
            outcome, fill, exit_index = "STOP_GAP", bar["open"], index
            break
        if index > 0 and bar["open"] >= target:
            mfe_pct = max(mfe_pct, (bar["open"] / entry - 1) * 100)
            outcome, fill, exit_index = "TARGET", target, index
            break
        # For an intrabar exit, OHLC cannot tell whether the other extreme was
        # seen before or after the barrier.  Including the whole exit bar is a
        # conservative excursion estimate and is disclosed in the report.
        mfe_pct = max(mfe_pct, (bar["high"] / entry - 1) * 100)
        mae_pct = min(mae_pct, (bar["low"] / entry - 1) * 100)
        target_hit = bar["high"] >= target
        stop_hit = bar["low"] <= stop
        if target_hit and stop_hit:
            # OHLC cannot reveal intrabar ordering.  Stop-first is the frozen,
            # conservative primary assumption; ambiguity is still counted.
            outcome, fill, exit_index = "AMBIGUOUS_AS_STOP", stop, index
            break
        if stop_hit:
            outcome, fill, exit_index = "STOP", stop, index
            break
        if target_hit:
            outcome, fill, exit_index = "TARGET", target, index
            break
    gross_pct = (fill / entry - 1) * 100
    return {
        "available": True, "outcome": outcome,
        "entry_price": entry, "exit_price": fill,
        "gross_return_pct": gross_pct,
        "net_return_pct": gross_pct - cost_bps / 100,
        "minutes_to_exit": (exit_index + 1) * 5,
        "mfe_pct": mfe_pct, "mae_pct": mae_pct,
    }


def _bootstrap_nonpositive(outcomes: list[dict]) -> float | None:
    by_day = defaultdict(list)
    for row in outcomes:
        day = datetime.fromtimestamp(
            row["entry_time_ms"] / 1000, tz=timezone.utc).date().isoformat()
        by_day[day].append(row["net_return_pct"])
    daily = [statistics.mean(values) for values in by_day.values()]
    if len(daily) < 2:
        return None
    rng = random.Random(20260831)
    nonpositive = 0
    for _ in range(BOOTSTRAP_SAMPLES):
        sample = [rng.choice(daily) for _ in daily]
        nonpositive += statistics.mean(sample) <= 0
    return nonpositive / BOOTSTRAP_SAMPLES


def summarize_outcomes(rows: list[dict], n_total: int) -> dict:
    available = [row for row in rows if row.get("available")]
    values = [row["net_return_pct"] for row in available]
    targets = [row for row in available if row["outcome"] == "TARGET"]
    stops = [row for row in available if row["outcome"] in
             {"STOP", "STOP_GAP", "AMBIGUOUS_AS_STOP"}]
    ambiguous = [row for row in available
                 if row["outcome"] == "AMBIGUOUS_AS_STOP"]
    timeouts = [row for row in available if row["outcome"] == "TIMEOUT"]
    n = len(available)
    rate = lambda count: round(count / n * 100, 1) if n else None
    target_minutes = [row["minutes_to_exit"] for row in targets]
    maes = [row["mae_pct"] for row in available]
    independent_days = len({
        datetime.fromtimestamp(
            row["entry_time_ms"] / 1000, tz=timezone.utc
        ).date().isoformat()
        for row in available
    })
    return {
        "n_total": n_total, "n": n, "n_unavailable": n_total - n,
        "independent_days": independent_days,
        "target_first_pct_lower": rate(len(targets)),
        "target_first_pct_upper": rate(len(targets) + len(ambiguous)),
        "stop_first_pct": rate(len(stops)),
        "timeout_pct": rate(len(timeouts)),
        "ambiguous_count": len(ambiguous),
        "win_rate_pct": rate(sum(value > 0 for value in values)),
        "mean_net_pct": round(statistics.mean(values), 4) if values else None,
        "median_net_pct": round(statistics.median(values), 4) if values else None,
        "q10_net_pct": round(percentile(values, .10), 4) if values else None,
        "q90_net_pct": round(percentile(values, .90), 4) if values else None,
        "median_mae_pct": round(statistics.median(maes), 4) if maes else None,
        "median_minutes_to_target": (
            round(statistics.median(target_minutes), 1)
            if target_minutes else None),
        "bootstrap_p_mean_nonpositive": (
            round(_bootstrap_nonpositive(available), 4) if available else None),
        "sample_warning": "small_sample" if n < 30 else "",
    }


def break_even_win_rate(target_pct: float, stop_pct: float,
                        cost_bps: float = COST_BPS) -> float:
    win = target_pct - cost_bps / 100
    loss = stop_pct + cost_bps / 100
    return loss / (win + loss) * 100


def analyze(root: Path, cache_dir: Path, allow_download: bool = True,
            workers: int = DEFAULT_WORKERS, quiet: bool = False) -> dict:
    panel, ingest = load_rows(root)
    features = build_features(panel)
    rule_names = list(conditions(features[0])) if features else [
        "P0_top10_gainer5", "P1_plus_volume2x", "P2_plus_any_oi_up",
        "P3_plus_oi_2pct", "P4_plus_short_majority",
        "P5_plus_funding_rise", "Q1_squeeze_proxy_oi_down",
    ]
    events_by_rule = {rule: independent_events(features, rule)
                      for rule in rule_names}
    feature_hours = sorted({int(row["hour"]) for row in features})
    jobs = required_jobs(events_by_rule)
    daily, download = load_jobs(
        VisionKlineStore(cache_dir, allow_download), jobs, workers, quiet)
    grid = {}
    for rule, events in events_by_rule.items():
        grid[rule] = {}
        windows = {}
        for horizon in HORIZONS_HOURS:
            windows[horizon] = {
                event_key(event): window_for_event(event, daily, horizon)
                for event in events
            }
        for target in TARGETS_PCT:
            for stop in STOPS_PCT:
                for horizon in HORIZONS_HOURS:
                    outcomes = []
                    for event in events:
                        bars, reason = windows[horizon][event_key(event)]
                        result = (simulate_long(bars, target, stop)
                                  if not reason else {
                                      "available": False,
                                      "unavailable_reason": reason,
                                  })
                        result.update({
                            "symbol": event["symbol"],
                            "entry_time_ms": entry_time_ms(event),
                        })
                        outcomes.append(result)
                    key = f"tp{target:g}_sl{stop:g}_{horizon}h"
                    grid[rule][key] = summarize_outcomes(outcomes, len(events))
    return {
        "schema_version": "forward-oi-barrier-discovery-v1",
        "mode": "EXPLORATORY_NOT_OOS_NO_LIVE_SIGNAL",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "data": {
            **ingest,
            "symbols": len(panel),
            "feature_rows": len(features),
            "feature_first_utc": (
                datetime.fromtimestamp(feature_hours[0] * 3600,
                                       tz=timezone.utc).isoformat()
                if feature_hours else None),
            "feature_last_utc": (
                datetime.fromtimestamp(feature_hours[-1] * 3600,
                                       tz=timezone.utc).isoformat()
                if feature_hours else None),
            "download": download,
        },
        "method": {
            "event_rules": rule_names,
            "entry": "next exact UTC hour 5m USD-M contract kline open",
            "targets_pct": TARGETS_PCT, "stops_pct": STOPS_PCT,
            "horizons_hours": HORIZONS_HOURS,
            "round_trip_cost_bps": COST_BPS,
            "same_bar_policy": "stop_first_conservative",
            "timeout_exit": "last 5m close strictly inside horizon",
            "excursion_policy": "includes full exit bar; conservative",
            "target_time": "end of first target-touching 5m bar; upper bound",
            "source": VISION_BASE,
            "break_even_win_rate_pct_no_timeouts": {
                f"tp{target:g}_sl{stop:g}": round(
                    break_even_win_rate(target, stop), 2)
                for target in TARGETS_PCT for stop in STOPS_PCT
            },
        },
        "rules": grid,
        "limitations": [
            "Discovery data only; not train/test or OOS reliability.",
            "5m OHLC cannot reveal ordering when TP and SL occur in one bar; stop wins.",
            "Fees use a fixed 12bp round trip; slippage and funding cash flow are absent.",
            "Target hit rate alone is not edge; net expectancy and matched controls matter.",
            "No threshold is selected and no live notification is changed by this report.",
        ],
    }


def _shown(value, width: int = 7) -> str:
    return f"{'—' if value is None else value:>{width}}"


def print_report(report: dict, full: bool = False) -> None:
    data, method = report["data"], report["method"]
    dl = data["download"]
    print("FORWARD OI 5M HEDEF/STOP — KESIF, OOS DEGIL, CANLI SINYAL DEGIL")
    print(f"veri: {data['accepted']} arsiv satiri, {data['symbols']} sembol, "
          f"{data['feature_rows']} ozellik satiri")
    print(f"5m gun: {dl['requested']} istek · {dl['cached']} cache · "
          f"{dl['downloaded']} yeni · {dl['missing']} bekleyen/eksik · "
          f"{dl['errors']} hata")
    print("giris: sonraki tam saat 5m open · maliyet: 12bp · "
          "ayni 5m TP+SL: STOP once")
    stops = STOPS_PCT if full else (PRIMARY_STOP_PCT,)
    print("rule                         TP  SL   h    N eks  TPalt% TPust%  SL% "
          "timeout% ortnet% mednet% MAE%  tTPdk p<=0")
    for rule, results in report["rules"].items():
        for target in TARGETS_PCT:
            for stop in stops:
                for horizon in HORIZONS_HOURS:
                    key = f"tp{target:g}_sl{stop:g}_{horizon}h"
                    row = results[key]
                    print(f"{rule:<28} {target:>2g} {stop:>3g} {horizon:>3} "
                          f"{row['n']:>4} {row['n_unavailable']:>3} "
                          f"{_shown(row['target_first_pct_lower'], 6)} "
                          f"{_shown(row['target_first_pct_upper'], 6)} "
                          f"{_shown(row['stop_first_pct'], 5)} "
                          f"{_shown(row['timeout_pct'], 8)} "
                          f"{_shown(row['mean_net_pct'])} "
                          f"{_shown(row['median_net_pct'])} "
                          f"{_shown(row['median_mae_pct'], 5)} "
                          f"{_shown(row['median_minutes_to_target'], 6)} "
                          f"{_shown(row['bootstrap_p_mean_nonpositive'], 5)}"
                          f" {'KUCUK' if row['sample_warning'] else ''}")
    print("TPalt/TPust: ayni mum belirsizliginin muhafazakar alt/iyimser ust siniri.")
    print("KARAR: Bu tablo esik secmez. 90 gunluk kesif ve sonraki dondurulmus "
          "OOS tamamlanmadan guven orani veya canli sinyal uretilmez.")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dir", default=".", help="archive directory")
    parser.add_argument("--cache-dir", default=None,
                        help="5m ZIP cache (default: DIR/research/data/forward_oi_5m)")
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    parser.add_argument("--no-download", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--full", action="store_true",
                        help="print all stop sensitivities")
    args = parser.parse_args()
    root = Path(args.dir)
    cache = (Path(args.cache_dir) if args.cache_dir else
             root / "research" / "data" / "forward_oi_5m")
    report = analyze(root, cache, not args.no_download, args.workers, args.json)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print_report(report, args.full)


if __name__ == "__main__":
    main()
