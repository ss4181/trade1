"""Audit a private archive and prepare retrospective G1/S2 research inputs.

No bot import, credentials, signals, parameter fitting or forward-archive writes.
Network is opt-in; only official checksum-verified Binance public ZIPs are used.
Recovered fields are NOT contemporaneously recorded observations or OOS evidence.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import re
import sys
import zipfile
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote

import requests

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from shadow_experiments import _metric_before
from research.eval_forward_oi_barriers import event_days, window_for_event
from research.eval_g1_liquidation_proxy import load_g1_events

HOUR = 3_600_000
DAY = 24 * HOUR
FIELDS = ("oi", "perp_px", "global_ls_ratio", "taker_buy_sell_ratio",
          "funding_rate_snapshot")
BASE = "https://data.binance.vision/data/futures/um/daily"
REST_BASE = "https://fapi.binance.com/fapi/v1/klines?"
SYMBOL = re.compile(r"[^\W_]{2,30}", re.UNICODE)
METRICS = ("sum_open_interest", "sum_toptrader_long_short_ratio",
           "count_long_short_ratio", "sum_taker_long_short_vol_ratio")


def finite(value):
    if isinstance(value, bool):
        return None
    try:
        n = float(value)
        return n if math.isfinite(n) else None
    except (ValueError, TypeError, OverflowError):
        return None


def timestamp(value):
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            raise ValueError("timezone_required")
        return int(dt.timestamp() * 1000)
    except (ValueError, TypeError, OverflowError):
        return None


def iso(ms):
    return datetime.fromtimestamp(ms / 1000, timezone.utc).isoformat()


def dates_between(start, end):
    return [datetime.fromtimestamp(day * 86400, timezone.utc).date().isoformat()
            for day in range(start // DAY, end // DAY + 1)]


def read_rows(root, pattern):
    for path in sorted(root.glob(pattern)):
        with path.open(encoding="utf-8") as stream:
            for line in stream:
                try:
                    row = json.loads(line)
                    yield row if isinstance(row, dict) else None
                except ValueError:
                    yield None


def audit_market(root):
    rows, bad = [], 0
    for row in read_rows(root, "market_archive_*.jsonl"):
        stamp = timestamp(row.get("t")) if row else None
        symbol = str(row.get("sym") or "") if row else ""
        if stamp is None or not SYMBOL.fullmatch(symbol):
            bad += 1
            continue
        rows.append((stamp, symbol, row))
    rows.sort(key=lambda item: (item[0], item[1]))
    start = next((t for t, _, r in rows
                  if all(finite(r.get(f)) is not None for f in FIELDS)), None)
    selected = [(t, s, r) for t, s, r in rows if start is not None and t >= start]
    hours = {t // HOUR for t, _, _ in selected}
    missing = sorted(set(range(min(hours), max(hours) + 1)) - hours) if hours else []
    by_symbol = defaultdict(set)
    missing_fields = Counter()
    full = 0
    for t, symbol, row in selected:
        by_symbol[symbol].add(t // HOUR)
        absent = [f for f in FIELDS if finite(row.get(f)) is None]
        missing_fields.update(absent)
        full += not absent
    symbol_gaps = {s: sorted(set(range(min(h), max(h) + 1)) - h)
                   for s, h in sorted(by_symbol.items())}
    return {
        "market_rows": len(rows), "symbols_all_history": len({s for _, s, _ in rows}),
        "malformed_rows": bad, "research_start_utc": iso(start) if start else None,
        "last_utc": iso(rows[-1][0]) if rows else None,
        "rows_in_research_period": len(selected), "actually_complete_rows": full,
        "missing_fields_in_period": {f: missing_fields[f] for f in FIELDS},
        "observed_hours": len(hours), "missing_hours": len(missing),
        "missing_hours_utc": [iso(h * HOUR) for h in missing],
        "symbol_gap_hours": sum(map(len, symbol_gaps.values())),
        "symbol_gap_hours_utc": {s: [iso(h * HOUR) for h in hlist]
                                 for s, hlist in symbol_gaps.items() if hlist},
        "gap_caveat": "Only between first/last observed symbol hour; NOT a historical listing/universe calendar.",
    }


def s2_events(root):
    events, seen = [], set()
    for row in read_rows(root, "shadow_events_*.jsonl"):
        if not row or row.get("kind") != "S2_DERIV_SHADOW":
            continue
        symbol = str(row.get("performance_symbol") or row.get("symbol") or "")
        value = row.get("event_time_ms")
        if not SYMBOL.fullmatch(symbol) or not isinstance(value, int) or value <= 0:
            continue
        key = (symbol, value)
        if key not in seen:
            seen.add(key)
            events.append(row)
    return sorted(events, key=lambda r: (r["event_time_ms"], r["symbol"]))


def build_plan(root):
    g1, stats = load_g1_events(root)
    # Validate contract names before any URL/path construction.
    g1 = [r for r in g1 if SYMBOL.fullmatch(r["contract"])]
    s2 = s2_events(root)
    jobs = set()
    for event in g1:
        jobs.update(("klines", event["contract"], d) for d in event_days(event, 4))
    for event in s2:
        sym = str(event.get("performance_symbol") or event["symbol"])
        stamp = event["event_time_ms"]
        jobs.update(("metrics", sym, d) for d in dates_between(stamp - 8 * HOUR - 900_000, stamp - 1))
        entry = (stamp // HOUR + 1) * HOUR
        jobs.update(("klines", sym, d) for d in dates_between(entry, entry + 72 * HOUR - 1))
    return {"schema_version": "archive-preparation-v1",
            "classification": "retrospective_input_preparation_not_oos",
            "audit": audit_market(root), "g1_events": len(g1), "s2_events": len(s2),
            "g1_read_stats": stats, "jobs": [list(j) for j in sorted(jobs)],
            "job_counts": dict(Counter(j[0] for j in jobs))}, g1, s2


def parse_zip(raw, kind, symbol, day):
    start = timestamp(day + "T00:00:00+00:00")
    rows = {}
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        members = archive.infolist()
        if (len(members) != 1 or not members[0].filename.endswith(".csv")
                or members[0].file_size > 20_000_000 or archive.testzip() is not None):
            raise ValueError("invalid_zip")
        with archive.open(members[0]) as binary:
            stream = io.TextIOWrapper(binary, encoding="utf-8-sig", newline="")
            reader = csv.DictReader(stream) if kind == "metrics" else csv.reader(stream)
            if kind == "metrics" and not set(("create_time", "symbol", *METRICS)).issubset(reader.fieldnames or []):
                raise ValueError("metrics_columns_missing")
            for row in reader:
                if kind == "metrics":
                    dt = datetime.fromisoformat(row["create_time"])
                    t = int(dt.replace(tzinfo=timezone.utc).timestamp() * 1000) if dt.tzinfo is None else int(dt.timestamp() * 1000)
                    if row["symbol"] != symbol:
                        raise ValueError("wrong_symbol")
                    item = {"timestamp": t, **{f: finite(row[f]) for f in METRICS}}
                else:
                    if row and row[0] == "open_time":
                        continue
                    if len(row) < 7 or finite(row[0]) is None:
                        raise ValueError("invalid_kline")
                    t = int(row[0])
                    vals = [finite(v) for v in row[1:5]]
                    if any(v is None or v <= 0 for v in vals):
                        raise ValueError("invalid_price")
                    o, h, low, c = vals
                    if low > min(o, c) or h < max(o, c) or low > h:
                        raise ValueError("invalid_ohlc")
                    item = dict(zip(("open", "high", "low", "close"), vals))
                    item["open_time_ms"] = t
                if not start <= t < start + DAY or t % 300_000:
                    raise ValueError("invalid_bar_time")
                if t in rows and rows[t] != item:
                    raise ValueError("conflicting_duplicate_timestamp")
                rows[t] = item
    return [rows[t] for t in sorted(rows)]


def fetch_public(url):
    # No env/proxy credentials, redirects or arbitrary hosts/URLs.
    if not (url.startswith(BASE + "/") or url.startswith(REST_BASE)):
        raise ValueError("unexpected_source")
    with requests.Session() as session:
        session.trust_env = False
        with session.get(url, timeout=(10, 30), allow_redirects=False, stream=True) as response:
            if response.status_code == 404:
                return None
            if response.status_code != 200:
                raise ValueError("official_http_error")
            data = bytearray()
            for chunk in response.iter_content(65536):
                data.extend(chunk)
                if len(data) > 5_000_000:
                    raise ValueError("download_size_limit")
            return bytes(data)


class PublicStore:
    def __init__(self, root, download=False, fetch=fetch_public):
        self.root, self.download, self.fetch = root, download, fetch

    def load(self, job):
        kind, symbol, day = job
        if kind not in {"metrics", "klines"} or not SYMBOL.fullmatch(symbol):
            raise ValueError("invalid_job")
        if datetime.strptime(day, "%Y-%m-%d").date().isoformat() != day:
            raise ValueError("invalid_day")
        suffix = "metrics" if kind == "metrics" else "5m"
        name = f"{symbol}-{suffix}-{day}.zip"
        middle = f"metrics/{symbol}" if kind == "metrics" else f"klines/{symbol}/5m"
        url = f"{BASE}/{quote(middle, safe='/')}/{quote(name, safe='')}"
        path = self.root / kind / symbol / name
        proof = path.with_suffix(".zip.CHECKSUM")
        meta = path.with_suffix(".zip.provenance.json")
        state, raw, checksum, retrieved = "missing", None, None, None
        if path.is_file() and proof.is_file() and meta.is_file():
            try:
                raw, checksum = path.read_bytes(), proof.read_bytes()
                saved = json.loads(meta.read_text(encoding="utf-8"))
                retrieved = saved["retrieved_at_utc"]
                if saved.get("url") != url or timestamp(retrieved) is None:
                    raise ValueError("invalid_provenance")
                self.verify(raw, checksum, name)
                parse_zip(raw, kind, symbol, day)
                state = "cached"
            except (OSError, ValueError, KeyError, zipfile.BadZipFile):
                raw = None
        if state != "cached":
            if not self.download:
                return {"job": list(job), "status": "missing", "rows": [], "reason": "verified_cache_missing"}
            raw = self.fetch(url)
            if raw is None:
                return {"job": list(job), "status": "missing", "rows": [], "reason": "official_file_unavailable"}
            checksum = self.fetch(url + ".CHECKSUM")
            self.verify(raw, checksum, name)
            parse_zip(raw, kind, symbol, day)
            retrieved = datetime.now(timezone.utc).isoformat()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
            proof.write_bytes(checksum)
            meta.write_text(json.dumps({"url": url, "retrieved_at_utc": retrieved}), encoding="utf-8")
            state = "downloaded"
        return {"job": list(job), "status": state, "rows": parse_zip(raw, kind, symbol, day),
                "sha256": hashlib.sha256(raw).hexdigest(), "url": url,
                "retrieved_at_utc": retrieved}

    @staticmethod
    def verify(raw, checksum, name):
        parts = checksum.decode("utf-8").split() if checksum else []
        if len(parts) != 2 or parts[1].lstrip("*") != name or parts[0].lower() != hashlib.sha256(raw).hexdigest():
            raise ValueError("official_checksum_missing_or_mismatch")


def rest_url(job):
    kind, symbol, day = job
    if kind != "klines" or not SYMBOL.fullmatch(symbol):
        raise ValueError("invalid_rest_job")
    start = timestamp(day + "T00:00:00+00:00")
    if start is None:
        raise ValueError("invalid_day")
    return (f"{REST_BASE}symbol={quote(symbol, safe='')}&interval=5m"
            f"&startTime={start}&endTime={start + DAY - 1}&limit=1000")


def parse_rest(raw, symbol, day, cutoff):
    response = json.loads(raw)
    if not isinstance(response, list):
        raise ValueError("invalid_rest_response")
    # Reuse the same strict OHLC/time/duplicate validator, in memory only.
    stream = io.StringIO()
    writer = csv.writer(stream, lineterminator="\n")
    for row in response:
        if not isinstance(row, list) or len(row) < 7:
            raise ValueError("invalid_rest_kline")
        if not isinstance(row[0], int) or not isinstance(row[6], int):
            raise ValueError("invalid_rest_timestamp")
        if row[6] != row[0] + 299_999:
            raise ValueError("invalid_rest_close_time")
        if row[6] < cutoff:
            writer.writerow(row)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("validated_rest_rows.csv", stream.getvalue())
    return parse_zip(buffer.getvalue(), "klines", symbol, day)


def rest_cached(job, root):
    url = rest_url(job)
    _, symbol, day = job
    folder = root / "rest" / symbol
    candidates = []
    for path in folder.glob(f"{day}-*.provenance.json"):
        try:
            saved = json.loads(path.read_text(encoding="utf-8"))
            digest = saved.get("sha256", "")
            cutoff = timestamp(saved.get("retrieved_at_utc"))
            if (not re.fullmatch(r"[a-f0-9]{64}", digest) or cutoff is None
                    or saved.get("url") != url or saved.get("job") != list(job)):
                continue
            raw = (folder / f"{day}-{digest}.json").read_bytes()
            if hashlib.sha256(raw).hexdigest() != digest:
                continue
            rows = parse_rest(raw, symbol, day, cutoff)
            candidates.append((cutoff, {"job": list(job), "url": url, "sha256": digest,
                                       "retrieved_at_utc": saved["retrieved_at_utc"],
                                       "integrity_source": "local_response_sha256_not_publisher_checksum",
                                       "status": "rest_cached", "rows": rows}))
        except (OSError, ValueError, TypeError, zipfile.BadZipFile):
            continue
    return max(candidates, key=lambda item: item[0])[1] if candidates else None


def rest_price_fallback(job, root, fetch=fetch_public, now=None):
    """Recent REST input, separately hashed; tomorrow's official ZIP wins."""
    url = rest_url(job)
    _, symbol, day = job
    start = timestamp(day + "T00:00:00+00:00")
    now = now or datetime.now(timezone.utc)
    cutoff = int(now.timestamp() * 1000)
    if start > cutoff or cutoff - start > 3 * DAY:
        return rest_cached(job, root) or {"job": list(job), "status": "missing", "rows": [],
                                         "reason": "rest_fallback_only_last_three_days"}
    raw = fetch(url)
    if raw is None:
        raise ValueError("rest_unavailable")
    rows = parse_rest(raw, symbol, day, cutoff)
    digest = hashlib.sha256(raw).hexdigest()
    result = {"job": list(job), "status": "rest_downloaded", "rows": rows,
              "url": url, "sha256": digest, "retrieved_at_utc": now.isoformat(),
              "integrity_source": "local_response_sha256_not_publisher_checksum"}
    folder = root / "rest" / symbol
    folder.mkdir(parents=True, exist_ok=True)
    # Content-addressed raw observations preserve subsequent revisions.
    (folder / f"{day}-{digest}.json").write_bytes(raw)
    (folder / f"{day}-{digest}.provenance.json").write_text(
        json.dumps({k: v for k, v in result.items() if k != "rows"}, sort_keys=True), encoding="utf-8")
    return result


def prepare_context(g1, s2, results):
    by_job = {tuple(r["job"]): r for r in results}
    prices = {(s, d): r["rows"] for (k, s, d), r in by_job.items() if k == "klines"}
    windows, recovered = [], []
    for event in g1 + [{"symbol": r["symbol"], "contract": r.get("performance_symbol") or r["symbol"],
                        "entry_hour": r["event_time_ms"] // HOUR + 1, "strategy": "S2"} for r in s2]:
        strategy = event.get("strategy", "G1")
        horizon = 72 if strategy == "S2" else 4
        bars, reason = window_for_event(event, prices, horizon)
        windows.append({"strategy": strategy, "symbol": event["symbol"],
                        "entry_time_utc": iso(event["entry_hour"] * HOUR),
                        "horizon_hours": horizon, "bars": len(bars),
                        "complete": reason is None, "unavailable_reason": reason})
    for event in s2:
        stamp = event["event_time_ms"]
        symbol = event.get("performance_symbol") or event["symbol"]
        rows = [row for (k, s, _), r in by_job.items() if k == "metrics" and s == symbol for row in r["rows"]]
        top, at = _metric_before(rows, stamp, "sum_toptrader_long_short_ratio")
        # Only recover the missing field; never invent prior funding timestamps.
        original_top = finite(event.get("top_position_ls_ratio"))
        oi = finite(event.get("oi_change_8h"))
        recovered.append({
            "event_id": f"S2-DERIV|{symbol}|{stamp}", "symbol": symbol,
            "event_time_ms": stamp, "classification": "retrospective_backfill_not_forward",
            "original_top_position_ls_ratio": original_top,
            "archive_top_position_ls_ratio": top, "archive_top_position_at_ms": at,
            "original_oi_change_8h": oi,
            "missing_top_recovered": original_top is None and top is not None,
            "oi_short_build_complete_after_backfill": oi is not None and top is not None,
            "unavailable_reason": None if top is not None else "no_top_position_before_event_within_15m",
            "funding": "original_observation_unchanged_not_reconstructed",
        })
    return {"s2_context": recovered, "price_windows": windows,
            "complete_price_windows": sum(w["complete"] for w in windows)}


def run(root, output, download=False, workers=4, rest_fallback=False):
    root, output = root.resolve(), output.resolve()
    if output == root or root in output.parents or output in root.parents:
        raise ValueError("output_must_be_separate_from_source_archive")
    if not root.is_dir() or not list(root.glob("market_archive_*.jsonl")):
        raise ValueError("source_market_archive_missing")
    paths = sorted(root.glob("market_archive_*.jsonl")) + sorted(root.glob("shadow_events_*.jsonl"))
    before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    plan, g1, s2 = build_plan(root)
    store = PublicStore(output / "cache", download)
    def safe_load(job):
        try:
            result = store.load(job)
            if (download and rest_fallback and job[0] == "klines"
                    and result.get("reason") == "official_file_unavailable"):
                return rest_price_fallback(job, output / "cache")
            if rest_fallback and not download and job[0] == "klines" and result["status"] == "missing":
                return rest_cached(job, output / "cache") or result
            return result
        except Exception as exc:
            return {"job": list(job), "status": "error", "rows": [], "reason": type(exc).__name__}
    with ThreadPoolExecutor(max_workers=max(1, min(workers, 6))) as pool:
        results = list(pool.map(safe_load, plan["jobs"]))
    after_paths = sorted(root.glob("market_archive_*.jsonl")) + sorted(root.glob("shadow_events_*.jsonl"))
    after = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in after_paths}
    if before != after:
        raise ValueError("source_archive_changed_rerun_on_stable_snapshot")
    report = {**plan, "generated_at_utc": datetime.now(timezone.utc).isoformat(),
              "source_sha256": before, "network_enabled": download,
              "rest_fallback_enabled": rest_fallback,
              "download_status": dict(Counter(r["status"] for r in results)),
              "provenance": [{k: v for k, v in r.items() if k != "rows"} for r in results],
              **prepare_context(g1, s2, results),
              "live_signals_changed": False, "forward_archive_changed": False,
              "oos_evaluated": False,
              "limitations": ["Input preparation, not a strategy success estimate.",
                              "Missing snapshot funding/basis/receipt times are not replaced with settled funding or daily bars.",
                              "Liquidation heatmaps and missed websocket events cannot be reconstructed here.",
                              "Backfills do not advance the forward-research clock; historical S2 TEST stays unopened."]}
    output.mkdir(parents=True, exist_ok=True)
    (output / "preparation_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dir", type=Path, required=True, help="Verified private snapshot, read-only")
    parser.add_argument("--output", type=Path, required=True, help="Separate private research directory")
    parser.add_argument("--download", action="store_true", help="Enable official public downloads")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--rest-fallback", action="store_true", help="Permit labelled REST cache; with --download fetch unpublished last-three-day prices")
    args = parser.parse_args()
    try:
        result = run(args.dir, args.output, args.download, args.workers, args.rest_fallback)
    except Exception as exc:
        print(json.dumps({"ok": False, "error_type": type(exc).__name__}))
        return 1
    print(json.dumps({"market_rows": result["audit"]["market_rows"],
                      "complete_rows": result["audit"]["actually_complete_rows"],
                      "missing_hours": result["audit"]["missing_hours"],
                      "jobs": result["job_counts"], "downloads": result["download_status"],
                      "g1_events": result["g1_events"], "s2_events": result["s2_events"],
                      "s2_top_recovered": sum(r["missing_top_recovered"] for r in result["s2_context"]),
                      "price_windows_complete": result["complete_price_windows"],
                      "oos_evaluated": False}, indent=2))
    return int(result["download_status"].get("error", 0) > 0)


if __name__ == "__main__":
    raise SystemExit(main())
