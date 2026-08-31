"""G1 için resmî Binance USD-M daily metrics verisini seçici indirir.

Yalnız aynı saat içinde sabit 89 evrende 24h getirisi >=%5 ve ilk 10'da olan
sembollerin UTC günleri ile 00:00 OI değişimi için gereken bir önceki bağlam
günü indirilir. Önceden indirilmiş metrics günleri yeniden kullanılır. Kaynak:
  data.binance.vision/data/futures/um/daily/metrics

Kullanım: python download_gainer_metrics.py data
"""

from __future__ import annotations

import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd

from download_pump_metrics import fetch_day, parse_zip

RETURN_MIN = 0.05
TOP_N = 10


def candidate_days(root: Path, symbols: list[str]) -> dict[str, list[str]]:
    closes = {}
    for symbol in symbols:
        frame = pd.read_parquet(root / "um" / f"{symbol}.parquet",
                                columns=["open_time", "close"])
        idx = pd.to_datetime(frame["open_time"], unit="ms", utc=True)
        closes[symbol] = pd.Series(frame["close"].astype(float).to_numpy(),
                                   index=idx)
    close = pd.DataFrame(closes).sort_index()
    ret24 = close / close.shift(24) - 1
    rank = ret24.rank(axis=1, ascending=False, method="min")
    eligible = (ret24 >= RETURN_MIN) & (rank <= TOP_N)
    return {
        symbol: sorted(eligible.index[eligible[symbol]].strftime(
            "%Y-%m-%d").unique())
        for symbol in symbols
    }


def _seed_frame(root: Path, symbol: str, wanted: set[str]) -> pd.DataFrame:
    if not wanted:
        return pd.DataFrame()
    frames = []
    for folder in ("metrics_gainer", "metrics_pump"):
        path = root / folder / f"{symbol}.parquet"
        if not path.exists():
            continue
        frame = pd.read_parquet(path)
        stamp = pd.to_datetime(frame["create_time"], utc=True)
        frames.append(frame.loc[stamp.dt.strftime("%Y-%m-%d").isin(wanted)])
    return pd.concat(frames, ignore_index=True).drop_duplicates(
        "create_time") if frames else pd.DataFrame()


def download_symbol(root: Path, symbol: str, contract: str,
                    candidate: list[str], days: list[str]) -> dict:
    wanted = set(days)
    seed = _seed_frame(root, symbol, wanted)
    covered = set()
    if not seed.empty:
        covered = set(pd.to_datetime(seed["create_time"], utc=True).dt.strftime(
            "%Y-%m-%d").unique())
    missing_jobs = sorted(wanted - covered)
    frames = [seed] if not seed.empty else []
    absent, failures = [], {}
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(fetch_day, contract, day): day
                   for day in missing_jobs}
        for future in as_completed(futures):
            day = futures[future]
            try:
                _day, raw = future.result()
                if raw is None:
                    absent.append(day)
                else:
                    frames.append(parse_zip(raw))
            except Exception as exc:
                failures[day] = f"{type(exc).__name__}: {exc}"
    output = root / "metrics_gainer" / f"{symbol}.parquet"
    rows = 0
    if frames:
        frame = pd.concat(frames, ignore_index=True)
        frame["create_time"] = pd.to_datetime(frame["create_time"], utc=True)
        frame = frame.sort_values("create_time").drop_duplicates("create_time")
        rows = len(frame)
        frame.to_parquet(output, index=False)
    return {
        "symbol": symbol, "contract": contract,
        "candidate_days": len(candidate), "requested_with_context": len(days),
        "seed_days": len(covered), "downloaded_days": len(missing_jobs) -
        len(absent) - len(failures), "written_rows": rows,
        "missing_days": sorted(absent), "failures": failures,
    }


def main(data_dir: str) -> int:
    root = Path(data_dir)
    (root / "metrics_gainer").mkdir(parents=True, exist_ok=True)
    spot_manifest = json.loads((root / "manifest_spot89.json").read_text(
        encoding="utf-8"))
    um_manifest = json.loads((root / "manifest_um89.json").read_text(
        encoding="utf-8"))
    symbols = spot_manifest["symbols"]
    mapping = um_manifest["contract_map"]
    wanted = candidate_days(root, symbols)
    requested = {
        symbol: sorted(set(days) | {
            (pd.Timestamp(day) - pd.Timedelta(days=1)).strftime("%Y-%m-%d")
            for day in days
        })
        for symbol, days in wanted.items()
    }
    print(f"G1 metrics: {len(symbols)} sembol · "
          f"{sum(map(len, wanted.values())):,} aday sembol-gunu · "
          f"{sum(map(len, requested.values())):,} baglam dahil", flush=True)

    results = []
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {
            pool.submit(download_symbol, root, symbol, mapping[symbol],
                        wanted[symbol], requested[symbol]): symbol
            for symbol in symbols
        }
        for done, future in enumerate(as_completed(futures), 1):
            result = future.result()
            results.append(result)
            print(f"metrics {done}/{len(symbols)}: {result['symbol']} "
                  f"{result['written_rows']:,} satir", flush=True)
    order = {symbol: i for i, symbol in enumerate(symbols)}
    results.sort(key=lambda row: order[row["symbol"]])
    manifest = {
        "source": "data.binance.vision futures/um/daily/metrics",
        "return_24h_min": RETURN_MIN, "cross_section_top_n": TOP_N,
        "symbols": results,
    }
    (root / "manifest_metrics_gainer.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    failures = sum(len(row["failures"]) for row in results)
    missing = sum(len(row["missing_days"]) for row in results)
    rows = sum(row["written_rows"] for row in results)
    print(f"bitti: {rows:,} satir · eksik-gun {missing} · hata {failures}",
          flush=True)
    return 0 if failures == 0 and missing == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else "data"))
