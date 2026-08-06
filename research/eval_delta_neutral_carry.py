"""C1: ön-kayıtlı delta-nötr spot long + USD-M perp short carry testi."""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from common import TRAIN_END

ENTRY_APR_PCT = 15.0
EXIT_APR_PCT = 5.0
ENTRY_BASIS = 0.0005
BASIS_STRESS = 0.02
MAX_HOLD_HOURS = 30 * 24
MARGIN_STRESS_MULTIPLE = 1.8
FILL_COST_BPS = 7.0


def _hourly(raw: pd.DataFrame, prefix: str, scale: float = 1.0) -> pd.DataFrame:
    frame = raw.copy()
    frame["dt"] = pd.to_datetime(frame["open_time"], unit="ms", utc=True)
    frame = frame.set_index("dt").sort_index()
    cols = ["open", "high", "low", "close"]
    out = frame[cols].astype(float) / scale
    return out.rename(columns={c: f"{prefix}_{c}" for c in cols})


def funding_features(rows: list[list]) -> pd.DataFrame:
    frame = pd.DataFrame(rows, columns=["funding_ms", "fund_rate"])
    if frame.empty:
        return pd.DataFrame(columns=[
            "fund_rate", "fund_apr72", "last3_positive", "last2_nonpositive"])
    frame["t"] = pd.to_datetime(frame["funding_ms"], unit="ms", utc=True).dt.floor("h")
    frame = frame.sort_values("t").drop_duplicates("t", keep="last").set_index("t")
    rate = frame["fund_rate"].astype(float)
    frame["fund_apr72"] = rate.rolling("72h", min_periods=3).sum() * (365 / 3) * 100
    frame["last3_positive"] = rate.gt(0).rolling(3, min_periods=3).sum().eq(3)
    frame["last2_nonpositive"] = rate.le(0).rolling(2, min_periods=2).sum().eq(2)
    return frame[["fund_rate", "fund_apr72", "last3_positive",
                  "last2_nonpositive"]]


def build_panel(spot: pd.DataFrame, perp: pd.DataFrame, funding: list[list],
                contract_scale: float = 1.0) -> pd.DataFrame:
    panel = _hourly(spot, "spot").join(
        _hourly(perp, "perp", contract_scale), how="inner")
    features = funding_features(funding)
    panel = panel.join(features, how="left")
    panel["basis_open"] = panel["perp_open"] / panel["spot_open"] - 1
    panel["basis_close"] = panel["perp_close"] / panel["spot_close"] - 1
    event = panel["fund_rate"].notna()
    panel["entry_signal"] = (
        event & panel["last3_positive"].fillna(False)
        & (panel["fund_apr72"] >= ENTRY_APR_PCT)
        & (panel["basis_open"] >= ENTRY_BASIS)
    )
    return panel


def _profit_factor(values: pd.Series) -> float:
    gains = float(values[values > 0].sum())
    losses = float(-values[values < 0].sum())
    if losses == 0:
        return float("inf") if gains > 0 else float("nan")
    return gains / losses


def simulate(symbol: str, panel: pd.DataFrame,
             split: str) -> tuple[list[dict], int]:
    if split == "train":
        frame = panel.loc[panel.index < TRAIN_END]
    elif split == "test":
        frame = panel.loc[panel.index >= TRAIN_END]
    else:
        raise ValueError(f"bilinmeyen split: {split}")

    rows: list[dict] = []
    position: dict | None = None
    pending_entry: pd.Timestamp | None = None
    pending_exit: str | None = None
    previous_t = None
    abandoned = 0

    def finish(t: pd.Timestamp, spot_exit: float, perp_exit: float,
               reason: str) -> None:
        nonlocal position
        assert position is not None
        price_pnl = ((spot_exit - position["spot_entry"])
                     + (position["perp_entry"] - perp_exit))
        gross_dollars = price_pnl + position["funding_pnl"]
        capital = position["capital"]
        fill_notional = (position["spot_entry"] + position["perp_entry"]
                         + spot_exit + perp_exit)
        cost_dollars = fill_notional * FILL_COST_BPS / 10_000
        gross_pct = gross_dollars / capital * 100
        cost_pct = cost_dollars / capital * 100
        rows.append({
            "symbol": symbol, "signal_t": position["signal_t"],
            "entry_t": position["entry_t"], "exit_t": t,
            "spot_entry": position["spot_entry"],
            "perp_entry": position["perp_entry"],
            "spot_exit": spot_exit, "perp_exit": perp_exit,
            "entry_basis_pct": position["entry_basis"] * 100,
            "exit_basis_pct": (perp_exit / spot_exit - 1) * 100,
            "funding_pct": position["funding_pnl"] / capital * 100,
            "price_pnl_pct": price_pnl / capital * 100,
            "gross_pct": gross_pct, "cost_pct": cost_pct,
            "net_pct": gross_pct - cost_pct, "reason": reason,
            "hold_hours": (t - position["entry_t"]).total_seconds() / 3600,
        })
        position = None

    for t, bar in frame.iterrows():
        if previous_t is not None and t - previous_t != pd.Timedelta(hours=1):
            if position is not None or pending_entry is not None:
                abandoned += 1
            position, pending_entry, pending_exit = None, None, None
        previous_t = t
        prices = [float(bar[f"{leg}_{field}"])
                  for leg in ("spot", "perp")
                  for field in ("open", "high", "low", "close")]
        if not all(math.isfinite(x) and x > 0 for x in prices):
            if position is not None or pending_entry is not None:
                abandoned += 1
            position, pending_entry, pending_exit = None, None, None
            continue

        spot_open, spot_high, spot_low, spot_close = prices[:4]
        perp_open, perp_high, perp_low, perp_close = prices[4:]

        # Açılış dolumları settlement ile aynı zaman damgasındaysa funding'i
        # iyimser biçimde yazmamak için önce çıkış/giriş yapılır.
        if position is not None and (
                pending_exit is not None
                or (t - position["entry_t"]).total_seconds() / 3600
                >= MAX_HOLD_HOURS):
            reason = pending_exit or "timeout_30d"
            finish(t, spot_open, perp_open, reason)
            pending_exit = None

        entered_now = False
        if pending_entry is not None and position is None:
            capital = spot_open + perp_open
            position = {
                "signal_t": pending_entry, "entry_t": t,
                "spot_entry": spot_open, "perp_entry": perp_open,
                "entry_basis": perp_open / spot_open - 1,
                "capital": capital, "funding_pnl": 0.0,
            }
            pending_entry = None
            entered_now = True

        rate = float(bar["fund_rate"])
        if (position is not None and not entered_now and math.isfinite(rate)):
            position["funding_pnl"] += rate * perp_open

        if position is not None:
            margin_barrier = position["perp_entry"] * MARGIN_STRESS_MULTIPLE
            if perp_high >= margin_barrier:
                # Aynı saatte spotun düşük, shortun stres bariyeri: muhafazakâr.
                finish(t, spot_low, margin_barrier, "margin_stress_1p8x")
            else:
                basis = float(bar["basis_close"])
                apr = float(bar["fund_apr72"])
                nonpositive = bool(bar["last2_nonpositive"]) \
                    if pd.notna(bar["last2_nonpositive"]) else False
                if basis <= 0:
                    pending_exit = "basis_converged"
                elif basis >= BASIS_STRESS:
                    pending_exit = "basis_stress_2pct"
                elif math.isfinite(apr) and apr < EXIT_APR_PCT:
                    pending_exit = "funding_apr_below_5"
                elif nonpositive:
                    pending_exit = "two_nonpositive_funding"

        if position is None and bool(bar["entry_signal"]):
            pending_entry = t

    pending = abandoned + int(position is not None) + int(pending_entry is not None)
    return rows, pending


def cluster_pvalue(frame: pd.DataFrame, iterations: int = 6000,
                   seed: int = 97) -> float:
    if frame.empty:
        return float("nan")
    values = frame["net_pct"].to_numpy(dtype=float)
    days = pd.to_datetime(frame["entry_t"], utc=True).dt.floor("D")
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


def summary(frame: pd.DataFrame, pending: int = 0) -> dict:
    if frame.empty:
        return {"N": 0, "pending": pending}
    net = frame["net_pct"]
    counts = frame["symbol"].value_counts()
    return {
        "N": len(frame), "pending": pending,
        "mean": float(net.mean()), "median": float(net.median()),
        "wr": float((net > 0).mean()), "pf": _profit_factor(net),
        "q10": float(net.quantile(.10)), "q90": float(net.quantile(.90)),
        "funding": float(frame["funding_pct"].mean()),
        "price": float(frame["price_pnl_pct"].mean()),
        "cost": float(frame["cost_pct"].mean()),
        "p": cluster_pvalue(frame),
        "hold_h": float(frame["hold_hours"].median()),
        "stress": float((frame["reason"] == "margin_stress_1p8x").mean()),
        "top5_share": float(counts.head(5).sum() / len(frame)),
    }


def fmt(label: str, r: dict) -> str:
    if r.get("N", 0) == 0:
        return f"{label:<23} N=0 pending={r.get('pending', 0)}"
    pf = "inf" if math.isinf(r["pf"]) else f"{r['pf']:.2f}"
    return (f"{label:<23} N={r['N']:4d} pending={r['pending']:2d} "
            f"net={r['mean']:+.3f}% med={r['median']:+.3f}% WR={r['wr']:.1%} "
            f"PF={pf} q10={r['q10']:+.2f}% q90={r['q90']:+.2f}% "
            f"fund={r['funding']:+.3f}% basisPnL={r['price']:+.3f}% "
            f"cost={r['cost']:.3f}% p(day)={r['p']:.4f} "
            f"hold-med={r['hold_h']:.0f}h stress={r['stress']:.1%} "
            f"top5={r['top5_share']:.1%}")


def _core_pass(r: dict) -> bool:
    return (r.get("N", 0) >= 100 and r["mean"] > 0 and r["median"] > 0
            and r["wr"] >= .55 and r["pf"] >= 1.25 and r["q10"] > -1
            and r["p"] <= .05 and r["stress"] <= .01)


def _extended_pass(r: dict) -> bool:
    return (r.get("N", 0) >= 100 and r["mean"] > 0 and r["median"] > 0
            and r["pf"] >= 1.10 and r["q10"] > -1)


def _test_pass(all_r: dict, core_r: dict, ext_r: dict) -> bool:
    return (all_r.get("N", 0) >= 50 and all_r["mean"] > 0
            and all_r["median"] > 0 and all_r["pf"] >= 1.10
            and all_r["q10"] > -1 and all_r["p"] <= .05
            and core_r.get("mean", -1) >= 0 and ext_r.get("mean", -1) >= 0)


def main(data_dir: str) -> int:
    root = Path(data_dir)
    spot_manifest = json.loads((root / "manifest_spot89.json").read_text(
        encoding="utf-8"))
    um_manifest = json.loads((root / "manifest_um89.json").read_text(
        encoding="utf-8"))
    funding_path = Path(__file__).parent / "funding_cache" / "funding_history.json"
    funding = json.loads(funding_path.read_text(encoding="utf-8"))
    symbols = [s for s in spot_manifest["symbols"]
               if s in set(um_manifest["symbols_written"]) and s in funding]
    core = set(spot_manifest["symbols"][:30]) & set(symbols)
    extended = set(spot_manifest["symbols"][30:]) & set(symbols)
    mapping = um_manifest["contract_map"]
    panel = {}
    print("C1 delta-notr carry — ON-KAYITLI TEK KONFIG", flush=True)
    print(f"APR72>={ENTRY_APR_PCT:.0f}% basis>={ENTRY_BASIS:.2%} "
          f"exitAPR<{EXIT_APR_PCT:.0f}% max={MAX_HOLD_HOURS//24}d "
          f"fill={FILL_COST_BPS:.0f}bp x4 train<{TRAIN_END.date()}", flush=True)
    for i, symbol in enumerate(symbols, 1):
        contract = mapping[symbol]
        scale = 1.0
        if contract.startswith("1000000") and not symbol.startswith("1000000"):
            scale = 1_000_000.0
        elif contract.startswith("1000") and not symbol.startswith("1000"):
            scale = 1_000.0
        panel[symbol] = build_panel(
            pd.read_parquet(root / "spot" / f"{symbol}.parquet"),
            pd.read_parquet(root / "um" / f"{symbol}.parquet"),
            funding[symbol], scale)
        if i % 20 == 0:
            print(f"hazir: {i}/{len(symbols)}", flush=True)

    def collect(group: set[str], split: str) -> tuple[pd.DataFrame, int]:
        rows, pending = [], 0
        for symbol in sorted(group):
            got, count = simulate(symbol, panel[symbol], split)
            rows.extend(got)
            pending += count
        return pd.DataFrame(rows), pending

    tc, pc = collect(core, "train")
    te, pe = collect(extended, "train")
    rc, re = summary(tc, pc), summary(te, pe)
    print(fmt("TRAIN core30", rc), flush=True)
    print(fmt("TRAIN extended59", re), flush=True)
    if not (_core_pass(rc) and _extended_pass(re)):
        print("KARAR: RED — train/bağımsız-evren kapısı geçilmedi; TESTE BAKILMADI.")
        return 2

    xc, pc = collect(core, "test")
    xe, pe = collect(extended, "test")
    xa = pd.concat((xc, xe), ignore_index=True)
    rtc, rte, rta = summary(xc, pc), summary(xe, pe), summary(xa, pc + pe)
    print(fmt("TEST core30", rtc), flush=True)
    print(fmt("TEST extended59", rte), flush=True)
    print(fmt("TEST all89", rta), flush=True)
    passed = _test_pass(rta, rtc, rte)
    print("KARAR: " + ("KABUL — operasyonel incelemeye geçebilir." if passed
                       else "RED — dokunulmamış test kapısı geçilmedi."))
    return 0 if passed else 3


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else "data"))
