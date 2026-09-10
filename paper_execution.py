"""Strict offline price-path experiments. No orders, invented quantity or dollar PnL.

Entry = next FULL 5m bar strictly after confirmed delivery (plus chosen latency).
Exit = first TP/SL or fixed timeout. A signal's old/reference/proxy price is NEVER
used as its entry fill. Percentages are simple underlying-price returns, not ROI.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import math

FIVE_MIN_MS = 300_000
MEASUREMENT_VERSION = "paper-barriers-v1"


@dataclass(frozen=True)
class ExecutionSpec:
    target_pct: float = 2.0
    stop_pct: float = 1.5
    horizon_hours: int = 24
    latency_ms: int = 0
    round_trip_cost_bps: float = 12.0  # explicit research assumption, not a fee quote

    def __post_init__(self):
        if (not 0 < self.target_pct < 100 or not 0 < self.stop_pct < 100
                or type(self.horizon_hours) is not int or self.horizon_hours <= 0
                or type(self.latency_ms) is not int or self.latency_ms < 0
                or not math.isfinite(self.round_trip_cost_bps)
                or self.round_trip_cost_bps < 0):
            raise ValueError("invalid_execution_spec")

    def fingerprint(self):
        raw = json.dumps({"version": MEASUREMENT_VERSION, **asdict(self)},
                         sort_keys=True, separators=(",", ":"), allow_nan=False)
        return hashlib.sha256(raw.encode()).hexdigest()


def simple_return_pct(entry, exit_price, direction="LONG"):
    if not all(math.isfinite(x) and x > 0 for x in (entry, exit_price)):
        raise ValueError("invalid_outcome_price")
    if direction not in ("LONG", "SHORT"):
        raise ValueError("invalid_direction")
    return (1 if direction == "LONG" else -1) * (exit_price / entry - 1) * 100


def log_price_return_to_simple_pct(log_price_return, direction="LONG"):
    """Input is log(exit/entry), NOT an already direction-signed legacy return."""
    if direction not in ("LONG", "SHORT") or not math.isfinite(log_price_return):
        raise ValueError("invalid_log_price_return")
    return (1 if direction == "LONG" else -1) * math.expm1(log_price_return) * 100


def evaluate_path(candles, *, delivered_at_ms, delivery_confirmed, market,
                  candle_market, symbol, candle_symbol, spec: ExecutionSpec,
                  as_of_ms, direction="LONG"):
    """Return measured/pending/unavailable with coverage and ambiguity metadata.

    Complete candles only. An exit in an incomplete bar is still pending. Missing
    candles before exit invalidate the result; missing candles AFTER exit do not.
    Intrabar exit time is an interval, never fabricated to the second. Fees and
    slippage are a fixed entry-notional sensitivity assumption. Funding is NOT
    modeled: perp net_return_pct stays None, with ex-funding net shown separately.
    """
    result = {
        "measurement_version": MEASUREMENT_VERSION,
        "execution_spec_hash": spec.fingerprint(), "spec": asdict(spec),
        "performance_market": market, "status": "unavailable", "reason": None,
        "entry_price": None, "entry_time_ms": None, "exit_price": None,
        "exit_window_start_ms": None, "exit_window_end_ms": None,
        "exit_reason": None, "gross_return_pct": None,
        "net_ex_funding_return_pct": None, "net_return_pct": None,
        "funding_status": "not_modeled" if market == "um_perp" else "not_applicable",
        "same_bar_ambiguous": False, "tp_before_sl_lower": None,
        "tp_before_sl_upper": None, "entry_definition": "next_full_5m_open_after_delivery",
        "fill_assumption": "hypothetical_ohlc_with_fixed_cost_not_actual_fill",
    }

    def fail(reason):
        result["reason"] = reason
        return result

    if delivery_confirmed is not True:
        return fail("delivery_not_confirmed")
    if market not in ("spot", "um_perp") or candle_market != market:
        return fail("market_mismatch_or_unsupported")
    if not symbol or symbol != candle_symbol:
        return fail("contract_mismatch")
    if direction not in ("LONG", "SHORT"):
        return fail("invalid_direction")
    if market == "spot" and direction == "SHORT":
        return fail("spot_borrow_not_modeled")
    if any(type(t) is not int or t < 0 for t in (delivered_at_ms, as_of_ms)):
        return fail("invalid_timestamp")
    entry_at = ((delivered_at_ms + spec.latency_ms) // FIVE_MIN_MS + 1) * FIVE_MIN_MS
    result["entry_time_ms"] = entry_at
    expiry = entry_at + spec.horizon_hours * 3_600_000
    by_time = {}
    for bar in candles:
        stamp = bar.get("open_time")
        if type(stamp) is not int or stamp % FIVE_MIN_MS:
            return fail("invalid_candle_timestamp")
        if not entry_at <= stamp < expiry or stamp + FIVE_MIN_MS > as_of_ms:
            continue
        if stamp in by_time and bar != by_time[stamp]:
            return fail("conflicting_candle")
        by_time[stamp] = bar
    sign = 1 if direction == "LONG" else -1
    entry = target = stop = None
    for stamp in range(entry_at, expiry, FIVE_MIN_MS):
        if stamp + FIVE_MIN_MS > as_of_ms:
            result["status"], result["reason"] = "pending", "awaiting_closed_bar"
            return result
        bar = by_time.get(stamp)
        if bar is None:
            return fail("missing_required_candle")
        try:
            o, h, l, c = (float(bar[k]) for k in ("open", "high", "low", "close"))
        except (KeyError, TypeError, ValueError, OverflowError):
            return fail("invalid_ohlc")
        if not all(math.isfinite(p) and p > 0 for p in (o, h, l, c)) or not (
                l <= min(o, c) <= max(o, c) <= h):
            return fail("invalid_ohlc")
        if entry is None:
            entry = o
            target = entry * (1 + sign * spec.target_pct / 100)
            stop = entry * (1 - sign * spec.stop_pct / 100)
            result.update(entry_price=entry, target_price=target, stop_price=stop)
        favorable, adverse = (h, l) if sign == 1 else (l, h)
        tp = sign * (favorable - target) >= 0
        sl = sign * (adverse - stop) <= 0
        tp_open = sign * (o - target) >= 0
        sl_open = sign * (o - stop) <= 0
        price = reason = None
        if sl_open:
            price, reason = o, "stop_gap"  # gap through stop fills worse than stop
        elif tp_open:
            price, reason = target, "target_gap"  # conservative target-limit proxy
        elif sl:
            price, reason = stop, "stop"
            if tp:
                result["same_bar_ambiguous"] = True
        elif tp:
            price, reason = target, "target"
        elif stamp + FIVE_MIN_MS == expiry:
            price, reason = c, "timeout"
        if price is None:
            continue
        gross = simple_return_pct(entry, price, direction)
        net = gross - spec.round_trip_cost_bps / 100
        success = reason.startswith("target")
        result.update(
            status="measured", reason=None, exit_price=price, exit_reason=reason,
            exit_window_start_ms=stamp, exit_window_end_ms=stamp + FIVE_MIN_MS,
            gross_return_pct=gross, net_ex_funding_return_pct=net,
            net_return_pct=net if market == "spot" else None,
            tp_before_sl_lower=success,
            tp_before_sl_upper=success or result["same_bar_ambiguous"],
        )
        return result
    raise AssertionError("unreachable_window")
