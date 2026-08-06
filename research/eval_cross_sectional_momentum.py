"""R1: ön-kayıtlı cross-sectional relative-strength portföy testi."""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from common import TRAIN_END

LOOKBACK_HOURS = 30 * 24
SKIP_HOURS = 24
HOLD_HOURS = 72
TOP_FRACTION = 0.20
MAX_WEIGHT = 0.25
ROUND_TRIP_COST_PCT = 0.12
ANCHOR = pd.Timestamp("2024-07-01", tz="UTC")


def enrich(raw: pd.DataFrame) -> pd.DataFrame:
    frame = raw.copy()
    frame["dt"] = pd.to_datetime(frame["open_time"], unit="ms", utc=True)
    frame = frame.set_index("dt").sort_index()
    grid = pd.date_range(frame.index[0], frame.index[-1], freq="h", tz="UTC")
    frame = frame.reindex(grid)
    close = frame["close"].astype(float)
    # t açılışında son bilinen kapanış t-1'dir. Son 24 saati atınca bitiş
    # t-25, 30 günlük başlangıç t-745 olur.
    endpoint = close.shift(SKIP_HOURS + 1)
    startpoint = close.shift(SKIP_HOURS + LOOKBACK_HOURS + 1)
    frame["score"] = endpoint / startpoint - 1
    logret = np.log(close).diff()
    frame["selection_vol"] = logret.shift(SKIP_HOURS + 1).rolling(
        LOOKBACK_HOURS, min_periods=600).std()
    frame["forward_return"] = frame["open"].shift(-HOLD_HOURS) / frame["open"] - 1
    return frame[["open", "score", "selection_vol", "forward_return"]]


def capped_inverse_vol(volatility: pd.Series,
                       cap: float = MAX_WEIGHT) -> pd.Series:
    """Kaldıraçsız inverse-vol; cap yüzünden kullanılamayan kısım nakittir."""
    inv = 1 / volatility.astype(float)
    inv = inv.replace([np.inf, -np.inf], np.nan).dropna()
    if inv.empty:
        return inv
    remaining = set(inv.index)
    weights = pd.Series(0.0, index=inv.index)
    budget = 1.0
    while remaining and budget > 1e-12:
        current = inv.loc[sorted(remaining)]
        proposed = current / current.sum() * budget
        over = proposed[proposed > cap]
        if over.empty:
            weights.loc[proposed.index] = proposed
            break
        for symbol in over.index:
            weights.loc[symbol] = cap
            budget -= cap
            remaining.remove(symbol)
        if len(remaining) * cap < budget:
            # Dört adetten az uygun varlık: kalan zorla dağıtılmaz, nakitte kalır.
            weights.loc[sorted(remaining)] = cap
            break
    return weights


def rebalance_times(panel: dict[str, pd.DataFrame]) -> pd.DatetimeIndex:
    first = max(frame.index.min() for frame in panel.values())
    last = min(frame.index.max() for frame in panel.values())
    start_steps = math.ceil((first - ANCHOR) / pd.Timedelta(hours=HOLD_HOURS))
    start = ANCHOR + start_steps * pd.Timedelta(hours=HOLD_HOURS)
    return pd.date_range(start, last, freq=f"{HOLD_HOURS}h", tz="UTC")


def portfolio_periods(panel: dict[str, pd.DataFrame], symbols: set[str],
                      split: str) -> pd.DataFrame:
    subset = {s: panel[s] for s in sorted(symbols) if s in panel}
    rows = []
    for t in rebalance_times(subset):
        exit_t = t + pd.Timedelta(hours=HOLD_HOURS)
        if split == "train" and not (t < TRAIN_END and exit_t < TRAIN_END):
            continue
        if split == "test" and t < TRAIN_END:
            continue
        candidates = []
        for symbol, frame in subset.items():
            if t not in frame.index:
                continue
            row = frame.loc[t]
            try:
                score = float(row["score"])
                vol = float(row["selection_vol"])
                ret = float(row["forward_return"])
                entry = float(row["open"])
            except (TypeError, ValueError):
                continue
            if all(math.isfinite(x) for x in (score, vol, ret, entry)) \
                    and vol > 0 and entry > 0:
                candidates.append((symbol, score, vol, ret))
        if len(candidates) < 5:
            continue
        universe = pd.DataFrame(candidates, columns=[
            "symbol", "score", "vol", "ret"]).set_index("symbol")
        count = max(1, math.ceil(len(universe) * TOP_FRACTION))
        selected = universe.nlargest(count, "score")
        selected = selected.loc[selected["score"] > 0]
        weights = capped_inverse_vol(selected["vol"])
        if weights.empty or float(weights.sum()) <= 0:
            continue
        gross = float((weights * selected.loc[weights.index, "ret"]).sum() * 100)
        invested = float(weights.sum())
        cost = invested * ROUND_TRIP_COST_PCT
        benchmark = float(universe["ret"].mean() * 100)
        rows.append({
            "t": t, "exit_t": exit_t, "n_universe": len(universe),
            "n_selected": len(weights), "invested": invested,
            "gross_pct": gross, "cost_pct": cost,
            "net_pct": gross - cost, "benchmark_pct": benchmark,
            "alpha_pct": gross - cost - benchmark,
            "symbols": ",".join(weights.index),
        })
    return pd.DataFrame(rows)


def _profit_factor(values: pd.Series) -> float:
    gains = float(values[values > 0].sum())
    losses = float(-values[values < 0].sum())
    if losses == 0:
        return float("inf") if gains > 0 else float("nan")
    return gains / losses


def signflip_pvalue(values: pd.Series, iterations: int = 8000,
                    seed: int = 109) -> float:
    array = values.dropna().to_numpy(dtype=float)
    if len(array) == 0:
        return float("nan")
    actual = float(array.mean())
    rng = np.random.default_rng(seed)
    exceed = 0
    for _ in range(iterations):
        simulated = array * rng.choice((-1.0, 1.0), size=len(array))
        exceed += float(simulated.mean()) >= actual
    return (exceed + 1) / (iterations + 1)


def max_drawdown(values: pd.Series) -> float:
    curve = (1 + values.fillna(0) / 100).cumprod()
    drawdown = curve / curve.cummax() - 1
    return float(drawdown.min() * 100) if len(drawdown) else float("nan")


def summary(frame: pd.DataFrame) -> dict:
    if frame.empty:
        return {"N": 0}
    net, alpha = frame["net_pct"], frame["alpha_pct"]
    return {
        "N": len(frame), "mean": float(net.mean()),
        "median": float(net.median()), "wr": float((net > 0).mean()),
        "pf": _profit_factor(net), "q10": float(net.quantile(.10)),
        "q90": float(net.quantile(.90)), "alpha": float(alpha.mean()),
        "alpha_med": float(alpha.median()), "alpha_p": signflip_pvalue(alpha),
        "benchmark": float(frame["benchmark_pct"].mean()),
        "max_dd": max_drawdown(net),
        "selected": float(frame["n_selected"].mean()),
        "invested": float(frame["invested"].mean()),
    }


def fmt(label: str, r: dict) -> str:
    if r.get("N", 0) == 0:
        return f"{label:<23} N=0"
    pf = "inf" if math.isinf(r["pf"]) else f"{r['pf']:.2f}"
    return (f"{label:<23} N={r['N']:3d} net={r['mean']:+.3f}% "
            f"med={r['median']:+.3f}% WR={r['wr']:.1%} PF={pf} "
            f"q10={r['q10']:+.2f}% q90={r['q90']:+.2f}% "
            f"alpha={r['alpha']:+.3f}% p(alpha)={r['alpha_p']:.4f} "
            f"bench={r['benchmark']:+.3f}% maxDD={r['max_dd']:+.1f}% "
            f"sec={r['selected']:.1f} invested={r['invested']:.1%}")


def _core_pass(r: dict) -> bool:
    return (r.get("N", 0) >= 100 and r["mean"] > 0 and r["alpha"] > 0
            and r["pf"] >= 1.10 and r["alpha_p"] <= .05
            and r["q10"] > -10 and r["max_dd"] > -35)


def _extended_pass(r: dict) -> bool:
    return (r.get("N", 0) >= 100 and r["mean"] > 0 and r["alpha"] > 0
            and r["pf"] >= 1.05)


def _test_pass(all_r: dict, core_r: dict, ext_r: dict) -> bool:
    return (all_r.get("N", 0) >= 30 and all_r["mean"] > 0
            and all_r["alpha"] > 0 and all_r["pf"] >= 1.05
            and all_r["alpha_p"] <= .05 and all_r["q10"] > -10
            and all_r["max_dd"] > -35 and core_r.get("alpha", -1) >= 0
            and ext_r.get("alpha", -1) >= 0)


def main(data_dir: str) -> int:
    root = Path(data_dir)
    symbols = json.loads((root / "manifest_spot89.json").read_text(
        encoding="utf-8"))["symbols"]
    core, extended = set(symbols[:30]), set(symbols[30:])
    panel = {}
    print("R1 cross-sectional momentum — ON-KAYITLI TEK KONFIG", flush=True)
    print(f"lookback={LOOKBACK_HOURS//24}d skip={SKIP_HOURS//24}d "
          f"hold={HOLD_HOURS}h top={TOP_FRACTION:.0%} cap={MAX_WEIGHT:.0%} "
          f"cost={ROUND_TRIP_COST_PCT:.2f}% train<{TRAIN_END.date()}", flush=True)
    for i, symbol in enumerate(symbols, 1):
        panel[symbol] = enrich(pd.read_parquet(
            root / "spot" / f"{symbol}.parquet"))
        if i % 20 == 0:
            print(f"hazir: {i}/{len(symbols)}", flush=True)

    train_core = portfolio_periods(panel, core, "train")
    train_ext = portfolio_periods(panel, extended, "train")
    rc, re = summary(train_core), summary(train_ext)
    print(fmt("TRAIN core30", rc), flush=True)
    print(fmt("TRAIN extended59", re), flush=True)
    if not (_core_pass(rc) and _extended_pass(re)):
        print("KARAR: RED — train/bağımsız-evren kapısı geçilmedi; TESTE BAKILMADI.")
        return 2

    test_core = portfolio_periods(panel, core, "test")
    test_ext = portfolio_periods(panel, extended, "test")
    test_all = portfolio_periods(panel, set(symbols), "test")
    rtc, rte, rta = summary(test_core), summary(test_ext), summary(test_all)
    print(fmt("TEST core30", rtc), flush=True)
    print(fmt("TEST extended59", rte), flush=True)
    print(fmt("TEST all89", rta), flush=True)
    passed = _test_pass(rta, rtc, rte)
    print("KARAR: " + ("KABUL — canlı sepet tasarımı incelenebilir." if passed
                       else "RED — dokunulmamış test kapısı geçilmedi."))
    return 0 if passed else 3


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else "data"))
