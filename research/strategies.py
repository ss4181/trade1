"""Uc stratejinin parametrik sinyal uretimi (arastirma tarafi).

Botun canli mantigiyla birebir ayni kosullar; tek fark burada tum tarih
uzerinde vektorize calisiyor olmalari.
"""

import numpy as np
import pandas as pd
from numpy.lib.stride_tricks import sliding_window_view

from common import edge_trigger


def wilder_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    rs = avg_gain / avg_loss
    return 100 - 100 / (1 + rs)


def _rolling_argmax_val(arr: np.ndarray, window: int, gap: int, mode: str):
    """Her t icin [t-gap-window+1, t-gap] araliginin max/min degeri ve o
    bardaki indeks (mutlak konum). NaN'ler max icin -inf, min icin +inf."""
    n = len(arr)
    fill = -np.inf if mode == "max" else np.inf
    a = np.where(np.isnan(arr), fill, arr)
    out_val = np.full(n, np.nan)
    out_idx = np.full(n, -1, dtype=int)
    if n < window + gap:
        return out_val, out_idx
    sw = sliding_window_view(a, window)          # sw[i] = a[i : i+window]
    rel = sw.argmax(axis=1) if mode == "max" else sw.argmin(axis=1)
    vals = sw[np.arange(len(sw)), rel]
    # pencere [t-gap-window+1 .. t-gap] -> baslangic i = t-gap-window+1
    t0 = window + gap - 1
    out_val[t0:] = vals[: n - t0]
    out_idx[t0:] = rel[: n - t0] + np.arange(n - t0)
    valid = np.isfinite(out_val)
    out_val[~valid] = np.nan
    out_idx[~valid] = -1
    return out_val, out_idx


def s1_events(panel: dict, overbought: float, oversold: float,
              lookback: int = 60, gap: int = 5, margin: float = 0.0,
              cooldown: int = 12, require_divergence: bool = True) -> dict:
    """RSI uyumsuzlugu.

    Bearish: rsi[t] >= overbought  VE  high[t] > onceki tepe (son
    `lookback` bar, son `gap` bar haric)  VE  rsi[t] < o tepedeki RSI - margin
    -> SHORT (-1). Bullish ayna -> LONG (+1).
    require_divergence=False ise sadece RSI ekstremi (fiyat/uyumsuzluk sarti yok).
    """
    events = {}
    for sym, df in panel.items():
        rsi = wilder_rsi(df["close"])
        high, low = df["high"].to_numpy(), df["low"].to_numpy()
        r = rsi.to_numpy()
        if require_divergence:
            pmax, imax = _rolling_argmax_val(high, lookback, gap, "max")
            pmin, imin = _rolling_argmax_val(low, lookback, gap, "min")
            rsi_at_max = np.where(imax >= 0, r[imax], np.nan)
            rsi_at_min = np.where(imin >= 0, r[imin], np.nan)
            bear = (r >= overbought) & (high > pmax) & (r < rsi_at_max - margin)
            bull = (r <= oversold) & (low < pmin) & (r > rsi_at_min + margin)
        else:
            bear = r >= overbought
            bull = r <= oversold
        bear_t = edge_trigger(pd.Series(bear, index=df.index), cooldown)
        bull_t = edge_trigger(pd.Series(bull, index=df.index), cooldown)
        times = bear_t.append(bull_t)
        dirs = np.r_[np.full(len(bear_t), -1), np.full(len(bull_t), 1)]
        order = np.argsort(times)
        events[sym] = (times[order], dirs[order])
    return events


def s2_events(funding: dict, threshold_pct: float, persistence: int = 1,
              cooldown: int = 24) -> dict:
    """Funding squeeze: funding orani esigin altina inince LONG.

    threshold_pct yuzde cinsinden (-0.02 => -%0.02 => kesir -0.0002).
    persistence: ardarda kac funding araligi esigin altinda kalmali.
    Olay zamani: funding settlement saatine yuvarlanir (o barin acilisi giris).
    """
    thr = threshold_pct / 100.0
    events = {}
    for sym, fr in funding.items():
        t = pd.to_datetime(fr["calc_time"], unit="ms", utc=True).dt.floor("h")
        below = (fr["last_funding_rate"] <= thr).to_numpy()
        if persistence > 1:
            ok = below.copy()
            for k in range(1, persistence):
                ok &= np.r_[np.zeros(k, dtype=bool), below[:-k]]
            below = ok
        cond = pd.Series(below, index=pd.DatetimeIndex(t))
        cond = cond[~cond.index.duplicated(keep="last")]
        times = edge_trigger(cond, cooldown)
        events[sym] = (times, np.full(len(times), 1))
    return events


def volume_zscore(volume: pd.Series, window: int = 168,
                  use_log: bool = False) -> pd.Series:
    v = np.log1p(volume) if use_log else volume
    mu = v.rolling(window, min_periods=window // 2).mean()
    sd = v.rolling(window, min_periods=window // 2).std()
    return (v - mu) / sd


def s3_events(panel: dict, z_thresh: float, window: int = 168,
              use_log: bool = False, cooldown: int = 12,
              direction: str = "bar") -> dict:
    """Hacim anomalisi: Z > esik. Yon:
    'bar'      -> anomali barinin yonu (momentum devam hipotezi)
    'bar_up'   -> sadece yukari barlar, LONG (pump devami)
    'bar_down' -> sadece asagi barlar, SHORT (dump devami)
    'long'/'short' -> kosulsuz tek yon (fade hipotezi testi icin)."""
    events = {}
    for sym, df in panel.items():
        z = volume_zscore(df["volume"], window, use_log)
        cond = pd.Series(z > z_thresh, index=df.index)
        times = edge_trigger(cond, cooldown)
        barsign = np.sign((df["close"] - df["open"]).reindex(times).to_numpy())
        barsign[barsign == 0] = 1
        if direction == "bar":
            dirs = barsign
        elif direction == "bar_up":
            times = times[barsign > 0]
            dirs = np.full(len(times), 1)
        elif direction == "bar_down":
            times = times[barsign < 0]
            dirs = np.full(len(times), -1)
        else:
            dirs = np.full(len(times), 1 if direction == "long" else -1)
        events[sym] = (times, dirs)
    return events
