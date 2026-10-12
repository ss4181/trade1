"""Pure forward-only hypothetical LONG price paths; no I/O or live execution.

API: create_event(record, event_id, activated_ms, now_ms), advance(event, bars,
as_of_ms), public_event(event). Times are integer UTC milliseconds. Bars are
dicts with open_time, close_time and open/high/low/close (numeric strings OK).
close_time must equal open_time + STEP - 1; processing waits until open_time +
STEP <= as_of_ms. The caller must supply the event's exact symbol/market bars.

The caller enforces frozen symbol-list membership (not runtime overrides), owns
event-ID deduplication/persistence and passes delivered_at = FIRST Telegram API
acknowledgement. No notified_at/reference-price/legacy fallback exists here.
Config labels must be non-placeholder safe tokens; distinct labels/hashes MUST
remain distinct cohorts. S1/S3 require engine provenance; native G2 records may
lack engine provenance, which remains None rather than an invented hash.

Consumed bars are immutable: retries may overlap them, but do not revise them.
Duplicate conflicts in the unconsumed path stop at the affected candle. Fetch
again from next_start_ms to recover; no future bars are retained across calls.
Private _confirmation contains only the first three normalized OHLC tuples and
must be persisted with the event, never reconstructed from a public projection.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import math
import re

VERSION = "execution-shadow-v1"
STEP = 300_000
_HOUR = 3_600_000
# Tuples, not a mutable parameter grid. Changes require a new study/version.
_SPECS = (
    ("S1", "extended59", "spot", 24, (
        ("baseline", "NOW", "FIXED", 3., 2.),
        ("distant", "NOW", "FIXED", 6., 3.))),
    ("S3", "core30", "spot", 4, (
        ("baseline", "NOW", "FIXED", 3., 2.),
        ("confirm15_fixed", "CONFIRM15", "FIXED", 3., 3.),
        ("confirm15_trail", "CONFIRM15", "TRAIL", 3., 3.))),
    ("G2", "g2_fixed87_binance_signal_universe", "um_perp", 24, (
        ("baseline", "NOW", "FIXED", 3., 2.),
        ("previous_fixed", "NOW", "FIXED", 4., 3.),
        ("partial_trail", "NOW", "PARTIAL", 6., 3.))),
)
_METHOD = (
    "research_only_hypothetical_simple_price_percent_not_trading_or_portfolio",
    "first_confirmed_ack_push_allowed_not_suppressed_LONG_canonical32hex",
    "nonplaceholder_config_core_engine_version_sha256_G2_optional_provenance",
    "caller_checks_frozen_symbol_membership_and_exact_market_contract",
    "activated<=delivered<=now;now-delivered<=300000;no_legacy_backfill",
    "S1_S3_strict_next_5m;G2_exact_planned_UTC_hour_delivery_strictly_before",
    "shared_deadline_anchor_plus_horizon;confirm_first3:c2>o0,c2>c1,l2>=l1",
    "confirm_entry_fourth_open;failed_confirm_NO_ENTRY_zero_cost_zero_return",
    "closed_contiguous_5m;close_time=open_time+299999;closed_at=open_time+300000",
    "consumed_prefix_immutable;sort_pending;equal_duplicates_OK;conflicts_block",
    "gap_invalid_UNKNOWN_cursor_retry;future_not_cached;terminal_outcomes_frozen",
    "old_simulate:fixed_open>=TP_first_at_target;else_stop_first;adverse_gap_at_open",
    "intrabar_stop_and_unactivated_target_AMBIGUOUS_STOP;gap_not_ambiguous",
    "trail_activation_target;next_bar_stop=max(old,entry,peak_high*(1-sl/100))",
    "PARTIAL_half_target_half_trail;abstract_weights_not_quantity",
    "20_40bps_roundtrip_cost_times_closed_fraction;perp_funding_not_modeled",
    "perp_net_including_funding_null_except_NO_ENTRY;timeout_last_close",
    "MAE_MFE_closed_bar_bounds_include_entire_exit_bar_not_intrabar_attainable",
    "full_path_anchor_open_reference;plan_full_path_from_entry_even_after_exit",
    "event_complete_only_final_contiguous_bar;no_auto_promotion_or_trading_claim",
)
PLAN_HASH = hashlib.sha256(json.dumps(
    {"version": VERSION, "step": STEP, "specs": _SPECS, "method": _METHOD},
    sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()

_TERMINAL = frozenset(("NO_ENTRY", "TP", "STOP", "STOP_GAP", "TRAIL_STOP",
                       "TRAIL_STOP_GAP", "AMBIGUOUS_STOP", "TIMEOUT"))
_REASONS = frozenset(("awaiting_closed_bar", "missing_bar", "invalid_timestamp",
                      "invalid_close_time", "invalid_ohlc", "conflicting_bar"))
_REGIMES = frozenset(("BULL", "BEAR", "TRANSITION", "UNKNOWN"))
_SYMBOL = re.compile(r"[A-Z0-9]+USDT\Z", re.ASCII)
_ID = re.compile(r"[0-9a-f]{32}\Z", re.ASCII)
_HASH = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)
_LABEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,95}\Z", re.ASCII)
_ISO = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?"
                  r"(?:Z|[+-]\d{2}:\d{2})\Z", re.ASCII)


def _matches(pattern, value):
    return type(value) is str and pattern.fullmatch(value) is not None


def _label(value):
    return (_matches(_LABEL, value)
            and value.lower() not in {"unknown", "legacy", "none", "null", "na", "n-a"})


def _ms(value):
    return type(value) is int and 0 <= value <= 253_402_300_799_999


def _number(value):
    return type(value) in (int, float) and math.isfinite(value)


def _time_us(value):
    if not _matches(_ISO, value):
        return None
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        delta = stamp.astimezone(timezone.utc) - datetime(1970, 1, 1, tzinfo=timezone.utc)
        return (delta.days * 86400 + delta.seconds) * 1_000_000 + delta.microseconds
    except (ValueError, OverflowError):
        return None


def _spec(strategy):
    return next((spec for spec in _SPECS if spec[0] == strategy), None)


def _new_plan(spec, end_ms, market):
    name, entry, mode, tp, sl = spec
    return dict(plan_id=name, entry_rule=entry, exit_rule=mode, tp_pct=tp, sl_pct=sl,
                end_ms=end_ms, status="WAITING", data_status="PENDING",
                data_reason="awaiting_closed_bar", entered=False, entry_ms=None,
                entry_price=None, decision_ms=None, target_price=None, stop_price=None,
                stop_effective_ms=None, peak_high=None, target_activated=False,
                trailing_active=False, same_bar_ambiguous=False, remaining_fraction=0.,
                closed_fraction=0., legs=[], exit_window_start_ms=None,
                exit_window_end_ms=None, realized_gross_pct=0., cost20_pct=0.,
                cost40_pct=0., gross_pct=None, net_ex_funding20_pct=None,
                net_ex_funding40_pct=None, net20_pct=None, net40_pct=None,
                funding_status="not_modeled" if market == "um_perp" else "not_applicable",
                until_exit_mae_pct=None, until_exit_mfe_pct=None,
                full_window_mae_pct=None, full_window_mfe_pct=None,
                full_window_complete=False, full_window_data_status="PENDING")


def create_event(record, event_id, activated_ms, now_ms) -> dict | None:
    """Enroll a fresh first-ACK record, or return None without side effects.

    symbol membership is deliberately checked by the caller using frozen lists.
    horizon_hours/market metadata, if present, must agree with the frozen cohort.
    engine_config_hash is a lowercase SHA256; no unknown placeholder is allowed.
    G2's absent engine fields are allowed, but malformed supplied fields are not.
    """
    if (type(record) is not dict or not _matches(_ID, event_id)
            or not _ms(activated_ms) or not _ms(now_ms) or activated_ms > now_ms):
        return None
    if (record.get("delivery_confirmed") is not True
            or record.get("push_allowed") is not True
            or record.get("suppressed", False) is not False
            or record.get("direction") != "LONG"
            or record.get("delivery_status", "delivered") not in ("delivered", "partial")):
        return None
    spec = _spec(record.get("strategy"))
    if spec is None or not _matches(_SYMBOL, record.get("symbol")):
        return None
    strategy, universe, market, hours, arms = spec
    if (record.get("universe") != universe or not _label(record.get("config_version"))
            or record.get("horizon_hours", hours) != hours):
        return None
    if any(record.get(key, market) != market
           for key in ("market", "performance_market", "signal_market")):
        return None
    symbol = record["symbol"]
    if record.get("performance_symbol", symbol) != symbol:
        return None
    engine_version, digest = record.get("engine_version"), record.get("engine_config_hash")
    if strategy != "G2":
        if not _label(engine_version) or not _matches(_HASH, digest):
            return None
    elif ((engine_version is not None and not _label(engine_version))
          or (digest is not None and not _matches(_HASH, digest))):
        return None
    delivered_us = _time_us(record.get("delivered_at"))
    if delivered_us is None:
        return None
    delivered = delivered_us // 1000
    if not activated_ms <= delivered <= now_ms or now_ms - delivered > STEP:
        return None
    anchor = (delivered // STEP + 1) * STEP
    if strategy == "G2":
        planned_us = _time_us(record.get("planned_entry_at"))
        if (record.get("performance_symbol") != symbol or planned_us is None
                or planned_us % (_HOUR * 1000) or delivered_us >= planned_us):
            return None
        anchor = planned_us // 1000
    end = anchor + hours * _HOUR
    if not _ms(end):
        return None
    regime = record.get("market_regime", record.get("regime", "UNKNOWN"))
    if type(regime) is not str or regime not in _REGIMES:
        regime = "UNKNOWN"
    return dict(event_id=event_id, study_version=VERSION, plan_hash=PLAN_HASH,
                research_only=True, created_at_ms=now_ms, activated_ms=activated_ms,
                delivered_ms=delivered, anchor_ms=anchor, end_ms=end,
                next_start_ms=anchor, strategy=strategy, symbol=symbol, market=market,
                universe=universe, direction="LONG", horizon_hours=hours,
                config_version=record["config_version"], engine_version=engine_version,
                engine_config_hash=digest, regime=regime, status="active",
                data_status="PENDING", data_reason="awaiting_closed_bar",
                blocked_ms=None, processed_bars=0, full_window_reference_price=None,
                full_window_mae_pct=None, full_window_mfe_pct=None,
                full_window_complete=False, plans={s[0]: _new_plan(s, end, market) for s in arms},
                _confirmation=[])


def _index_bars(bars, start, end, as_of):
    """Index only needed CLOSED bars; invalid duplicates poison their own slot."""
    indexed, errors = {}, {}
    for bar in bars:
        if type(bar) is not dict or not _ms(bar.get("open_time")):
            errors[start] = "invalid_timestamp"
            continue
        stamp = bar["open_time"]
        slot = stamp // STEP * STEP
        if not start <= slot < end or slot + STEP > as_of:
            continue
        if stamp != slot:
            errors[slot] = "invalid_timestamp"
            continue
        if type(bar.get("close_time")) is not int or bar["close_time"] != stamp + STEP - 1:
            errors[slot] = "invalid_close_time"
            continue
        try:
            raw = tuple(bar[k] for k in ("open", "high", "low", "close"))
            if any(type(v) not in (int, float, str) for v in raw):
                raise ValueError
            values = tuple(float(v) for v in raw)
            o, h, low, c = values
            if (not all(math.isfinite(v) and v > 0 for v in values)
                    or not low <= min(o, c) <= max(o, c) <= h):
                raise ValueError
        except (KeyError, TypeError, ValueError, OverflowError):
            errors[slot] = "invalid_ohlc"
            continue
        if slot in indexed and indexed[slot] != values:
            errors[slot] = "conflicting_bar"
        indexed[slot] = values
    return indexed, errors


def _excursion(obj, prefix, reference, high, low):
    mfe, mae = prefix + "mfe_pct", prefix + "mae_pct"
    obj[mfe] = max(obj[mfe] or 0., (high / reference - 1) * 100)
    obj[mae] = min(obj[mae] or 0., (low / reference - 1) * 100)


def _settle(plan, status):
    plan["status"] = status
    plan["data_status"], plan["data_reason"] = "OK", None
    plan["gross_pct"] = plan["realized_gross_pct"]
    for bps in (20, 40):
        net = plan["gross_pct"] - plan[f"cost{bps}_pct"]
        plan[f"net_ex_funding{bps}_pct"] = net
        plan[f"net{bps}_pct"] = (
            net if plan["funding_status"] == "not_applicable" or not plan["entered"] else None)


def _leg(plan, event, stamp, weight, price, reason, *, exact_open=False, timeout=False):
    start = stamp + STEP if timeout else stamp
    end = stamp if exact_open else stamp + STEP
    gross = (price / plan["entry_price"] - 1) * 100
    weighted = weight * gross
    plan["legs"].append(dict(weight=weight, price=price,
        index=(stamp - event["anchor_ms"]) // STEP, reason=reason,
        exit_window_start_ms=start, exit_window_end_ms=end,
        exact_open=exact_open, timeout=timeout, gross_pct=gross,
        weighted_gross_pct=weighted, cost20_pct=.2 * weight, cost40_pct=.4 * weight,
        net_ex_funding20_pct=weighted - .2 * weight,
        net_ex_funding40_pct=weighted - .4 * weight))
    plan["remaining_fraction"] -= weight
    plan["closed_fraction"] += weight
    plan["realized_gross_pct"] += weighted
    plan["cost20_pct"] += .2 * weight
    plan["cost40_pct"] += .4 * weight
    if plan["remaining_fraction"] == 0:
        plan["exit_window_start_ms"], plan["exit_window_end_ms"] = start, end
        _settle(plan, reason)


def _advance_plan(plan, event, stamp, bar):
    o, high, low, close = bar
    if plan["status"] == "WAITING":
        if plan["entry_rule"] == "CONFIRM15" and stamp < event["anchor_ms"] + 3 * STEP:
            if len(event["_confirmation"]) == 3:
                a, b, c = event["_confirmation"]
                plan["decision_ms"] = stamp + STEP
                if not (c[3] > a[0] and c[3] > b[3] and c[2] >= b[2]):
                    _settle(plan, "NO_ENTRY")
            return
        plan.update(status="ACTIVE", entered=True, entry_ms=stamp, entry_price=o,
                    remaining_fraction=1., peak_high=o, stop_effective_ms=stamp,
                    target_price=o * (1 + plan["tp_pct"] / 100),
                    stop_price=o * (1 - plan["sl_pct"] / 100))
    if not plan["entered"]:
        return
    _excursion(plan, "full_window_", plan["entry_price"], high, low)
    if plan["status"] in _TERMINAL:
        return
    # Deliberate closed-bar bounds, NOT exact intrabar excursions before the fill.
    _excursion(plan, "until_exit_", plan["entry_price"], high, low)
    target, stop, mode = plan["target_price"], plan["stop_price"], plan["exit_rule"]
    # Preserve research.all_execution_engine.simulate's known-open exception.
    if mode == "FIXED" and o >= target:
        plan["target_activated"] = True
        _leg(plan, event, stamp, 1., target, "TP", exact_open=True)
        return
    if o <= stop or low <= stop:
        gap = o <= stop
        reason = ("TRAIL_STOP" if plan["trailing_active"] else "STOP") + ("_GAP" if gap else "")
        if not gap and not plan["trailing_active"] and high >= target:
            reason = "AMBIGUOUS_STOP"
            plan["same_bar_ambiguous"] = True
        _leg(plan, event, stamp, plan["remaining_fraction"], o if gap else stop,
             reason, exact_open=gap)
        return
    if not plan["trailing_active"] and high >= target:
        plan["target_activated"] = True
        if mode == "FIXED":
            _leg(plan, event, stamp, 1., target, "TP")
            return
        plan["trailing_active"] = True
        if mode == "PARTIAL":
            _leg(plan, event, stamp, .5, target, "PARTIAL_TP", exact_open=o >= target)
    plan["peak_high"] = max(plan["peak_high"], high)
    if plan["trailing_active"]:
        plan["stop_price"] = max(stop, plan["entry_price"],
                                  plan["peak_high"] * (1 - plan["sl_pct"] / 100))
        plan["stop_effective_ms"] = stamp + STEP
    if stamp + STEP == event["end_ms"]:
        _leg(plan, event, stamp, plan["remaining_fraction"], close, "TIMEOUT", timeout=True)


def _coverage(event, status, reason=None, blocked=None):
    event.update(data_status=status, data_reason=reason, blocked_ms=blocked)
    for plan in event["plans"].values():
        plan["full_window_data_status"] = status
        if plan["status"] not in _TERMINAL:
            plan["data_status"], plan["data_reason"] = status, reason


def advance(event, bars, as_of_ms) -> None:
    """Mutate a persisted event using only its contiguous closed-bar prefix.

    UNKNOWN never realizes zero/loss or advances past the problem. Previously
    finished arms retain outcomes/data_status; full_window_data_status follows
    coverage separately. Passing the same consumed bars again is idempotent.
    """
    if (type(event) is not dict or event.get("study_version") != VERSION
            or event.get("plan_hash") != PLAN_HASH or not _ms(as_of_ms)):
        raise ValueError("invalid_execution_shadow_state_or_time")
    if event["status"] == "complete":
        return
    start, end = event["next_start_ms"], event["end_ms"]
    if start + STEP > as_of_ms:
        return
    indexed, errors = _index_bars(bars, start, end, as_of_ms)
    while event["next_start_ms"] < end and event["next_start_ms"] + STEP <= as_of_ms:
        stamp = event["next_start_ms"]
        reason = errors.get(stamp)
        if reason or stamp not in indexed:
            _coverage(event, "UNKNOWN", reason or "missing_bar", stamp)
            return
        bar = indexed[stamp]
        if event["full_window_reference_price"] is None:
            event["full_window_reference_price"] = bar[0]
        _excursion(event, "full_window_", event["full_window_reference_price"], bar[1], bar[2])
        if len(event["_confirmation"]) < 3:
            event["_confirmation"].append(list(bar))
        _coverage(event, "OK")
        for plan in event["plans"].values():
            _advance_plan(plan, event, stamp, bar)
        event["processed_bars"] += 1
        event["next_start_ms"] = stamp + STEP
    if event["next_start_ms"] == end:
        event.update(status="complete", full_window_complete=True)
        for plan in event["plans"].values():
            plan["full_window_complete"] = True


def _enum(*values):
    allowed = frozenset(values)
    return lambda value: type(value) is str and value in allowed


def _nullable(check):
    return lambda value: value is None or check(value)


def _schema_fields(obj, schema):
    """No recursive arbitrary values, coercion, repr or caller-controlled keys."""
    if type(obj) is not dict:
        return {}
    return {key: obj[key] for key, check in schema.items() if key in obj and check(obj[key])}


_BOOL = lambda value: type(value) is bool
_N = _nullable(_number)
_T = _nullable(_ms)
_DATA = _enum("PENDING", "OK", "UNKNOWN")
_REASON = _nullable(_enum(*_REASONS))
_PLAN_SCHEMA = {
    "plan_id": _enum(*(arm[0] for spec in _SPECS for arm in spec[4])),
    "entry_rule": _enum("NOW", "CONFIRM15"), "exit_rule": _enum("FIXED", "TRAIL", "PARTIAL"),
    "tp_pct": _number, "sl_pct": _number, "end_ms": _ms,
    "status": _enum("WAITING", "ACTIVE", *_TERMINAL), "data_status": _DATA,
    "data_reason": _REASON, "funding_status": _enum("not_modeled", "not_applicable"),
    **{k: _BOOL for k in ("entered", "target_activated", "trailing_active",
                           "same_bar_ambiguous", "full_window_complete")},
    **{k: _T for k in ("entry_ms", "decision_ms", "stop_effective_ms",
                        "exit_window_start_ms", "exit_window_end_ms")},
    **{k: _N for k in ("entry_price", "target_price", "stop_price", "peak_high",
                        "remaining_fraction", "closed_fraction", "realized_gross_pct",
                        "cost20_pct", "cost40_pct", "gross_pct", "net_ex_funding20_pct",
                        "net_ex_funding40_pct", "net20_pct", "net40_pct", "until_exit_mae_pct",
                        "until_exit_mfe_pct", "full_window_mae_pct", "full_window_mfe_pct")},
    "full_window_data_status": _DATA,
}
_LEG_SCHEMA = {
    **{k: _number for k in ("weight", "price", "gross_pct", "weighted_gross_pct",
                             "cost20_pct", "cost40_pct", "net_ex_funding20_pct",
                             "net_ex_funding40_pct")},
    "index": _ms, "reason": _enum("PARTIAL_TP", *_TERMINAL),
    "exit_window_start_ms": _ms, "exit_window_end_ms": _ms,
    "exact_open": _BOOL, "timeout": _BOOL,
}
_EVENT_SCHEMA = {
    "event_id": lambda v: _matches(_ID, v), "study_version": _enum(VERSION),
    "plan_hash": _enum(PLAN_HASH), "research_only": lambda v: v is True,
    "strategy": _enum("S1", "S3", "G2"), "symbol": lambda v: _matches(_SYMBOL, v),
    "market": _enum("spot", "um_perp"), "universe": _enum(*(s[1] for s in _SPECS)),
    "direction": _enum("LONG"), "config_version": _label,
    "engine_version": _nullable(_label), "engine_config_hash": _nullable(lambda v: _matches(_HASH, v)),
    "regime": _enum(*_REGIMES), "status": _enum("active", "complete"),
    "data_status": _DATA, "data_reason": _REASON, "blocked_ms": _T,
    "horizon_hours": lambda v: type(v) is int and v in (4, 24),
    "processed_bars": _ms, "full_window_complete": _BOOL,
    **{k: _ms for k in ("created_at_ms", "activated_ms", "delivered_ms", "anchor_ms",
                         "end_ms", "next_start_ms")},
    **{k: _N for k in ("full_window_reference_price", "full_window_mae_pct", "full_window_mfe_pct")},
}


def public_event(event) -> dict:
    """Return an independent JSON-safe schema projection, never raw input/state.

    Invalid values and unknown keys at every nesting level are omitted. Only
    expected arm IDs and up to two schema-validated legs per arm can be exposed.
    Internal confirmation, raw bars, exceptions, recipients and secrets cannot
    pass through an arbitrary nested dict/list hidden under a recognized key.
    """
    result = _schema_fields(event, _EVENT_SCHEMA)
    spec = _spec(result.get("strategy"))
    if not spec or type(event.get("plans")) is not dict:
        return result
    result["plans"] = {}
    for arm in spec[4]:
        name = arm[0]
        raw = event["plans"].get(name)
        if type(raw) is not dict:
            continue
        plan = _schema_fields(raw, _PLAN_SCHEMA)
        plan["legs"] = []
        if type(raw.get("legs")) is list:
            plan["legs"] = [_schema_fields(leg, _LEG_SCHEMA) for leg in raw["legs"][:2]
                            if type(leg) is dict]
        result["plans"][name] = plan
    return result


def validate_persisted(event, key, activated_ms):
    """Reject incompatible/corrupt checkpoints without rebuilding old outcomes."""
    if (type(event) is not dict or event.get("event_id") != key
            or event.get("activated_ms") != activated_ms
            or any(k not in event or not check(event[k]) for k, check in _EVENT_SCHEMA.items())):
        raise ValueError("invalid_execution_shadow_checkpoint")
    spec = _spec(event["strategy"])
    if (event["universe"] != spec[1] or event["market"] != spec[2]
            or event["horizon_hours"] != spec[3] or event["anchor_ms"] % STEP
            or event["end_ms"] != event["anchor_ms"]+spec[3]*_HOUR
            or not event["anchor_ms"] <= event["next_start_ms"] <= event["end_ms"]
            or event["next_start_ms"] != event["anchor_ms"]+STEP*event["processed_bars"]
            or set(event.get("plans", {})) != {a[0] for a in spec[4]}
            or len(event.get("_confirmation", [])) != min(3, event["processed_bars"])):
        raise ValueError("invalid_execution_shadow_cursor")
    for row in event["_confirmation"]:
        if (not isinstance(row, list) or len(row) != 4 or not all(_number(v) and v > 0 for v in row)
                or not row[2] <= min(row[0], row[3]) <= max(row[0], row[3]) <= row[1]):
            raise ValueError("invalid_execution_shadow_confirmation")
    for name, entry, mode, tp, sl in spec[4]:
        plan = event["plans"][name]
        if (any(k not in plan or not check(plan[k]) for k, check in _PLAN_SCHEMA.items())
                or (plan["entry_rule"], plan["exit_rule"], plan["tp_pct"], plan["sl_pct"]) != (entry, mode, tp, sl)
                or plan["end_ms"] != event["end_ms"] or not isinstance(plan.get("legs"), list)
                or len(plan["legs"]) > 2):
            raise ValueError("invalid_execution_shadow_plan")
        for leg in plan["legs"]:
            if type(leg) is not dict or any(k not in leg or not check(leg[k]) for k, check in _LEG_SCHEMA.items()):
                raise ValueError("invalid_execution_shadow_leg")
