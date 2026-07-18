"""Uc acik soru:
A) S3 bar_up (train'de en guclu yuz) test'te tutunuyor mu?
B) S2 icin sembol-goreli funding z-skoru, seviye esiginden saglam mi?
C) S1 + S3(hacim) confluence S1'den guclu mu?
Kullanim: python explore_variants.py <data_dir>
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

from common import (baseline_stats, collect_event_returns, edge_trigger,
                    per_month_rate, summarize)
from strategies import s3_events
from sweep_s1 import gen_events, load_enriched, precompute


def show(tag, panel, ev, base, hs, split):
    parts = [f"[{tag}/{split}] N={len(ev)} rate={per_month_rate(ev, len(panel), split):.2f}"]
    for h in hs:
        s = summarize(panel, ev, base, h, split)
        if s.get("N", 0) == 0:
            parts.append(f"h{h}: yok")
            continue
        parts.append(f"h{h}: edge={s['edge_voln']:+.3f} p={s['p_boot']:.3f} wr={s['winrate']:.2f}")
    print("  ".join(parts), flush=True)


def main(data_dir):
    spot = load_enriched(data_dir, "spot")
    um = {f.stem: pd.read_parquet(f)
          for f in sorted(Path(data_dir, "enriched", "um").glob("*.parquet"))}
    funding = {f.stem: pd.read_parquet(f)
               for f in sorted(Path(data_dir, "funding").glob("*.parquet"))}

    print("==== A) S3 bar_up (log, w=168) train->test ====")
    for z in (3.0, 3.5):
        evd = s3_events(spot, z, 168, True, direction="bar_up")
        for split in ("train", "test"):
            base = baseline_stats(spot, split)
            ev = collect_event_returns(spot, evd, split)
            show(f"S3 up z={z}", spot, ev, base, [4, 24], split)

    print("\n==== B) S2 funding z-skoru (son 90 settlement, kendinden onceki) ====")
    for zthr in (-2.0, -2.5, -3.0, -4.0):
        evd = {}
        for sym, fr in funding.items():
            r = fr["last_funding_rate"]
            mu = r.shift(1).rolling(90, min_periods=45).mean()
            sd = r.shift(1).rolling(90, min_periods=45).std()
            zf = (r - mu) / sd
            t = pd.to_datetime(fr["calc_time"], unit="ms", utc=True).dt.floor("h")
            cond = pd.Series(((zf <= zthr) & (r < 0)).to_numpy(),
                             index=pd.DatetimeIndex(t))
            cond = cond[~cond.index.duplicated(keep="last")]
            times = edge_trigger(cond, 24)
            evd[sym] = (times, np.full(len(times), 1))
        for split in ("train", "test"):
            base = baseline_stats(um, split)
            ev = collect_event_returns(um, evd, split)
            show(f"S2 zf<={zthr}", um, ev, base, [24, 72], split)

    print("\n==== C) S1(22.5) confluence: son 24h icinde S3(log z>=3.0) var mi ====")
    feats = precompute(spot)
    ev_s1 = gen_events(feats, "bull", 22.5, "div")
    s3d = s3_events(spot, 3.0, 168, True, direction="bar")
    s3_times = {sym: t for sym, (t, d) in s3d.items()}
    with_v, without_v = {}, {}
    for sym, (times, dirs) in ev_s1.items():
        st = s3_times.get(sym, pd.DatetimeIndex([]))
        has = np.array([((st >= t - pd.Timedelta(hours=24)) & (st <= t)).any()
                        for t in times]) if len(times) else np.array([], bool)
        with_v[sym] = (times[has], dirs[has])
        without_v[sym] = (times[~has], dirs[~has])
    for split in ("train", "test", "all"):
        base = baseline_stats(spot, split)
        ev_w = collect_event_returns(spot, with_v, split)
        ev_wo = collect_event_returns(spot, without_v, split)
        show("S1+S3var", spot, ev_w, base, [24, 72], split)
        show("S1 yalniz", spot, ev_wo, base, [24, 72], split)


if __name__ == "__main__":
    main(sys.argv[1])
