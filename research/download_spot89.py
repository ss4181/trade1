"""S3 arastirmasi icin 89 sembol x 24 ay SPOT 1h verisi (yalniz spot).

Cekirdek 30 + genis 59 = botun canli evreni. Cikti: <out>/spot/*.parquet
Kullanim: python download_spot89.py <out_dir>
"""

import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))
import signal_bot as bot  # noqa: E402
from download_data import MONTHS, job  # noqa: E402


def main(out_dir):
    out = Path(out_dir) / "spot"
    out.mkdir(parents=True, exist_ok=True)
    syms = list(bot.SYMBOLS)
    print(f"{len(syms)} sembol x {len(MONTHS)} ay indiriliyor...", flush=True)
    res, missing, done = {}, set(), 0
    jobs = [(s, m) for s in syms for m in MONTHS]
    with ThreadPoolExecutor(max_workers=16) as pool:
        futs = {pool.submit(job, "spot", s, m): (s, m) for s, m in jobs}
        for f in as_completed(futs):
            s, m = futs[f]
            done += 1
            if done % 400 == 0:
                print(f"  {done}/{len(jobs)}", flush=True)
            _, _, _, df = f.result()
            if df is None:
                missing.add(s)
            else:
                res.setdefault(s, {})[m] = df
    kept = 0
    for s, months in res.items():
        if s in missing or len(months) < len(MONTHS):
            continue
        df = pd.concat([months[m] for m in sorted(months)], ignore_index=True)
        df.sort_values("open_time").drop_duplicates("open_time").to_parquet(
            out / f"{s}.parquet", index=False)
        kept += 1
    print(f"bitti: {kept} sembol tam veriyle yazildi "
          f"(eksikli: {len(missing)})", flush=True)


if __name__ == "__main__":
    main(sys.argv[1])
