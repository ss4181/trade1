"""S3 (hacim anomalisi) esik taramasi.

Z esigi x pencere x log/raw x yon hipotezi (momentum devam / fade).
Spot verisi uzerinde.
Kullanim: python sweep_s3.py <data_dir> <split>
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

from common import baseline_stats, collect_event_returns, per_month_rate, summarize
from strategies import s3_events

Z_GRID = [2.0, 2.5, 3.0, 3.5, 4.0, 5.0]
VARIANTS = [  # (direction, use_log, window)
    ("bar", False, 168),
    ("bar", False, 720),
    ("bar", True, 168),
    ("bar_up", False, 168),
    ("bar_down", False, 168),
    ("long", False, 168),
    ("short", False, 168),
]
REPORT_H = [1, 2, 4, 12, 24, 48]


def main(data_dir, split):
    panel = {f.stem: pd.read_parquet(f)
             for f in sorted(Path(data_dir, "enriched", "spot").glob("*.parquet"))}
    base = baseline_stats(panel, split)
    rows = []
    for direction, use_log, window in VARIANTS:
        for z in Z_GRID:
            ev = collect_event_returns(
                panel, s3_events(panel, z, window, use_log, direction=direction),
                split)
            row = {"direction": direction, "log": use_log, "window": window,
                   "z": z,
                   "sig_per_sym_month": round(per_month_rate(ev, len(panel), split), 2)}
            for h in REPORT_H:
                s = summarize(panel, ev, base, h, split, with_pval=(h in (4, 24)))
                row[f"N_{h}"] = s.get("N", 0)
                row[f"edge_voln_{h}"] = round(s.get("edge_voln", np.nan), 4)
                row[f"edge_bp_{h}"] = round(s.get("edge_bp", np.nan), 1)
                row[f"wr_edge_{h}"] = round(s.get("wr_edge", np.nan), 4)
                if h in (4, 24):
                    row[f"p{h}"] = s.get("p_boot", np.nan)
            rows.append(row)
            print(f"{direction:9s} log={int(use_log)} w={window:3d} z={z:.1f} "
                  f"N={row['N_4']:5d} rate={row['sig_per_sym_month']:5.2f} "
                  f"edge4={row['edge_voln_4']:+.3f} p4={row['p4']:.3f} "
                  f"edge24={row['edge_voln_24']:+.3f} p24={row['p24']:.3f}", flush=True)
    out = pd.DataFrame(rows)
    res = Path(__file__).parent / "results"
    res.mkdir(exist_ok=True)
    out.to_csv(res / f"s3_sweep_{split}.csv", index=False)
    print(f"yazildi: results/s3_sweep_{split}.csv")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
