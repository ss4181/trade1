"""S2 iyilestirme adayi: BAZIS filtresi (spot-perp farki).

Hipotez (onceden kayitli): negatif funding + perp SPOT'A PRIMLI (bazis > esik)
= gercek spot alimi eslikli short sikismasi -> daha temiz S2. Kronik-negatif
coinler perp iskontolu islem gordugu icin konsantrasyonu da dusurmeli.
Bazis, olay barinin (settlement saati) kapanislarindan: um_close/spot_close-1
(giris sonraki barin acilisi oldugu icin sizinti yok).
Grid: esik in {baseline(yok), >0, >0.0005, >0.001}. Karar: train'de edge72,
N>=100, p<=0.05, konsantrasyon raporlanir; kazanan tek test atisi alir.
Kullanim: python sweep_s2_basis.py <data_dir>
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

from common import TRAIN_END
from strategies import s2_events

GRID = [None, 0.0, 0.0005, 0.001]


def evaluate(panel, evs, split, rng):
    ex, pools, counts, gross, syms_of = [], [], [], [], []
    for sym, t in evs.items():
        df = panel.get(sym)
        if df is None or len(t) == 0:
            continue
        m = t < TRAIN_END if split == "train" else t >= TRAIN_END
        t = t[m]
        if len(t) == 0:
            continue
        sub = df[df.index < TRAIN_END] if split == "train" else df[df.index >= TRAIN_END]
        x = df.reindex(t)["fwdn_72"].dropna().to_numpy()
        g = df.reindex(t)["fwd_72"].dropna().to_numpy()
        pool = sub["fwdn_72"].dropna().to_numpy()
        if len(x) == 0 or len(pool) == 0:
            continue
        ex.append(x - pool.mean())
        pools.append(pool - pool.mean())
        counts.append(len(x))
        gross.append(g)
        syms_of += [sym] * len(x)
    if not ex:
        return None
    e = np.concatenate(ex)
    sims = np.empty(500)
    for i in range(500):
        tot = n = 0
        for p, cnt in zip(pools, counts):
            tot += rng.choice(p, cnt).sum()
            n += cnt
        sims[i] = tot / n
    g = np.concatenate(gross)
    vc = pd.Series(syms_of).value_counts()
    top5 = vc.head(5).sum() / len(e) if len(e) else np.nan
    return {"N": len(e), "edge": e.mean(),
            "p": float((sims >= e.mean()).mean()),
            "med_bp": np.median(g) * 1e4, "wr": float((g > 0).mean()),
            "top5": top5}


def main(data_dir):
    data_dir = Path(data_dir)
    um = {f.stem: pd.read_parquet(f)
          for f in sorted((data_dir / "enriched" / "um").glob("*.parquet"))}
    spot_close = {}
    for f in sorted((data_dir / "spot").glob("*.parquet")):
        df = pd.read_parquet(f)
        df["dt"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
        spot_close[f.stem] = df.set_index("dt")["close"].sort_index()
    funding = {f.stem: pd.read_parquet(f)
               for f in sorted((data_dir / "funding").glob("*.parquet"))}
    base_evs = s2_events(funding, -0.03, 2)   # um adlariyla (1000PEPE dahil)

    # bazis serileri: um sembol adi -> (um_close / spot_close - 1)
    basis = {}
    for um_sym in base_evs:
        spot_sym = um_sym.replace("1000", "")
        if um_sym in um and spot_sym in spot_close:
            uc = um[um_sym]["close"]
            sc = spot_close[spot_sym].reindex(uc.index)
            scale = 1000.0 if um_sym.startswith("1000") else 1.0
            basis[um_sym] = uc / (sc * scale) - 1

    rng = np.random.default_rng(9)
    best = None
    for thr in GRID:
        evs = {}
        for sym, (times, _d) in base_evs.items():
            if thr is None:
                evs[sym] = times
                continue
            b = basis.get(sym)
            if b is None:
                evs[sym] = times[:0]
                continue
            bv = b.reindex(times).to_numpy()
            evs[sym] = times[np.isfinite(bv) & (bv > thr)]
        r = evaluate(um, evs, "train", rng)
        if r is None:
            continue
        name = "baseline" if thr is None else f"bazis>{thr:.4f}"
        print(f"{name:14s} N={r['N']:4d} edge72={r['edge']:+.3f} p={r['p']:.3f} "
              f"med={r['med_bp']:+6.1f}bp wr={r['wr']:.2f} top5=%{r['top5']*100:.0f}",
              flush=True)
        if thr is not None and r["N"] >= 100 and r["p"] <= 0.05 and \
                (best is None or r["edge"] > best[0]):
            best = (r["edge"], thr, evs)
    if best is None:
        print("\nSONUC: hicbir bazis esigi train kuralini gecemedi -> "
              "test'e BAKILMADI, S2 degismez.")
        return
    edge, thr, evs = best
    r = evaluate(um, evs, "test", rng)
    print(f"\nTEST (bazis>{thr:.4f}): N={r['N']} edge72={r['edge']:+.3f} "
          f"p={r['p']:.3f} med={r['med_bp']:+.1f}bp wr={r['wr']:.2f} "
          f"top5=%{r['top5']*100:.0f}", flush=True)


if __name__ == "__main__":
    main(sys.argv[1])
