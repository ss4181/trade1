"""Descriptive hourly regime churn review; no tuning, P&L claim or bot import."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from intraday_regime import trend, HOUR, VERSION
from research.market_regime_review import daily_table, labels, load_hourly


def series(frame, start, end):
    bars = [{"time": int(row.open_time), "open": row.open, "high": row.high,
             "low": row.low, "close": row.close} for row in frame.itertuples()]
    output = {}
    for i in range(239, len(bars)):
        close = bars[i]["time"]+HOUR
        if not start <= close < end:
            continue
        window = bars[i-239:i+1]
        if not frame.valid.iloc[i-239:i+1].all():
            continue
        current, previous = trend(window)["label"], trend(window, offset=1)["label"]
        output[close] = current if current == previous else "TRANSITION"
    return output


def describe(values):
    runs, current = [], 1
    for a, b in zip(values, values[1:]):
        if a == b:
            current += 1
        else:
            runs.append(current)
            current = 1
    runs.append(current)
    return {"hours": len(values), "counts": dict(Counter(values)),
            "changes": len(runs)-1, "median_run_hours": float(np.median(runs))}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--data", type=Path, required=True)
    p.add_argument("--daily", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    start = int(pd.Timestamp("2026-01-01", tz="UTC").timestamp()*1000)
    end = int(pd.Timestamp("2026-07-01", tz="UTC").timestamp()*1000)
    sources = [args.data/"spot"/(symbol+".parquet") for symbol in ("BTCUSDT", "ETHUSDT")]
    btc, eth = [series(load_hourly(path), start, end) for path in sources]
    stamps = sorted(set(btc) & set(eth))
    if stamps != list(range(start, end, HOUR)):
        raise ValueError("incomplete_comparison_period")
    hourly = [btc[t] if btc[t] == eth[t] else "TRANSITION" for t in stamps]
    daily = list(labels(daily_table(json.loads(args.daily.read_text())), stamps)[0])
    report = {"version": VERSION, "start_utc": "2026-01-01T00:00:00Z",
              "end_exclusive_utc": "2026-07-01T00:00:00Z", "hourly": describe(hourly),
              "daily": describe(daily), "disagreement_hours": sum(a!=b for a,b in zip(hourly,daily)),
              "scope": "descriptive_churn_only_not_strategy_success_or_invalidation_validation",
              "fifteen_minute_backtest": "not_performed_no_matching_local_spot_15m_archive",
              "sources": [{"file": str(path.name), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
                          for path in sources+[args.daily, Path(__file__).resolve().parents[1]/"intraday_regime.py"]]}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2)+"\n")
    print(json.dumps({k:v for k,v in report.items() if k != "sources"}, indent=2))


if __name__ == "__main__":
    main()
