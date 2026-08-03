"""Ek J — 2. asama: adayi SAGLAMLASTIR, DONDUR, tek test atisini yap.

1. asama (sweep_s1_filters.py) train'de 127 kurulum buldu; ilk 12'sinin
TAMAMI bagimsiz kumede (genis-59) de olcutu gecti. Kazananlarin hepsi ayni
iki mekanizmanin varyantiydi: (a) sinyal barinda HACIM patlamasi,
(b) 168h zirvesinden derin DUSUS.

Bu asamada:
  1) Kuantil-turevli cirkin esikler yerine YUVARLAK esikler denenir.
  2) Aday, alt donemlerde (2024H2/2025H1/2025H2) kararli mi diye bakilir.
  3) S4 ile ortusme olculur — bu zaten bilinen mekanizmanin tekrari mi?
  4) TEK bir konfigurasyon DONDURULUR ve test dilimine (2026H1) TEK atis.

Test atisi `--test` ile acilir; once train ciktisina bakilmalidir.
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
from sweep_s1_filters import (CORE, EXT, HORIZON, COST_BP, build_features,
                              pool_events, wilder_rsi)  # noqa: E402

ROUND_VOLZ = [1.0, 1.25, 1.5, 1.75, 2.0, 2.5, 3.0]
ROUND_DD = [-0.15, -0.20, -0.25, -0.30]
POOLS = [22.5, 25.0, 27.5, 30.0]
SUBPERIODS = [("2024H2", "2024-07-01", "2025-01-01"),
              ("2025H1", "2025-01-01", "2025-07-01"),
              ("2025H2", "2025-07-01", "2026-01-01")]

HEAD = (f"{'kurulum':<32}{'N':>6}{'sin/ay':>7}{'isabet':>8}{'medyan':>8}"
        f"{'ort':>8}{'edge':>8}{'p':>7}")


def evaluate(panel, feats, base, syms, split, thr, metric=None, op=None,
             cut=None, label="", pval=False):
    ev = pool_events(feats, list(syms), thr)
    df = common.collect_event_returns(panel, ev, split)
    if len(df) == 0:
        return None
    if metric is not None:
        vals = np.array([feats[r["sym"]][metric].get(r["t"], np.nan)
                         if r["sym"] in feats else np.nan
                         for _, r in df.iterrows()])
        df = df[vals >= cut] if op == ">=" else df[vals <= cut]
        if len(df) == 0:
            return None
    s = common.summarize(panel, df, base, HORIZON, split, with_pval=pval)
    if not s.get("N"):
        return None
    s["label"] = label
    s["rate"] = common.per_month_rate(df, len(syms), split)
    s["_df"] = df
    return s


def line(s) -> str:
    p = s.get("p_boot")
    ps = f"{p:>7.3f}" if p is not None and not pd.isna(p) else f"{'-':>7}"
    return (f"{s['label']:<32}{s['N']:>6}{s['rate']:>7.2f}"
            f"{s['winrate']*100:>7.0f}%{s['med_bp']:>8.0f}"
            f"{s['mean_bp']:>8.0f}{s['edge_voln']:>8.3f}{ps}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=str(Path(__file__).parent / "data"))
    ap.add_argument("--test", action="store_true",
                    help="DONDURULMUS konfig icin tek test atisi")
    args = ap.parse_args()

    panel = common.load_panel(args.data, "spot")
    btc = panel.get("BTCUSDT")
    feats = build_features(panel, wilder_rsi(btc["close"]) if btc is not None
                           else None)
    base_tr = common.baseline_stats(panel, "train")
    core = [s for s in CORE if s in panel]
    ext = [s for s in EXT if s in panel]

    print("=" * 86)
    print("1) YUVARLAK ESIKLER — hacim patlamasi (vol_z), cekirdek-30 TRAIN")
    print("=" * 86)
    print(HEAD)
    for thr in POOLS:
        for z in ROUND_VOLZ:
            s = evaluate(panel, feats, base_tr, core, "train", thr,
                         "vol_z", ">=", z, f"RSI<={thr} · vol_z>={z}")
            if s and s["N"] >= 60:
                print(line(s))
        print()

    print("=" * 86)
    print("2) AYNI YUVARLAK ESIKLER — genis-59 TRAIN (BAGIMSIZ)")
    print("=" * 86)
    print(HEAD)
    for thr in POOLS:
        for z in ROUND_VOLZ:
            s = evaluate(panel, feats, base_tr, ext, "train", thr,
                         "vol_z", ">=", z, f"RSI<={thr} · vol_z>={z}")
            if s and s["N"] >= 60:
                print(line(s))
        print()

    print("=" * 86)
    print("3) KARSILASTIRMA TABANI — mevcut canli konfig (filtresiz RSI<=22.5)")
    print("=" * 86)
    print(HEAD)
    for name, syms in (("cekirdek-30", core), ("genis-59", ext)):
        s = evaluate(panel, feats, base_tr, syms, "train", 22.5,
                     label=f"MEVCUT RSI<=22.5 · {name}", pval=True)
        if s:
            print(line(s))

    # ---- alt donem kararliligi (aday, TRAIN icinde) ----
    print("\n" + "=" * 86)
    print("4) ALT DONEM KARARLILIGI — RSI<=30 · vol_z>=1.5 (tum 89, TRAIN)")
    print("=" * 86)
    s = evaluate(panel, feats, base_tr, core + ext, "train", 30.0,
                 "vol_z", ">=", 1.5, "tum train")
    if s:
        df = s["_df"]
        print(f"{'donem':<12}{'N':>6}{'isabet':>8}{'medyan':>9}{'ort':>9}")
        for name, a, b in SUBPERIODS:
            m = ((df["t"] >= pd.Timestamp(a, tz="UTC"))
                 & (df["t"] < pd.Timestamp(b, tz="UTC")))
            sub = df[m].dropna(subset=[f"fwd_{HORIZON}"])
            if len(sub) < 20:
                continue
            r = sub[f"fwd_{HORIZON}"]
            print(f"{name:<12}{len(sub):>6}{(r > 0).mean()*100:>7.0f}%"
                  f"{r.median()*1e4:>9.0f}{r.mean()*1e4:>9.0f}")

    # ---- S4 ile ortusme: bu zaten bilinen mekanizma mi? ----
    print("\n" + "=" * 86)
    print("5) S4 ORTUSMESI — aday sinyallerin kaci zaten S1+S4 olurdu?")
    print("=" * 86)
    if s:
        df = s["_df"]
        hit_s4 = hit_cur = 0
        for _, r in df.iterrows():
            f = feats.get(r["sym"])
            if f is None:
                continue
            win = f["vol_z"].loc[:r["t"]].tail(bot.CONFLUENCE_LOOKBACK_HOURS + 1)
            if (win >= bot.VOLUME_ZSCORE_THRESHOLD).any():
                hit_s4 += 1
            if f["rsi"].get(r["t"], np.nan) <= 22.5:
                hit_cur += 1
        n = len(df)
        print(f"Aday sinyal sayisi        : {n}")
        print(f"Zaten S4 kosulunu tasiyan : {hit_s4} (%{hit_s4/n*100:.0f}) "
              f"-> mevcut S1+S4 etiketiyle ortusur")
        print(f"Zaten RSI<=22.5 olan      : {hit_cur} (%{hit_cur/n*100:.0f}) "
              f"-> mevcut S1 zaten uretiyor")
        print(f"TAMAMEN YENI sinyal       : "
              f"{n - hit_cur} (%{(n-hit_cur)/n*100:.0f})")

    if not args.test:
        print("\n(Test atisi icin --test; once yukaridaki train tablolarina bak.)")
        return

    # ---------------- DONDURULMUS KONFIG — TEK TEST ATISI ----------------
    # KARAR KONFIGU (test'i GORMEDEN, train tablolarina bakarak donduruldu):
    #   RSI <= 30.0 · vol_z >= 1.5
    # Gerekce: kullanicinin hedefi DAHA COK sinyal; 30/1.5 cekirdekte
    # 0.84 sin/sembol/ay (mevcut 0.38'in 2.2 kati) verirken train'de her iki
    # kumede de isabet %62 ve medyan 124-160bp (maliyet 12bp) tutuyor.
    # 27.5/1.5 BILGI AMACLI birlikte yazdirilir (karar ondan degistirilmez);
    # boylece "test'i gorup en iyisini secme" imkani ONCEDEN kapatilmistir.
    FROZEN = (30.0, 1.5)
    INFO = (27.5, 1.5)
    print("\n" + "=" * 86)
    print(f"6) TEST 2026H1 — KARAR KONFIGU: RSI<={FROZEN[0]} · "
          f"vol_z>={FROZEN[1]}  (TEK ATIS)")
    print("=" * 86)
    base_te = common.baseline_stats(panel, "test")
    print(HEAD)
    for name, syms in (("cekirdek-30", core), ("genis-59", ext),
                       ("tum 89", core + ext)):
        for tag, (t, z) in (("KARAR", FROZEN), ("bilgi", INFO)):
            s = evaluate(panel, feats, base_te, syms, "test", t, "vol_z",
                         ">=", z, f"{tag} RSI<={t}/z>={z} · {name}",
                         pval=(tag == "KARAR"))
            if s:
                print(line(s))
        b = evaluate(panel, feats, base_te, syms, "test", 22.5,
                     label=f"MEVCUT RSI<=22.5 · {name}", pval=True)
        if b:
            print(line(b))
        print()


if __name__ == "__main__":
    main()
