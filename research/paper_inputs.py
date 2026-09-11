"""Read-only paper input preparation. No bot import, downloads or state writes.

A manifest binds declared source and observed file coverage to exact bytes.
It does not authenticate the exchange or prove historical universe membership.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from notification_delivery import _validate_events

M = 300_000
MANIFEST_VERSION = "paper-candles-manifest-v1"
SOURCES = ("binance_spot_klines", "binance_um_klines", "mixed_binance_klines", "synthetic")
SIGNAL_FIELDS = ("event_id", "strategy", "symbol", "direction", "performance_market",
                 "performance_symbol", "bar_time", "horizon_hours", "universe",
                 "config_version", "engine_version", "engine_config_hash")


def stamp_ms(value):
    stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if stamp.tzinfo is None:
        raise ValueError("timezone_required")
    return int(stamp.astimezone(timezone.utc).timestamp() * 1000)


def file_sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_outbox_records(path, *, as_of_ms):
    """Keep first confirmed delivery; never copy recipient IDs or raw messages."""
    raw = Path(path).read_bytes()
    try:
        items = _validate_events(json.loads(raw))
        rows = []
        counts = dict(events=len(items), confirmed_at_cutoff=0,
                      delivered_after_cutoff=0, unconfirmed=0,
                      sha256=hashlib.sha256(raw).hexdigest())
        for item in items.values():
            times = [stamp_ms(r["delivered_at"]) for r in item["recipients"].values()
                     if r["status"] == "delivered"]
            if not times:
                counts["unconfirmed"] += 1
                continue
            first = stamp_ms(item["first_delivered_at"])
            if first != min(times) or first < stamp_ms(item["created_at"]):
                raise ValueError("invalid_delivery_snapshot")
            if first > as_of_ms:
                counts["delivered_after_cutoff"] += 1
                continue
            row = {k: item["record"][k] for k in SIGNAL_FIELDS if k in item["record"]}
            row.update(delivery_confirmed=True, delivered_at=item["first_delivered_at"])
            rows.append(row)
            counts["confirmed_at_cutoff"] += 1
    except (KeyError, TypeError, ValueError, OverflowError):
        raise ValueError("invalid_delivery_snapshot") from None
    return rows, counts


def candle_inventory(raw):
    groups = defaultdict(list)
    try:
        for line in raw.decode("utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if not isinstance(row, dict) or row.get("market") not in ("spot", "um_perp"):
                raise ValueError()
            symbol, stamp = row.get("symbol"), row.get("open_time")
            if not isinstance(symbol, str) or not re.fullmatch(r"\w+USDT", symbol):
                raise ValueError()
            if type(stamp) is not int or stamp < 0 or stamp % M:
                raise ValueError()
            o, h, l, c = (float(row[k]) for k in ("open", "high", "low", "close"))
            if not all(math.isfinite(v) and v > 0 for v in (o, h, l, c)) or not l <= min(o, c) <= max(o, c) <= h:
                raise ValueError()
            groups[row["market"], symbol].append((stamp, o, h, l, c))
    except (UnicodeError, KeyError, TypeError, ValueError, OverflowError):
        raise ValueError("invalid_candles_for_manifest") from None
    result = []
    for (market, symbol), rows in sorted(groups.items()):
        unique = set(rows)
        times = {r[0] for r in rows}
        if len(unique) != len(times):
            raise ValueError("conflicting_candles_for_manifest")
        first, last = min(times), max(times)
        result.append(dict(market=market, symbol=symbol, rows=len(rows),
                           unique_bars=len(times), duplicate_rows=len(rows)-len(times),
                           first_open_ms=first, last_open_ms=last,
                           missing_bars=(last-first)//M+1-len(times)))
    return result


def build_candle_manifest(path, *, source, captured_at):
    if source not in SOURCES:
        raise ValueError("unsupported_declared_source")
    captured = stamp_ms(captured_at)
    raw = Path(path).read_bytes()
    series = candle_inventory(raw)
    if captured < 0 or any(s["last_open_ms"] + M > captured for s in series):
        raise ValueError("manifest_contains_unclosed_candles")
    expected_market = {"binance_spot_klines": "spot", "binance_um_klines": "um_perp"}.get(source)
    if expected_market and any(s["market"] != expected_market for s in series):
        raise ValueError("manifest_source_market_mismatch")
    return dict(schema_version=MANIFEST_VERSION, interval="5m", source=source,
                captured_at_ms=captured, sha256=hashlib.sha256(raw).hexdigest(), series=series)


def verify_candle_manifest(manifest_path, candle_path):
    try:
        manifest = json.loads(Path(manifest_path).read_bytes())
        if not isinstance(manifest, dict) or manifest.get("schema_version") != MANIFEST_VERSION:
            raise ValueError()
        captured = manifest["captured_at_ms"]
        if type(captured) is not int:
            raise ValueError()
        expected = build_candle_manifest(candle_path, source=manifest["source"],
            captured_at=datetime.fromtimestamp(captured/1000, tz=timezone.utc).isoformat())
        if any(manifest.get(k) != v for k, v in expected.items()):
            raise ValueError()
    except (KeyError, TypeError, ValueError, OverflowError, OSError):
        raise ValueError("candle_manifest_mismatch") from None
    return {**expected, "status": "checksum_and_inventory_verified"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candles-jsonl", type=Path, required=True)
    parser.add_argument("--source", choices=SOURCES, required=True)
    parser.add_argument("--captured-at", required=True, help="Timezone-aware capture cutoff")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.resolve() == args.candles_jsonl.resolve():
        parser.error("output_must_not_overwrite_inputs")
    manifest = build_candle_manifest(args.candles_jsonl, source=args.source, captured_at=args.captured_at)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(manifest, indent=2, allow_nan=False)+"\n", encoding="utf-8")
    print("Manifest written; source is declared, checksum and file inventory recorded.")


if __name__ == "__main__":
    main()
