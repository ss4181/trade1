"""Closed-bar BTC/ETH trend context. No trading decisions, I/O or live candles."""
from datetime import datetime, timezone
import math

VERSION = "btc-eth-intraday-v1"
MINUTE = 60_000
HOUR = 60 * MINUTE
NAMES = {"BULL": "BOĞA", "BEAR": "AYI", "TRANSITION": "GEÇİŞ", "UNKNOWN": "BELİRSİZ"}


def iso(ms):
    return datetime.fromtimestamp(ms / 1000, timezone.utc).isoformat()


def closed_bars(raw, interval_ms, as_of_ms, *, minimum=2):
    bars = []
    for row in raw:
        t, end = int(row[0]), int(row[6])
        if end >= as_of_ms:
            continue
        o, h, l, c = map(float, row[1:5])
        if (t % interval_ms or end != t + interval_ms - 1
                or not all(math.isfinite(v) and v > 0 for v in (o, h, l, c))
                or not l <= min(o, c) <= max(o, c) <= h):
            raise ValueError("invalid_intraday_candle")
        bars.append({"time": t, "open": o, "high": h, "low": l, "close": c})
    bars.sort(key=lambda b: b["time"])
    if (len(bars) < minimum or any(b["time"] - a["time"] != interval_ms
                                  for a, b in zip(bars, bars[1:]))):
        raise ValueError("missing_or_duplicate_intraday_candles")
    if bars[-1]["time"] != as_of_ms // interval_ms * interval_ms - interval_ms:
        raise ValueError("stale_intraday_candle")
    return bars


def ema(values, period):
    out = [values[0]]
    alpha = 2 / (period + 1)
    for value in values[1:]:
        out.append(out[-1] + alpha * (value - out[-1]))
    return out


def trend(bars, *, offset=0):
    """EMA20/50 direction with a 0.25 ATR dead band and four-bar slope."""
    values = bars[:len(bars)-offset] if offset else bars
    closes = [b["close"] for b in values]
    fast, slow = ema(closes, 20), ema(closes, 50)
    ranges = [max(b["high"]-b["low"], abs(b["high"]-a["close"]),
                  abs(b["low"]-a["close"])) for a, b in zip(values, values[1:])]
    atr = sum(ranges[-14:]) / 14
    band = max(0.25 * atr, closes[-1] * 0.001)
    up = closes[-1] > slow[-1]+band and fast[-1] > slow[-1]+band and fast[-1] > fast[-5]
    down = closes[-1] < slow[-1]-band and fast[-1] < slow[-1]-band and fast[-1] < fast[-5]
    return {"label": "BULL" if up else "BEAR" if down else "TRANSITION",
            "close": closes[-1], "ema20": fast[-1], "ema50": slow[-1], "atr14": atr}


def snapshot(raw_by_symbol_interval, as_of_ms):
    details = {}
    for symbol in ("BTCUSDT", "ETHUSDT"):
        for interval, ms in (("1h", HOUR), ("15m", 15*MINUTE)):
            bars = closed_bars(raw_by_symbol_interval[symbol, interval], ms, as_of_ms, minimum=240)[-240:]
            current, previous = trend(bars), trend(bars, offset=1)
            # Two distinct closed bars, never two polls of the same candle.
            confirmed = current["label"] if current["label"] == previous["label"] else "TRANSITION"
            details[f"{symbol}:{interval}"] = {**current, "confirmed": confirmed}
    def combined(interval):
        btc = details[f"BTCUSDT:{interval}"]["confirmed"]
        eth = details[f"ETHUSDT:{interval}"]["confirmed"]
        return btc if btc == eth else "TRANSITION"
    return {"version": VERSION, "hourly": combined("1h"), "early": combined("15m"),
            "hourly_reference_at": iso(as_of_ms//HOUR*HOUR),
            "reference_at": iso(as_of_ms//(15*MINUTE)*(15*MINUTE)),
            "computed_at": iso(as_of_ms), "fresh": True, "details": details, "last_error": None}
