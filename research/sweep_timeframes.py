"""Zaman dilimi cesitlendirme taramasi: S1 ve S3'u 15m/30m/1h/2h/4h mumlarda
ayni olay-calismasi protokoluyle degerlendirir.

Adalet icin: ufuklar duvar-saati (S1: 24h, S3: 4h), cooldown duvar-saati 12h,
z penceresi duvar-saati 7 gun, divergence lookback/gap BAR cinsinden (60/5 —
gostergenin dogasi bar-goreli). Secim yalnizca train'de; en iyi TF+esik
kombinasyonu test'te tek atis (strateji basina 1).
Kullanim: python sweep_timeframes.py <data_dir>
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

from common import TRAIN_END, edge_trigger
from strategies import _rolling_argmax_val, wilder_rsi

TFS = {"15m": 0.25, "30m": 0.5, "1h": 1.0, "2h": 2.0, "4h": 4.0}
S1_GRID = [17.5, 20.0, 22.5, 25.0]
S3_GRID = [2.5, 3.0, 3.5]
S1_H_HOURS, S3_H_HOURS = 24, 4
COOLDOWN_H = 12
VOLWIN_H = 168


def load_raw(data_dir: Path, tf: str, sym: str) -> pd.DataFrame:
    """Ham OHLCV'yi hedef TF'e getirir (5m'den veya 1h'den resample)."""
    src = "spot5m" if TFS[tf] < 1 else "spot"
    df = pd.read_parquet(data_dir / src / f"{sym}.parquet")
    df["dt"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    df = df.set_index("dt").sort_index()
    base_tf = "5min" if src == "spot5m" else "1h"
    rule = {"15m": "15min", "30m": "30min", "1h": "1h", "2h": "2h", "4h": "4h"}[tf]
    if rule != base_tf:
        df = df.resample(rule, label="left", closed="left").agg(
            {"open": "first", "high": "max", "low": "min", "close": "last",
             "volume": "sum"}).dropna(subset=["open"])
    return df[["open", "high", "low", "close", "volume"]]


def enrich(df: pd.DataFrame, tf: str, h_hours_list) -> pd.DataFrame:
    tf_h = TFS[tf]
    c, o, v = df["close"], df["open"], df["volume"]
    df = df.copy()
    df["logret"] = np.log(c).diff()
    volwin = max(int(VOLWIN_H / tf_h), 20)
    df["sigma"] = df["logret"].rolling(volwin, min_periods=volwin // 2).std()
    lv = np.log1p(v)
    mu = lv.rolling(volwin, min_periods=volwin // 2).mean()
    sd = lv.rolling(volwin, min_periods=volwin // 2).std()
    df["volz"] = (lv - mu) / sd
    entry = o.shift(-1)
    for hh in h_hours_list:
        hb = max(int(round(hh / tf_h)), 1)
        df[f"fwd_{hh}"] = np.log(c.shift(-hb) / entry)
        df[f"fwdn_{hh}"] = df[f"fwd_{hh}"] / (df["sigma"] * np.sqrt(hb))
    return df


def s1_ev(df, tf, os_thr):
    rsi = wilder_rsi(df["close"]).to_numpy()
    low = df["low"].to_numpy()
    pmin, imin = _rolling_argmax_val(low, 60, 5, "min")
    rsi_at = np.where(imin >= 0, rsi[imin], np.nan)
    cond = (rsi <= os_thr) & (low < pmin) & (rsi > rsi_at)
    return edge_trigger(pd.Series(cond, index=df.index), COOLDOWN_H)


def s3_ev(df, tf, z_thr):
    spike = pd.Series((df["volz"] >= z_thr).to_numpy(), index=df.index)
    t = edge_trigger(spike, COOLDOWN_H)
    up = (df["close"] > df["open"]).reindex(t).fillna(False).to_numpy(bool)
    return t[up]


def evaluate(panel_ev, panel_df, hh, split, rng):
    """Sembol-eslesmeli edge (fwdn) + bootstrap p + ozet."""
    sig_all, base_pools, counts = [], [], []
    gross = []
    for sym, times in panel_ev.items():
        df = panel_df[sym]
        m = times < TRAIN_END if split == "train" else times >= TRAIN_END
        times = times[m]
        if len(times) == 0:
            continue
        sub = df[df.index < TRAIN_END] if split == "train" else df[df.index >= TRAIN_END]
        sel = df.reindex(times)
        x = sel[f"fwdn_{hh}"].dropna().to_numpy()
        g = sel[f"fwd_{hh}"].dropna().to_numpy()
        pool = sub[f"fwdn_{hh}"].dropna().to_numpy()
        if len(x) == 0 or len(pool) == 0:
            continue
        sig_all.append(x - pool.mean())
        gross.append(g)
        base_pools.append(pool - pool.mean())
        counts.append(len(x))
    if not sig_all:
        return None
    excess = np.concatenate(sig_all)
    actual = excess.mean()
    sims = np.empty(400)
    for i in range(400):
        tot = n = 0
        for pool, cnt in zip(base_pools, counts):
            tot += rng.choice(pool, cnt).sum()
            n += cnt
        sims[i] = tot / n
    g = np.concatenate(gross)
    return {"N": len(excess), "edge": actual,
            "p": float((sims >= actual).mean()),
            "gross_bp": g.mean() * 1e4, "med_bp": np.median(g) * 1e4,
            "wr": float((g > 0).mean())}


def main(data_dir):
    data_dir = Path(data_dir)
    syms = sorted(p.stem for p in (data_dir / "spot5m").glob("*.parquet"))
    rng = np.random.default_rng(3)
    best = {}
    for tf in TFS:
        panel = {}
        for sym in syms:
            panel[sym] = enrich(load_raw(data_dir, tf, sym), tf,
                                [S1_H_HOURS, S3_H_HOURS])
        for strat, grid, hh, evfn in (("S1", S1_GRID, S1_H_HOURS, s1_ev),
                                      ("S3", S3_GRID, S3_H_HOURS, s3_ev)):
            for thr in grid:
                evs = {s: evfn(panel[s], tf, thr) for s in syms}
                r = evaluate(evs, panel, hh, "train", rng)
                if r is None:
                    continue
                print(f"{strat} {tf:>3} thr={thr:<5} N={r['N']:5d} "
                      f"edge={r['edge']:+.3f} p={r['p']:.3f} "
                      f"med={r['med_bp']:+6.1f}bp wr={r['wr']:.2f}", flush=True)
                key = (strat,)
                cand = (r["edge"], tf, thr, r)
                if r["N"] >= 100 and r["p"] <= 0.05 and \
                        (key not in best or cand[0] > best[key][0]):
                    best[key] = cand
        del panel
    print("\n==== TRAIN kazananlari -> TEST (tek atis) ====", flush=True)
    for (strat,), (edge, tf, thr, _) in best.items():
        panel = {s: enrich(load_raw(data_dir, tf, s), tf,
                           [S1_H_HOURS, S3_H_HOURS]) for s in syms}
        hh = S1_H_HOURS if strat == "S1" else S3_H_HOURS
        evfn = s1_ev if strat == "S1" else s3_ev
        evs = {s: evfn(panel[s], tf, thr) for s in syms}
        r = evaluate(evs, panel, hh, "test", rng)
        print(f"{strat}: train-kazanan TF={tf} thr={thr} (train edge {edge:+.3f}) "
              f"-> TEST: N={r['N']} edge={r['edge']:+.3f} p={r['p']:.3f} "
              f"med={r['med_bp']:+.1f}bp wr={r['wr']:.2f}", flush=True)
        del panel


if __name__ == "__main__":
    main(sys.argv[1])
