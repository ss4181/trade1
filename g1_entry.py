"""G1 quote and research-only entry alternatives. Never places an order."""
from __future__ import annotations

import math

MEASUREMENT = "signal-reference-touch-1m-v2"
CONFIG_VERSION = "G1-prereg-2026-10-03-v3-fresh-ask"
PATH_VERSION = "g1-entry-path-v1"
MINUTE = 60_000


def book_reference(payload, symbol, received_ms, max_age_ms=30_000):
    """Fresh best ask for a LONG reference, not a guaranteed executable fill."""
    if not isinstance(payload, dict) or payload.get("symbol") != symbol:
        raise ValueError("quote_symbol_mismatch")
    bid, ask = float(payload["bidPrice"]), float(payload["askPrice"])
    timestamp = int(payload["time"])
    if not all(math.isfinite(x) for x in (bid, ask)) or not 0 < bid <= ask:
        raise ValueError("invalid_book")
    if not math.isfinite(ask / bid):
        raise ValueError("invalid_spread")
    age = received_ms - timestamp
    if age < -5_000 or age > max_age_ms:
        raise ValueError("stale_or_future_book")
    return {"price": ask, "bid": bid, "ask": ask, "exchange_time_ms": timestamp,
            "received_ms": received_ms, "age_seconds": max(0, age) / 1000,
            "spread_bps": (ask / bid - 1) * 10_000,
            "source": "usdm_book_best_ask_after_validation"}


def tracking_step(event):
    return MINUTE if event.get("measurement_version") == MEASUREMENT else 300_000


def ceil_bar(timestamp, step):
    return ((timestamp + step - 1) // step) * step


def _observe_plan_path(plan, bar):
    """Add diagnostics only; never feed extremes back into the entry decision.

    Includes the full exit candle: intrabar order of its extremes is unknown.
    A plan upgraded mid-path cannot claim complete MAE/MFE coverage.
    """
    t, price = int(bar["open_time"]), plan["entry_price"]
    path = plan.setdefault("path", {
        "version": PATH_VERSION, "complete_from_entry": t == plan["entry_time_ms"],
        "last_open_ms": t-MINUTE, "n_bars": 0, "mae_full_bar_pct": 0.,
        "mfe_full_bar_pct": 0.,
    })
    if t <= path["last_open_ms"]:
        return
    if t != path["last_open_ms"]+MINUTE:
        path["complete_from_entry"] = False
    path["last_open_ms"] = t
    path["n_bars"] += 1
    path["mae_full_bar_pct"] = min(path["mae_full_bar_pct"], (float(bar["low"])/price-1)*100)
    path["mfe_full_bar_pct"] = max(path["mfe_full_bar_pct"], (float(bar["high"])/price-1)*100)


def advance_entry_shadow(event, bars):
    """Fixed 5/15m alternatives; no signal filtering, alerts, or parameter fitting.

    Starts at the first *full* minute after delivery. Confirmation only reads
    those already-closed minutes; the entry is the following minute open.
    Missing bars never imply a failed confirmation or a negative outcome.
    """
    if event.get("measurement_version") != MEASUREMENT:
        return
    shadow = event.setdefault("entry_shadow", {
        "version": "g1-entry-shadow-v1", "research_only": True,
        "minutes": [], "plans": {},
    })
    start = event["tracking_start_ms"]
    plans = shadow["plans"]
    for bar in bars:
        t = int(bar["open_time"])
        if t < start:
            continue
        history = shadow["minutes"]
        expected = start + len(history) * MINUTE
        if len(history) < 16 and t == expected:
            history.append({k: bar[k] for k in ("open_time", "open", "high", "low", "close")})
        # Eligible confirmations are locked at their decision close, not
        # retroactively selected based on the remainder of the price path.
        for wait in (0, 5, 15):
            for kind in (("immediate",) if wait == 0 else ("wait", "confirm")):
                key = "immediate" if wait == 0 else f"{kind}_{wait}m"
                if key not in plans:
                    if t != start + wait * MINUTE or len(history) < wait + 1:
                        continue
                    eligible = (kind != "confirm" or
                                history[wait-1]["close"] > history[0]["open"])
                    plans[key] = {"status": "active" if eligible else "no_entry",
                                  "entry_time_ms": t if eligible else None,
                                  "entry_price": float(bar["open"]) if eligible else None,
                                  "tp_pct": 3., "sl_pct": 2., "net_cost_bps": [20, 40],
                                  "funding": "not_modeled", "same_bar": "stop_first"}
                plan = plans[key]
                if plan["status"] != "active" or t < plan["entry_time_ms"]:
                    continue
                _observe_plan_path(plan, bar)
                price = plan["entry_price"]
                stop, target = price * .98, price * 1.03
                o, h, l = (float(bar[k]) for k in ("open", "high", "low"))
                if o <= stop:
                    status, fill = "SL_GAP", o
                elif o >= target:
                    status, fill = "TP", target
                elif l <= stop:
                    status, fill = ("AMBIGUOUS_SL" if h >= target else "SL"), stop
                elif h >= target:
                    status, fill = "TP", target
                else:
                    plan["last_close"] = float(bar["close"])
                    plan["last_close_time_ms"] = t+MINUTE
                    continue
                plan.update(status=status, exit_time_upper_ms=t+MINUTE,
                            gross_pct=(fill/price-1)*100)


def finish_entry_shadow(event):
    """Use the same signal deadline for every alternative, including no-entry."""
    for plan in event.get("entry_shadow", {}).get("plans", {}).values():
        if plan["status"] == "active" and "last_close" in plan:
            plan.update(status="TIMEOUT", gross_pct=(plan["last_close"]/plan["entry_price"]-1)*100)
            if "last_close_time_ms" in plan:
                plan["exit_time_upper_ms"] = plan["last_close_time_ms"]


def public_shadow(event):
    shadow = event.get("entry_shadow")
    if not isinstance(shadow, dict):
        return None
    fields = ("status", "entry_time_ms", "entry_price", "tp_pct", "sl_pct",
              "exit_time_upper_ms", "gross_pct", "funding", "same_bar")
    return {"version": "g1-entry-shadow-v1", "research_only": True,
            "plans": {k: {f: v[f] for f in fields if f in v}
                      for k,v in shadow.get("plans", {}).items()
                      if isinstance(v,dict) and k in ("immediate","wait_5m","wait_15m","confirm_5m","confirm_15m")}}
