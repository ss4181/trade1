"""Gemini onerisi: Volatility Squeeze Breakout (BB icinde KC + hacimli kirilim).

Tanim (onceden kayitli):
  Squeeze: BB(20, 2sigma) bantlari KC(20, 1.5xATR20) icine girer ve en az L bar
  surer. Kirilim: squeeze aktifken kapanis ONCEKI barin ust BB'sinin ustune
  cikar VE log-hacim z(168) >= zc -> LONG. Cooldown 24h. Sadece long (short
  taraf bu evrende olu — S1 bear / S3 down kanitlari).
Grid: L in {4, 8, 12}, zc in {1.5, 2.0}. Ufuklar 4/12/24/48h.
Karar: train'de edge_voln24 maks, N>=100, p<=0.05 -> TEK test atisi.
Sizinti onlemi: bantlar/squeeze onceki bar degerleriyle (shift 1) test edilir.
Kullanim: python sweep_squeeze.py <data_dir>
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

from common import TRAIN_END, edge_trigger

H_LIST = [4, 12, 24, 48]


def atr_wilder(df, n=20):
    h, l, c = df["high"], df["low"], df["close"]
    tr = pd.concat([h - l, (h - c.shift(1)).abs(), (l - c.shift(1)).abs()],
                   axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()


def build(df):
    c, v = df["close"], df["volume"]
    out = df.copy()
    out["logret"] = np.log(c).diff()
    out["sigma"] = out["logret"].rolling(168, min_periods=100).std()
    lv = np.log1p(v)
    out["volz"] = (lv - lv.rolling(168, min_periods=84).mean()) / \
        lv.rolling(168, min_periods=84).std()
    sma, sd = c.rolling(20).mean(), c.rolling(20).std()
    bb_u, bb_l = sma + 2 * sd, sma - 2 * sd
    ema20 = c.ewm(span=20, adjust=False, min_periods=20).mean()
    atr = atr_wilder(df, 20)
    kc_u, kc_l = ema20 + 1.5 * atr, ema20 - 1.5 * atr
    out["squeeze"] = (bb_u < kc_u) & (bb_l > kc_l)
    out["bb_u_prev"] = bb_u.shift(1)
    entry = df["open"].shift(-1)
    for h in H_LIST:
        out[f"fwd_{h}"] = np.log(c.shift(-h) / entry)
        out[f"fwdn_{h}"] = out[f"fwd_{h}"] / (out["sigma"] * np.sqrt(h))
    return out


def events(df, L, zc):
    sq_run = df["squeeze"].shift(1).rolling(L).sum() >= L   # onceki L bar squeeze
    cond = sq_run & (df["close"] > df["bb_u_prev"]) & (df["volz"] >= zc)
    return edge_trigger(cond.fillna(False), 24)


def evaluate(panel, evs, h, split, rng):
    ex, pools, counts, gross = [], [], [], []
    for sym, t in evs.items():
        df = panel[sym]
        m = t < TRAIN_END if split == "train" else t >= TRAIN_END
        t = t[m]
        if len(t) == 0:
            continue
        sub = df[df.index < TRAIN_END] if split == "train" else df[df.index >= TRAIN_END]
        x = df.reindex(t)[f"fwdn_{h}"].dropna().to_numpy()
        g = df.reindex(t)[f"fwd_{h}"].dropna().to_numpy()
        pool = sub[f"fwdn_{h}"].dropna().to_numpy()
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
        for p, cnt in zip(pools, counts):
            tot += rng.choice(p, cnt).sum()
            n += cnt
        sims[i] = tot / n
    g = np.concatenate(gross)
    return {"N": len(e), "edge": e.mean(), "p": float((sims >= e.mean()).mean()),
            "med_bp": np.median(g) * 1e4, "wr": float((g > 0).mean())}


def main(data_dir):
    data_dir = Path(data_dir)
    panel = {}
    for f in sorted((data_dir / "spot").glob("*.parquet")):
        df = pd.read_parquet(f)
        df["dt"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
        panel[f.stem] = build(df.set_index("dt").sort_index())
    rng = np.random.default_rng(5)
    best = None
    for L in (4, 8, 12):
        for zc in (1.5, 2.0):
            evs = {s: events(panel[s], L, zc) for s in panel}
            r = evaluate(panel, evs, 24, "train", rng)
            if r is None:
                continue
            r4 = evaluate(panel, evs, 4, "train", rng)
            print(f"L={L:2d} zc={zc} N={r['N']:5d} edge24={r['edge']:+.3f} "
                  f"p={r['p']:.3f} med={r['med_bp']:+6.1f}bp wr={r['wr']:.2f} "
                  f"| edge4={r4['edge']:+.3f} p4={r4['p']:.3f}", flush=True)
            if r["N"] >= 100 and r["p"] <= 0.05 and \
                    (best is None or r["edge"] > best[0]):
                best = (r["edge"], L, zc)
    if best is None:
        print("\nSONUC: hicbir konfig train kuralini gecemedi -> test'e "
              "BAKILMADI, strateji eklenmez.")
        return
    _, L, zc = best
    evs = {s: events(panel[s], L, zc) for s in panel}
    for h in (4, 24, 48):
        r = evaluate(panel, evs, h, "test", rng)
        print(f"TEST (L={L}, zc={zc}) h={h}: N={r['N']} edge={r['edge']:+.3f} "
              f"p={r['p']:.3f} med={r['med_bp']:+.1f}bp wr={r['wr']:.2f}",
              flush=True)


if __name__ == "__main__":
    main(sys.argv[1])
