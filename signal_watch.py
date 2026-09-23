"""Independent, durable context warnings for delivered signals within their horizon.

Warnings are observations, not revised strategy outcomes or execution instructions.
The signal outbox and scorecards are read-only inputs. This module owns its own
state/outbox, and never imports the bot. Call tick from one background worker.
"""
from datetime import datetime, timezone
import hashlib
import html
import json
import math
from pathlib import Path

import intraday_regime as regime
from notification_delivery import DeliveryOutbox

SUPPORTED = {"S1", "S1+S4", "S2", "S3", "S5", "S6", "G1", "G2"}
BAR = 15 * regime.MINUTE


def millis(value):
    dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("missing_watch_timezone")
    return int(dt.timestamp()*1000)


def tr(value):
    from datetime import timedelta
    return datetime.fromisoformat(value).astimezone(timezone(timedelta(hours=3))).strftime("%d.%m %H:%M TRT")


def changed_against(old, current, direction):
    if old not in {"BULL", "TRANSITION", "BEAR"} or current not in {"BULL", "TRANSITION", "BEAR"}:
        return False
    rank = {"BEAR": -1, "TRANSITION": 0, "BULL": 1}
    return rank[current] < rank[old] if direction == "LONG" else rank[current] > rank[old]


def register(record, now_ms, fast, daily):
    """Keep the existing notified-at horizon; G2 retains its planned-entry clock."""
    if (record.get("strategy") not in SUPPORTED or not record.get("delivery_confirmed")
            or record.get("direction") not in {"LONG", "SHORT"}):
        return None
    try:
        delivered = millis(record["delivered_at"])
        start = millis(record.get("planned_entry_at") if record["strategy"] == "G2"
                       else record["notified_at"])
        horizon = float(record["horizon_hours"])
        if not math.isfinite(horizon) or horizon <= 0:
            return None
        end = start + int(horizon * regime.HOUR)
        if delivered > now_ms or now_ms >= end:
            return None
        # S2's bar timestamp is a funding event, not a candle open.
        reference = (millis(record.get("signal_reference_at") or record["bar_time"])
                     // regime.HOUR * regime.HOUR - regime.HOUR
                     if record["strategy"] == "S2" else millis(record["bar_time"]))
        if reference % regime.HOUR or reference + regime.HOUR > delivered:
            return None
        market = record.get("performance_market") or ("um_perp" if record["strategy"] == "S2" else "spot")
        if market not in {"spot", "um_perp"}:
            return None
        return {"event_id": record["event_id"], "strategy": record["strategy"],
                "symbol": record["symbol"], "direction": record["direction"],
                "market": market, "performance_symbol": record.get("performance_symbol") or record["symbol"],
                "delivered_ms": delivered, "end_ms": end, "reference_ms": reference,
                "baseline": {"daily": record.get("market_regime") or daily.get("label", "UNKNOWN"),
                             "hourly": record.get("intraday_regime", {}).get("hourly", fast.get("hourly", "UNKNOWN")),
                             "early": record.get("intraday_regime", {}).get("early", fast.get("early", "UNKNOWN"))},
                "warned": [], "last_checked_ms": 0, "last_error": None}
    except (KeyError, ValueError, TypeError, OverflowError, AttributeError):
        return None


def structure_reason(event, reference_raw, recent_raw, now_ms):
    ref = regime.closed_bars(reference_raw, regime.HOUR,
                             event["reference_ms"] + regime.HOUR, minimum=1)[-1]
    bars = regime.closed_bars(recent_raw, BAR, now_ms)
    pair = bars[-2:]
    if pair[0]["time"] < event["delivered_ms"]:
        return None  # No pre-notification/partially pre-notification bars.
    level = ref["low"] if event["direction"] == "LONG" else ref["high"]
    broken = (all(b["close"] < level for b in pair) if event["direction"] == "LONG"
              else all(b["close"] > level for b in pair))
    if not broken:
        return None
    side = "altında" if event["direction"] == "LONG" else "üstünde"
    return f"İki kapanmış 15dk mum, referans saatlik mumun {level:.8g} seviyesinin {side}."


class SignalWatch:
    def __init__(self, path, *, fetch, records, recipients, subscribers, sender, max_symbols=20):
        self.path = Path(path)
        self.outbox = DeliveryOutbox(self.path.with_name(".signal_watch_outbox.json"))
        self.fetch, self.records, self.recipients = fetch, records, recipients
        self.subscribers, self.sender = subscribers, sender
        self.max_symbols = max_symbols
        self.state = None
        self.fast = {"hourly": "UNKNOWN", "early": "UNKNOWN", "fresh": False}
        self.status = {"enabled": True, "active_signals": 0, "last_error": None}
        self.next_check_ms = 0
        self.last_fast_slot = None

    def load(self):
        if self.state is None:
            if self.path.exists():
                data = json.loads(self.path.read_text(encoding="utf-8"))
                if (data.get("version") != 1 or not isinstance(data.get("events"), dict)
                        or not isinstance(data.get("regimes"), dict)):
                    raise ValueError("invalid_signal_watch_state")
                for key, event in data["events"].items():
                    if (event.get("event_id") != key or not isinstance(event.get("warned"), list)
                            or not isinstance(event.get("baseline"), dict)
                            or not isinstance(event.get("end_ms"), int)):
                        raise ValueError("invalid_signal_watch_event")
                self.state = data
            else:
                self.state = {"version": 1, "events": {}, "regimes": {}}

    def save(self):
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.state, ensure_ascii=False, allow_nan=False), encoding="utf-8")
        tmp.replace(self.path)

    def enqueue(self, key, text, recipients, now_ms, expires_ms, *, signal_id=None, reasons=None):
        eid = "watch-" + hashlib.sha256(key.encode()).hexdigest()[:32]
        self.outbox.enqueue({"event_id": eid, "text": text, "expires_ms": expires_ms,
                             "signal_id": signal_id, "reasons": reasons or []},
                            recipients, now=datetime.fromtimestamp(now_ms/1000, timezone.utc))

    def flush(self, now_ms, stop_event=None):
        for eid in self.outbox.pending_ids(due_only=True):
            if stop_event is not None and stop_event.is_set():
                break
            def send(cid, record):
                if int(record["expires_ms"]) <= now_ms or cid not in self.subscribers():
                    return False
                return self.sender(record["text"], cid)
            self.outbox.deliver(eid, send, stop_event=stop_event)
        records = self.outbox.all_records()
        self.status["pending_alerts"] = sum(r.get("delivery_pending_count", 0) for r in records)
        self.status["failed_alert_deliveries"] = sum(r.get("delivery_failed_count", 0) for r in records)

    def tick(self, daily, *, now_ms=None, stop_event=None):
        now_ms = int(datetime.now(timezone.utc).timestamp()*1000) if now_ms is None else now_ms
        try:
            self.load()
            # Keep the first 30 seconds of every scan boundary for signal delivery.
            if now_ms % (5*regime.MINUTE) < 30_000:
                return
            if now_ms < self.next_check_ms:
                self.flush(now_ms, stop_event)
                return
            self.next_check_ms = now_ms + regime.MINUTE
            self._check(daily, now_ms, stop_event)
            self.save()
            self.status["last_error"] = None
            self.status["last_check_at"] = regime.iso(now_ms)
            self.next_check_ms = (now_ms//(5*regime.MINUTE)+1)*(5*regime.MINUTE)+30_000
            self.flush(now_ms, stop_event)
        except Exception as exc:
            # Preserve corrupt files; no silent reset/replay. Do not expose payloads.
            self.status["last_error"] = type(exc).__name__

    def _check(self, daily, now_ms, stop_event):
        slot = now_ms // BAR
        if slot != self.last_fast_slot:
            try:
                raw = {}
                for symbol in ("BTCUSDT", "ETHUSDT"):
                    for interval in ("1h", "15m"):
                        if stop_event is not None and stop_event.is_set():
                            return
                        raw[symbol, interval] = self.fetch("spot", symbol, interval, {"limit": 241})
                self.fast = regime.snapshot(raw, now_ms)
                self.last_fast_slot = slot
            except Exception as exc:
                self.fast = {**self.fast, "fresh": False, "last_error": type(exc).__name__}
        daily_label = daily.get("label", "UNKNOWN") if daily.get("fresh") else "UNKNOWN"
        fast_fresh = self.fast.get("fresh") and self.last_fast_slot == slot
        labels = {"daily": daily_label,
                  "hourly": self.fast.get("hourly", "UNKNOWN") if fast_fresh else "UNKNOWN",
                  "early": self.fast.get("early", "UNKNOWN") if fast_fresh else "UNKNOWN"}
        titles = {"daily": "Günlük ana rejim", "hourly": "Saatlik yön", "early": "15dk erken yön"}
        changes = []
        for key, label in labels.items():
            if label == "UNKNOWN":
                continue
            previous = self.state["regimes"].get(key)
            if previous and previous != label:
                changes.append(f"• {titles[key]}: {regime.NAMES[previous]} → {regime.NAMES[label]}")
        if changes:
            text = ("🌐 <b>Piyasa yönü değişti</b>\n" + "\n".join(changes)
                    + f"\n🕒 {tr(regime.iso(now_ms))}\n<i>Gün içi ölçüm BTC ve ETH teyitlidir; günlük rejim ayrı izlenir.</i>")
            self.enqueue("regime|"+str(slot)+"|"+json.dumps(labels, sort_keys=True), text,
                         list(self.subscribers()), now_ms, now_ms+BAR)
        self.state["regimes"].update({k:v for k,v in labels.items() if v != "UNKNOWN"})
        events = self.state["events"]
        for eid in list(events):
            if now_ms >= events[eid]["end_ms"]:
                del events[eid]
        for record in self.records():
            if record.get("event_id") not in events:
                event = register(record, now_ms, self.fast if fast_fresh else {}, daily)
                if event:
                    events[event["event_id"]] = event
        # Recover an enqueue-before-state-save crash without re-warning a reason.
        for alert in self.outbox.all_records():
            event = events.get(alert.get("signal_id"))
            if event:
                event["warned"] = sorted(set(event["warned"]) | set(alert.get("reasons", [])))
        cache = {}
        symbols = set()
        price_errors = 0
        market_blocked = self.fast.get("last_error") in {"MarketRateLimitError", "MarketTransientError"}
        for event in sorted(events.values(), key=lambda e:e["last_checked_ms"]):
            if stop_event is not None and stop_event.is_set():
                break
            reasons = {}
            for key, label in labels.items():
                initial = event["baseline"].get(key, "UNKNOWN")
                if label != "UNKNOWN" and initial == "UNKNOWN":
                    event["baseline"][key] = label
                elif changed_against(initial, label, event["direction"]) and key not in event["warned"]:
                    reasons[key] = f"{titles[key]}: {regime.NAMES[initial]} → {regime.NAMES[label]}."
            symbol_key = event["market"], event["performance_symbol"]
            if (not market_blocked and "structure" not in event["warned"]
                    and (symbol_key in symbols or len(symbols) < self.max_symbols)):
                symbols.add(symbol_key)
                try:
                    if symbol_key not in cache:
                        cache[symbol_key] = self.fetch(*symbol_key, "15m", {"limit": 4})
                    reference = event.get("reference_raw")
                    if not reference:
                        reference = self.fetch(*symbol_key, "1h", {
                            "startTime": event["reference_ms"],
                            "endTime": event["reference_ms"]+regime.HOUR-1, "limit": 1})
                    reason = structure_reason(event, reference, cache[symbol_key], now_ms)
                    event["reference_raw"] = reference
                    if reason:
                        reasons["structure"] = reason
                    event["last_error"] = None
                except Exception as exc:
                    event["last_error"] = type(exc).__name__
                    price_errors += 1
                    market_blocked = type(exc).__name__ in {"MarketRateLimitError", "MarketTransientError"}
                event["last_checked_ms"] = now_ms
            if reasons:
                description = html.escape(f"{event['strategy']} — {event['symbol']} {event['direction']}")
                text = (f"⚠️ <b>Sinyal koşulu zayıfladı</b>\n<b>{description}</b>\n"
                        + "\n".join("• "+html.escape(s) for s in reasons.values())
                        + f"\n🔔 İlk bildirim: {tr(regime.iso(event['delivered_ms']))}"
                        + f"\n🕒 Kontrol: {tr(regime.iso(now_ms))}"
                        + f"\n⏳ Takip sonu: {tr(regime.iso(event['end_ms']))}"
                        + "\n<i>Risk uyarısıdır; kesin başarısızlık veya işlem kapatma emri değildir.</i>")
                self.enqueue(event["event_id"]+"|"+"|".join(sorted(reasons)), text,
                             [cid for cid in self.recipients(event["event_id"]) if cid in self.subscribers()],
                             now_ms, event["end_ms"], signal_id=event["event_id"], reasons=list(reasons))
                event["warned"].extend(reasons)
        self.status.update(active_signals=len(events), price_errors=price_errors,
                           price_backlog=sum(e["last_checked_ms"] != now_ms and "structure" not in e["warned"]
                                             for e in events.values()),
                           fast_error=self.fast.get("last_error"))
