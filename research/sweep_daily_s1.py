"""Kullanici onerisi: GUNLUK mumda S1 (RSI-14 oversold + bullish divergence)
+ hacim teyidi.

Onceden kayitli tasarim:
  - 1d barlar (1h'den resample), RSI(14) gunluk, divergence lookback 60 gun /
    gap 5 gun (S1 ile ayni bar-goreli mantik).
  - OS grid: {22.5, 25, 30}  (gunluk RSI 22.5 altina nadir iner)
  - Hacim teyidi varyantlari: yok | gunluk log-hacim z(30g) >= {1.0, 1.5}
  - Ufuklar (duvar-saati): 24h(1 bar), 72h(3 bar), 168h(7 bar). BIRINCIL: 72h.
  - Karar kurali: train'de N>=100 VE p<=0.05 VE edge>0 -> tek test atisi.
    ONEMLI GUC NOTU: 30 sembol x 18 ay gunluk barda olay sayisinin 100'e
    ulasmasi zor — ulasamazsa sonuc "kanit yetersiz"dir (ne kabul ne red).
Kullanim: python sweep_daily_s1.py <data_dir>
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

from common import TRAIN_END, edge_trigger
from strategies import _rolling_argmax_val, wilder_rsi

OS_GRID = [22.5, 25.0, 30.0]
VOLZ_GRID = [None, 1.0, 1.5]
H_BARS = {24: 1, 72: 3, 168: 7}
PRIMARY_H = 72


def load_daily(data_dir: Path, sym: str) -> pd.DataFrame:
    df = pd.read_parquet(data_dir / "spot" / f"{sym}.parquet")
    df["dt"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    df = df.set_index("dt").sort_index()
    d = df.resample("1D", label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last",
         "volume": "sum"}).dropna(subset=["open"])
    d["logret"] = np.log(d["close"]).diff()
    d["sigma"] = d["logret"].rolling(30, min_periods=15).std()
    lv = np.log1p(d["volume"])
    d["volz"] = (lv - lv.rolling(30, min_periods=15).mean()) / \
        lv.rolling(30, min_periods=15).std()
    entry = d["open"].shift(-1)
    for hh, hb in H_BARS.items():
        d[f"fwd_{hh}"] = np.log(d["close"].shift(-hb) / entry)
        d[f"fwdn_{hh}"] = d[f"fwd_{hh}"] / (d["sigma"] * np.sqrt(hb))
    return d


def s1d_events(d: pd.DataFrame, os_thr: float, volz_thr) -> pd.DatetimeIndex:
    rsi = wilder_rsi(d["close"]).to_numpy()
    low = d["low"].to_numpy()
    pmin, imin = _rolling_argmax_val(low, 60, 5, "min")
    rsi_at = np.where(imin >= 0, rsi[imin], np.nan)
    cond = (rsi <= os_thr) & (low < pmin) & (rsi > rsi_at)
    if volz_thr is not None:
        cond &= (d["volz"].to_numpy() >= volz_thr)
    return edge_trigger(pd.Series(cond, index=d.index), 24 * 5)  # 5 gun cooldown


def evaluate(panel, evs, hh, split, rng):
    ex, pools, counts, gross = [], [], [], []
    for sym, t in evs.items():
        d = panel[sym]
        m = t < TRAIN_END if split == "train" else t >= TRAIN_END
        t = t[m]
        if len(t) == 0:
            continue
        sub = d[d.index < TRAIN_END] if split == "train" else d[d.index >= TRAIN_END]
        x = d.reindex(t)[f"fwdn_{hh}"].dropna().to_numpy()
        g = d.reindex(t)[f"fwd_{hh}"].dropna().to_numpy()
        pool = sub[f"fwdn_{hh}"].dropna().to_numpy()
        if len(x) == 0 or len(pool) == 0:
            continue
        ex.append(x - pool.mean())
        pools.append(pool - pool.mean())
        counts.append(len(x))
        gross.append(g)
    if not ex:
        return None
    e = np.concatenate(ex)
    sims = np.empty(400)
    for i in range(400):
        tot = n = 0
        for p, c in zip(pools, counts):
            tot += rng.choice(p, c).sum()
            n += c
        sims[i] = tot / n
    g = np.concatenate(gross)
    return {"N": len(e), "edge": e.mean(),
            "p": float((sims >= e.mean()).mean()),
            "med_bp": np.median(g) * 1e4, "wr": float((g > 0).mean())}


def main(data_dir):
    data_dir = Path(data_dir)
    panel = {f.stem: load_daily(data_dir, f.stem)
             for f in sorted((data_dir / "spot").glob("*.parquet"))}
    rng = np.random.default_rng(13)
    best = None
    for os_thr in OS_GRID:
        for vz in VOLZ_GRID:
            evs = {s: s1d_events(panel[s], os_thr, vz) for s in panel}
            r = evaluate(panel, evs, PRIMARY_H, "train", rng)
            if r is None:
                print(f"OS={os_thr} volz={vz}: olay yok", flush=True)
                continue
            name = f"OS={os_thr:<4} volz={str(vz):<4}"
            print(f"{name} N={r['N']:4d} edge72={r['edge']:+.3f} p={r['p']:.3f} "
                  f"med={r['med_bp']:+7.1f}bp wr={r['wr']:.2f}", flush=True)
            if r["N"] >= 100 and r["p"] <= 0.05 and r["edge"] > 0 and \
                    (best is None or r["edge"] > best[0]):
                best = (r["edge"], os_thr, vz)
    if best is None:
        print("\nSONUC: hicbir konfig kurali gecemedi (buyuk olasilikla N<100 "
              "— gunluk barda olay az). KANIT YETERSIZ -> strateji eklenmez; "
              "test dilimine bakilmadi (gelecekte daha uzun veriyle "
              "yeniden denenebilir).")
        return
    _, os_thr, vz = best
    evs = {s: s1d_events(panel[s], os_thr, vz) for s in panel}
    for hh in (24, 72, 168):
        r = evaluate(panel, evs, hh, "test", rng)
        if r:
            print(f"TEST (OS={os_thr}, volz={vz}) h={hh}: N={r['N']} "
                  f"edge={r['edge']:+.3f} p={r['p']:.3f} "
                  f"med={r['med_bp']:+.1f}bp wr={r['wr']:.2f}", flush=True)


if __name__ == "__main__":
    main(sys.argv[1])
