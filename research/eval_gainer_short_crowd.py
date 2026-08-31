"""G1: günün yükseleni + hacim/OI artışı + short hesap çoğunluğu testi."""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from common import TRAIN_END, edge_trigger
from eval_pump_short_squeeze import cluster_pvalue

RETURN_MIN = 0.05
TOP_N = 10
VOLUME_RATIO_MIN = 2.0
OI_CHANGE_MIN = 0.02
LONG_SHORT_MAX = 1.0
COOLDOWN_HOURS = 24
ROUND_TRIP_COST_PCT = 0.12
HORIZONS = (1, 4, 12, 24)
PRIMARY_HORIZON = 4


def prepare(perp: pd.DataFrame, metrics: pd.DataFrame) -> pd.DataFrame:
    price = perp.copy()
    price["dt"] = pd.to_datetime(price["open_time"], unit="ms", utc=True)
    price = price.set_index("dt").sort_index()
    grid = pd.date_range(price.index[0], price.index[-1], freq="h", tz="UTC")
    price = price.reindex(grid)
    for col in ("open", "close", "quote_volume"):
        price[col] = pd.to_numeric(price[col], errors="coerce")
    price["return_24h"] = price["close"] / price["close"].shift(24) - 1
    prior_volume_median = price["quote_volume"].shift(1).rolling(
        24, min_periods=18).median()
    price["volume_ratio"] = price["quote_volume"] / prior_volume_median

    m = metrics.copy()
    m["create_time"] = pd.to_datetime(m["create_time"], utc=True)
    m["hour"] = m["create_time"].dt.floor("h")
    for col in ("sum_open_interest", "count_long_short_ratio"):
        m[col] = pd.to_numeric(m[col], errors="coerce").replace(
            [np.inf, -np.inf], np.nan)
    hourly = m.groupby("hour").agg(
        open_interest=("sum_open_interest", "last"),
        long_short_ratio=("count_long_short_ratio", "last"),
    ).reindex(grid)
    hourly["oi_change_1h"] = hourly["open_interest"] / \
        hourly["open_interest"].shift(1) - 1
    price = price.join(hourly)
    entry = price["open"].shift(-1)
    for horizon in HORIZONS:
        gross = (price["close"].shift(-horizon) / entry - 1) * 100
        price[f"net_{horizon}"] = gross - ROUND_TRIP_COST_PCT
    return price


def assign_events(panel: dict[str, pd.DataFrame]) -> None:
    returns = pd.DataFrame({symbol: frame["return_24h"]
                            for symbol, frame in panel.items()})
    ranks = returns.rank(axis=1, ascending=False, method="min")
    for symbol, frame in panel.items():
        frame["rank"] = ranks[symbol]
        base = ((frame["return_24h"] >= RETURN_MIN) &
                (frame["rank"] <= TOP_N)).fillna(False)
        signal = (base & (frame["volume_ratio"] >= VOLUME_RATIO_MIN) &
                  (frame["oi_change_1h"] >= OI_CHANGE_MIN) &
                  (frame["long_short_ratio"] < LONG_SHORT_MAX)).fillna(False)
        frame["signal"] = False
        frame.loc[edge_trigger(signal, COOLDOWN_HOURS), "signal"] = True
        frame["base_event"] = False
        frame.loc[edge_trigger(base, COOLDOWN_HOURS), "base_event"] = True


def _split_ok(t: pd.Timestamp, split: str, horizon: int) -> bool:
    if split == "train":
        return t < TRAIN_END and t + pd.Timedelta(hours=horizon + 1) < TRAIN_END
    if split == "test":
        return t >= TRAIN_END
    raise ValueError(f"bilinmeyen split: {split}")


def collect(panel: dict[str, pd.DataFrame], symbols: set[str], split: str,
            horizon: int, event_col: str) -> pd.DataFrame:
    rows = []
    for symbol in sorted(symbols):
        frame = panel.get(symbol)
        if frame is None:
            continue
        for t in frame.index[frame[event_col].fillna(False)]:
            if not _split_ok(t, split, horizon):
                continue
            value = float(frame.at[t, f"net_{horizon}"])
            if not math.isfinite(value):
                continue
            rows.append({"symbol": symbol, "t": t, "net_pct": value})
    return pd.DataFrame(rows)


def summarize(events: pd.DataFrame, baseline: pd.DataFrame) -> dict:
    if events.empty:
        return {"N": 0, "baseline_n": len(baseline)}
    values = events["net_pct"]
    baseline_mean = float(baseline["net_pct"].mean()) if not baseline.empty \
        else float("nan")
    counts = events["symbol"].value_counts()
    return {
        "N": len(events), "mean": float(values.mean()),
        "median": float(values.median()), "wr": float((values > 0).mean()),
        "q10": float(values.quantile(.10)), "q90": float(values.quantile(.90)),
        "p": cluster_pvalue(events), "baseline_n": len(baseline),
        "baseline_mean": baseline_mean,
        "edge": float(values.mean() - baseline_mean),
        "top5_share": float(counts.head(5).sum() / len(events)),
    }


def fmt(label: str, result: dict) -> str:
    if result.get("N", 0) == 0:
        return f"{label:<25} N=0 baseN={result.get('baseline_n', 0)}"
    return (f"{label:<25} N={result['N']:4d} net={result['mean']:+.3f}% "
            f"med={result['median']:+.3f}% WR={result['wr']:.1%} "
            f"q10={result['q10']:+.2f}% q90={result['q90']:+.2f}% "
            f"p(day)={result['p']:.4f} base={result['baseline_mean']:+.3f}% "
            f"edge={result['edge']:+.3f}% top5={result['top5_share']:.1%}")


def train_part_pass(r: dict, minimum: int) -> bool:
    return (r.get("N", 0) >= minimum and r["mean"] > 0 and r["median"] > 0
            and r["wr"] >= .52 and r["edge"] > 0)


def main(data_dir: str) -> int:
    root = Path(data_dir)
    symbols = json.loads((root / "manifest_spot89.json").read_text(
        encoding="utf-8"))["symbols"]
    manifest = json.loads((root / "manifest_metrics_gainer.json").read_text(
        encoding="utf-8"))
    bad = [row for row in manifest["symbols"]
           if row["missing_days"] or row["failures"]]
    if bad:
        print(f"RED: {len(bad)} sembolde eksik metrics günü var; test yapılmadı")
        return 1
    available = {row["symbol"] for row in manifest["symbols"]
                 if row["written_rows"] > 0}
    core = set(symbols[:30]) & available
    extended = set(symbols[30:]) & available
    panel = {}
    print("G1 gainer + yeni short birikimi — ON-KAYITLI", flush=True)
    print(f"ret24>={RETURN_MIN:.0%} top{TOP_N} volume>={VOLUME_RATIO_MIN:.1f}x "
          f"OI1h>={OI_CHANGE_MIN:.0%} LS<{LONG_SHORT_MAX:.1f} "
          f"primary={PRIMARY_HORIZON}h", flush=True)
    for i, symbol in enumerate(sorted(available), 1):
        panel[symbol] = prepare(
            pd.read_parquet(root / "um" / f"{symbol}.parquet"),
            pd.read_parquet(root / "metrics_gainer" / f"{symbol}.parquet"))
        if i % 20 == 0:
            print(f"hazır: {i}/{len(available)}", flush=True)
    assign_events(panel)

    def evaluate(group: set[str], split: str, horizon: int) -> dict:
        return summarize(collect(panel, group, split, horizon, "signal"),
                         collect(panel, group, split, horizon, "base_event"))

    rc = evaluate(core, "train", PRIMARY_HORIZON)
    re = evaluate(extended, "train", PRIMARY_HORIZON)
    ra = evaluate(core | extended, "train", PRIMARY_HORIZON)
    print(fmt("TRAIN core30 4h", rc), flush=True)
    print(fmt("TRAIN extended59 4h", re), flush=True)
    print(fmt("TRAIN all89 4h", ra), flush=True)
    for horizon in (1, 12, 24):
        print(fmt(f"TRAIN all89 {horizon}h diag",
                  evaluate(core | extended, "train", horizon)), flush=True)
    train_pass = (train_part_pass(rc, 30) and train_part_pass(re, 50) and
                  ra.get("p", 1) <= .05 and ra.get("q10", -99) > -5)
    if not train_pass:
        print("KARAR: RED — train/bağımsız-evren kapısı geçilmedi; TESTE BAKILMADI.")
        return 2

    rtc = evaluate(core, "test", PRIMARY_HORIZON)
    rte = evaluate(extended, "test", PRIMARY_HORIZON)
    rta = evaluate(core | extended, "test", PRIMARY_HORIZON)
    print(fmt("TEST core30 4h", rtc), flush=True)
    print(fmt("TEST extended59 4h", rte), flush=True)
    print(fmt("TEST all89 4h", rta), flush=True)
    passed = (rta.get("N", 0) >= 30 and rta["mean"] > 0 and
              rta["median"] > 0 and rta["wr"] >= .52 and rta["p"] <= .05 and
              rta["q10"] > -5 and rta["edge"] > 0 and
              rtc.get("mean", -1) >= 0 and rte.get("mean", -1) >= 0)
    print("KARAR: " + ("KABUL — bağımsız test kapısı geçti."
                       if passed else "RED — dokunulmamış test kapısı geçilmedi."))
    return 0 if passed else 3


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else "data"))
