"""Ek G: 100-coin genisletilmis evrende DONMUS konfigurasyon dogrulamasi.

Birincil soru (secimsiz -> snooping yok): mevcut dogrulanmis ayarlar
(S1 22.5/div, S1+S4, S2 -0.03/p2, S3 logz3/up) genis evrende tutuyor mu?
Kirilimlar: eski-30 vs YENI coinler (asil genelleme sorusu) + hacim kademeleri.
Ikincil (yalniz rapor): train-100'de esik taramasi — optimum kaydi mi?
Kullanim: python eval_100.py <data100_dir>
"""

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from common import baseline_stats, collect_event_returns, per_month_rate, summarize
from strategies import s2_events, s3_events
from sweep_s1 import gen_events, load_enriched, precompute

ORIG30 = set(
    "BTCUSDT ETHUSDT BNBUSDT SOLUSDT XRPUSDT DOGEUSDT ADAUSDT TRXUSDT "
    "LINKUSDT AVAXUSDT LTCUSDT DOTUSDT BCHUSDT UNIUSDT ATOMUSDT NEARUSDT "
    "APTUSDT ARBUSDT OPUSDT FILUSDT SUIUSDT INJUSDT SEIUSDT TIAUSDT "
    "AAVEUSDT ETCUSDT XLMUSDT SANDUSDT GALAUSDT PEPEUSDT".split())


def sub_events(evs, keep):
    return {s: v for s, v in evs.items() if s in keep}


def line(tag, panel, evs, h, split, n_syms):
    ev = collect_event_returns(panel, evs, split)
    base = baseline_stats(panel, split)
    s = summarize(panel, ev, base, h, split)
    if s.get("N", 0) == 0:
        print(f"  {tag:34s} olay yok")
        return
    print(f"  {tag:34s} N={s['N']:5d} rate={per_month_rate(ev, n_syms, split):4.2f} "
          f"edge{h}={s['edge_voln']:+.3f} p={s['p_boot']:.3f} "
          f"med={s['med_bp']:+6.1f}bp wr={s['winrate']:.2f}")


def main(data_dir):
    data_dir = Path(data_dir)
    uni = json.loads((data_dir / "universe.json").read_text())
    ranks = {u["symbol"]: u["rank"] for u in uni}
    spot = load_enriched(data_dir, "spot")
    um = {f.stem: pd.read_parquet(f)
          for f in sorted((data_dir / "enriched" / "um").glob("*.parquet"))}
    funding = {f.stem: pd.read_parquet(f)
               for f in sorted((data_dir / "funding").glob("*.parquet"))}
    print(f"panel: {len(spot)} spot / {len(um)} um sembol", flush=True)
    feats = precompute(spot)

    ev_s1 = gen_events(feats, "bull", 22.5, "div")
    s3_any = s3_events(spot, 3.0, 168, True, direction="bar")
    stimes = {s: t for s, (t, d) in s3_any.items()}
    s1conf = {}
    for sym, (times, dirs) in ev_s1.items():
        st = stimes.get(sym, pd.DatetimeIndex([]))
        has = np.array([((st >= t - pd.Timedelta(hours=24)) & (st <= t)).any()
                        for t in times]) if len(times) else np.array([], bool)
        s1conf[sym] = (times[has], dirs[has])
    ev_s2 = s2_events(funding, -0.03, 2)
    ev_s3 = s3_events(spot, 3.0, 168, True, direction="bar_up")

    new_spot = {s for s in spot if s not in ORIG30}
    um30 = {s for s in um if s.replace("1000", "") in ORIG30 or s in ORIG30}
    new_um = {s for s in um if s not in um30}
    tiers = {"kademe1(1-33)": {s for s, r in ranks.items() if r <= 33},
             "kademe2(34-66)": {s for s, r in ranks.items() if 34 <= r <= 66},
             "kademe3(67+)": {s for s, r in ranks.items() if r >= 67}}

    for split in ("train", "test"):
        print(f"\n======== {split.upper()} — donmus konfigurasyonlar ========",
              flush=True)
        for name, evs, panel, h, seg30, segnew in (
                ("S1 (22.5 div)", ev_s1, spot, 24, ORIG30, new_spot),
                ("S1+S4", s1conf, spot, 24, ORIG30, new_spot),
                ("S2 (-0.03 p2)", ev_s2, um, 72, um30, new_um),
                ("S3 (logz3 up)", ev_s3, spot, 4, ORIG30, new_spot)):
            line(f"{name} TUM-100", panel, evs, h, split, len(panel))
            line(f"{name} eski-30", panel, sub_events(evs, seg30), h, split,
                 len(seg30 & set(panel)))
            line(f"{name} YENI-{len(segnew & set(panel))}", panel,
                 sub_events(evs, segnew), h, split, len(segnew & set(panel)))
        print("  -- S1 hacim kademeleri --", flush=True)
        for tname, tset in tiers.items():
            line(f"S1 {tname}", spot, sub_events(ev_s1, tset), 24, split,
                 len(tset & set(spot)))

    print("\n======== TRAIN-100 esik taramasi (yalniz rapor) ========",
          flush=True)
    for th in (17.5, 20.0, 22.5, 25.0, 27.5):
        line(f"S1 OS={th}", spot, gen_events(feats, "bull", th, "div"),
             24, "train", len(spot))
    for z in (2.5, 3.0, 3.5):
        line(f"S3 z={z}", spot,
             s3_events(spot, z, 168, True, direction="bar_up"), 4, "train",
             len(spot))
    for th in (-0.02, -0.03, -0.04):
        line(f"S2 {th} p2", um, s2_events(funding, th, 2), 72, "train",
             len(um))


if __name__ == "__main__":
    main(sys.argv[1])
