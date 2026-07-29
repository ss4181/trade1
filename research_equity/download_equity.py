"""US / CN-A / HK gunluk hisse verisi indirici (yfinance, split+temettu duzeltmeli).

Evren: US = S&P 500 uyeleri (Wikipedia), CN-A + HK = elle secilmis buyuk/likit
liste. Kapsam filtresi: >= MIN_YEARS yillik kesintisiz veri.
Cikti: <out>/{us,cn,hk}/{TICKER}.parquet + universe.json
Kullanim: python download_equity.py <cikti_dizini>
"""

import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd
import requests
import yfinance as yf

START, END = "2015-01-01", "2026-07-01"
MIN_YEARS = 8.0
MIN_DOLLAR_VOL = 3e6          # ortalama gunluk islem hacmi (yerel para)

# Cin A + HK: buyuk ve likit isimler (sektor dagilimi gozetildi)
CN_A = """600519.SS 601318.SS 600036.SS 601166.SS 600030.SS 601398.SS 601288.SS
601988.SS 600000.SS 600016.SS 601628.SS 601601.SS 600887.SS 603288.SS 600276.SS
600585.SS 600009.SS 601888.SS 600104.SS 601633.SS 600438.SS 601012.SS 600703.SS
601899.SS 600188.SS 601857.SS 600028.SS 601088.SS 600900.SS 601668.SS 601390.SS
601800.SS 600048.SS 601111.SS 600050.SS 600745.SS 603501.SS 688981.SS
000001.SZ 000002.SZ 000333.SZ 000651.SZ 000858.SZ 002415.SZ 002594.SZ 300750.SZ
000725.SZ 002304.SZ 002142.SZ 000568.SZ 002352.SZ 300059.SZ 000063.SZ 002230.SZ
300760.SZ 002027.SZ 000338.SZ 002714.SZ""".split()

HK = """0700.HK 0941.HK 0005.HK 1299.HK 0388.HK 0939.HK 1398.HK 3988.HK 2318.HK
0883.HK 0857.HK 0386.HK 0016.HK 0001.HK 0002.HK 0003.HK 0006.HK 0011.HK 0012.HK
0017.HK 0027.HK 0066.HK 0101.HK 0175.HK 0267.HK 0288.HK 0291.HK 0322.HK 0669.HK
0688.HK 0762.HK 0823.HK 0960.HK 1044.HK 1093.HK 1109.HK 1113.HK 1177.HK 1211.HK
1810.HK 1928.HK 1997.HK 2007.HK 2020.HK 2313.HK 2319.HK 2331.HK 2382.HK 2388.HK
2628.HK 3690.HK 6098.HK 9618.HK 9888.HK 9988.HK 9999.HK""".split()


def us_universe(limit=250):
    """S&P 500 uyeleri (Wikipedia). Survivorship serhi ONKAYIT.md'de.
    NOT: Wikipedia User-Agent'siz istekte 403 doner — basligi gondermek sart
    (ilk kosuda bu yuzden 50'lik yedek listeye dusup guc kaybedilmisti)."""
    try:
        import io
        r = requests.get(
            "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
            headers={"User-Agent": "Mozilla/5.0 (equity-research)"}, timeout=30)
        r.raise_for_status()
        tables = pd.read_html(io.StringIO(r.text))
        syms = [str(s).replace(".", "-") for s in tables[0]["Symbol"]]
        print(f"S&P listesi: {len(syms)} sembol (ilk {limit} kullanilacak)",
              flush=True)
        return syms[:limit]
    except Exception as e:
        print(f"uyari: S&P listesi alinamadi ({e}); yedek listeye dusuluyor",
              flush=True)
        return ("AAPL MSFT NVDA AMZN GOOGL META TSLA BRK-B JPM V UNH XOM JNJ WMT "
                "MA PG HD CVX ABBV KO PEP COST MRK AVGO ADBE CSCO ACN MCD TMO "
                "ABT CRM NFLX AMD LIN NKE DHR TXN PM ORCL WFC UPS MS INTC BMY "
                "RTX QCOM HON UNP CAT GS").split()


def fetch(ticker):
    for attempt in range(3):
        try:
            df = yf.download(ticker, start=START, end=END, interval="1d",
                             auto_adjust=True, progress=False, threads=False)
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            if df is None or df.empty:
                return ticker, None
            df = df.rename(columns=str.lower)[
                ["open", "high", "low", "close", "volume"]].dropna()
            return ticker, df
        except Exception:
            time.sleep(1 + attempt)
    return ticker, None


def main(out_dir):
    out = Path(out_dir)
    groups = {"us": us_universe(), "cn": CN_A, "hk": HK}
    kept = {}
    for market, tickers in groups.items():
        (out / market).mkdir(parents=True, exist_ok=True)
        good = []
        with ThreadPoolExecutor(max_workers=8) as pool:
            futs = [pool.submit(fetch, t) for t in tickers]
            for f in as_completed(futs):
                t, df = f.result()
                if df is None or len(df) / 252 < MIN_YEARS:
                    continue
                if (df["close"] * df["volume"]).mean() < MIN_DOLLAR_VOL:
                    continue
                df.to_parquet(out / market / f"{t}.parquet")
                good.append(t)
        kept[market] = sorted(good)
        print(f"{market}: {len(good)}/{len(tickers)} sembol tutuldu", flush=True)
    (out / "universe.json").write_text(json.dumps(kept, indent=1))
    print("bitti ->", out / "universe.json")


if __name__ == "__main__":
    main(sys.argv[1])
