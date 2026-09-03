"""S2-LS-v1 olay günlerinin resmî Binance USD-M metrics verisini indirir."""

from __future__ import annotations

import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd

try:
    from .download_pump_metrics import fetch_day, parse_zip
    from .s2_long_short_common import (build_events, load_core_symbols,
                                       load_funding, required_metric_days)
except ImportError:  # pragma: no cover - doğrudan script çalıştırma yolu
    from download_pump_metrics import fetch_day, parse_zip
    from s2_long_short_common import (build_events, load_core_symbols,
                                      load_funding, required_metric_days)


def seed_frame(root: Path, symbol: str, wanted: set[str]) -> pd.DataFrame:
    frames = []
    for folder in ("metrics_s2", "metrics_gainer", "metrics_pump"):
        path = root / folder / f"{symbol}.parquet"
        if not path.exists():
            continue
        frame = pd.read_parquet(path)
        stamp = pd.to_datetime(frame["create_time"], utc=True)
        chosen = frame.loc[stamp.dt.strftime("%Y-%m-%d").isin(wanted)]
        if not chosen.empty:
            frames.append(chosen)
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True).drop_duplicates(
        "create_time", keep="last")


def download_symbol(root: Path, symbol: str, contract: str,
                    days: list[str]) -> dict:
    wanted = set(days)
    seed = seed_frame(root, symbol, wanted)
    covered = (set(pd.to_datetime(seed["create_time"], utc=True).dt.strftime(
        "%Y-%m-%d")) if not seed.empty else set())
    jobs = sorted(wanted - covered)
    frames = [seed] if not seed.empty else []
    missing, failures = [], {}
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = {pool.submit(fetch_day, contract, day): day for day in jobs}
        for future in as_completed(futures):
            day = futures[future]
            try:
                _day, raw = future.result()
                if raw is None:
                    missing.append(day)
                else:
                    frames.append(parse_zip(raw))
            except Exception as exc:  # eksik veri manifestte görünür
                failures[day] = f"{type(exc).__name__}: {exc}"
    output = root / "metrics_s2" / f"{symbol}.parquet"
    rows = 0
    if frames:
        frame = pd.concat(frames, ignore_index=True)
        frame["create_time"] = pd.to_datetime(frame["create_time"], utc=True)
        frame = frame.sort_values("create_time").drop_duplicates(
            "create_time", keep="last")
        rows = len(frame)
        frame.to_parquet(output, index=False)
    return {
        "symbol": symbol, "contract": contract, "requested_days": len(days),
        "seed_days": len(covered), "download_jobs": len(jobs),
        "written_rows": rows, "missing_days": sorted(missing),
        "failures": failures,
    }


def main(data_dir: str) -> int:
    root = Path(data_dir)
    output = root / "metrics_s2"
    output.mkdir(parents=True, exist_ok=True)
    symbols = load_core_symbols(root)
    funding = load_funding(Path(__file__).parent / "funding_cache" /
                           "funding_history.json", symbols)
    events = build_events(funding)
    wanted = required_metric_days(events)
    mapping = json.loads((root / "manifest_um89.json").read_text(
        encoding="utf-8"))["contract_map"]
    print(f"S2-LS-v1: {len(events)} olay · "
          f"{sum(map(len, wanted.values()))} sembol-günü (bağlam dahil)",
          flush=True)
    results = []
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {
            pool.submit(download_symbol, root, symbol, mapping[symbol],
                        wanted.get(symbol, [])): symbol
            for symbol in symbols
        }
        for done, future in enumerate(as_completed(futures), 1):
            result = future.result()
            results.append(result)
            print(f"metrics {done}/{len(symbols)}: {result['symbol']} "
                  f"{result['written_rows']:,} satır", flush=True)
    order = {symbol: i for i, symbol in enumerate(symbols)}
    results.sort(key=lambda row: order[row["symbol"]])
    manifest = {
        "study_id": "S2-LS-v1",
        "source": "data.binance.vision futures/um/daily/metrics",
        "event_count": len(events), "symbols": results,
    }
    (root / "manifest_metrics_s2.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    failures = sum(len(row["failures"]) for row in results)
    missing = sum(len(row["missing_days"]) for row in results)
    print(f"bitti: eksik-gün {missing} · hata {failures}", flush=True)
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else "data"))
