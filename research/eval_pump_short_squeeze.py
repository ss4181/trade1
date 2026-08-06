"""L1: pump + short crowding + gerçekleşmiş squeeze vekili testi."""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from common import TRAIN_END, edge_trigger

PUMP_RETURN_6H = 0.05
LONG_SHORT_MAX = 0.80
OI_CHANGE_1H_MAX = -0.03
TAKER_RATIO_MIN = 1.20
FUNDING_DELTA_MIN = 0.0001
FUNDING_MAX_AGE_HOURS = 4.0
COOLDOWN_HOURS = 24
ROUND_TRIP_COST_PCT = 0.12
HORIZONS = (1, 4, 12, 24)
PRIMARY_HORIZON = 4


def prepare(perp: pd.DataFrame, metrics: pd.DataFrame,
            funding_rows: list[list]) -> pd.DataFrame:
    price = perp.copy()
    price["dt"] = pd.to_datetime(price["open_time"], unit="ms", utc=True)
    price = price.set_index("dt").sort_index()
    grid = pd.date_range(price.index[0], price.index[-1], freq="h", tz="UTC")
    price = price.reindex(grid)
    price["open"] = price["open"].astype(float)
    price["close"] = price["close"].astype(float)

    m = metrics.copy()
    m["create_time"] = pd.to_datetime(m["create_time"], utc=True)
    m["hour"] = m["create_time"].dt.floor("h")
    for col in ("sum_open_interest", "count_long_short_ratio",
                "sum_taker_long_short_vol_ratio"):
        m[col] = pd.to_numeric(m[col], errors="coerce").replace(
            [np.inf, -np.inf], np.nan)
    hourly = m.groupby("hour").agg(
        open_interest=("sum_open_interest", "last"),
        long_short_ratio=("count_long_short_ratio", "last"),
        taker_ratio=("sum_taker_long_short_vol_ratio", "median"),
    ).reindex(grid)
    hourly["oi_change_1h"] = hourly["open_interest"] / \
        hourly["open_interest"].shift(1) - 1
    price = price.join(hourly)

    funding = pd.DataFrame(funding_rows, columns=["funding_ms", "funding_rate"])
    if not funding.empty:
        funding["funding_time"] = pd.to_datetime(
            funding["funding_ms"], unit="ms", utc=True).dt.floor("h")
        funding["funding_time"] = funding["funding_time"].astype(
            "datetime64[ns, UTC]")
        funding = funding.sort_values("funding_time").drop_duplicates(
            "funding_time", keep="last")
        funding["funding_rate"] = funding["funding_rate"].astype(float)
        funding["funding_delta"] = funding["funding_rate"].diff()
        signal_times = pd.DatetimeIndex(
            grid + pd.Timedelta(hours=1)).as_unit("ns")
        left = pd.DataFrame({"signal_time": signal_times})
        aligned = pd.merge_asof(
            left.sort_values("signal_time"),
            funding[["funding_time", "funding_rate", "funding_delta"]],
            left_on="signal_time", right_on="funding_time", direction="backward")
        price["funding_rate"] = aligned["funding_rate"].to_numpy()
        price["funding_delta"] = aligned["funding_delta"].to_numpy()
        price["funding_age_h"] = (
            aligned["signal_time"] - aligned["funding_time"]
        ).dt.total_seconds().to_numpy() / 3600
    else:
        price[["funding_rate", "funding_delta", "funding_age_h"]] = np.nan

    price["pump6"] = price["close"] / price["close"].shift(6) - 1
    pump = price["pump6"] >= PUMP_RETURN_6H
    condition = (
        pump
        & (price["long_short_ratio"] < LONG_SHORT_MAX)
        & (price["oi_change_1h"] <= OI_CHANGE_1H_MAX)
        & (price["taker_ratio"] > TAKER_RATIO_MIN)
        & (price["funding_delta"] >= FUNDING_DELTA_MIN)
        & price["funding_age_h"].between(0, FUNDING_MAX_AGE_HOURS)
    ).fillna(False)
    price["signal"] = False
    price.loc[edge_trigger(condition, COOLDOWN_HOURS), "signal"] = True
    price["pump_event"] = False
    price.loc[edge_trigger(pump.fillna(False), COOLDOWN_HOURS), "pump_event"] = True
    entry = price["open"].shift(-1)
    for horizon in HORIZONS:
        gross = (price["close"].shift(-horizon) / entry - 1) * 100
        price[f"net_{horizon}"] = gross - ROUND_TRIP_COST_PCT
    return price


def _split_ok(t: pd.Timestamp, split: str, horizon: int) -> bool:
    if split == "train":
        return t < TRAIN_END and \
            t + pd.Timedelta(hours=horizon + 1) < TRAIN_END
    if split == "test":
        return t >= TRAIN_END
    raise ValueError(f"bilinmeyen split: {split}")


def collect(panel: dict[str, pd.DataFrame], symbols: set[str], split: str,
            horizon: int, event_col: str = "signal") -> pd.DataFrame:
    rows = []
    for symbol in sorted(symbols):
        if symbol not in panel:
            continue
        frame = panel[symbol]
        times = frame.index[frame[event_col].fillna(False)]
        for t in times:
            if not _split_ok(t, split, horizon):
                continue
            value = float(frame.at[t, f"net_{horizon}"])
            if not math.isfinite(value):
                continue
            rows.append({
                "symbol": symbol, "t": t, "net_pct": value,
                "pump6": float(frame.at[t, "pump6"]),
                "long_short_ratio": float(frame.at[t, "long_short_ratio"]),
                "oi_change_1h": float(frame.at[t, "oi_change_1h"]),
                "taker_ratio": float(frame.at[t, "taker_ratio"]),
                "funding_delta": float(frame.at[t, "funding_delta"]),
            })
    return pd.DataFrame(rows)


def cluster_pvalue(frame: pd.DataFrame, iterations: int = 6000,
                   seed: int = 127) -> float:
    if frame.empty:
        return float("nan")
    values = frame["net_pct"].to_numpy(dtype=float)
    days = pd.to_datetime(frame["t"], utc=True).dt.floor("D")
    groups = [np.flatnonzero(days.to_numpy() == day)
              for day in days.drop_duplicates().to_numpy()]
    actual = float(values.mean())
    rng = np.random.default_rng(seed)
    exceed = 0
    for _ in range(iterations):
        simulated = values.copy()
        for idx, sign in zip(groups, rng.choice((-1.0, 1.0), len(groups))):
            simulated[idx] *= sign
        exceed += float(simulated.mean()) >= actual
    return (exceed + 1) / (iterations + 1)


def summary(events: pd.DataFrame, baseline: pd.DataFrame) -> dict:
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
        "edge_vs_pump": float(values.mean() - baseline_mean),
        "top5_share": float(counts.head(5).sum() / len(events)),
    }


def fmt(label: str, result: dict) -> str:
    if result.get("N", 0) == 0:
        return f"{label:<24} N=0 pumpN={result.get('baseline_n', 0)}"
    return (f"{label:<24} N={result['N']:4d} net={result['mean']:+.3f}% "
            f"med={result['median']:+.3f}% WR={result['wr']:.1%} "
            f"q10={result['q10']:+.2f}% q90={result['q90']:+.2f}% "
            f"p(day)={result['p']:.4f} pump={result['baseline_mean']:+.3f}% "
            f"edge={result['edge_vs_pump']:+.3f}% top5={result['top5_share']:.1%}")


def _core_pass(r: dict) -> bool:
    return (r.get("N", 0) >= 50 and r["mean"] > 0 and r["median"] > 0
            and r["wr"] >= .55 and r["p"] <= .05 and r["q10"] > -5
            and r["edge_vs_pump"] > 0)


def _extended_pass(r: dict) -> bool:
    return (r.get("N", 0) >= 100 and r["mean"] > 0 and r["median"] > 0
            and r["wr"] >= .52 and r["edge_vs_pump"] > 0)


def _test_pass(all_r: dict, core_r: dict, ext_r: dict) -> bool:
    return (all_r.get("N", 0) >= 30 and all_r["mean"] > 0
            and all_r["median"] > 0 and all_r["wr"] >= .52
            and all_r["p"] <= .05 and all_r["q10"] > -5
            and all_r["edge_vs_pump"] > 0
            and core_r.get("mean", -1) >= 0 and ext_r.get("mean", -1) >= 0)


def main(data_dir: str) -> int:
    root = Path(data_dir)
    symbols = json.loads((root / "manifest_spot89.json").read_text(
        encoding="utf-8"))["symbols"]
    manifest = json.loads((root / "manifest_metrics_pump.json").read_text(
        encoding="utf-8"))
    funding = json.loads((Path(__file__).parent / "funding_cache" /
                          "funding_history.json").read_text(encoding="utf-8"))
    available = {row["symbol"] for row in manifest["symbols"]
                 if row["written_rows"] > 0 and not row["failures"]}
    core, extended = set(symbols[:30]) & available, set(symbols[30:]) & available
    panel = {}
    print("L1 pump/short-crowding squeeze vekili — ON-KAYITLI", flush=True)
    print(f"pump6>={PUMP_RETURN_6H:.0%} LS<{LONG_SHORT_MAX:.2f} "
          f"OI1h<={OI_CHANGE_1H_MAX:.0%} taker>{TAKER_RATIO_MIN:.2f} "
          f"dFunding>={FUNDING_DELTA_MIN:.4f} primary={PRIMARY_HORIZON}h",
          flush=True)
    for i, symbol in enumerate(sorted(available), 1):
        panel[symbol] = prepare(
            pd.read_parquet(root / "um" / f"{symbol}.parquet"),
            pd.read_parquet(root / "metrics_pump" / f"{symbol}.parquet"),
            funding[symbol])
        if i % 20 == 0:
            print(f"hazir: {i}/{len(available)}", flush=True)

    def evaluate(group: set[str], split: str, horizon: int) -> dict:
        events = collect(panel, group, split, horizon, "signal")
        baseline = collect(panel, group, split, horizon, "pump_event")
        return summary(events, baseline)

    rc = evaluate(core, "train", PRIMARY_HORIZON)
    re = evaluate(extended, "train", PRIMARY_HORIZON)
    print(fmt("TRAIN core30 4h", rc), flush=True)
    print(fmt("TRAIN extended59 4h", re), flush=True)
    for horizon in (1, 12, 24):
        print(fmt(f"TRAIN all89 {horizon}h diag",
                  evaluate(core | extended, "train", horizon)), flush=True)
    if not (_core_pass(rc) and _extended_pass(re)):
        print("KARAR: RED — train/bağımsız-evren kapısı geçilmedi; TESTE BAKILMADI.")
        return 2

    rtc = evaluate(core, "test", PRIMARY_HORIZON)
    rte = evaluate(extended, "test", PRIMARY_HORIZON)
    rta = evaluate(core | extended, "test", PRIMARY_HORIZON)
    print(fmt("TEST core30 4h", rtc), flush=True)
    print(fmt("TEST extended59 4h", rte), flush=True)
    print(fmt("TEST all89 4h", rta), flush=True)
    passed = _test_pass(rta, rtc, rte)
    print("KARAR: " + ("KABUL — canlı tasarım incelemesine geçebilir." if passed
                       else "RED — dokunulmamış test kapısı geçilmedi."))
    return 0 if passed else 3


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else "data"))
