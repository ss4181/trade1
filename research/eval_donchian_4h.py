"""D1: ön-kayıtlı 4h Donchian long/flat trend stratejisi.

Kurallar ve kabul kapıları PREREG_DONCHIAN_4H.md dosyasındadır. Bu script
tek konfigürasyon çalıştırır ve train kapıları geçmeden test sonuçlarını
hesaplamaz/yazdırmaz.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from common import TRAIN_END

ENTRY_WINDOW = 20
EXIT_WINDOW = 10
ATR_PERIOD = 20
STOP_ATR = 2.0
RISK_BUDGET = 0.01
ROUND_TRIP_COST_PCT = 0.12
BAR_HOURS = 4


def _wilder_atr(df: pd.DataFrame, n: int = ATR_PERIOD) -> pd.Series:
    high, low, close = df["high"], df["low"], df["close"]
    tr = pd.concat((high - low, (high - close.shift()).abs(),
                    (low - close.shift()).abs()), axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()


def enrich_4h(raw: pd.DataFrame) -> pd.DataFrame:
    """Saatlik spot verisini UTC-ankorlu, yalnız eksiksiz 4h barlara çevirir."""
    hourly = raw.copy()
    hourly["dt"] = pd.to_datetime(hourly["open_time"], unit="ms", utc=True)
    hourly = hourly.set_index("dt").sort_index()
    spec = dict(rule="4h", origin="epoch", label="left", closed="left")
    bars = hourly.resample(**spec).agg({
        "open": "first", "high": "max", "low": "min", "close": "last",
        "volume": "sum", "quote_volume": "sum",
    })
    source_count = hourly["open"].resample(**spec).count()
    bars = bars.loc[source_count.eq(4)].copy()
    bars["upper20"] = bars["high"].shift(1).rolling(
        ENTRY_WINDOW, min_periods=ENTRY_WINDOW).max()
    bars["lower10"] = bars["low"].shift(1).rolling(
        EXIT_WINDOW, min_periods=EXIT_WINDOW).min()
    bars["atr20"] = _wilder_atr(bars)
    above = (bars["close"] > bars["upper20"]).fillna(False)
    bars["entry_signal"] = above & ~above.shift(1, fill_value=False)
    return bars


def _profit_factor(values: pd.Series) -> float:
    gains = float(values[values > 0].sum())
    losses = float(-values[values < 0].sum())
    if losses == 0:
        return float("inf") if gains > 0 else float("nan")
    return gains / losses


def simulate(symbol: str, bars: pd.DataFrame,
             split: str) -> tuple[list[dict], int]:
    """Nedensel dolumlarla tek sembolü çalıştırır; split başında flat başlar."""
    if split == "train":
        frame = bars.loc[bars.index < TRAIN_END]
    elif split == "test":
        frame = bars.loc[bars.index >= TRAIN_END]
    else:
        raise ValueError(f"bilinmeyen split: {split}")

    rows: list[dict] = []
    position: dict | None = None
    pending_entry: dict | None = None
    pending_exit = False
    abandoned = 0
    previous_t = None

    def finish(exit_t: pd.Timestamp, exit_price: float, reason: str) -> None:
        nonlocal position
        assert position is not None
        gross = (exit_price / position["entry"] - 1) * 100
        net = gross - ROUND_TRIP_COST_PCT
        rows.append({
            "symbol": symbol,
            "signal_t": position["signal_t"],
            "entry_t": position["entry_t"],
            "entry": position["entry"],
            "stop": position["stop"],
            "exit_t": exit_t,
            "exit": exit_price,
            "reason": reason,
            "hold_hours": (exit_t - position["entry_t"]).total_seconds() / 3600,
            "weight": position["weight"],
            "gross_pct": gross,
            "net_pct": net,
            "scaled_net_pct": net * position["weight"],
        })
        position = None

    for t, bar in frame.iterrows():
        if previous_t is not None and t - previous_t != pd.Timedelta(hours=4):
            if position is not None or pending_entry is not None:
                abandoned += 1
            position = None
            pending_entry = None
            pending_exit = False
        previous_t = t

        open_px = float(bar["open"])
        low_px = float(bar["low"])
        close_px = float(bar["close"])
        if not all(math.isfinite(x) and x > 0 for x in
                   (open_px, low_px, close_px)):
            if position is not None or pending_entry is not None:
                abandoned += 1
            position = None
            pending_entry = None
            pending_exit = False
            continue

        if pending_exit and position is not None:
            finish(t, open_px, "donchian_exit")
            pending_exit = False

        if pending_entry is not None and position is None:
            atr = float(pending_entry["atr"])
            if math.isfinite(atr) and atr > 0:
                stop = open_px - STOP_ATR * atr
                stop_risk = (open_px - stop) / open_px
                weight = min(1.0, RISK_BUDGET / stop_risk)
                position = {
                    "signal_t": pending_entry["signal_t"], "entry_t": t,
                    "entry": open_px, "stop": stop, "weight": weight,
                }
            pending_entry = None

        if position is not None:
            if low_px <= position["stop"]:
                finish(t, min(open_px, position["stop"]), "atr_stop")
            else:
                lower = float(bar["lower10"])
                if math.isfinite(lower) and close_px < lower:
                    pending_exit = True

        if position is None and bool(bar["entry_signal"]):
            atr = float(bar["atr20"])
            if math.isfinite(atr) and atr > 0:
                pending_entry = {"signal_t": t, "atr": atr}

    pending = abandoned + int(position is not None) + int(pending_entry is not None)
    return rows, pending


def cluster_pvalue(frame: pd.DataFrame, iterations: int = 6000,
                   seed: int = 83) -> float:
    """Aynı UTC giriş günündeki korele olayları birlikte işaret çevirir."""
    if frame.empty:
        return float("nan")
    values = frame["scaled_net_pct"].to_numpy(dtype=float)
    days = pd.to_datetime(frame["entry_t"], utc=True).dt.floor("D")
    unique_days = days.drop_duplicates().to_numpy()
    groups = [np.flatnonzero(days.to_numpy() == day) for day in unique_days]
    actual = float(values.mean())
    rng = np.random.default_rng(seed)
    exceed = 0
    for _ in range(iterations):
        simulated = values.copy()
        signs = rng.choice((-1.0, 1.0), size=len(groups))
        for idx, sign in zip(groups, signs):
            simulated[idx] *= sign
        exceed += float(simulated.mean()) >= actual
    return (exceed + 1) / (iterations + 1)


def summary(frame: pd.DataFrame, pending: int = 0) -> dict:
    if frame.empty:
        return {"N": 0, "pending": pending}
    net = frame["net_pct"]
    scaled = frame["scaled_net_pct"]
    counts = frame["symbol"].value_counts()
    return {
        "N": len(frame), "pending": pending,
        "mean": float(net.mean()), "median": float(net.median()),
        "wr": float((net > 0).mean()), "pf": _profit_factor(net),
        "q10": float(net.quantile(0.10)), "q90": float(net.quantile(0.90)),
        "scaled_mean": float(scaled.mean()), "scaled_pf": _profit_factor(scaled),
        "p": cluster_pvalue(frame),
        "hold_h": float(frame["hold_hours"].median()),
        "stop_rate": float((frame["reason"] == "atr_stop").mean()),
        "top5_share": float(counts.head(5).sum() / len(frame)),
    }


def fmt(label: str, result: dict) -> str:
    if result.get("N", 0) == 0:
        return f"{label:<23} N=0 pending={result.get('pending', 0)}"
    pf = "inf" if math.isinf(result["pf"]) else f"{result['pf']:.2f}"
    return (f"{label:<23} N={result['N']:4d} pending={result['pending']:2d} "
            f"net ort={result['mean']:+.3f}% med={result['median']:+.3f}% "
            f"WR={result['wr']:.1%} PF={pf} q10={result['q10']:+.2f}% "
            f"q90={result['q90']:+.2f}% scaled={result['scaled_mean']:+.3f}% "
            f"p(day)={result['p']:.4f} hold-med={result['hold_h']:.0f}h "
            f"stop={result['stop_rate']:.1%} top5={result['top5_share']:.1%}")


def _train_core_pass(r: dict) -> bool:
    return (r.get("N", 0) >= 100 and r["mean"] > 0 and r["pf"] >= 1.10
            and r["scaled_mean"] > 0 and r["q90"] > abs(r["q10"])
            and r["p"] <= 0.05)


def _train_extended_pass(r: dict) -> bool:
    return (r.get("N", 0) >= 100 and r["mean"] > 0 and r["pf"] >= 1.05
            and r["scaled_mean"] > 0)


def _test_pass(all_r: dict, core_r: dict, ext_r: dict) -> bool:
    return (all_r.get("N", 0) >= 50 and all_r["mean"] > 0
            and all_r["pf"] >= 1.05 and all_r["scaled_mean"] > 0
            and all_r["p"] <= 0.05 and core_r.get("mean", -1) >= 0
            and ext_r.get("mean", -1) >= 0)


def main(data_dir: str) -> int:
    root = Path(data_dir)
    manifest = json.loads((root / "manifest_spot89.json").read_text(
        encoding="utf-8"))
    symbols = manifest["symbols"]
    core, extended = set(symbols[:30]), set(symbols[30:])
    panel = {}
    print("D1 4h Donchian trend — ON-KAYITLI TEK KONFIG", flush=True)
    print(f"entry={ENTRY_WINDOW} exit={EXIT_WINDOW} ATR={ATR_PERIOD} "
          f"stop={STOP_ATR}N risk={RISK_BUDGET:.1%} cost="
          f"{ROUND_TRIP_COST_PCT:.2f}% train<{TRAIN_END.date()}", flush=True)
    for i, symbol in enumerate(symbols, 1):
        panel[symbol] = enrich_4h(pd.read_parquet(
            root / "spot" / f"{symbol}.parquet"))
        if i % 20 == 0:
            print(f"hazir: {i}/{len(symbols)}", flush=True)

    def collect(group: set[str], split: str) -> tuple[pd.DataFrame, int]:
        rows, pending = [], 0
        for symbol in sorted(group):
            symbol_rows, symbol_pending = simulate(symbol, panel[symbol], split)
            rows.extend(symbol_rows)
            pending += symbol_pending
        return pd.DataFrame(rows), pending

    train_core, pc = collect(core, "train")
    train_ext, pe = collect(extended, "train")
    rc, re = summary(train_core, pc), summary(train_ext, pe)
    print(fmt("TRAIN core30", rc), flush=True)
    print(fmt("TRAIN extended59", re), flush=True)
    if not (_train_core_pass(rc) and _train_extended_pass(re)):
        print("KARAR: RED — train/bağımsız-evren kapısı geçilmedi; TESTE BAKILMADI.")
        return 2

    test_core, pc = collect(core, "test")
    test_ext, pe = collect(extended, "test")
    test_all = pd.concat((test_core, test_ext), ignore_index=True)
    rtc, rte = summary(test_core, pc), summary(test_ext, pe)
    rta = summary(test_all, pc + pe)
    print(fmt("TEST core30", rtc), flush=True)
    print(fmt("TEST extended59", rte), flush=True)
    print(fmt("TEST all89", rta), flush=True)
    passed = _test_pass(rta, rtc, rte)
    print("KARAR: " + ("KABUL — canlı entegrasyon incelemesine geçebilir." if passed
                       else "RED — dokunulmamış test kapısı geçilmedi."))
    return 0 if passed else 3


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else "data"))
