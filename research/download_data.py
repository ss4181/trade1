"""Binance tarihsel veri indirici — data.binance.vision aylik zip arsivi.

Indirilenler (sembol basina):
  - spot 1h klines   -> {OUT}/spot/{SYMBOL}.parquet
  - UM perp 1h klines-> {OUT}/um/{SYMBOL}.parquet
  - UM funding rate  -> {OUT}/funding/{SYMBOL}.parquet

Eksik aylar (HTTP 404) {OUT}/manifest.json icine kaydedilir.
Kullanim: python download_data.py <cikti_dizini>
"""

import io
import json
import sys
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import pandas as pd
import requests

BASE = "https://data.binance.vision/data"

SYMBOLS = [
    # majorler
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT",
    "ADAUSDT", "TRXUSDT", "LINKUSDT", "AVAXUSDT", "LTCUSDT", "DOTUSDT",
    "BCHUSDT",
    # orta boy
    "UNIUSDT", "ATOMUSDT", "NEARUSDT", "APTUSDT", "ARBUSDT", "OPUSDT",
    "FILUSDT", "SUIUSDT", "INJUSDT", "SEIUSDT", "TIAUSDT", "AAVEUSDT",
    "ETCUSDT", "XLMUSDT", "SANDUSDT", "GALAUSDT", "PEPEUSDT",
]

MONTHS = [f"{y}-{m:02d}" for y in (2024, 2025, 2026)
          for m in range(1, 13)][6:30]  # 2024-07 .. 2026-06

KLINE_COLS = ["open_time", "open", "high", "low", "close", "volume",
              "close_time", "quote_volume", "count", "taker_buy_volume",
              "taker_buy_quote_volume", "ignore"]
KEEP_COLS = ["open_time", "open", "high", "low", "close", "volume",
             "quote_volume", "count", "taker_buy_volume"]


def fetch(url: str, retries: int = 3) -> bytes | None:
    """Zip'i indir; 404 -> None, diger hatalarda backoff'lu retry."""
    for attempt in range(retries):
        try:
            r = requests.get(url, timeout=60)
            if r.status_code == 404:
                return None
            r.raise_for_status()
            return r.content
        except Exception:
            if attempt == retries - 1:
                raise
            time.sleep(2 ** attempt)
    return None


def parse_klines(raw: bytes) -> pd.DataFrame:
    z = zipfile.ZipFile(io.BytesIO(raw))
    with z.open(z.namelist()[0]) as f:
        df = pd.read_csv(f, header=None, names=KLINE_COLS)
    # UM dosyalarinda baslik satiri var, spotta yok
    if df.iloc[0]["open_time"] == "open_time":
        df = df.iloc[1:].reset_index(drop=True)
    df = df[KEEP_COLS].astype(float)
    # spot 2025+ dosyalari mikrosaniye, digerleri milisaniye -> hepsi ms'e
    ts = df["open_time"].to_numpy(dtype="float64")
    ts = np.where(ts > 1e14, ts / 1000, ts)
    df["open_time"] = ts.astype("int64")
    return df


def parse_funding(raw: bytes) -> pd.DataFrame:
    z = zipfile.ZipFile(io.BytesIO(raw))
    with z.open(z.namelist()[0]) as f:
        df = pd.read_csv(f)
    df.columns = ["calc_time", "funding_interval_hours", "last_funding_rate"]
    return df.astype(float)


def job(kind: str, symbol: str, month: str):
    if kind == "spot":
        url = f"{BASE}/spot/monthly/klines/{symbol}/1h/{symbol}-1h-{month}.zip"
    elif kind == "um":
        url = f"{BASE}/futures/um/monthly/klines/{symbol}/1h/{symbol}-1h-{month}.zip"
    else:
        url = f"{BASE}/futures/um/monthly/fundingRate/{symbol}/{symbol}-fundingRate-{month}.zip"
    raw = fetch(url)
    if raw is None:
        return kind, symbol, month, None
    df = parse_funding(raw) if kind == "funding" else parse_klines(raw)
    return kind, symbol, month, df


def main(out_dir: str):
    out = Path(out_dir)
    for sub in ("spot", "um", "funding"):
        (out / sub).mkdir(parents=True, exist_ok=True)

    jobs = [(k, s, m) for k in ("spot", "um", "funding")
            for s in SYMBOLS for m in MONTHS]
    results: dict[tuple[str, str], dict[str, pd.DataFrame]] = {}
    missing: dict[str, list[str]] = {}
    done = 0

    with ThreadPoolExecutor(max_workers=16) as pool:
        futs = [pool.submit(job, *j) for j in jobs]
        for fut in as_completed(futs):
            kind, symbol, month, df = fut.result()
            done += 1
            if done % 200 == 0:
                print(f"progress: {done}/{len(jobs)}", flush=True)
            if df is None:
                missing.setdefault(f"{kind}/{symbol}", []).append(month)
            else:
                results.setdefault((kind, symbol), {})[month] = df

    for (kind, symbol), months in results.items():
        df = pd.concat([months[m] for m in sorted(months)], ignore_index=True)
        tcol = "open_time" if kind != "funding" else "calc_time"
        df = df.sort_values(tcol).drop_duplicates(tcol).reset_index(drop=True)
        df.to_parquet(out / kind / f"{symbol}.parquet", index=False)

    for k in missing:
        missing[k] = sorted(missing[k])
    (out / "manifest.json").write_text(json.dumps(
        {"symbols": SYMBOLS, "months": MONTHS, "missing": missing}, indent=2))
    print(f"bitti: {len(results)} seri yazildi, {len(missing)} seride eksik ay var")
    if missing:
        print(json.dumps(missing, indent=2))


if __name__ == "__main__":
    main(sys.argv[1])
