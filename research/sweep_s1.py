"""S1 (RSI uyumsuzlugu) esik taramasi.

Bearish (short) ve bullish (long) taraflar AYRI taranir; iki varyant:
  div  : RSI ekstremi + fiyat yeni tepe/dip + RSI uyumsuzlugu (botun mantigi)
  plain: sadece RSI ekstremi
Kullanim: python sweep_s1.py <data_dir> <split>   (split: train|test|all)
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

from common import (HORIZONS, baseline_stats, collect_event_returns,
                    edge_trigger, per_month_rate, summarize)
from strategies import _rolling_argmax_val, wilder_rsi

LOOKBACK, GAP, COOLDOWN = 60, 5, 12
OB_GRID = [70, 72.5, 75, 77.5, 80, 82.5, 85, 87.5, 90]
OS_GRID = [10, 12.5, 15, 17.5, 20, 22.5, 25, 27.5, 30]
REPORT_H = [4, 12, 24, 48, 72]


def load_enriched(data_dir, market):
    out = {}
    for f in sorted(Path(data_dir, "enriched", market).glob("*.parquet")):
        out[f.stem] = pd.read_parquet(f)
    return out


def precompute(panel):
    feats = {}
    for sym, df in panel.items():
        rsi = wilder_rsi(df["close"]).to_numpy()
        high, low = df["high"].to_numpy(), df["low"].to_numpy()
        pmax, imax = _rolling_argmax_val(high, LOOKBACK, GAP, "max")
        pmin, imin = _rolling_argmax_val(low, LOOKBACK, GAP, "min")
        feats[sym] = dict(
            idx=df.index, rsi=rsi, high=high, low=low, pmax=pmax, pmin=pmin,
            rsi_at_max=np.where(imax >= 0, rsi[imax], np.nan),
            rsi_at_min=np.where(imin >= 0, rsi[imin], np.nan))
    return feats


def gen_events(feats, side, thresh, variant):
    events = {}
    for sym, f in feats.items():
        r = f["rsi"]
        if side == "bear":
            cond = r >= thresh
            if variant == "div":
                cond &= (f["high"] > f["pmax"]) & (r < f["rsi_at_max"])
            d = -1
        else:
            cond = r <= thresh
            if variant == "div":
                cond &= (f["low"] < f["pmin"]) & (r > f["rsi_at_min"])
            d = 1
        times = edge_trigger(pd.Series(cond, index=f["idx"]), COOLDOWN)
        events[sym] = (times, np.full(len(times), d))
    return events


def main(data_dir, split):
    panel = load_enriched(data_dir, "spot")
    feats = precompute(panel)
    base = baseline_stats(panel, split)
    rows = []
    for variant in ("div", "plain"):
        for side, grid in (("bear", OB_GRID), ("bull", OS_GRID)):
            for th in grid:
                ev = collect_event_returns(
                    panel, gen_events(feats, side, th, variant), split)
                row = {"variant": variant, "side": side, "thresh": th,
                       "sig_per_sym_month": round(per_month_rate(ev, len(panel), split), 2)}
                for h in REPORT_H:
                    s = summarize(panel, ev, base, h, split,
                                  with_pval=(h == 24))
                    row[f"N_{h}"] = s.get("N", 0)
                    row[f"edge_voln_{h}"] = round(s.get("edge_voln", np.nan), 4)
                    row[f"edge_bp_{h}"] = round(s.get("edge_bp", np.nan), 1)
                    row[f"wr_edge_{h}"] = round(s.get("wr_edge", np.nan), 4)
                    if h == 24:
                        row["p24"] = s.get("p_boot", np.nan)
                        row["med_bp_24"] = round(s.get("med_bp", np.nan), 1)
                        row["q10_24"] = round(s.get("q10_bp", np.nan), 0)
                        row["q90_24"] = round(s.get("q90_bp", np.nan), 0)
                rows.append(row)
                print(f"{variant:5s} {side:4s} th={th:5.1f} "
                      f"N={row['N_24']:5d} rate={row['sig_per_sym_month']:5.2f} "
                      f"edge24={row['edge_voln_24']:+.3f} p24={row['p24']:.3f} "
                      f"edge72={row['edge_voln_72']:+.3f}", flush=True)
    out = pd.DataFrame(rows)
    res = Path(__file__).parent / "results"
    res.mkdir(exist_ok=True)
    out.to_csv(res / f"s1_sweep_{split}.csv", index=False)
    print(f"yazildi: results/s1_sweep_{split}.csv")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
