"""Pure daily BTC market-regime calculation used by the bot and tests.

The module deliberately has no network, file, Telegram or environment access.
The caller owns fetching/caching Binance spot BTCUSDT UTC daily klines.
"""
from __future__ import annotations

from datetime import datetime, timezone
import math

DAY_MS = 86_400_000
VERSION = "btc-daily-regime-v1"
SOURCE = "binance_spot_btcusdt_1d_utc"
MIN_CLOSED_DAYS = 220
SMA_DAYS = 200
SLOPE_DAYS = 20
MOMENTUM_DAYS = 30


def _iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, timezone.utc).isoformat()


def _pct(value: float) -> float:
    return round(value * 100, 4)


def _validate_rows(rows: list[list], as_of_ms: int) -> list[tuple[int, float, int]]:
    closed = []
    for row in rows:
        if not isinstance(row, (list, tuple)) or len(row) < 7:
            continue
        try:
            open_ms, close_ms = int(row[0]), int(row[6])
            close = float(row[4])
        except (TypeError, ValueError, OverflowError):
            continue
        if close_ms >= as_of_ms:
            continue
        if close_ms != open_ms + DAY_MS - 1 or open_ms % DAY_MS:
            raise ValueError("invalid_daily_close_boundary")
        if not math.isfinite(close) or close <= 0:
            raise ValueError("invalid_daily_close")
        closed.append((open_ms, close, close_ms))
    closed.sort()
    if not closed:
        raise ValueError("no_closed_daily_btc_rows")
    for (previous, _, _), (current, _, _) in zip(closed, closed[1:]):
        if current == previous:
            raise ValueError("duplicate_daily_btc_row")
        if current - previous != DAY_MS:
            raise ValueError("noncontiguous_daily_btc_rows")
    if len(closed) < MIN_CLOSED_DAYS:
        raise ValueError(f"insufficient_closed_daily_btc_rows:{len(closed)}")
    return closed


def compute_snapshot(rows: list[list], *, as_of_ms: int | None = None,
                     fetched_at: str | None = None,
                     computed_at: str | None = None) -> dict:
    """Return the versioned label from closed daily Binance spot rows.

    Rows are Binance kline arrays. The latest row whose close time is before
    ``as_of_ms`` is the reference; an open/current daily candle can never leak
    into the label. ``TRANSITION`` means valid data without a decisive trend.
    """
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    as_of_ms = int(as_of_ms if as_of_ms is not None else now_ms)
    closed = _validate_rows(rows, as_of_ms)
    closes = [value for _, value, _ in closed]
    latest_open, latest, latest_close = closed[-1]
    sma200 = sum(closes[-SMA_DAYS:]) / SMA_DAYS
    old_sma = sum(closes[-SMA_DAYS-SLOPE_DAYS:-SLOPE_DAYS]) / SMA_DAYS
    slope = sma200 / old_sma - 1 if old_sma > 0 else math.nan
    momentum = (latest / closes[-1-MOMENTUM_DAYS] - 1
                if len(closes) > MOMENTUM_DAYS else math.nan)
    distance = latest / sma200 - 1
    fresh = as_of_ms - latest_close <= 2 * DAY_MS
    if not fresh:
        label, subtype = "UNKNOWN", "UNKNOWN"
    elif distance > 0.02 and slope > 0:
        label = "BULL"
        if momentum < 0:
            subtype = "bull_pullback"
        elif momentum <= 0.10:
            subtype = "bull_moderate"
        else:
            subtype = "bull_strong"
    elif distance < -0.02 and slope < 0:
        label, subtype = "BEAR", "BEAR"
    else:
        label, subtype = "TRANSITION", "TRANSITION"
    return {
        "version": VERSION,
        "source": SOURCE,
        "label": label,
        "subtype": subtype,
        "reference_at": _iso(latest_close + 1),
        "data_close_at": _iso(latest_close),
        "computed_at": computed_at or _iso(now_ms),
        "fetched_at": fetched_at,
        "btc_close": round(latest, 8),
        "sma200": round(sma200, 8),
        "distance_pct": _pct(distance),
        "slope20_pct": _pct(slope),
        "momentum30_pct": _pct(momentum),
        "fresh": fresh,
        "last_error": None if fresh else "stale_daily_btc_data",
    }


def unknown_snapshot(error: str | None = None, *, fetched_at: str | None = None) -> dict:
    return {
        "version": VERSION, "source": SOURCE, "label": "UNKNOWN",
        "subtype": "UNKNOWN", "reference_at": None, "data_close_at": None,
        "computed_at": None, "fetched_at": fetched_at, "btc_close": None,
        "sma200": None, "distance_pct": None, "slope20_pct": None,
        "momentum30_pct": None, "fresh": False,
        "last_error": error,
    }
