"""Pure live-compatible signal mathematics. No I/O, environment or trade execution.

Version 1 preserves the live bot, including SMA-seeded Wilder RSI, the current
bar in volume windows, first tied low, and cooldown consumption before S3's
green-bar filter. Historical vectorized research remains a separate legacy model.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import math

ENGINE_VERSION = "live-compatible-v1"
HOUR_MS = 3_600_000


@dataclass(frozen=True)
class CoreRules:
    kline_limit: int = 250  # API limit includes the open candle; use 249 closed.
    rsi_period: int = 14
    oversold: float = 22.5
    divergence_lookback: int = 60
    divergence_gap: int = 5
    volume_window: int = 168
    volume_threshold: float = 3.0
    confluence_hours: int = 24
    funding_threshold_pct: float = -0.03
    funding_persistence: int = 2
    s1_cooldown_hours: float = 12
    s2_cooldown_hours: float = 24
    s3_cooldown_hours: float = 12

    def __post_init__(self):
        for name in ("kline_limit", "rsi_period", "divergence_lookback",
                     "divergence_gap", "volume_window", "funding_persistence"):
            value = getattr(self, name)
            if type(value) is not int or value <= 0:
                raise ValueError("invalid_rule_" + name)
        if type(self.confluence_hours) is not int or self.confluence_hours < 0:
            raise ValueError("invalid_confluence_hours")
        if self.kline_limit - 1 < self.minimum_bars:
            raise ValueError("insufficient_kline_limit")
        for name, value in asdict(self).items():
            if not math.isfinite(value):
                raise ValueError("nonfinite_rule_" + name)
        if not 0 <= self.oversold <= 100 or self.volume_threshold < 0:
            raise ValueError("invalid_threshold")
        if min(self.s1_cooldown_hours, self.s2_cooldown_hours,
               self.s3_cooldown_hours) < 0:
            raise ValueError("invalid_cooldown")

    @property
    def minimum_bars(self):
        return max(self.divergence_lookback + self.divergence_gap,
                   self.volume_window // 2) + self.rsi_period

    def fingerprint(self):
        body = json.dumps({"engine": ENGINE_VERSION, "rules": asdict(self)},
                          sort_keys=True, separators=(",", ":"), allow_nan=False)
        return hashlib.sha256(body.encode()).hexdigest()


def wilder_rsi(closes, period=14):
    n = len(closes)
    rsi = [math.nan] * n
    if n <= period:
        return rsi
    gains = losses = 0.0
    for i in range(1, period + 1):
        d = closes[i] - closes[i - 1]
        gains += max(d, 0.0)
        losses += max(-d, 0.0)
    avg_g, avg_l = gains / period, losses / period
    rsi[period] = 100.0 if avg_l == 0 else 100 - 100 / (1 + avg_g / avg_l)
    for i in range(period + 1, n):
        d = closes[i] - closes[i - 1]
        avg_g = (avg_g * (period - 1) + max(d, 0.0)) / period
        avg_l = (avg_l * (period - 1) + max(-d, 0.0)) / period
        rsi[i] = 100.0 if avg_l == 0 else 100 - 100 / (1 + avg_g / avg_l)
    return rsi


def log_volume_zscore(volumes, window=168):
    logs = [math.log1p(v) for v in volumes]
    z = [math.nan] * len(logs)
    for i in range(len(logs)):
        w = logs[max(0, i - window + 1):i + 1]
        if len(w) < window // 2:
            continue
        mu = sum(w) / len(w)
        var = sum((x - mu) ** 2 for x in w) / (len(w) - 1) if len(w) > 1 else 0.0
        sd = math.sqrt(var)
        if sd > 0:
            z[i] = (logs[i] - mu) / sd
    return z


def bullish_divergence(lows, rsi, i, lookback=60, gap=5):
    hi = i - gap
    lo = hi - lookback + 1
    if lo < 0 or hi <= lo:
        return False
    window = lows[lo:hi + 1]
    pmin = min(window)
    pidx = lo + window.index(pmin)
    return lows[i] < pmin and not math.isnan(rsi[pidx]) and rsi[i] > rsi[pidx]


def oversold(value, threshold):
    return not math.isnan(value) and value <= threshold


def volume_spike(value, threshold):
    return not math.isnan(value) and value >= threshold


def recent_volume_spike(zscores, i, lookback, threshold):
    # Inclusive endpoints intentionally retain the live 24h lag convention.
    return any(volume_spike(z, threshold)
               for z in zscores[max(0, i - lookback):i + 1])


def funding_squeeze(records, threshold_pct, persistence):
    return len(records) >= persistence and all(
        x["rate"] <= threshold_pct / 100.0 for x in records[-persistence:])


def should_fire(prev_cond, last_fire, strategy, symbol, cond, cooldown_hours, now_s):
    """Mutate caller-owned maps, exactly as ScanState did before extraction."""
    key = (strategy, symbol)
    prev = prev_cond.get(key)
    prev_cond[key] = cond
    if not cond or prev is None or prev:
        return False
    if now_s - last_fire.get(key, 0.0) < cooldown_hours * 3600:
        return False
    last_fire[key] = now_s
    return True


def closed_window_features(candles, rules: CoreRules):
    """Research adapter; caller supplies only closed, consecutive hourly bars.

    Reset the RSI seed for every API-sized window, not once over full history.
    This function neither advances cooldowns nor chooses a universe.
    """
    bars = candles[-(rules.kline_limit - 1):]
    if len(bars) < rules.minimum_bars:
        return None
    times = [b["open_time"] for b in bars]
    if any(type(t) is not int or t % HOUR_MS for t in times):
        raise ValueError("invalid_hourly_timestamp")
    if any(b - a != HOUR_MS for a, b in zip(times, times[1:])):
        raise ValueError("noncontiguous_hourly_window")
    for b in bars:
        if any(not math.isfinite(b[k]) or b[k] <= 0
               for k in ("open", "high", "low", "close")):
            raise ValueError("invalid_price")
        if not math.isfinite(b["volume"]) or b["volume"] < 0:
            raise ValueError("invalid_volume")
        if not b["low"] <= min(b["open"], b["close"]) <= max(
                b["open"], b["close"]) <= b["high"]:
            raise ValueError("invalid_ohlc")
    closes = [b["close"] for b in bars]
    rsi = wilder_rsi(closes, rules.rsi_period)
    zs = log_volume_zscore([b["volume"] for b in bars], rules.volume_window)
    i = len(bars) - 1
    return {
        "bar_time_ms": times[-1], "signal_price": closes[-1],
        "rsi": rsi[-1], "volume_logz": zs[-1],
        "s1": oversold(rsi[-1], rules.oversold) and bullish_divergence(
            [b["low"] for b in bars], rsi, i, rules.divergence_lookback,
            rules.divergence_gap),
        "s3_spike": volume_spike(zs[-1], rules.volume_threshold),
        "green_bar": closes[-1] > bars[-1]["open"],
        "s4": recent_volume_spike(zs, i, rules.confluence_hours,
                                   rules.volume_threshold),
    }
