"""Zenginlestirilmis paneli (fwd/fwdn/sigma kolonlariyla) parquet olarak
onbellege yazar; sweep scriptleri bunu okur. Kullanim: python build_cache.py <data_dir>"""

import sys
from pathlib import Path

from common import load_panel

data_dir = sys.argv[1]
out = Path(data_dir) / "enriched"
for market in ("spot", "um"):
    (out / market).mkdir(parents=True, exist_ok=True)
    panel = load_panel(data_dir, market)
    for sym, df in panel.items():
        df.to_parquet(out / market / f"{sym}.parquet")
    print(f"{market}: {len(panel)} sembol cachelendi")
