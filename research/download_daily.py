"""5+ yillik GUNLUK klines indirici (major/kokusal semboller, 2019-01'den).

API uzerinden sayfalamali (interval=1d, limit=1000; sembol basi ~3 istek).
Cikti: {OUT}/spot1d/{SYMBOL}.parquet   Kullanim: python download_daily.py <out>
"""

import sys
import time
from pathlib import Path

import pandas as pd
import requests

SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "XRPUSDT", "ADAUSDT", "DOGEUSDT",
    "LTCUSDT", "TRXUSDT", "LINKUSDT", "XLMUSDT", "ETCUSDT", "BCHUSDT",
    "ATOMUSDT", "SOLUSDT", "DOTUSDT", "AVAXUSDT", "UNIUSDT", "FILUSDT",
    "AAVEUSDT", "SANDUSDT", "NEARUSDT", "ALGOUSDT", "VETUSDT", "THETAUSDT",
]
START_MS = 1546300800000          # 2019-01-01
END_MS = 1782864000000            # 2026-07-01 (veri 2026-06-30'a kadar)
MIN_YEARS = 5.0


def fetch_daily(sym: str) -> pd.DataFrame:
    rows = []
    start = START_MS
    while start < END_MS:
        r = requests.get("https://api.binance.com/api/v3/klines",
                         params={"symbol": sym, "interval": "1d",
                                 "startTime": start, "endTime": END_MS,
                                 "limit": 1000}, timeout=30)
        r.raise_for_status()
        ks = r.json()
        if not ks:
            break
        rows += ks
        start = ks[-1][0] + 86400000
        time.sleep(0.15)
        if len(ks) < 1000:
            break
    df = pd.DataFrame([{
        "open_time": k[0], "open": float(k[1]), "high": float(k[2]),
        "low": float(k[3]), "close": float(k[4]), "volume": float(k[5]),
    } for k in rows])
    return df.drop_duplicates("open_time").sort_values("open_time")


def main(out_dir):
    out = Path(out_dir) / "spot1d"
    out.mkdir(parents=True, exist_ok=True)
    kept, dropped = [], []
    for sym in SYMBOLS:
        df = fetch_daily(sym)
        years = len(df) / 365.25
        if years < MIN_YEARS:
            dropped.append(f"{sym}({years:.1f}y)")
            continue
        df.to_parquet(out / f"{sym}.parquet", index=False)
        kept.append(sym)
        print(f"{sym}: {len(df)} gun ({years:.1f}y)", flush=True)
    print(f"\ntutulan: {len(kept)} sembol; dusen: {dropped or 'yok'}")


if __name__ == "__main__":
    main(sys.argv[1])
