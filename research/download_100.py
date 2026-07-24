"""100-coin genisletilmis evren indirici (Ek G calismasi).

Adaylar: bugun aktif spot+perp cifti olan, perp hacmine gore top ~150 coin
(stable/pegli haric). On-eleme: 2024-07 spot ayi var mi? Sonra tam indirme;
HERHANGI bir ayi eksik olan sembol DUSULUR (tam 24 ay sart — boylece genc
memecoinler otomatik elenir). Ilk 100 (perp hacim sirali) tutulur.
Cikti: <out>/spot|um|funding/*.parquet + universe.json (hacim siralari).
Kullanim: python download_100.py <out_dir>
"""

import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd
import requests

from download_data import MONTHS, fetch, job

STABLE_OR_PEGGED = {
    "USDC", "FDUSD", "TUSD", "DAI", "USDP", "PYUSD", "BUSD", "AEUR", "EUR",
    "EURI", "USDE", "USD1", "BFUSD", "XUSD", "USDF", "PAXG", "XAUT",
    "WBTC", "WBETH",
}


def candidates(top_n=150, min_perp_vol=2e6):
    fut = requests.get("https://fapi.binance.com/fapi/v1/exchangeInfo",
                       timeout=30).json()
    perps = {s["symbol"] for s in fut["symbols"]
             if s.get("contractType") == "PERPETUAL"
             and s.get("status") == "TRADING" and s.get("quoteAsset") == "USDT"}
    pv = {}
    for t in requests.get("https://fapi.binance.com/fapi/v1/ticker/24hr",
                          timeout=30).json():
        try:
            pv[t["symbol"]] = float(t.get("quoteVolume") or 0)
        except (TypeError, ValueError):
            pass
    spot = requests.get("https://api.binance.com/api/v3/exchangeInfo",
                        timeout=60).json()
    rows = []
    for s in spot["symbols"]:
        sym = s["symbol"]
        if s.get("status") != "TRADING" or s.get("quoteAsset") != "USDT":
            continue
        if s.get("baseAsset") in STABLE_OR_PEGGED:
            continue
        perp = sym if sym in perps else (
            "1000" + sym if "1000" + sym in perps else None)
        if perp and pv.get(perp, 0) >= min_perp_vol:
            rows.append((pv[perp], sym, perp))
    rows.sort(reverse=True)
    return rows[:top_n]


def main(out_dir):
    out = Path(out_dir)
    for sub in ("spot", "um", "funding"):
        (out / sub).mkdir(parents=True, exist_ok=True)
    cand = candidates()
    print(f"aday: {len(cand)} sembol; on-eleme (2024-07 spot var mi?)...",
          flush=True)
    ok = []
    with ThreadPoolExecutor(max_workers=16) as pool:
        futs = {pool.submit(
            fetch, f"https://data.binance.vision/data/spot/monthly/klines/"
                   f"{sym}/1h/{sym}-1h-2024-07.zip"): (v, sym, perp)
            for v, sym, perp in cand}
        for f in as_completed(futs):
            if f.result() is not None:
                ok.append(futs[f])
    ok.sort(reverse=True)
    print(f"on-elemeyi gecen: {len(ok)}; tam indirme basliyor...", flush=True)

    def dl_kind(kind, name, month):
        return job(kind, name, month)

    results, bad = {}, set()
    jobs = []
    for v, sym, perp in ok:
        for m in MONTHS:
            jobs.append(("spot", sym, m, sym))
            jobs.append(("um", perp, m, sym))
            jobs.append(("funding", perp, m, sym))
    done = 0
    with ThreadPoolExecutor(max_workers=16) as pool:
        futs = {pool.submit(job, k, n, m): (k, n, m, base)
                for k, n, m, base in jobs}
        for f in as_completed(futs):
            k, n, m, base = futs[f]
            done += 1
            if done % 1000 == 0:
                print(f"progress: {done}/{len(jobs)}", flush=True)
            _, _, _, df = f.result()
            if df is None:
                bad.add(base)
            else:
                results.setdefault((k, n, base), {})[m] = df
    kept = []
    for v, sym, perp in ok:
        if sym in bad:
            continue
        kept.append((v, sym, perp))
        if len(kept) >= 100:
            break
    keep_syms = {s for _, s, _ in kept}
    for (kind, name, base), months in results.items():
        if base not in keep_syms or len(months) < len(MONTHS):
            continue
        df = pd.concat([months[m] for m in sorted(months)], ignore_index=True)
        tcol = "open_time" if kind != "funding" else "calc_time"
        df = df.sort_values(tcol).drop_duplicates(tcol)
        df.to_parquet(out / kind / f"{name}.parquet", index=False)
    (out / "universe.json").write_text(json.dumps(
        [{"rank": i + 1, "symbol": s, "perp": p, "perp_vol": v}
         for i, (v, s, p) in enumerate(kept)], indent=1))
    print(f"bitti: {len(kept)} sembol tam 24 ayla tutuldu "
          f"(eksikli dusen: {len(bad)})", flush=True)


if __name__ == "__main__":
    main(sys.argv[1])
