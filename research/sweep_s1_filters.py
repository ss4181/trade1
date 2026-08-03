"""Ek J — "Daha cok sinyal + guclendirici metrik" arayisi (2026-08-03).

SORU (kullanici): S1'i gevsetip daha COK sinyal uretelim, ama her sinyali
degerlendiren bir metrik ekleyip isabeti %55+ ve medyani maliyetin ustunde
tutalim. Boyle bir metrik var mi?

ONCEDEN KAYITLI PROTOKOL (REPORT.md §10):
  Havuz     : S1 divergence, RSI <= T, T in {22.5, 25, 27.5, 30}
              kenar-tetikleme + 12h cooldown (canli botla birebir), ufuk 24h
  Tasarim   : cekirdek-30, TRAIN (< 2026-01-01)
  Bagimsiz  : genis-59, TRAIN — S1 FILTRE tasariminda hic kullanilmadi
  Test 2026H1: kazanan bagimsiz kumede de gecerse ACILIR; aksi halde HIC
              bakilmaz.
  Gecme olcutu (ONCEDEN, tek): filtreli havuzda ayni anda
      isabet >= %55  VE  medyan >= 12bp (gidis-donus maliyet)  VE
      sinyal sayisi mevcut 22.5 havuzundan FAZLA (amac daha cok sinyal)
  Coklu karsilastirma serhi: 10 metrik x 6 bolme x 4 esik = ~240 train
  denemesi. Train'de "kazanan" cikmasi SANS ESERI beklenir; bu yuzden karar
  YALNIZCA bagimsiz kume sonucuna gore verilir (Ek H'de ayni desen gorulmustu).

Kullanim: python research/sweep_s1_filters.py [--data DIR]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))
import common  # noqa: E402
import signal_bot as bot  # noqa: E402

RSI_PERIOD = 14
GAP = 5
LOOKBACK = 60
COOLDOWN = 12
HORIZON = 24
COST_BP = 12.0
POOL_THRESHOLDS = [22.5, 25.0, 27.5, 30.0]
QUANTILES = [0.25, 0.33, 0.50, 0.67, 0.75]

CORE = [s.strip() for s in bot.DEFAULT_SYMBOLS.split(",")]
EXT = sorted(bot.EXTENDED_SET)


def wilder_rsi(close: pd.Series, period: int = RSI_PERIOD) -> pd.Series:
    d = close.diff()
    gain = d.clip(lower=0.0)
    loss = (-d).clip(lower=0.0)
    ag = gain.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    al = loss.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    rs = ag / al.replace(0.0, np.nan)
    out = 100 - 100 / (1 + rs)
    return out.where(al != 0, 100.0)


def divergence_parts(low: np.ndarray, rsi: np.ndarray):
    """Botun bullish_divergence tanimiyla birebir: bar i icin onceki dip
    penceresi low[i-64 : i-5] (60 bar). Doner: (pmin, rsi_at_pmin)."""
    n = len(low)
    pmin = np.full(n, np.nan)
    rsi_at = np.full(n, np.nan)
    if n < GAP + LOOKBACK:
        return pmin, rsi_at
    win = np.lib.stride_tricks.sliding_window_view(low, LOOKBACK)
    for i in range(GAP + LOOKBACK - 1, n):
        j = i - GAP - LOOKBACK + 1          # pencere baslangic indeksi
        if j < 0 or j >= len(win):
            continue
        w = win[j]
        k = int(np.nanargmin(w)) if not np.all(np.isnan(w)) else None
        if k is None:
            continue
        pmin[i] = w[k]
        rsi_at[i] = rsi[j + k]
    return pmin, rsi_at


def build_features(panel: dict[str, pd.DataFrame],
                   btc_rsi: pd.Series | None) -> dict[str, pd.DataFrame]:
    feats = {}
    for sym, df in panel.items():
        c, h, l, v = df["close"], df["high"], df["low"], df["volume"]
        rsi = wilder_rsi(c)
        pmin, rsi_at = divergence_parts(l.to_numpy(float), rsi.to_numpy(float))
        f = pd.DataFrame(index=df.index)
        f["rsi"] = rsi
        f["div"] = (l.to_numpy(float) < pmin) & (rsi.to_numpy(float) > rsi_at)
        # --- aday guclendirici metrikler (hepsi sinyal barinda BILINIR) ---
        f["div_strength"] = rsi - rsi_at             # uyusmazligin buyuklugu
        f["rsi_turn"] = rsi - rsi.shift(1)           # RSI zaten donuyor mu
        f["drawdown_168"] = c / h.rolling(168, min_periods=48).max() - 1
        f["undercut"] = l / pmin - 1                 # dibi ne kadar kirdi
        rng = (h - l).replace(0, np.nan)
        f["bar_close_pos"] = (c - l) / rng           # bar icinde kapanis yeri
        lv = np.log1p(v)
        f["vol_z"] = ((lv - lv.rolling(168, min_periods=84).mean())
                      / lv.rolling(168, min_periods=84).std())
        sig = df["logret"].rolling(168, min_periods=100).std()
        f["sigma_pct"] = sig.rolling(720, min_periods=200).rank(pct=True)
        f["consec_down"] = (c < c.shift(1)).astype(int).groupby(
            (c >= c.shift(1)).cumsum()).cumsum()
        qv = df["quote_volume"]
        f["liq_ratio"] = qv / qv.rolling(168, min_periods=84).median()
        if btc_rsi is not None:
            f["btc_rsi"] = btc_rsi.reindex(f.index)
        feats[sym] = f
    return feats


METRICS = ["div_strength", "rsi_turn", "drawdown_168", "undercut",
           "bar_close_pos", "vol_z", "sigma_pct", "consec_down",
           "liq_ratio", "btc_rsi"]


def pool_events(feats: dict, syms: list[str], thr: float) -> dict:
    ev = {}
    for sym in syms:
        f = feats.get(sym)
        if f is None:
            continue
        cond = f["div"] & (f["rsi"] <= thr)
        times = common.edge_trigger(cond, COOLDOWN)
        if len(times):
            ev[sym] = (times, np.ones(len(times)))
    return ev


def attach(ev_df: pd.DataFrame, feats: dict) -> pd.DataFrame:
    for m in METRICS:
        vals = []
        for _, r in ev_df.iterrows():
            f = feats.get(r["sym"])
            vals.append(np.nan if f is None or m not in f
                        else f[m].get(r["t"], np.nan))
        ev_df[m] = vals
    return ev_df


def row(panel, ev, base, label, split, n_syms):
    s = common.summarize(panel, ev, base, HORIZON, split, with_pval=False)
    if not s.get("N"):
        return None
    s["label"] = label
    s["rate"] = common.per_month_rate(ev, n_syms, split)
    return s


def fmt(s) -> str:
    return (f"{s['label']:<34}{s['N']:>6}{s['rate']:>7.2f}"
            f"{s['winrate']*100:>8.0f}%{s['med_bp']:>9.0f}"
            f"{s['mean_bp']:>9.0f}{s['edge_voln']:>9.3f}")


HEAD = (f"{'kurulum':<34}{'N':>6}{'sin/ay':>7}{'isabet':>9}{'medyan':>9}"
        f"{'ortalama':>9}{'edge':>9}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=str(Path(__file__).parent / "data"))
    args = ap.parse_args()

    panel = common.load_panel(args.data, "spot")
    print(f"panel: {len(panel)} sembol")
    btc = panel.get("BTCUSDT")
    btc_rsi = wilder_rsi(btc["close"]) if btc is not None else None
    feats = build_features(panel, btc_rsi)
    base_tr = common.baseline_stats(panel, "train")

    core = {s: panel[s] for s in CORE if s in panel}
    ext = {s: panel[s] for s in EXT if s in panel}
    print(f"cekirdek-30: {len(core)} · genis-59: {len(ext)}\n")

    # ---------- 1. havuzlar (filtresiz) ----------
    print("=" * 84)
    print("1) HAVUZLAR — S1 esigi gevsetilince ne oluyor? (cekirdek-30, TRAIN)")
    print("=" * 84)
    print(HEAD)
    pools = {}
    for thr in POOL_THRESHOLDS:
        ev = pool_events(feats, list(core), thr)
        df = common.collect_event_returns(panel, ev, "train")
        if len(df) == 0:
            continue
        pools[thr] = df
        r = row(panel, df, base_tr, f"S1 RSI<={thr} (filtresiz)", "train",
                len(core))
        if r:
            print(fmt(r))
    baseline_n = len(pools.get(22.5, pd.DataFrame()))
    print(f"\nOlcut: isabet >= %55 VE medyan >= {COST_BP:.0f}bp VE "
          f"N > {baseline_n} (mevcut 22.5 havuzu)")

    # ---------- 2. metrik taramasi ----------
    print("\n" + "=" * 84)
    print("2) GUCLENDIRICI METRIK TARAMASI (cekirdek-30 TRAIN — TASARIM)")
    print("=" * 84)
    winners = []
    for thr, df in pools.items():
        df = attach(df.copy(), feats)
        for m in METRICS:
            if m not in df or df[m].notna().sum() < 50:
                continue
            for q in QUANTILES:
                cut = df[m].quantile(q)
                for side, sub in (("<=", df[df[m] <= cut]),
                                  (">=", df[df[m] >= cut])):
                    if len(sub) < 40:
                        continue
                    r = row(panel, sub, base_tr,
                            f"RSI<={thr} · {m}{side}{cut:.3g}", "train",
                            len(core))
                    if not r:
                        continue
                    r["thr"], r["metric"], r["side"], r["cut"] = thr, m, side, cut
                    if (r["winrate"] >= 0.55 and r["med_bp"] >= COST_BP
                            and r["N"] > baseline_n):
                        winners.append(r)
    if not winners:
        print("TRAIN'de olcutu gecen kurulum YOK "
              "(isabet>=%55 & medyan>=12bp & N>mevcut).")
    else:
        winners.sort(key=lambda r: -r["med_bp"])
        print(HEAD)
        for r in winners[:12]:
            print(fmt(r))
        print(f"\nToplam {len(winners)} kurulum train olcutunu gecti "
              "(coklu karsilastirma: bu BEKLENEN, kanit DEGIL).")

    # ---------- 3. bagimsiz kume ----------
    if winners:
        print("\n" + "=" * 84)
        print("3) BAGIMSIZ DOGRULAMA — genis-59, TRAIN (tasarimda kullanilmadi)")
        print("=" * 84)
        print(HEAD)
        survived = []
        for r in winners[:12]:
            ev = pool_events(feats, list(ext), r["thr"])
            df = common.collect_event_returns(panel, ev, "train")
            if len(df) == 0:
                continue
            df = attach(df, feats)
            sub = (df[df[r["metric"]] <= r["cut"]] if r["side"] == "<="
                   else df[df[r["metric"]] >= r["cut"]])
            rr = row(panel, sub, base_tr,
                     f"RSI<={r['thr']} · {r['metric']}{r['side']}{r['cut']:.3g}",
                     "train", len(ext))
            if rr:
                print(fmt(rr))
                if rr["winrate"] >= 0.55 and rr["med_bp"] >= COST_BP:
                    survived.append((r, rr))
        print(f"\nBagimsiz kumede AYNI olcutu gecen: {len(survived)}/"
              f"{min(12, len(winners))}")
        if not survived:
            print("KARAR: hicbiri gecmedi -> uygulanmaz, test dilimine "
                  "BAKILMADI.")
        else:
            print("Aday(lar) bagimsiz kumede de gecti -> test atisi "
                  "degerlendirilebilir (REPORT §10).")


if __name__ == "__main__":
    main()
