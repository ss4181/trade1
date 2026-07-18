"""S2 (funding squeeze) esik taramasi.

Negatif funding esigi + persistence varyanti; degerlendirme perp (um)
fiyatlari uzerinde, yon LONG.
Kullanim: python sweep_s2.py <data_dir> <split>
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

from common import baseline_stats, collect_event_returns, per_month_rate, summarize
from strategies import s2_events

THRESH_GRID = [-0.005, -0.01, -0.015, -0.02, -0.03, -0.04, -0.05, -0.075, -0.10]
REPORT_H = [4, 8, 12, 24, 48, 72]


def main(data_dir, split):
    panel = {f.stem: pd.read_parquet(f)
             for f in sorted(Path(data_dir, "enriched", "um").glob("*.parquet"))}
    funding = {f.stem: pd.read_parquet(f)
               for f in sorted(Path(data_dir, "funding").glob("*.parquet"))}
    base = baseline_stats(panel, split)
    rows = []
    for persistence in (1, 2):
        for th in THRESH_GRID:
            ev = collect_event_returns(
                panel, s2_events(funding, th, persistence), split)
            row = {"persistence": persistence, "thresh_pct": th,
                   "sig_per_sym_month": round(per_month_rate(ev, len(panel), split), 2)}
            for h in REPORT_H:
                s = summarize(panel, ev, base, h, split, with_pval=(h in (8, 24, 72)))
                row[f"N_{h}"] = s.get("N", 0)
                row[f"edge_voln_{h}"] = round(s.get("edge_voln", np.nan), 4)
                row[f"edge_bp_{h}"] = round(s.get("edge_bp", np.nan), 1)
                row[f"wr_edge_{h}"] = round(s.get("wr_edge", np.nan), 4)
                if h in (8, 24, 72):
                    row[f"p{h}"] = s.get("p_boot", np.nan)
                if h == 24:
                    row["med_bp_24"] = round(s.get("med_bp", np.nan), 1)
                    row["q10_24"] = round(s.get("q10_bp", np.nan), 0)
                    row["q90_24"] = round(s.get("q90_bp", np.nan), 0)
            rows.append(row)
            print(f"pers={persistence} th={th:+.3f}% N={row['N_24']:4d} "
                  f"rate={row['sig_per_sym_month']:5.2f} "
                  f"edge24={row['edge_voln_24']:+.3f} p24={row['p24']:.3f} "
                  f"edge72={row['edge_voln_72']:+.3f} p72={row['p72']:.3f}", flush=True)
    out = pd.DataFrame(rows)
    res = Path(__file__).parent / "results"
    res.mkdir(exist_ok=True)
    out.to_csv(res / f"s2_sweep_{split}.csv", index=False)
    print(f"yazildi: results/s2_sweep_{split}.csv")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
