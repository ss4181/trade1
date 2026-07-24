"""Ortak analiz altyapisi: panel yukleme, ileri getiriler, olay degerlendirme."""

import json
from pathlib import Path

import numpy as np
import pandas as pd

HORIZONS = [1, 2, 4, 8, 12, 24, 48, 72]
VOL_WINDOW = 168          # gerceklesen volatilite penceresi (saat)
TRAIN_END = pd.Timestamp("2026-01-01", tz="UTC")   # train < bu, test >= bu
BOOTSTRAP_ITERATIONS = 2000


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


def split_mask(times: pd.DatetimeIndex, split: str,
               horizon_hours: int = 0) -> np.ndarray:
    """Train/test maskesi; train ileri getirilerini sinirda purge eder.

    Olay ``t`` aninda olusur, giris ``t+1`` acilisi ve ``h`` saatlik cikis
    ``t+h`` kapanisidir. Bu nedenle train olayinin cikis bari test donemine
    degiyorsa ilgili ufuk train ornekleminden cikarilir. ``horizon_hours=0``
    eski olay-zamani maskesini korur.
    """
    if horizon_hours < 0:
        raise ValueError("horizon_hours negatif olamaz")
    if split == "train":
        mask = times < TRAIN_END
        if horizon_hours:
            mask &= times + pd.Timedelta(hours=horizon_hours) < TRAIN_END
        return np.asarray(mask, dtype=bool)
    if split == "test":
        return np.asarray(times >= TRAIN_END, dtype=bool)
    return np.ones(len(times), dtype=bool)


def collect_event_returns(panel: dict, events: dict, split: str) -> pd.DataFrame:
    """events: sym -> (DatetimeIndex, yon dizisi +1/-1).
    Donus: satir=olay, kolonlar sym, t, dir, fwd_H, fwdn_H (yon-carpimli).

    Train/test sinirindaki olay satiri korunur; test fiyatina tasan ufuklar
    NaN yapilir. Boylece ayni olay tablosu birden cok ufukta guvenle
    kullanilabilir ve kisa ufuklar gereksiz yere 72 saat purge edilmez.
    """
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
            valid = split_mask(times, split, horizon_hours=h)
            fwd = sel[f"fwd_{h}"].to_numpy() * dirs
            fwdn = sel[f"fwdn_{h}"].to_numpy() * dirs
            out[f"fwd_{h}"] = np.where(valid, fwd, np.nan)
            out[f"fwdn_{h}"] = np.where(valid, fwdn, np.nan)
        rows.append(out)
    if not rows:
        return pd.DataFrame()
    return pd.concat(rows, ignore_index=True)


def baseline_stats(panel: dict, split: str) -> dict[str, pd.DataFrame]:
    """Sembol basina kosulsuz istatistikler (long yonu): mean fwd, mean fwdn,
    winrate. Kisa yon icin isaretler ters cevrilir."""
    out = {}
    for sym, df in panel.items():
        stats = {}
        for h in HORIZONS:
            sub = df.loc[split_mask(df.index, split, horizon_hours=h)]
            f = sub[f"fwd_{h}"].dropna()
            fn = sub[f"fwdn_{h}"].dropna()
            stats[h] = (f.mean(), fn.mean(), (f > 0).mean())
        out[sym] = pd.DataFrame(stats, index=["mean_fwd", "mean_fwdn", "winrate"]).T
    return out


def bootstrap_pvalue(panel: dict, ev: pd.DataFrame, h: int, split: str,
                     n_iter: int = BOOTSTRAP_ITERATIONS, seed: int = 7) -> float:
    """Sembol-eslesmeli bootstrap: her sembolden olay sayisi kadar rastgele bar
    cek, yon dagilimini koruyarak isaretle, ortalama fwdn dagilimi cikar.
    p = P(rastgele >= gercek).

    Monte Carlo p-degerinde plus-one duzeltmesi kullanilir; sonlu simulasyonda
    sahte ``p=0`` raporlanmaz.
    """
    if n_iter <= 0:
        raise ValueError("n_iter pozitif olmali")
    rng = np.random.default_rng(seed)
    col = f"fwdn_{h}"
    ev = ev.dropna(subset=[col])
    if len(ev) == 0:
        return np.nan
    actual = ev[col].mean()
    pools, counts, dirpools = [], [], []
    for sym, g in ev.groupby("sym"):
        df = panel[sym]
        sub = df.loc[split_mask(df.index, split, horizon_hours=h)]
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
    exceedances = int(np.count_nonzero(sims >= actual))
    return float((exceedances + 1) / (n_iter + 1))


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
