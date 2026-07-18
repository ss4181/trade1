"""5 dakikalik spot klines indirici (scalping arastirmasi).

download_data.py'nin parse/fetch mantigini yeniden kullanir; ayni 30 sembol,
ayni 24 ay. Cikti: {OUT}/spot5m/{SYMBOL}.parquet
Kullanim: python download_5m.py <cikti_dizini>
"""

import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd

from download_data import BASE, MONTHS, SYMBOLS, fetch, parse_klines


def job(symbol: str, month: str):
    url = f"{BASE}/spot/monthly/klines/{symbol}/5m/{symbol}-5m-{month}.zip"
    raw = fetch(url)
    return symbol, month, (None if raw is None else parse_klines(raw))


def main(out_dir: str):
    out = Path(out_dir) / "spot5m"
    out.mkdir(parents=True, exist_ok=True)
    results: dict[str, dict[str, pd.DataFrame]] = {}
    missing = []
    jobs = [(s, m) for s in SYMBOLS for m in MONTHS]
    done = 0
    with ThreadPoolExecutor(max_workers=16) as pool:
        futs = [pool.submit(job, *j) for j in jobs]
        for fut in as_completed(futs):
            sym, month, df = fut.result()
            done += 1
            if done % 100 == 0:
                print(f"progress: {done}/{len(jobs)}", flush=True)
            if df is None:
                missing.append(f"{sym}/{month}")
            else:
                results.setdefault(sym, {})[month] = df
    for sym, months in results.items():
        df = pd.concat([months[m] for m in sorted(months)], ignore_index=True)
        df = df.sort_values("open_time").drop_duplicates("open_time")
        df.to_parquet(out / f"{sym}.parquet", index=False)
    print(f"bitti: {len(results)} sembol, eksik: {missing if missing else 'yok'}")


if __name__ == "__main__":
    main(sys.argv[1])
