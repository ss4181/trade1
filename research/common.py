"""Ortak analiz altyapisi: panel yukleme, ileri getiriler, olay degerlendirme."""

import json
from pathlib import Path

import numpy as np
import pandas as pd

HORIZONS = [1, 2, 4, 8, 12, 24, 48, 72]
VOL_WINDOW = 168          # gerceklesen volatilite penceresi (saat)
TRAIN_END = pd.Timestamp("2026-01-01", tz="UTC")   # train < bu, test >= bu


def load_panel(data_dir: str, market: str) -> dict[str, pd.DataFrame]:
    """Sembol -> saatlik UTC grid'e oturtulmus OHLCV + turev kolonlar.

    Kolonlar: open high low close volume quote_volume taker_buy_volume
              logret sigma1h fwd_{H} fwdn_{H}
    Eksik saatler NaN kalir (fiyat uydurulmaz); shift'ler grid uzerinde
    calistigi icin satir kaymasi olmaz.
    """
    panel = {}
    for f in sorted(Path(data_dir, market).glob("*.parquet")):
        df = pd.read_parquet(f)
        df["dt"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
        df = df.set_index("dt").sort_index()
        grid = pd.date_range(df.index[0], df.index[-1], freq="h", tz="UTC")
        df = df.reindex(grid)
        c, o = df["close"], df["open"]
        df["logret"] = np.log(c).diff()
        df["sigma1h"] = df["logret"].rolling(VOL_WINDOW, min_periods=100).std()
        entry = o.shift(-1)                      # giris: sonraki barin acilisi (wall t+1)
        for h in HORIZONS:
            # cikis: bar t+h kapanisi = wall t+1+h -> giristen tam h saat sonra
            fwd = np.log(c.shift(-h) / entry)
            df[f"fwd_{h}"] = fwd
            df[f"fwdn_{h}"] = fwd / (df["sigma1h"] * np.sqrt(h))
        panel[f.stem] = df
    return panel


def edge_trigger(cond: pd.Series, cooldown: int) -> pd.DatetimeIndex:
    """Kosulun False->True gectigi anlar; ustune ayni sembolde `cooldown`
    saat icinde tekrar tetiklenmeyi ele (greedy)."""
    cond = cond.fillna(False)
    rising = cond & ~cond.shift(1, fill_value=False)
    times = cond.index[rising]
    if cooldown <= 0 or len(times) == 0:
        return times
    kept, last = [], None
    for t in times:
        if last is None or (t - last) >= pd.Timedelta(hours=cooldown):
            kept.append(t)
            last = t
    return pd.DatetimeIndex(kept)


def split_mask(times: pd.DatetimeIndex, split: str) -> np.ndarray:
    if split == "train":
        return times < TRAIN_END
    if split == "test":
        return times >= TRAIN_END
    return np.ones(len(times), dtype=bool)


def collect_event_returns(panel: dict, events: dict, split: str) -> pd.DataFrame:
    """events: sym -> (DatetimeIndex, yon dizisi +1/-1).
    Donus: satir=olay, kolonlar sym, t, dir, fwd_H, fwdn_H (yon-carpimli)."""
    rows = []
    for sym, (times, dirs) in events.items():
        if sym not in panel or len(times) == 0:
            continue
        df = panel[sym]
        m = split_mask(times, split)
        times, dirs = times[m], np.asarray(dirs)[m]
        if len(times) == 0:
            continue
        sel = df.reindex(times)
        out = pd.DataFrame({"sym": sym, "t": times, "dir": dirs})
        for h in HORIZONS:
            out[f"fwd_{h}"] = sel[f"fwd_{h}"].to_numpy() * dirs
            out[f"fwdn_{h}"] = sel[f"fwdn_{h}"].to_numpy() * dirs
        rows.append(out)
    if not rows:
        return pd.DataFrame()
    return pd.concat(rows, ignore_index=True)


def baseline_stats(panel: dict, split: str) -> dict[str, pd.DataFrame]:
    """Sembol basina kosulsuz istatistikler (long yonu): mean fwd, mean fwdn,
    winrate. Kisa yon icin isaretler ters cevrilir."""
    out = {}
    for sym, df in panel.items():
        sub = df[df.index < TRAIN_END] if split == "train" else (
            df[df.index >= TRAIN_END] if split == "test" else df)
        stats = {}
        for h in HORIZONS:
            f = sub[f"fwd_{h}"].dropna()
            fn = sub[f"fwdn_{h}"].dropna()
            stats[h] = (f.mean(), fn.mean(), (f > 0).mean())
        out[sym] = pd.DataFrame(stats, index=["mean_fwd", "mean_fwdn", "winrate"]).T
    return out


def bootstrap_pvalue(panel: dict, ev: pd.DataFrame, h: int, split: str,
                     n_iter: int = 500, seed: int = 7) -> float:
    """Sembol-eslesmeli bootstrap: her sembolden olay sayisi kadar rastgele bar
    cek, yon dagilimini koruyarak isaretle, ortalama fwdn dagilimi cikar.
    p = P(rastgele >= gercek)."""
    rng = np.random.default_rng(seed)
    col = f"fwdn_{h}"
    actual = ev[col].mean()
    pools, counts, dirpools = [], [], []
    for sym, g in ev.groupby("sym"):
        df = panel[sym]
        sub = df[df.index < TRAIN_END] if split == "train" else (
            df[df.index >= TRAIN_END] if split == "test" else df)
        pool = sub[col].dropna().to_numpy()
        if len(pool) == 0:
            continue
        pools.append(pool)
        counts.append(len(g))
        dirpools.append(g["dir"].to_numpy())
    if not pools:
        return np.nan
    sims = np.empty(n_iter)
    for i in range(n_iter):
        tot, n = 0.0, 0
        for pool, cnt, dirs in zip(pools, counts, dirpools):
            draw = rng.choice(pool, size=cnt, replace=True)
            tot += (draw * dirs).sum()
            n += cnt
        sims[i] = tot / n
    return float((sims >= actual).mean())


def summarize(panel: dict, ev: pd.DataFrame, base: dict, h: int, split: str,
              with_pval: bool = True) -> dict:
    """Tek satirlik ozet: N, ort/medyan getiri, vol-norm edge, winrate edge, p."""
    if len(ev) == 0:
        return {"N": 0}
    col, coln = f"fwd_{h}", f"fwdn_{h}"
    e = ev.dropna(subset=[col])
    if len(e) == 0:
        return {"N": 0}
    # sembol-eslesmeli baseline (yon dikkate alinarak)
    bl_f, bl_fn, bl_wr = [], [], []
    for _, r in e.iterrows():
        b = base[r["sym"]].loc[h]
        bl_f.append(b["mean_fwd"] * r["dir"])
        bl_fn.append(b["mean_fwdn"] * r["dir"])
        bl_wr.append(b["winrate"] if r["dir"] > 0 else 1 - b["winrate"])
    res = {
        "N": len(e),
        "mean_bp": e[col].mean() * 1e4,
        "med_bp": e[col].median() * 1e4,
        "edge_bp": (e[col].mean() - np.mean(bl_f)) * 1e4,
        "mean_voln": e[coln].mean(),
        "edge_voln": e[coln].mean() - np.mean(bl_fn),
        "winrate": (e[col] > 0).mean(),
        "wr_edge": (e[col] > 0).mean() - np.mean(bl_wr),
        "q10_bp": e[col].quantile(0.10) * 1e4,
        "q90_bp": e[col].quantile(0.90) * 1e4,
    }
    if with_pval:
        res["p_boot"] = bootstrap_pvalue(panel, e, h, split)
    return res


def per_month_rate(ev: pd.DataFrame, n_syms: int, split: str) -> float:
    """Sembol basina aylik ortalama sinyal sayisi."""
    if len(ev) == 0:
        return 0.0
    months = 18.0 if split == "train" else (6.0 if split == "test" else 24.0)
    return len(ev) / n_syms / months
