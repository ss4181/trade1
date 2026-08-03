"""Rejim analizi: boga vs ayi piyasasinda sinyaller nasil degisir?

TANIMSAL bir analizdir — yeni strateji/esik ARANMAZ, test atisi harcanmaz.
Mevcut canli konfigurasyonun (S1 RSI<=22.5, S3 log-z>=3.0 yukari-bar,
S2 funding<=-0.03% persistence 2) rejime gore hem SIKLIGI hem SONUCU olculur.

Rejim (BTC, nedensel): kapanis > 200 gunluk (4800 saat) SMA -> BOGA, aksi AYI.
Ek kirilim: BTC'nin son 30 gunluk getirisi.

Kullanim: python research/regime_breakdown.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))
import common  # noqa: E402
import signal_bot as bot  # noqa: E402
from sweep_s1_filters import CORE, EXT, wilder_rsi  # noqa: E402

SMA_HOURS = 4800          # ~200 gun
MOM_HOURS = 720           # ~30 gun
FUNDING_CACHE = Path(__file__).parent / "funding_cache" / "funding_history.json"


def regimes(btc: pd.DataFrame) -> pd.DataFrame:
    c = btc["close"]
    sma = c.rolling(SMA_HOURS, min_periods=SMA_HOURS // 2).mean()
    mom = c / c.shift(MOM_HOURS) - 1
    r = pd.DataFrame(index=c.index)
    r["trend"] = np.where(c.isna() | sma.isna(), None,
                          np.where(c > sma, "BOGA", "AYI"))
    r["mom"] = pd.cut(mom, [-9, -0.10, 0.10, 9],
                      labels=["dusus>%10", "yatay", "yukselis>%10"])
    return r


def log_volume_z(v: pd.Series, window: int = 168) -> pd.Series:
    lv = np.log1p(v)
    return ((lv - lv.rolling(window, min_periods=window // 2).mean())
            / lv.rolling(window, min_periods=window // 2).std())


def s1_events(panel, syms):
    from sweep_s1_filters import build_features, pool_events
    feats = build_features({s: panel[s] for s in syms if s in panel}, None)
    return pool_events(feats, syms, bot.RSI_OVERSOLD)


def s3_events(panel, syms):
    ev = {}
    for s in syms:
        if s not in panel:
            continue
        df = panel[s]
        z = log_volume_z(df["volume"])
        spike = z >= bot.VOLUME_ZSCORE_THRESHOLD
        # bot ile ayni: kenar-tetikleme SPIKE uzerinde, yon filtresi SONRA
        times = common.edge_trigger(spike, bot.S3_COOLDOWN_HOURS)
        if len(times) == 0:
            continue
        up = (df["close"] > df["open"]).reindex(times).fillna(False)
        times = times[up.to_numpy()]
        if len(times):
            ev[s] = (times, np.ones(len(times)))
    return ev


def s2_events(panel, syms):
    if not FUNDING_CACHE.exists():
        return {}
    hist = json.loads(FUNDING_CACHE.read_text())
    thr = bot.FUNDING_SQUEEZE_THRESHOLD_PCT / 100.0
    ev = {}
    for s in syms:
        rows = hist.get(s) or []
        if len(rows) < 3 or s not in panel:
            continue
        fr = pd.Series([r for _t, r in rows],
                       index=pd.to_datetime([t for t, _r in rows], unit="ms",
                                            utc=True)).sort_index()
        cond = (fr <= thr) & (fr.shift(1) <= thr)     # persistence = 2
        # saatlik grid'e tasi (settlement anindan sonraki ilk saat)
        hourly = cond.reindex(panel[s].index, method="ffill", limit=1)
        hourly = hourly.astype("boolean").fillna(False).astype(bool)
        times = common.edge_trigger(hourly, bot.S2_COOLDOWN_HOURS)
        if len(times):
            ev[s] = (times, np.ones(len(times)))
    return ev


def tag(ev_df: pd.DataFrame, reg: pd.DataFrame, col: str) -> pd.Series:
    return reg[col].reindex(ev_df["t"]).to_numpy()


def report(panel, reg, ev, name, horizon, syms, months=24.0):
    df = common.collect_event_returns(panel, ev, "all")
    if len(df) == 0:
        print(f"  {name}: olay yok")
        return
    base = common.baseline_stats(panel, "all")
    print(f"\n### {name} (ufuk {horizon}h) — toplam N={len(df)}")
    for col, label in (("trend", "BTC 200g trendi"), ("mom", "BTC 30g getirisi")):
        vals = tag(df, reg, col)
        print(f"  {label}:")
        print(f"    {'rejim':<16}{'N':>6}{'pay':>7}{'sin/ay':>8}{'isabet':>8}"
              f"{'medyan':>9}{'ort':>8}{'edge':>8}")
        for r in pd.unique(pd.Series(vals).dropna()):
            sub = df[vals == r]
            if len(sub) < 15:
                continue
            hours = float((reg[col] == r).sum())
            mo = hours / 730.0 if hours else np.nan
            s = common.summarize(panel, sub, base, horizon, "all",
                                 with_pval=False)
            if not s.get("N"):
                continue
            rate = len(sub) / len(syms) / mo if mo and mo > 0 else np.nan
            print(f"    {str(r):<16}{s['N']:>6}{len(sub)/len(df)*100:>6.0f}%"
                  f"{rate:>8.2f}{s['winrate']*100:>7.0f}%{s['med_bp']:>9.0f}"
                  f"{s['mean_bp']:>8.0f}{s['edge_voln']:>8.3f}")


def main() -> None:
    panel = common.load_panel(str(Path(__file__).parent / "data"), "spot")
    reg = regimes(panel["BTCUSDT"])
    core = [s for s in CORE if s in panel]
    allsym = core + [s for s in EXT if s in panel]

    tr = reg["trend"].dropna()
    print("=" * 82)
    print("REJIM DAGILIMI (2024-07 -> 2026-06, BTC 200 gunluk SMA)")
    print("=" * 82)
    for r, n in tr.value_counts().items():
        print(f"  {r:<8}{n:>7} saat  (%{n/len(tr)*100:.0f}, ~{n/730:.1f} ay)")
    mm = reg["mom"].dropna()
    for r, n in mm.value_counts().items():
        print(f"  BTC 30g {str(r):<14}{n:>7} saat (%{n/len(mm)*100:.0f})")

    print("\n" + "=" * 82)
    print("STRATEJI BAZINDA (tum 89 sembol, 24 ay, canli konfigurasyon)")
    print("=" * 82)
    report(panel, reg, s1_events(panel, allsym), "S1 (RSI<=22.5 + divergence)",
           24, allsym)
    report(panel, reg, s3_events(panel, core), "S3 (log-z>=3.0, yukari-bar)",
           4, core)
    s2 = s2_events(panel, core)
    if s2:
        report(panel, reg, s2, "S2 (funding<=-0.03%, persistence 2)", 72, core)
    else:
        print("\n### S2: funding onbellegi yok (Ek I scriptini once calistir)")


if __name__ == "__main__":
    main()
