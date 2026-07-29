"""Hisse senedi aday taramasi (ONKAYIT.md'deki tasarim).

Aileler: E1 (RSI+divergence), E2 (sade oversold), E3 (hacim patlamasi+yesil),
E4 (gap-down donusu). Train'de tarama, kurali gecen aileye TEK test atisi.
Kullanim: python sweep_equity.py <veri_dizini> [pazar]
"""

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

TRAIN_END = pd.Timestamp("2023-01-01")
HORIZONS = [1, 3, 5, 10]
PRIMARY = {"E1": 5, "E2": 5, "E3": 3, "E4": 3}
COST_BPS = {"us": 5.0, "cn": 15.0, "hk": 20.0}
BOOT = 2000


def wilder_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    d = close.diff()
    g = d.clip(lower=0).ewm(alpha=1 / period, adjust=False,
                            min_periods=period).mean()
    l = (-d).clip(lower=0).ewm(alpha=1 / period, adjust=False,
                               min_periods=period).mean()
    return 100 - 100 / (1 + g / l)


def prep(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    d["logret"] = np.log(d["close"]).diff()
    d["sigma"] = d["logret"].rolling(60, min_periods=30).std()
    d["rsi"] = wilder_rsi(d["close"])
    lv = np.log1p(d["volume"])
    d["volz"] = ((lv - lv.rolling(60, min_periods=30).mean())
                 / lv.rolling(60, min_periods=30).std())
    d["prev_low60"] = d["low"].rolling(60, min_periods=60).min().shift(5)
    # divergence icin: onceki dip barindaki RSI
    d["rsi_at_low"] = np.nan
    lows = d["low"].to_numpy()
    rsis = d["rsi"].to_numpy()
    n = len(d)
    ral = np.full(n, np.nan)
    for i in range(65, n):
        w = lows[i - 65:i - 5]
        if len(w) == 0:
            continue
        j = i - 65 + int(np.argmin(w))
        ral[i] = rsis[j]
    d["rsi_at_low"] = ral
    d["gap_pct"] = d["open"] / d["close"].shift(1) - 1
    # A-hisselerinde uzun ISLEM DURDURMALARI sifir-volatilite penceresi
    # yaratir; sigma=0 -> fwd/0 = inf -> tum istatistikler cokerdi (ilk
    # kosuda CN sonuclari nan/sahte-p uretti). Sifir/gecersiz sigma NaN.
    d.loc[~(d["sigma"] > 0), "sigma"] = np.nan
    entry = d["open"].shift(-1)
    for h in HORIZONS:
        d[f"fwd_{h}"] = np.log(d["close"].shift(-h) / entry)
        d[f"fwdn_{h}"] = d[f"fwd_{h}"] / (d["sigma"] * np.sqrt(h))
    # inf/-inf kalmasin (bolme ve log kaynakli)
    for h in HORIZONS:
        for c in (f"fwd_{h}", f"fwdn_{h}"):
            d[c] = d[c].replace([np.inf, -np.inf], np.nan)
    return d


def events(d: pd.DataFrame, fam: str, p) -> pd.DatetimeIndex:
    r = d["rsi"]
    if fam == "E1":
        cond = (r <= p) & (d["low"] < d["prev_low60"]) & (r > d["rsi_at_low"])
        cd = 10
    elif fam == "E2":
        cond = r <= p
        cd = 10
    elif fam == "E3":
        cond = (d["volz"] >= p) & (d["close"] > d["open"])
        cd = 5
    else:
        cond = (d["gap_pct"] <= -p / 100.0) & (d["close"] > d["open"])
        cd = 5
    cond = cond.fillna(False)
    rising = cond & ~cond.shift(1, fill_value=False)
    times = d.index[rising]
    kept, last = [], None
    for t in times:                       # cooldown: cd islem gunu
        if last is None or (t - last).days >= cd:
            kept.append(t)
            last = t
    return pd.DatetimeIndex(kept)


def evaluate(panel, evs, h, split, rng, cost_bps):
    ex, pools, counts, gross, days = [], [], [], [], []
    for sym, t in evs.items():
        d = panel[sym]
        m = t < TRAIN_END if split == "train" else t >= TRAIN_END
        t = t[m]
        if len(t) == 0:
            continue
        sub = d[d.index < TRAIN_END] if split == "train" else d[d.index >= TRAIN_END]
        sel = d.reindex(t)
        x = sel[f"fwdn_{h}"].dropna()
        g = sel[f"fwd_{h}"].dropna()
        pool = sub[f"fwdn_{h}"].dropna().to_numpy()
        if len(x) == 0 or len(pool) == 0:
            continue
        ex.append(x.to_numpy() - pool.mean())
        pools.append(pool - pool.mean())
        counts.append(len(x))
        gross.append(g.to_numpy())
        days += list(x.index)
    if not ex:
        return None
    e = np.concatenate(ex)
    if not np.isfinite(e).all() or not all(np.isfinite(p_).all() for p_ in pools):
        raise ValueError("finite olmayan deger — veri temizligi hatasi")
    sims = np.empty(BOOT // 4)
    for i in range(len(sims)):
        tot = n = 0
        for p_, c in zip(pools, counts):
            tot += rng.choice(p_, c).sum()
            n += c
        sims[i] = tot / n
    g = np.concatenate(gross)
    net = (np.exp(g) - 1) * 100 - cost_bps / 100.0
    cm = pd.Series(e).groupby(pd.DatetimeIndex(days)).mean().to_numpy()
    csims = np.array([rng.choice(cm, len(cm)).mean() for _ in range(BOOT)])
    return {
        "N": len(e), "edge": e.mean(),
        "p": float((np.count_nonzero(sims >= e.mean()) + 1) / (len(sims) + 1)),
        "p_gun": float((np.count_nonzero(csims <= 0) + 1) / (BOOT + 1)),
        "net_med": float(np.median(net)), "net_mean": float(net.mean()),
        "wr": float((net > 0).mean()), "gun": len(cm),
    }


def main(data_dir, only=None):
    data_dir = Path(data_dir)
    uni = json.loads((data_dir / "universe.json").read_text())
    rng = np.random.default_rng(42)
    for market, syms in uni.items():
        if only and market != only:
            continue
        panel = {}
        for s in syms:
            f = data_dir / market / f"{s}.parquet"
            if f.exists():
                panel[s] = prep(pd.read_parquet(f))
        if not panel:
            continue
        cost = COST_BPS[market]
        print(f"\n{'='*72}\n{market.upper()} — {len(panel)} sembol "
              f"(maliyet {cost:.0f}bp)\n{'='*72}", flush=True)
        cfgs = ([("E1", v) for v in (20.0, 25.0, 30.0)]
                + [("E2", v) for v in (20.0, 25.0, 30.0)]
                + [("E3", v) for v in (2.0, 2.5, 3.0)]
                + [("E4", v) for v in (3.0, 5.0)])
        best = {}
        for fam, p in cfgs:
            evs = {s: events(panel[s], fam, p) for s in panel}
            h = PRIMARY[fam]
            r = evaluate(panel, evs, h, "train", rng, cost)
            if r is None:
                continue
            print(f"  {fam} {p:<5} N={r['N']:5d} edge{h}g={r['edge']:+.3f} "
                  f"p={r['p']:.3f} p_gun={r['p_gun']:.3f} "
                  f"net_med={r['net_med']:+.2f}% wr={r['wr']:.2f}", flush=True)
            if (r["N"] >= 300 and r["p"] <= 0.05 and r["p_gun"] <= 0.10
                    and r["edge"] > 0
                    and (fam not in best or r["edge"] > best[fam][0])):
                best[fam] = (r["edge"], p)
        print(f"\n  -- {market.upper()} TRAIN kazananlari -> TEST (tek atis) --")
        if not best:
            print("  hicbir aile train kuralini gecemedi -> test'e BAKILMADI")
            continue
        for fam, (edge, p) in best.items():
            evs = {s: events(panel[s], fam, p) for s in panel}
            for h in HORIZONS:
                r = evaluate(panel, evs, h, "test", rng, cost)
                if r:
                    mark = " <-- birincil" if h == PRIMARY[fam] else ""
                    print(f"  {fam} {p} TEST h={h}g: N={r['N']} "
                          f"edge={r['edge']:+.3f} p={r['p']:.3f} "
                          f"p_gun={r['p_gun']:.3f} net_med={r['net_med']:+.2f}% "
                          f"wr={r['wr']:.2f}{mark}", flush=True)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
