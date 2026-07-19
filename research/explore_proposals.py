"""Gemini/Kimi onerilerinin hizli deneyleri (yalniz TRAIN — test yakilmaz):

A) HTF filtreleri S1/S3 uzerinde:
   - Gemini: 4h EMA50 & EMA200 egimi pozitif degilse LONG'u ele
   - Kimi S10: S1 icin 4h RSI14<50, S3 icin 4h RSI14>45
   Sizinti onlemi: 4h ozellikleri bar KAPANIS zamanina indekslenir (ffill) —
   olay aninda yalnizca kapanmis 4h bar bilgisi kullanilir.

B) ATR'li dinamik TP/SL (Gemini: stop 1.5xATR14, hedef 3.0xATR14) — 5m yol
   analiziyle, zaman-tavani ufuk; zaman cikisiyla kiyas.

Kullanim: python explore_proposals.py <data_dir>
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

from common import TRAIN_END
from strategies import s3_events, wilder_rsi
from sweep_s1 import gen_events, load_enriched, precompute
from bracket_analysis import event_paths, first_touch, load_5m_paths

FEE_RT = 0.001


def htf_features(data_dir, sym):
    """4h EMA egimleri + RSI, 1h grid'e 'yalnizca kapanmis bar' kuraliyla."""
    df = pd.read_parquet(data_dir / "spot" / f"{sym}.parquet")
    df["dt"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    df = df.set_index("dt").sort_index()
    c4 = df["close"].resample("4h", label="left", closed="left").last().dropna()
    ema50 = c4.ewm(span=50, adjust=False, min_periods=50).mean()
    ema200 = c4.ewm(span=200, adjust=False, min_periods=200).mean()
    rsi4 = wilder_rsi(c4)
    feats = pd.DataFrame({
        "trend_ok": (ema50.diff() > 0) & (ema200.diff() > 0),
        "rsi4": rsi4,
    })
    feats.index = feats.index + pd.Timedelta(hours=4)   # bar kapanis ani
    grid = pd.date_range(feats.index[0], df.index[-1] + pd.Timedelta(hours=1),
                         freq="1h", tz="UTC")
    return feats.reindex(grid, method="ffill")


def edge_of(panel, evs_filtered, h, split):
    ex = []
    for sym, t in evs_filtered.items():
        df = panel[sym]
        m = t < TRAIN_END if split == "train" else t >= TRAIN_END
        t = t[m]
        if len(t) == 0:
            continue
        sub = df[df.index < TRAIN_END] if split == "train" else df[df.index >= TRAIN_END]
        x = df.reindex(t)[f"fwdn_{h}"].dropna().to_numpy()
        pool = sub[f"fwdn_{h}"].dropna()
        if len(x):
            ex.append(x - pool.mean())
    if not ex:
        return None, 0
    e = np.concatenate(ex)
    return e.mean(), len(e)


def part_a(data_dir, spot, feats1h):
    fS1 = gen_events(precompute(spot), "bull", 22.5, "div")
    fS3 = s3_events(spot, 3.0, 168, True, direction="bar_up")
    for tag, evs, h, cond_fn in (
        ("S1 x Gemini-EMA", fS1, 24, lambda f, t: bool(f.loc[t, "trend_ok"])),
        ("S1 x Kimi-RSI<50", fS1, 24, lambda f, t: f.loc[t, "rsi4"] < 50),
        ("S3 x Gemini-EMA", fS3, 4, lambda f, t: bool(f.loc[t, "trend_ok"])),
        ("S3 x Kimi-RSI>45", fS3, 4, lambda f, t: f.loc[t, "rsi4"] > 45),
    ):
        pas, red = {}, {}
        for sym, (times, dirs) in evs.items():
            f = feats1h[sym]
            ok = []
            for t in times:
                try:
                    ok.append(bool(cond_fn(f, t)) and not pd.isna(f.loc[t, "rsi4"]))
                except KeyError:
                    ok.append(False)
            ok = np.array(ok, bool) if len(times) else np.array([], bool)
            pas[sym] = times[ok]
            red[sym] = times[~ok]
        e_all, n_all = edge_of(spot, {s: np.concatenate([pas[s], red[s]])
                                      if len(pas[s]) or len(red[s]) else pas[s]
                                      for s in evs}, h, "train")
        e_p, n_p = edge_of(spot, pas, h, "train")
        e_r, n_r = edge_of(spot, red, h, "train")
        print(f"{tag:18s} (h={h}) TUM: edge={e_all:+.3f} N={n_all} | "
              f"GECEN: edge={(e_p if e_p is not None else float('nan')):+.3f} N={n_p} | "
              f"ELENEN: edge={(e_r if e_r is not None else float('nan')):+.3f} N={n_r}",
              flush=True)


def part_b(data_dir, spot, paths):
    # ATR14 (1h, Wilder) her sembol icin
    atrs = {}
    for sym in spot:
        df = pd.read_parquet(Path(data_dir) / "spot" / f"{sym}.parquet")
        df["dt"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
        df = df.set_index("dt").sort_index()
        h, l, c = df["high"], df["low"], df["close"]
        tr = pd.concat([h - l, (h - c.shift(1)).abs(),
                        (l - c.shift(1)).abs()], axis=1).max(axis=1)
        atrs[sym] = tr.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    for tag, evs, hor in (
        ("S1", gen_events(precompute(spot), "bull", 22.5, "div"), 24),
        ("S3", s3_events(spot, 3.0, 168, True, direction="bar_up"), 4),
    ):
        outs, times_ret = [], []
        for sym, (times, _d) in evs.items():
            times = times[times < TRAIN_END]
            rows = event_paths(paths, sym, times, hor)
            a = atrs[sym]
            for t, entry, hi, lo, cl in rows:
                atr = a.asof(t)
                if not np.isfinite(atr) or entry <= 0:
                    continue
                stop = 1.5 * atr / entry
                tgt = 3.0 * atr / entry
                o, r = first_touch(entry, hi, lo, cl, tgt, stop)
                outs.append(o)
                times_ret.append(r)
        rets = np.array(times_ret) - FEE_RT
        outs = np.array(outs)
        print(f"ATR-bracket {tag} (train, ufuk-tavan {hor}h): N={len(rets)} "
              f"hedef-once %{(outs == 1).mean()*100:.0f} "
              f"stop-once %{(outs == -1).mean()*100:.0f} "
              f"zaman %{(outs == 0).mean()*100:.0f} "
              f"E[net]={rets.mean()*1e4:+.0f}bp "
              f"(kiyas: zaman-cikisi {'~+167bp' if tag == 'S1' else '~+37bp'})",
              flush=True)


def main(data_dir):
    data_dir = Path(data_dir)
    spot = load_enriched(data_dir, "spot")
    feats1h = {s: htf_features(data_dir, s) for s in spot}
    print("==== A) HTF filtreleri (train) ====")
    part_a(data_dir, spot, feats1h)
    print("\n==== B) ATR bracket 1.5/3.0 (train) ====")
    paths = load_5m_paths(data_dir)
    part_b(data_dir, spot, paths)


if __name__ == "__main__":
    main(sys.argv[1])
