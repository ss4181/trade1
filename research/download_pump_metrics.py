"""L1 için resmî Binance USD-M daily metrics verisini seçici indirir.

Yalnız ön-kayıtlı pump6 >= %5 görülen günler indirilir. Dosya kaynağı:
  data.binance.vision/data/futures/um/daily/metrics

Kullanım: python download_pump_metrics.py data
"""

from __future__ import annotations

import io
import json
import sys
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd
import requests

BASE = "https://data.binance.vision/data/futures/um/daily/metrics"
PUMP_RETURN = 0.05


def candidate_dates(perp_path: Path) -> list[str]:
    frame = pd.read_parquet(perp_path, columns=["open_time", "close"])
    t = pd.to_datetime(frame["open_time"], unit="ms", utc=True)
    pump = frame["close"].astype(float) / frame["close"].astype(float).shift(6) - 1
    return sorted(t.loc[pump >= PUMP_RETURN].dt.strftime("%Y-%m-%d").unique())


def fetch_day(contract: str, day: str, retries: int = 4) -> tuple[str, bytes | None]:
    url = f"{BASE}/{contract}/{contract}-metrics-{day}.zip"
    for attempt in range(retries):
        try:
            response = requests.get(url, timeout=45)
            if response.status_code == 404:
                return day, None
            response.raise_for_status()
            return day, response.content
        except requests.RequestException:
            if attempt == retries - 1:
                raise
            time.sleep(2 ** attempt)
    return day, None


def parse_zip(raw: bytes) -> pd.DataFrame:
    archive = zipfile.ZipFile(io.BytesIO(raw))
    if archive.testzip() is not None:
        raise zipfile.BadZipFile("ZIP CRC dogrulamasi basarisiz")
    with archive.open(archive.namelist()[0]) as stream:
        frame = pd.read_csv(stream)
    required = {
        "create_time", "symbol", "sum_open_interest",
        "count_long_short_ratio", "sum_taker_long_short_vol_ratio",
    }
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"metrics kolonlari eksik: {sorted(missing)}")
    return frame


def download_symbol(root: Path, symbol: str, contract: str,
                    days: list[str]) -> dict:
    output = root / "metrics_pump" / f"{symbol}.parquet"
    frames, missing, failures = [], [], {}
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(fetch_day, contract, day): day for day in days}
        for future in as_completed(futures):
            day = futures[future]
            try:
                _day, raw = future.result()
                if raw is None:
                    missing.append(day)
                else:
                    frames.append(parse_zip(raw))
            except Exception as exc:  # veri uydurulmaz; manifestte görünür
                failures[day] = f"{type(exc).__name__}: {exc}"
    if frames:
        frame = pd.concat(frames, ignore_index=True)
        frame["create_time"] = pd.to_datetime(frame["create_time"], utc=True)
        frame = frame.sort_values("create_time").drop_duplicates("create_time")
        frame.to_parquet(output, index=False)
    return {
        "symbol": symbol, "contract": contract, "requested": len(days),
        "written_rows": int(sum(len(x) for x in frames)),
        "missing_days": sorted(missing), "failures": failures,
    }


def main(data_dir: str) -> int:
    root = Path(data_dir)
    (root / "metrics_pump").mkdir(parents=True, exist_ok=True)
    spot_manifest = json.loads((root / "manifest_spot89.json").read_text(
        encoding="utf-8"))
    um_manifest = json.loads((root / "manifest_um89.json").read_text(
        encoding="utf-8"))
    mapping = um_manifest["contract_map"]
    jobs = []
    for symbol in spot_manifest["symbols"]:
        days = candidate_dates(root / "um" / f"{symbol}.parquet")
        jobs.append((symbol, mapping[symbol], days))
    total_days = sum(len(x[2]) for x in jobs)
    print(f"L1 metrics: {len(jobs)} sembol · {total_days} pump-gunu", flush=True)

    results = []
    # Her sembol kendi içinde 8 paralel istek kullanır; aynı anda yalnız 3
    # sembol çalışarak CDN'e aşırı yük bindirilmez (en çok 24 istek).
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {
            pool.submit(download_symbol, root, symbol, contract, days): symbol
            for symbol, contract, days in jobs
        }
        for done, future in enumerate(as_completed(futures), 1):
            result = future.result()
            results.append(result)
            print(f"metrics {done}/{len(jobs)}: {result['symbol']} "
                  f"{result['written_rows']} satir", flush=True)

    results.sort(key=lambda x: spot_manifest["symbols"].index(x["symbol"]))
    manifest = {
        "source": "data.binance.vision futures/um/daily/metrics",
        "pump_return_6h": PUMP_RETURN,
        "symbols": results,
    }
    (root / "manifest_metrics_pump.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    failures = sum(len(x["failures"]) for x in results)
    missing = sum(len(x["missing_days"]) for x in results)
    rows = sum(x["written_rows"] for x in results)
    print(f"bitti: {rows:,} satir · eksik-gun {missing} · hata {failures}",
          flush=True)
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else "data"))
