"""S7 adayi: long-only VWAP Z-score mean reversion (tek atis).

Hipotez/parametreler bu dosya calistirilmadan once sabitlendi:
  * 1h spot, 24 saatlik rolling VWAP = sum(quote_volume)/sum(volume)
  * spread = log(close / VWAP24), rolling 20 bar Z-skoru
  * ADX(14) < 20, Z < -2.0, yesil sinyal bari
  * false->true + 24h cooldown; giris sonraki bar acilisi
  * cikis: Z >= -0.2 oldugu ilk bar kapanisi veya 24h timeout
  * stop: sinyal anindaki ATR(14) x 1.8; gap stopta kotu olan acilis
  * round-trip maliyet: 12bp

Karar kapisi (parametre taramasi YOK):
  1) core30 train: N>=100, net mean/median>0, WR>=55%, gun-kumesi p<=0.05
  2) extended59 train: N>=100, net mean/median>0
  3) tum89 test: N>=30, net mean/median>0, WR>=52%, gun-kumesi p<=0.05

Test dilimi yalniz train kapilari gecerse acilir. Sonuc RED ise ayni hipotez
yeniden ayarlanip test edilemez.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from common import TRAIN_END, edge_trigger

ADX_PERIOD = 14
VWAP_WINDOW = 24
ZSCORE_WINDOW = 20
ZSCORE_ENTRY = -2.0
ZSCORE_EXIT = -0.2
STOP_ATR = 1.8
TIMEOUT_HOURS = 24
COOLDOWN_HOURS = 24
ROUND_TRIP_COST_PCT = 0.12


def _wilder_atr(df: pd.DataFrame, n: int = ADX_PERIOD) -> pd.Series:
    high, low, close = df["high"], df["low"], df["close"]
    tr = pd.concat((high - low, (high - close.shift()).abs(),
                    (low - close.shift()).abs()), axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()


def _adx(df: pd.DataFrame, n: int = ADX_PERIOD) -> pd.Series:
    high, low = df["high"], df["low"]
    up, down = high.diff(), -low.diff()
    plus_dm = up.where((up > down) & (up > 0), 0.0)
    minus_dm = down.where((down > up) & (down > 0), 0.0)
    atr = _wilder_atr(df, n)
    plus_di = 100 * plus_dm.ewm(alpha=1 / n, adjust=False,
                                min_periods=n).mean() / atr
    minus_di = 100 * minus_dm.ewm(alpha=1 / n, adjust=False,
                                  min_periods=n).mean() / atr
    denom = (plus_di + minus_di).replace(0, np.nan)
    dx = 100 * (plus_di - minus_di).abs() / denom
    return dx.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()


def enrich(raw: pd.DataFrame) -> pd.DataFrame:
    df = raw.copy()
    df["dt"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    df = df.set_index("dt").sort_index()
    grid = pd.date_range(df.index[0], df.index[-1], freq="h", tz="UTC")
    df = df.reindex(grid)
    quote = df["quote_volume"].rolling(VWAP_WINDOW,
                                        min_periods=VWAP_WINDOW).sum()
    volume = df["volume"].rolling(VWAP_WINDOW,
                                   min_periods=VWAP_WINDOW).sum()
    df["vwap24"] = quote / volume.replace(0, np.nan)
    spread = np.log(df["close"] / df["vwap24"])
    mean = spread.rolling(ZSCORE_WINDOW,
                          min_periods=ZSCORE_WINDOW).mean()
    sd = spread.rolling(ZSCORE_WINDOW,
                        min_periods=ZSCORE_WINDOW).std()
    df["vwap_z"] = (spread - mean) / sd.replace(0, np.nan)
    df["atr14"] = _wilder_atr(df)
    df["adx14"] = _adx(df)
    return df


def signal_times(df: pd.DataFrame) -> pd.DatetimeIndex:
    cond = ((df["adx14"] < 20) & (df["vwap_z"] < ZSCORE_ENTRY)
            & (df["close"] > df["open"]))
    return edge_trigger(cond.fillna(False), COOLDOWN_HOURS)


def trade_outcomes(symbol: str, df: pd.DataFrame,
                   times: pd.DatetimeIndex, split: str) -> list[dict]:
    rows = []
    if split == "train":
        times = times[times + pd.Timedelta(hours=TIMEOUT_HOURS + 1) < TRAIN_END]
    elif split == "test":
        times = times[times >= TRAIN_END]
    for t in times:
        try:
            pos = df.index.get_loc(t)
        except KeyError:
            continue
        if not isinstance(pos, (int, np.integer)) or pos + TIMEOUT_HOURS >= len(df):
            continue
        sig = df.iloc[pos]
        entry_bar = df.iloc[pos + 1]
        entry = float(entry_bar["open"])
        atr = float(sig["atr14"])
        if not math.isfinite(entry) or entry <= 0 or not math.isfinite(atr):
            continue
        stop = entry - STOP_ATR * atr
        exit_price = exit_t = reason = None
        for step in range(1, TIMEOUT_HOURS + 1):
            bar = df.iloc[pos + step]
            if not all(math.isfinite(float(bar[k])) for k in
                       ("open", "low", "close")):
                break
            if float(bar["low"]) <= stop:
                exit_price = min(float(bar["open"]), stop)
                exit_t = df.index[pos + step]
                reason = "stop"
                break
            if math.isfinite(float(bar["vwap_z"])) and float(bar["vwap_z"]) >= ZSCORE_EXIT:
                exit_price = float(bar["close"])
                exit_t = df.index[pos + step]
                reason = "z_exit"
                break
            if step == TIMEOUT_HOURS:
                exit_price = float(bar["close"])
                exit_t = df.index[pos + step]
                reason = "timeout"
        if exit_price is None:
            continue
        gross = (exit_price / entry - 1) * 100
        rows.append({
            "symbol": symbol, "t": t, "entry": entry, "exit": exit_price,
            "exit_t": exit_t, "reason": reason, "gross_pct": gross,
            "net_pct": gross - ROUND_TRIP_COST_PCT,
        })
    return rows


def cluster_pvalue(frame: pd.DataFrame, iterations: int = 4000,
                   seed: int = 71) -> float:
    """Ayni UTC gunundeki korele olaylari birlikte isaret-cevirir."""
    if frame.empty:
        return float("nan")
    values = frame["net_pct"].to_numpy()
    days = pd.to_datetime(frame["t"], utc=True).dt.floor("D")
    groups = [np.flatnonzero(days.to_numpy() == day)
              for day in days.drop_duplicates().to_numpy()]
    actual = values.mean()
    rng = np.random.default_rng(seed)
    exceed = 0
    for _ in range(iterations):
        sim = values.copy()
        signs = rng.choice((-1.0, 1.0), size=len(groups))
        for idx, sign in zip(groups, signs):
            sim[idx] *= sign
        exceed += sim.mean() >= actual
    return (exceed + 1) / (iterations + 1)


def summary(frame: pd.DataFrame) -> dict:
    if frame.empty:
        return {"N": 0}
    net = frame["net_pct"]
    return {
        "N": len(frame), "mean": net.mean(), "median": net.median(),
        "wr": (net > 0).mean(), "q10": net.quantile(0.10),
        "q90": net.quantile(0.90), "p": cluster_pvalue(frame),
        "stop": (frame["reason"] == "stop").mean(),
        "z_exit": (frame["reason"] == "z_exit").mean(),
    }


def fmt(label: str, result: dict) -> str:
    if result.get("N", 0) == 0:
        return f"{label:<24} N=0"
    return (f"{label:<24} N={result['N']:4d} net ort={result['mean']:+.3f}% "
            f"med={result['median']:+.3f}% WR={result['wr']:.1%} "
            f"q10={result['q10']:+.2f}% p(day)={result['p']:.4f} "
            f"stop={result['stop']:.1%} z-exit={result['z_exit']:.1%}")


def main(data_dir: str) -> int:
    root = Path(data_dir)
    manifest = json.loads((root / "manifest_spot89.json").read_text(
        encoding="utf-8"))
    symbols = manifest["symbols"]
    core, extended = set(symbols[:30]), set(symbols[30:])
    panel = {}
    events = {}
    print("S7 VWAP mean-reversion — SABIT TEK ATIS", flush=True)
    print(f"veri: {len(symbols)} sembol · train < {TRAIN_END.date()} · test >= "
          f"{TRAIN_END.date()} · maliyet {ROUND_TRIP_COST_PCT:.2f}%", flush=True)
    for i, symbol in enumerate(symbols, 1):
        frame = enrich(pd.read_parquet(root / "spot" / f"{symbol}.parquet"))
        panel[symbol] = frame
        events[symbol] = signal_times(frame)
        if i % 20 == 0:
            print(f"hazir: {i}/{len(symbols)}", flush=True)

    def collect(group: set[str], split: str) -> pd.DataFrame:
        rows = []
        for symbol in sorted(group):
            rows += trade_outcomes(symbol, panel[symbol], events[symbol], split)
        return pd.DataFrame(rows)

    train_core = collect(core, "train")
    train_ext = collect(extended, "train")
    rc, re = summary(train_core), summary(train_ext)
    print(fmt("TRAIN core30", rc), flush=True)
    print(fmt("TRAIN extended59", re), flush=True)
    train_pass = (rc["N"] >= 100 and rc["mean"] > 0 and rc["median"] > 0
                  and rc["wr"] >= 0.55 and rc["p"] <= 0.05
                  and re["N"] >= 100 and re["mean"] > 0
                  and re["median"] > 0)
    if not train_pass:
        print("KARAR: RED — train/bağımsız-evren kapısı geçilmedi; TESTE BAKILMADI.")
        return 2

    test_core = collect(core, "test")
    test_ext = collect(extended, "test")
    test_all = pd.concat((test_core, test_ext), ignore_index=True)
    rtc, rte, rta = summary(test_core), summary(test_ext), summary(test_all)
    print(fmt("TEST core30", rtc), flush=True)
    print(fmt("TEST extended59", rte), flush=True)
    print(fmt("TEST all89", rta), flush=True)
    passed = (rta["N"] >= 30 and rta["mean"] > 0 and rta["median"] > 0
              and rta["wr"] >= 0.52 and rta["p"] <= 0.05)
    print("KARAR: " + ("KABUL — S7 canlı adayıdır." if passed else
                       "RED — tek test atışında kapı geçilmedi."), flush=True)
    return 0 if passed else 3


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else "data"))
