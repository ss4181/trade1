"""Secilen konfigurasyonlarin nihai degerlendirmesi.

Train'de secilen esikler test'te (2026H1, ayi rejimi) dogrulanir; ek olarak:
  - yarim-yil rejim kirilimi
  - sembol konsantrasyonu
  - ayni-gun kumelenmesi + kume-duzeyi (gun) bootstrap  (semboller ayni anda
    hareket ettigi icin olay-duzeyi bootstrap bagimsizligi abartir)
Kullanim: python eval_final.py <data_dir>
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

from common import (HORIZONS, TRAIN_END, baseline_stats, collect_event_returns,
                    per_month_rate, summarize)
from strategies import s2_events, s3_events
from sweep_s1 import gen_events, load_enriched, precompute

# ---- train taramasindan secilen konfigurasyonlar (sweep sonuclarina gore)
S1_SIDE, S1_VARIANT, S1_THRESH = "bull", "div", 22.5
S1_ALT_THRESH = 20.0                      # mevcut bot esigi = muhafazakar alternatif
S2_THRESH, S2_PERSISTENCE = -0.03, 2
S3_DIRECTION, S3_LOG, S3_WINDOW, S3_Z = "bar", True, 168, 3.5
PRIMARY_H = {"S1": 24, "S2": 72, "S3": 24}


def excess_returns(panel, ev, base, h):
    """Olay basina sembol-eslesmeli fazla getiri (yonlu, vol-normalize)."""
    e = ev.dropna(subset=[f"fwdn_{h}"]).copy()
    bl = np.array([base[r["sym"]].loc[h, "mean_fwdn"] * r["dir"]
                   for _, r in e.iterrows()])
    e["excess"] = e[f"fwdn_{h}"] - bl
    return e


def cluster_stats(e: pd.DataFrame, n_boot: int = 2000, seed: int = 11):
    """Ayni UTC gunune dusen olaylari tek kumeye indir; kume ortalamalarinin
    ortalamasi + kume bootstrap %90 GA + p."""
    if len(e) == 0:
        return {}
    days = e["t"].dt.floor("D")
    cm = e.groupby(days)["excess"].mean().to_numpy()
    rng = np.random.default_rng(seed)
    sims = np.array([rng.choice(cm, size=len(cm), replace=True).mean()
                     for _ in range(n_boot)])
    lo, hi = np.percentile(sims, [5, 95])
    return {"n_clusters": len(cm), "cluster_mean": cm.mean(),
            "ci90": (lo, hi), "p_cluster": float((sims <= 0).mean())}


def regime_breakdown(e: pd.DataFrame):
    bins = [("2024H2", "2024-07-01", "2025-01-01"),
            ("2025H1", "2025-01-01", "2025-07-01"),
            ("2025H2", "2025-07-01", "2026-01-01"),
            ("2026H1", "2026-01-01", "2026-07-01")]
    out = []
    for name, a, b in bins:
        m = (e["t"] >= pd.Timestamp(a, tz="UTC")) & (e["t"] < pd.Timestamp(b, tz="UTC"))
        sub = e[m]
        out.append((name, len(sub),
                    sub["excess"].mean() if len(sub) else np.nan,
                    (sub[[c for c in sub.columns if c == "excess"]] > 0).mean().iloc[0]
                    if len(sub) else np.nan))
    return out


def report(tag, panel, events, split, h, with_ev=None):
    base = baseline_stats(panel, split)
    ev = with_ev if with_ev is not None else collect_event_returns(panel, events, split)
    s = summarize(panel, ev, base, h, split)
    if s.get("N", 0) == 0:
        print(f"[{tag}/{split}] olay yok")
        return None
    e = excess_returns(panel, ev, base, h)
    cs = cluster_stats(e)
    top = e.groupby("sym").size().sort_values(ascending=False)
    conc = top.head(5).sum() / len(e)
    print(f"[{tag}/{split}] N={s['N']} rate={per_month_rate(ev, len(panel), split):.2f}/sym/ay "
          f"edge_voln{h}={s['edge_voln']:+.3f} p_boot={s['p_boot']:.3f} "
          f"edge_bp={s['edge_bp']:+.0f} wr={s['winrate']:.2f} (wr_edge {s['wr_edge']:+.3f})")
    print(f"    med={s['med_bp']:+.0f}bp q10={s['q10_bp']:+.0f} q90={s['q90_bp']:+.0f} | "
          f"gun-kumesi: n={cs['n_clusters']} mean={cs['cluster_mean']:+.3f} "
          f"CI90=({cs['ci90'][0]:+.3f},{cs['ci90'][1]:+.3f}) p_cl={cs['p_cluster']:.3f} | "
          f"top5 sembol payi={conc:.0%}")
    if split == "all":
        for name, n, mx, wr in regime_breakdown(e):
            print(f"    {name}: N={n:4d} excess={mx:+.3f}" if n else f"    {name}: N=0")
    return e


def main(data_dir):
    spot = load_enriched(data_dir, "spot")
    um = {f.stem: pd.read_parquet(f)
          for f in sorted(Path(data_dir, "enriched", "um").glob("*.parquet"))}
    funding = {f.stem: pd.read_parquet(f)
               for f in sorted(Path(data_dir, "funding").glob("*.parquet"))}
    feats = precompute(spot)

    print("==== S1: RSI oversold divergence (bull) ====")
    ev_s1 = gen_events(feats, S1_SIDE, S1_THRESH, S1_VARIANT)
    for split in ("train", "test", "all"):
        report(f"S1 div bull {S1_THRESH}", spot, ev_s1, split, PRIMARY_H["S1"])
    print("-- alternatif esik --")
    ev_alt = gen_events(feats, S1_SIDE, S1_ALT_THRESH, S1_VARIANT)
    for split in ("train", "test"):
        report(f"S1 div bull {S1_ALT_THRESH}", spot, ev_alt, split, PRIMARY_H["S1"])
    print("-- atilan bear tarafi (kayit icin, mevcut bot esigi 80) --")
    ev_bear = gen_events(feats, "bear", 80.0, "div")
    for split in ("train", "test"):
        report("S1 div bear 80", spot, ev_bear, split, PRIMARY_H["S1"])

    print("\n==== S2: funding squeeze (long) ====")
    ev_s2 = s2_events(funding, S2_THRESH, S2_PERSISTENCE)
    for split in ("train", "test", "all"):
        report(f"S2 {S2_THRESH}%", um, ev_s2, split, PRIMARY_H["S2"])
    print("-- mevcut bot esigi -0.02 --")
    ev_s2c = s2_events(funding, -0.02, 1)
    for split in ("train", "test"):
        report("S2 -0.02%", um, ev_s2c, split, PRIMARY_H["S2"])

    print("\n==== S3: hacim anomalisi ====")
    ev_s3 = s3_events(spot, S3_Z, S3_WINDOW, S3_LOG, direction=S3_DIRECTION)
    for split in ("train", "test", "all"):
        report(f"S3 log z={S3_Z}", spot, ev_s3, split, PRIMARY_H["S3"])
    print("-- alternatif z=3.0 (log) --")
    ev_s3a = s3_events(spot, 3.0, S3_WINDOW, True, direction=S3_DIRECTION)
    for split in ("train", "test"):
        report("S3 log z=3.0", spot, ev_s3a, split, PRIMARY_H["S3"])
    print("-- mevcut bot: ham hacim z=3.0 --")
    ev_s3c = s3_events(spot, 3.0, S3_WINDOW, False, direction="bar")
    for split in ("train", "test"):
        report("S3 raw z=3.0", spot, ev_s3c, split, PRIMARY_H["S3"])

    # ---- ortusme / confluence ----
    print("\n==== Ortusme (±24h ayni sembol) ====")
    def flat(evd):
        rows = []
        for sym, (times, dirs) in evd.items():
            for t, d in zip(times, dirs):
                rows.append((sym, t, d))
        return pd.DataFrame(rows, columns=["sym", "t", "dir"])
    f1, f2, f3 = flat(ev_s1), flat(ev_s2), flat(ev_s3)
    # S2 um sembol adlarini spota esle (1000PEPEUSDT -> PEPEUSDT)
    f2["sym"] = f2["sym"].str.replace("^1000", "", regex=True)
    for (na, fa), (nb, fb) in [(("S1", f1), ("S2", f2)),
                               (("S1", f1), ("S3", f3)),
                               (("S2", f2), ("S3", f3))]:
        both = 0
        for _, r in fa.iterrows():
            m = fb[(fb["sym"] == r["sym"]) &
                   (abs(fb["t"] - r["t"]) <= pd.Timedelta(hours=24))]
            if len(m):
                both += 1
        print(f"{na} olaylarinin {nb} ile ±24h ortusmesi: {both}/{len(fa)} ({both/max(len(fa),1):.0%})")


if __name__ == "__main__":
    main(sys.argv[1])
