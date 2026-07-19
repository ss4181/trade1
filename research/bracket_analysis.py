"""Hedef/stop dokunma analizi ("giris ve hedef fiyat" sorusunun veri cevabi).

Her dogrulanmis stratejinin olaylari icin, girisden sonraki yolu 5m barlarla
cozunurlukte izler:
  - MFE: ufuk icinde ulasilan en iyi seviye  (hedefe dokunma olasiliklari)
  - MAE: ufuk icinde ulasilan en kotu seviye (stop'a dokunma olasiliklari)
  - Bracket matrisi: (+hedef, -stop) cifti icin HANGISI ONCE dokundu
    (ayni 5m bar icinde ikisi de dokunduysa muhafazakar: stop sayilir)
    + beklenen net getiri (10bp gidis-donus ucretle)

NOT: Bunlar TANIMLAYICI istatistikler; dogrulanmis cikis kurali hala zaman
cikisidir. S2 yollari spot 5m ile yaklasiklanir (arastirma um 1h kullanmisti).
Kullanim: python bracket_analysis.py <data_dir>
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

from common import TRAIN_END
from strategies import s2_events, s3_events
from sweep_s1 import gen_events, load_enriched, precompute

TARGETS = [0.01, 0.02, 0.03, 0.05]
STOPS = [0.01, 0.02, 0.03, 0.05]
MFE_LEVELS = [0.005, 0.01, 0.02, 0.03, 0.05]
MAE_LEVELS = [0.01, 0.02, 0.03, 0.05, 0.10]
FEE_RT = 0.001
HORIZON_H = {"S1": 24, "S1+S4": 24, "S2": 72, "S3": 4}


def load_5m_paths(data_dir: Path) -> dict:
    out = {}
    for f in sorted((data_dir / "spot5m").glob("*.parquet")):
        df = pd.read_parquet(f)
        df["dt"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
        df = df.set_index("dt").sort_index()
        grid = pd.date_range(df.index[0], df.index[-1], freq="5min", tz="UTC")
        df = df.reindex(grid)
        out[f.stem] = df[["open", "high", "low", "close"]]
    return out


def event_paths(paths, sym, times, horizon_h):
    """Her olay icin (entry, mfe, mae, time_exit_ret) dizileri."""
    df = paths.get(sym)
    if df is None:
        return []
    res = []
    nbars = horizon_h * 12
    for t in times:
        start = t + pd.Timedelta(hours=1)
        try:
            i0 = df.index.get_loc(start)
        except KeyError:
            continue
        w = df.iloc[i0:i0 + nbars]
        entry = w["open"].iloc[0] if len(w) else np.nan
        if not np.isfinite(entry) or len(w) < nbars // 2:
            continue
        res.append((t, entry, w["high"].to_numpy(), w["low"].to_numpy(),
                    w["close"].to_numpy()))
    return res


def first_touch(entry, highs, lows, closes, target, stop):
    """+1 hedef once, -1 stop once, 0 zaman cikisi (getirisiyle)."""
    tp, sl = entry * (1 + target), entry * (1 - stop)
    ht = highs >= tp
    lt = lows <= sl
    for h, l in zip(ht, lt):
        if h and l:
            return -1, -stop          # ayni bar: muhafazakar -> stop
        if l:
            return -1, -stop
        if h:
            return +1, target
    last = closes[~np.isnan(closes)]
    ret = (last[-1] / entry - 1) if len(last) else 0.0
    return 0, ret


def analyze(tag, events, paths, split):
    rows = []
    for sym, (times, _dirs) in events.items():
        m = times < TRAIN_END if split == "train" else (
            times >= TRAIN_END if split == "test" else np.ones(len(times), bool))
        rows += event_paths(paths, sym, times[m], HORIZON_H[tag])
    if not rows:
        return None
    mfe = np.array([h.max() / e - 1 for _, e, h, l, c in rows])
    mae = np.array([l.min() / e - 1 for _, e, h, l, c in rows])
    print(f"\n[{tag} / {split}] N={len(rows)} olay (ufuk {HORIZON_H[tag]}h)")
    print("  Hedefe DOKUNMA olasiligi: " + "  ".join(
        f"+{x*100:.1f}%:{(mfe >= x).mean()*100:4.0f}%" for x in MFE_LEVELS))
    print("  Stop'a DOKUNMA olasiligi: " + "  ".join(
        f"-{y*100:.0f}%:{(mae <= -y).mean()*100:4.0f}%" for y in MAE_LEVELS))
    best = None
    print("  Bracket (hedef once gelme %% / beklenen net bp):")
    for x in TARGETS:
        cells = []
        for y in STOPS:
            outs = [first_touch(e, h, l, c, x, y) for _, e, h, l, c in rows]
            rets = np.array([r for _, r in outs]) - FEE_RT
            pt = np.mean([o == 1 for o, _ in outs])
            enet = rets.mean() * 1e4
            cells.append(f"{x*100:.0f}/{y*100:.0f}: %{pt*100:2.0f} {enet:+5.0f}bp")
            if best is None or enet > best[0]:
                best = (enet, x, y, pt)
        print("    " + " | ".join(cells))
    print(f"  En iyi bracket (net bp): hedef +{best[1]*100:.0f}% / "
          f"stop -{best[2]*100:.0f}% -> E[net]={best[0]:+.0f}bp, "
          f"hedef-once %{best[3]*100:.0f}")
    return best


def main(data_dir):
    data_dir = Path(data_dir)
    paths = load_5m_paths(data_dir)
    spot = load_enriched(data_dir, "spot")
    feats = precompute(spot)
    funding = {f.stem: pd.read_parquet(f)
               for f in sorted((data_dir / "funding").glob("*.parquet"))}

    ev_s1 = gen_events(feats, "bull", 22.5, "div")
    s3_any = s3_events(spot, 3.0, 168, True, direction="bar")
    spike_times = {s: t for s, (t, d) in s3_any.items()}
    s1_conf, s1_plain = {}, {}
    for sym, (times, dirs) in ev_s1.items():
        st = spike_times.get(sym, pd.DatetimeIndex([]))
        has = np.array([((st >= t - pd.Timedelta(hours=24)) & (st <= t)).any()
                        for t in times]) if len(times) else np.array([], bool)
        s1_conf[sym] = (times[has], dirs[has])
        s1_plain[sym] = (times[~has], dirs[~has])
    ev_s2 = {s.replace("1000", ""): v
             for s, v in s2_events(funding, -0.03, 2).items()}
    ev_s3 = s3_events(spot, 3.0, 168, True, direction="bar_up")

    for tag, evs in (("S1", ev_s1), ("S1+S4", s1_conf), ("S2", ev_s2),
                     ("S3", ev_s3)):
        b_train = analyze(tag, evs, paths, "train")
        analyze(tag, evs, paths, "all")
        if b_train:
            _, x, y, _ = b_train
            print(f"  [test tutarlilik kontrolu: train'in en iyi bracket'i "
                  f"+{x*100:.0f}/-{y*100:.0f}]")
            rows = []
            for sym, (times, _d) in evs.items():
                rows += event_paths(paths, sym, times[times >= TRAIN_END],
                                    HORIZON_H[tag])
            if rows:
                outs = [first_touch(e, h, l, c, x, y) for _, e, h, l, c in rows]
                rets = np.array([r for _, r in outs]) - FEE_RT
                pt = np.mean([o == 1 for o, _ in outs])
                print(f"    TEST: N={len(rows)} hedef-once %{pt*100:.0f} "
                      f"E[net]={rets.mean()*1e4:+.0f}bp")


if __name__ == "__main__":
    main(sys.argv[1])
