"""Shared, timestamp-based signal outcomes (no orders or fills)."""
from __future__ import annotations

import math

HOUR_MS = 3_600_000


def hourly_outcome(candles, bar_ms: int, horizon: int, direction: str = "LONG") -> dict:
    """Next hourly open -> final horizon close; reject gaps instead of shifting."""
    if horizon <= 0 or bar_ms % HOUR_MS:
        raise ValueError("invalid_hourly_window")
    by_time = {}
    for candle in candles:
        stamp = int(candle["open_time"])
        if stamp in by_time and candle != by_time[stamp]:
            raise ValueError("conflicting_candle")
        by_time[stamp] = candle
    expected = [bar_ms + i * HOUR_MS for i in range(1, horizon + 1)]
    if any(stamp not in by_time for stamp in expected):
        raise ValueError("missing_required_candle")
    entry = float(by_time[expected[0]]["open"])
    exit_price = float(by_time[expected[-1]]["close"])
    if not all(math.isfinite(x) and x > 0 for x in (entry, exit_price)):
        raise ValueError("invalid_outcome_price")
    if direction not in ("LONG", "SHORT"):
        raise ValueError("invalid_direction")
    sign = 1 if direction == "LONG" else -1
    return {"entry": entry, "exit": exit_price,
            "entry_time_ms": expected[0],
            "exit_time_ms": expected[-1] + HOUR_MS,
            "return_pct": sign * (exit_price / entry - 1) * 100}
