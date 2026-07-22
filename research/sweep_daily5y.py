"""5+ yillik gunluk-mum arastirmasi (2019-01 -> 2026-06, ~24 major).

Onceden kayitli aileler:
  D1: gunluk S1 — RSI(14)<=OS + bullish divergence (lookback 60g/gap 5g),
      hacim teyidi varyanti (gunluk log-hacim z(30g)>=1.0). OS in {25,30,35}.
  D2: sade gunluk oversold — RSI(14)<=OS, divergence sarti YOK. OS in {25,30}.
  D3: gunluk hacim patlamasi — log-volz(30g)>=zc VE yesil gun. zc in {2.0,2.5}.
Ufuklar: 3g/7g/14g. Birincil: D1,D2 -> 7g; D3 -> 3g.
Split: train < 2025-01-01, test >= (18 ay, tek atis/aile).
Kural: train N>=100, p<=0.05, edge>0. Kazanan icin gun-kumesi saglamlik testi.
Kullanim: python sweep_daily5y.py <data_dir>
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

from common import edge_trigger
from strategies import _rolling_argmax_val, wilder_rsi

SPLIT = pd.Timestamp("2025-01-01", tz="UTC")
H_BARS = {3: 3, 7: 7, 14: 14}
PRIMARY = {"D1": 7, "D2": 7, "D3": 3}


def load(data_dir: Path, sym: str) -> pd.DataFrame:
    df = pd.read_parquet(data_dir / "spot1d" / f"{sym}.parquet")
    df["dt"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    d = df.set_index("dt").sort_index()
    d["logret"] = np.log(d["close"]).diff()
    d["sigma"] = d["logret"].rolling(30, min_periods=15).std()
    lv = np.log1p(d["volume"])
    d["volz"] = (lv - lv.rolling(30, min_periods=15).mean()) / \
        lv.rolling(30, min_periods=15).std()
    d["rsi"] = wilder_rsi(d["close"])
    entry = d["open"].shift(-1)
    for h in H_BARS.values():
        d[f"fwd_{h}"] = np.log(d["close"].shift(-h) / entry)
        d[f"fwdn_{h}"] = d[f"fwd_{h}"] / (d["sigma"] * np.sqrt(h))
    return d


def events(d: pd.DataFrame, fam: str, param) -> pd.DatetimeIndex:
    r = d["rsi"].to_numpy()
    if fam == "D1":
        os_thr, volz = param
        low = d["low"].to_numpy()
        pmin, imin = _rolling_argmax_val(low, 60, 5, "min")
        rsi_at = np.where(imin >= 0, r[imin], np.nan)
        cond = (r <= os_thr) & (low < pmin) & (r > rsi_at)
        if volz is not None:
            cond &= (d["volz"].to_numpy() >= volz)
        cd = 24 * 5
    elif fam == "D2":
        cond = r <= param
        cd = 24 * 5
    else:
        zc = param
        cond = (d["volz"].to_numpy() >= zc) & \
            (d["close"].to_numpy() > d["open"].to_numpy())
        cd = 24 * 3
    return edge_trigger(pd.Series(cond, index=d.index), cd)


def evaluate(panel, evs, h, split, rng, n_iter=400):
    ex, pools, counts, gross, days = [], [], [], [], []
    for sym, t in evs.items():
        d = panel[sym]
        m = t < SPLIT if split == "train" else t >= SPLIT
        t = t[m]
        if len(t) == 0:
            continue
        sub = d[d.index < SPLIT] if split == "train" else d[d.index >= SPLIT]
        x = d.reindex(t)[f"fwdn_{h}"].dropna().to_numpy()
        g = d.reindex(t)[f"fwd_{h}"].dropna().to_numpy()
        pool = sub[f"fwdn_{h}"].dropna().to_numpy()
        if len(x) == 0 or len(pool) == 0:
            continue
        ex.append(x - pool.mean())
        pools.append(pool - pool.mean())
        counts.append(len(x))
        gross.append(g)
        days += [ts.floor("D") for ts in t[:len(x)]]
    if not ex:
        return None
    e = np.concatenate(ex)
    sims = np.empty(n_iter)
    for i in range(n_iter):
        tot = n = 0
        for p, c in zip(pools, counts):
            tot += rng.choice(p, c).sum()
            n += c
        sims[i] = tot / n
    g = np.concatenate(gross)
    cm = pd.Series(e).groupby(pd.DatetimeIndex(days)).mean().to_numpy()
    csims = np.array([rng.choice(cm, len(cm)).mean() for _ in range(1000)])
    return {"N": len(e), "edge": e.mean(),
            "p": float((sims >= e.mean()).mean()),
            "med_bp": np.median(g) * 1e4, "wr": float((g > 0).mean()),
            "n_days": len(cm), "p_cluster": float((csims <= 0).mean())}


def main(data_dir):
    data_dir = Path(data_dir)
    panel = {f.stem: load(data_dir, f.stem)
             for f in sorted((data_dir / "spot1d").glob("*.parquet"))}
    print(f"panel: {len(panel)} sembol, "
          f"{sum(len(d) for d in panel.values())} gunluk bar\n", flush=True)
    rng = np.random.default_rng(21)
    cfgs = ([("D1", (o, v)) for o in (25.0, 30.0, 35.0) for v in (None, 1.0)]
            + [("D2", o) for o in (25.0, 30.0)]
            + [("D3", z) for z in (2.0, 2.5)])
    best = {}
    for fam, param in cfgs:
        evs = {s: events(panel[s], fam, param) for s in panel}
        h = PRIMARY[fam]
        r = evaluate(panel, evs, h, "train", rng)
        if r is None:
            print(f"{fam} {param}: olay yok", flush=True)
            continue
        print(f"{fam} {str(param):12s} N={r['N']:4d} edge{h}g={r['edge']:+.3f} "
              f"p={r['p']:.3f} p_gun={r['p_cluster']:.3f} "
              f"med={r['med_bp']:+7.1f}bp wr={r['wr']:.2f} "
              f"gun={r['n_days']}", flush=True)
        if r["N"] >= 100 and r["p"] <= 0.05 and r["edge"] > 0 and \
                (fam not in best or r["edge"] > best[fam][0]):
            best[fam] = (r["edge"], param)
    print("\n==== TRAIN kazananlari -> TEST (aile basi tek atis) ====", flush=True)
    if not best:
        print("Hicbir aile train kuralini gecemedi -> test'e bakilmadi.")
        return
    for fam, (edge, param) in best.items():
        evs = {s: events(panel[s], fam, param) for s in panel}
        for h in (3, 7, 14):
            r = evaluate(panel, evs, h, "test", rng)
            if r:
                mark = " <-- birincil" if h == PRIMARY[fam] else ""
                print(f"{fam} {param} TEST h={h}g: N={r['N']} "
                      f"edge={r['edge']:+.3f} p={r['p']:.3f} "
                      f"p_gun={r['p_cluster']:.3f} med={r['med_bp']:+.1f}bp "
                      f"wr={r['wr']:.2f}{mark}", flush=True)


if __name__ == "__main__":
    main(sys.argv[1])
