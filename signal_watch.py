"""Independent, durable context warnings for delivered signals within their horizon.

Warnings are observations, not revised strategy outcomes or execution instructions.
The signal outbox and scorecards are read-only inputs. This module owns its own
state/outbox, and never imports the bot. Call tick from one background worker.
"""
from datetime import datetime, timezone
import copy
import hashlib
import html
import json
import math
from pathlib import Path
import re
from atomic_state import replace_state

import intraday_regime as regime
from notification_delivery import DeliveryOutbox

SUPPORTED = {"S1", "S1+S4", "S2", "S3", "S5", "S6", "G1", "G2"}
BAR = 15 * regime.MINUTE
MESSAGE_LIMIT = 3900  # Conservative HTML/UTF-16 budget below Telegram's limit.
CRITICAL_POLICY = "critical-reversal-v1"
CRITICAL_REASON = "critical_reversal"


def warning_links(record):
    """Both pre-upgrade individual alerts and new digests recover per-event dedup."""
    if record.get("signal_id"):
        yield record["signal_id"], record.get("reasons", [])
    for item in record.get("watch_items", []):
        if item.get("signal_id"):
            yield item["signal_id"], list(item.get("details", {}))
        elif item.get("legacy_signal_id"):
            yield item["legacy_signal_id"], item.get("legacy_reasons", [])


def digest_messages(items, now_ms):
    """Group identical causes; split only when the transport limit requires it."""
    critical = bool(items) and all(is_critical_item(item) for item in items)
    header = ("🚨 <b>Kritik risk — toplu uyarı</b>" if critical else
              "⚠️ <b>Sinyal koşulları — toplu güncelleme</b>")
    footer = ("\n\n🧭 <i>Kurulum/risk gözlemidir; doğrulanmış çıkış modeli değil. "
              "Gerçek pozisyonu/emirleri izlemez; borsadaki stop-loss yerine geçmez.</i>")
    if critical:
        footer = ("\n\n🛡️ <b>Aynı yönde açık pozisyonun varsa önceden belirlediğin stop/çıkış planını kontrol et.</b>"
                  "\n<i>Bu, kesin kapat emri veya toparlanma tahmini değildir. Gerçek girişini, "
                  "pozisyonunu, kaldıraç ve teminatını bilmez; emir açmaz/kapatmaz. "
                  "Teyit gecikebilir; borsadaki stop-loss yerine geçmez.</i>")
    def size(text):
        return len(text.encode("utf-16-le"))//2
    groups = {}
    for item in items:
        if item["expires_ms"] <= now_ms:
            continue
        if item["kind"] == "signal":
            for key, detail in sorted(item["details"].items()):
                label = ("G1 kurulum koşulları artık sağlanmıyor" if key == "conditions_lost" else
                         "Referans mum yapısı ihlal edildi" if key == "structure" else
                         "Ters yön ve belirgin fiyat kırılması birlikte teyit edildi" if key == CRITICAL_REASON else
                         "Piyasa riski arttı")
                # One shared cause even when each signal has other distinct
                # causes too. Metadata covers exactly the reasons on this page.
                member = {**item, "details": {key: detail}}
                groups.setdefault((label, detail), []).append(member)
            continue
        if item["kind"] == "regime":
            label = "🌐 Piyasa yönü değişti"
            detail = "\n".join(item["details"].values())
        elif item["kind"] == "horizon":
            label = "⏳ Sinyal takip süresi bitti"
            detail = "Pozisyonun kapandığı anlamına gelmez; bu sinyalin bağlam takibi sona erdi."
        elif item["kind"] == "legacy":
            label, detail = "Önceki kontrolden bekleyen uyarı", item["text"]
        else:
            raise ValueError("invalid_watch_item_kind")
        groups.setdefault((label, detail), []).append(item)
    # Each block retains its event metadata even if the same reason spans pages.
    blocks = []
    for (label, detail), members in groups.items():
        base = f"\n\n<b>{html.escape(label)}</b>\n{html.escape(detail)}"
        current, linked = base, []
        for item in members:
            line = ""
            if item.get("signal_id"):
                line = ("\n• <b>"+html.escape(f"{item['strategy']} — {item['symbol']} {item['direction']}")+"</b>"
                        + f" · İlk: {tr(regime.iso(item['delivered_ms']))}"
                        + f" · Takip sonu: {tr(regime.iso(item['end_ms']))}")
            if size(header+current+line+footer)+100 > MESSAGE_LIMIT:
                if not linked:
                    raise ValueError("watch_item_exceeds_message_limit")
                blocks.append((current, linked))
                current, linked = base, []
            current += line
            linked.append(item)
        blocks.append((current, linked))
    pages, body, linked = [], "", []
    for block, members in blocks:
        if size(header+body+block+footer)+100 > MESSAGE_LIMIT and linked:
            pages.append((body, linked))
            body, linked = "", []
        body += block
        linked += members
    if linked:
        pages.append((body, linked))
    messages = []
    for i, (body, members) in enumerate(pages, 1):
        suffix = f" ({i}/{len(pages)})" if len(pages)>1 else ""
        times = sorted({m["observed_ms"] for m in members})
        stamp = tr(regime.iso(times[0]))
        if times[-1] != times[0]:
            stamp += " — "+tr(regime.iso(times[-1]))
        text = header+suffix+"\n🕒 Kontrol: "+stamp+body+footer
        if size(text) > MESSAGE_LIMIT:
            raise ValueError("watch_message_exceeds_limit")
        messages.append((text, members))
    return messages


def is_critical_item(item):
    """An old context warning must never become critical merely by reformatting."""
    return (item.get("kind") == "signal" and item.get("alert_policy") == CRITICAL_POLICY
            and isinstance(item.get("details"), dict)
            and set(item["details"]) == {CRITICAL_REASON})


class WatchOutbox(DeliveryOutbox):
    """Atomic per-recipient digests, retaining each source event's dedup evidence."""
    def enqueue_groups(self, groups, now_ms):
        now = datetime.fromtimestamp(now_ms/1000, timezone.utc)
        with self.lock:
            items = self._load()
            previous = copy.deepcopy(items)
            try:
                self._add_groups(items, groups, now)
                self._save()
            except Exception:
                self.items = previous
                raise

    def _add_groups(self, queue, groups, now, *, created_at=None, attempts=0):
        ids = set()
        for cid, members in groups.items():
            for text, page in digest_messages(members, int(now.timestamp()*1000)):
                identity = json.dumps([cid, page], sort_keys=True, ensure_ascii=False)
                eid = "watch-digest-"+hashlib.sha256(identity.encode()).hexdigest()[:32]
                ids.add(eid)
                if eid not in queue:
                    queue[eid] = {"created_at": created_at or now.isoformat(),
                        "record": {"event_id": eid, "text": text, "watch_items": page,
                                   "watch_format": "digest-v1", "expires_ms": max(m["expires_ms"] for m in page)},
                        "recipients": {cid: {"status": "pending", "attempts": attempts}}}
        return ids

    def coalesce_due(self, now_ms, subscribers):
        """Old unsent individual alerts/retries must not burst after an upgrade.

        One atomic save replaces due unsent recipients with digest recipients.
        Successful deliveries are never replayed; backoff/TTL are not reset.
        """
        now = datetime.fromtimestamp(now_ms/1000, timezone.utc)
        with self.lock:
            queue = self._load()
            if not any(r["status"] in {"pending", "sending"}
                       for item in queue.values() for r in item["recipients"].values()):
                return
            previous = copy.deepcopy(queue)
            groups = {}
            try:
                for eid, item in list(queue.items()):
                    for cid, recipient in item["recipients"].items():
                        if (recipient["status"] not in {"pending", "sending"}
                                or (eid, cid) in self._inflight):
                            continue
                        expired = (now_ms >= item["record"]["expires_ms"] or
                            (now-datetime.fromisoformat(item["created_at"])).total_seconds() > self.ttl_minutes*60)
                        if expired or cid not in subscribers or recipient["attempts"] >= self.max_attempts:
                            recipient["status"] = "failed"
                            continue
                        if recipient.get("next_attempt_at") and now < datetime.fromisoformat(recipient["next_attempt_at"]):
                            continue
                        record = item["record"]
                        members = record.get("watch_items")
                        if members is None:
                            plain = html.unescape(re.sub(r"<[^>]+>", "", record["text"]))
                            members = [dict(kind="legacy", text=plain, observed_ms=millis(item["created_at"]),
                                expires_ms=record["expires_ms"], legacy_signal_id=record.get("signal_id"),
                                legacy_reasons=record.get("reasons", []))]
                        deadline = millis(item["created_at"])+self.ttl_minutes*60_000
                        live = [{**m, "expires_ms": min(m["expires_ms"], deadline)} for m in members
                                if min(m["expires_ms"], deadline) > now_ms]
                        if not live:
                            recipient["status"] = "failed"
                            continue
                        groups.setdefault(cid, []).append((eid, item, recipient, live))
                for cid, sources in groups.items():
                    if (len(sources) == 1 and sources[0][1]["record"].get("watch_format") == "digest-v1"
                            and len(sources[0][3]) == len(sources[0][1]["record"]["watch_items"])):
                        continue
                    members = [m for _, _, _, page in sources for m in page]
                    newest = max(item["created_at"] for _, item, _, _ in sources)
                    attempts = max(r["attempts"] for _, _, r, _ in sources)
                    # Each member keeps its original TTL. An older retry must
                    # neither prolong itself nor prematurely expire new alerts.
                    replacements = self._add_groups(queue, {cid: members}, now, created_at=newest, attempts=attempts)
                    for eid, _, r, _ in sources:
                        # Reformatting already split pages can yield the exact
                        # same IDs. Never supersede a pending page with itself.
                        if eid not in replacements:
                            r.update(status="failed", superseded_by_digest=True)
                if queue != previous:
                    self._save()
            except Exception:
                self.items = previous
                raise

    def suppress_context(self):
        """Cancel unsent pre-upgrade context pages without deleting ACK evidence.

        New critical-only pages have their own IDs and remain retryable. Mixed
        or unversioned pages fail closed rather than replaying routine updates.
        """
        with self.lock:
            queue = self._load()
            previous = copy.deepcopy(queue)
            try:
                for eid, item in queue.items():
                    members = item["record"].get("watch_items")
                    if isinstance(members, list) and members and all(is_critical_item(m) for m in members):
                        continue
                    for cid, recipient in item["recipients"].items():
                        if (recipient["status"] in {"pending", "sending"}
                                and (eid, cid) not in self._inflight):
                            recipient.update(status="failed", suppressed_by_policy=CRITICAL_POLICY)
                if queue != previous:
                    self._save()
            except Exception:
                self.items = previous
                raise


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
                "monitor_from_ms": max(delivered, start),
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


def critical_reversal_reason(event, reference_raw, recent_raw, now_ms, fast):
    """Conservative notification policy, NOT an optimized/validated exit rule.

    Require closed BTC+ETH hourly AND 15m consensus against this event, plus
    two post-delivery/post-planned-entry closes beyond its reference extreme.
    A fixed 0.5 pre-confirmation ATR14 / 0.2% floor rejects marginal crossings.
    No live bars, future or stale context, fabricated positions, or PnL.
    """
    if event.get("direction") not in {"LONG", "SHORT"} or now_ms >= event["end_ms"]:
        return None
    refs = regime.closed_bars(reference_raw, regime.HOUR,
                             event["reference_ms"] + regime.HOUR, minimum=1)
    if len(refs) != 1 or refs[0]["time"] != event["reference_ms"]:
        raise ValueError("wrong_critical_reference_candle")
    bars = regime.closed_bars(recent_raw, BAR, now_ms, minimum=17)
    if not fast.get("fresh"):
        return None
    opposite = "BEAR" if event["direction"] == "LONG" else "BULL"
    try:
        if millis(fast.get("reference_at")) != now_ms // BAR * BAR:
            return None
        if millis(fast.get("hourly_reference_at")) != now_ms // regime.HOUR * regime.HOUR:
            return None
    except (ValueError, TypeError, OverflowError):
        return None
    if fast.get("hourly") != opposite or fast.get("early") != opposite:
        return None
    monitor_from = event.get("monitor_from_ms")
    if monitor_from is None:
        # Old G2 state cannot invent the planned entry; refresh from the
        # original delivered record before allowing a critical notification.
        if event["strategy"] == "G2":
            return None
        monitor_from = event["delivered_ms"]
    pair, prior = bars[-2:], bars[:-2]
    if pair[0]["time"] < monitor_from:
        return None
    ranges = [max(b["high"] - b["low"], abs(b["high"] - a["close"]),
                  abs(b["low"] - a["close"])) for a, b in zip(prior, prior[1:])][-14:]
    atr = sum(ranges) / 14
    level = refs[0]["low"] if event["direction"] == "LONG" else refs[0]["high"]
    buffer = max(.5 * atr, level * .002)
    threshold = level - buffer if event["direction"] == "LONG" else level + buffer
    broken = (all(b["close"] < threshold for b in pair) if event["direction"] == "LONG"
              else all(b["close"] > threshold for b in pair))
    if not broken:
        return None
    side = "altında" if event["direction"] == "LONG" else "üstünde"
    return (f"Saatlik yön + 15dk yön: BTC ve ETH birlikte {regime.NAMES[opposite]}. "
            f"İki kapanmış 15dk mum, referans {level:.8g} seviyesinin {side}; "
            f"{buffer:.8g} tamponu da aştı (0.5 ATR14, en az %0.2). "
            f"Teyit sınırı {threshold:.8g}; son kapanış {pair[-1]['close']:.8g}. "
            "Sinyalin yön varsayımıyla belirgin çelişki; gerçek işlem K/Z hesabı değildir.")


class SignalWatch:
    def __init__(self, path, *, fetch, records, recipients, subscribers, sender, max_symbols=20,
                 condition_check=None, critical_only=True):
        self.path = Path(path)
        self.outbox = WatchOutbox(self.path.with_name(".signal_watch_outbox.json"))
        self.fetch, self.records, self.recipients = fetch, records, recipients
        self.subscribers, self.sender = subscribers, sender
        self.max_symbols = max_symbols
        self.condition_check = condition_check
        # Legacy context mode is retained only for explicit offline replay.
        # Production wiring always selects critical_only=True.
        self.critical_only = critical_only
        self.state = None
        self.fast = {"hourly": "UNKNOWN", "early": "UNKNOWN", "fresh": False}
        self.status = {"enabled": True, "active_signals": 0, "last_error": None,
                       "alert_policy": CRITICAL_POLICY if critical_only else "all-context-legacy"}
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
        replace_state(tmp, self.path)

    def enqueue(self, key, text, recipients, now_ms, expires_ms, *, signal_id=None, reasons=None):
        eid = "watch-" + hashlib.sha256(key.encode()).hexdigest()[:32]
        self.outbox.enqueue({"event_id": eid, "text": text, "expires_ms": expires_ms,
                             "signal_id": signal_id, "reasons": reasons or []},
                            recipients, now=datetime.fromtimestamp(now_ms/1000, timezone.utc))

    def flush(self, now_ms, stop_event=None, *, live_clock=False):
        if stop_event is not None and stop_event.is_set():
            return
        if self.critical_only:
            self.outbox.suppress_context()
        self.outbox.coalesce_due(now_ms, set(self.subscribers()))
        now = datetime.fromtimestamp(now_ms/1000, timezone.utc)
        for eid in self.outbox.pending_ids(due_only=True, now=now):
            if stop_event is not None and stop_event.is_set():
                break
            def send(cid, record):
                send_ms = int(datetime.now(timezone.utc).timestamp()*1000) if live_clock else now_ms
                if int(record["expires_ms"]) <= send_ms or cid not in self.subscribers():
                    return False
                return self.sender(record["text"], cid)
            self.outbox.deliver(eid, send, now=now, stop_event=stop_event)
        with self.outbox.lock:
            recipients = [r for item in self.outbox._load().values() for r in item["recipients"].values()
                          if not r.get("superseded_by_digest")]
        self.status["pending_alerts"] = sum(r["status"] in {"pending", "sending"} for r in recipients)
        self.status["failed_alert_deliveries"] = sum(r["status"] == "failed" and not r.get("suppressed_by_policy") for r in recipients)
        self.status["suppressed_context_deliveries"] = sum(bool(r.get("suppressed_by_policy")) for r in recipients)

    def tick(self, daily, *, now_ms=None, stop_event=None):
        live_clock = now_ms is None
        now_ms = int(datetime.now(timezone.utc).timestamp()*1000) if now_ms is None else now_ms
        try:
            self.load()
            # Keep the first 30 seconds of every scan boundary for signal delivery.
            if now_ms % (5*regime.MINUTE) < 30_000:
                return
            if now_ms < self.next_check_ms:
                self.flush(now_ms, stop_event, live_clock=live_clock)
                return
            self.next_check_ms = now_ms + regime.MINUTE
            self._check(daily, now_ms, stop_event)
            self.save()
            self.status["last_error"] = None
            self.status["last_check_at"] = regime.iso(now_ms)
            self.next_check_ms = (now_ms//(5*regime.MINUTE)+1)*(5*regime.MINUTE)+30_000
            completed_ms = int(datetime.now(timezone.utc).timestamp()*1000) if live_clock else now_ms
            self.flush(completed_ms, stop_event, live_clock=live_clock)
        except Exception as exc:
            # Preserve corrupt files; no silent reset/replay. Do not expose payloads.
            self.status["last_error"] = type(exc).__name__
            # Queue/state IO failed: retry from durable state, not half-mutated
            # condition timestamps that could silently skip the warning.
            self.state = None
            self.last_fast_slot = None

    def _check(self, daily, now_ms, stop_event):
        # Persist all recipients/pages atomically before marking any event warned.
        updates = []
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
        queued = self.outbox.all_records()
        known_transitions = {m.get("transition_key") for row in queued for m in row.get("watch_items", [])
                             if m.get("kind") == "regime"}
        for key, label in labels.items():
            if label == "UNKNOWN":
                continue
            previous = self.state["regimes"].get(key)
            if previous and previous != label:
                changes.append(f"• {titles[key]}: {regime.NAMES[previous]} → {regime.NAMES[label]}")
        transition_key = "regime|"+str(slot)+"|"+json.dumps(labels, sort_keys=True)
        if not self.critical_only and changes and transition_key not in known_transitions:
            updates.append((dict(kind="regime", observed_ms=now_ms, expires_ms=now_ms+BAR,
                details={"regime": "\n".join(changes)},
                transition_key=transition_key), list(self.subscribers())))
        self.state["regimes"].update({k:v for k,v in labels.items() if v != "UNKNOWN"})
        events = self.state["events"]
        for eid in list(events):
            if now_ms >= events[eid]["end_ms"]:
                event = events[eid]
                # Only previously registered, recently expired signals. Never
                # flood historical signals on startup or imply a closed position.
                if not self.critical_only and now_ms-event["end_ms"] < 5*regime.MINUTE:
                    updates.append((self._watch_item(event, {"horizon_end": "Süre bitti"}, now_ms,
                        kind="horizon", expires_ms=event["end_ms"]+BAR), self.recipients(eid)))
                del events[eid]
        for record in self.records():
            if record.get("event_id") not in events:
                event = register(record, now_ms, self.fast if fast_fresh else {}, daily)
                if event:
                    events[event["event_id"]] = event
            elif "monitor_from_ms" not in events[record["event_id"]]:
                refreshed = register(record, now_ms, {}, {})
                if refreshed:
                    events[record["event_id"]]["monitor_from_ms"] = refreshed["monitor_from_ms"]
        # Recover an enqueue-before-state-save crash without re-warning a reason.
        for alert in queued:
            for signal_id, reasons in warning_links(alert):
                event = events.get(signal_id)
                if event:
                    event["warned"] = sorted(set(event["warned"]) | set(reasons))
        cache = {}
        symbols = set()
        price_errors = 0
        condition_errors = 0
        condition_budget = self.max_symbols
        market_blocked = self.fast.get("last_error") in {"MarketRateLimitError", "MarketTransientError"}
        for event in sorted(events.values(), key=lambda e:e["last_checked_ms"]):
            if stop_event is not None and stop_event.is_set():
                break
            reasons = {}
            for key, label in labels.items():
                initial = event["baseline"].get(key, "UNKNOWN")
                if label != "UNKNOWN" and initial == "UNKNOWN":
                    event["baseline"][key] = label
                elif (not self.critical_only and changed_against(initial, label, event["direction"])
                      and key not in event["warned"]):
                    reasons[key] = f"{titles[key]}: {regime.NAMES[initial]} → {regime.NAMES[label]}."
            symbol_key = event["market"], event["performance_symbol"]
            price_reason = CRITICAL_REASON if self.critical_only else "structure"
            if (not market_blocked and price_reason not in event["warned"]
                    and (symbol_key in symbols or len(symbols) < self.max_symbols)):
                symbols.add(symbol_key)
                try:
                    if symbol_key not in cache:
                        cache[symbol_key] = self.fetch(*symbol_key, "15m", {"limit": 32 if self.critical_only else 4})
                    reference = event.get("reference_raw")
                    if not reference:
                        reference = self.fetch(*symbol_key, "1h", {
                            "startTime": event["reference_ms"],
                            "endTime": event["reference_ms"]+regime.HOUR-1, "limit": 1})
                    reason = (critical_reversal_reason(event, reference, cache[symbol_key], now_ms,
                              {**self.fast, "fresh": bool(fast_fresh)}) if self.critical_only else
                              structure_reason(event, reference, cache[symbol_key], now_ms))
                    event["reference_raw"] = reference
                    if reason:
                        reasons[price_reason] = reason
                    event["last_error"] = None
                except Exception as exc:
                    event["last_error"] = type(exc).__name__
                    price_errors += 1
                    market_blocked = type(exc).__name__ in {"MarketRateLimitError", "MarketTransientError"}
                event["last_checked_ms"] = now_ms
            if (event["strategy"] == "G1" and self.condition_check is not None
                    and "conditions_lost" not in event["warned"] and not market_blocked
                    and condition_budget > 0
                    and event.get("last_condition_bar_ms", 0) < now_ms//regime.HOUR*regime.HOUR
                    and now_ms//regime.HOUR*regime.HOUR > event["reference_ms"]+regime.HOUR):
                condition_budget -= 1
                try:
                    check = self.condition_check(event, now_ms)
                    if (not isinstance(check, dict) or check.get("status") not in {"ACTIVE", "CONDITIONS_LOST"}
                            or check.get("bar_end_ms") != now_ms//regime.HOUR*regime.HOUR):
                        condition_errors += 1
                        event["condition_status"] = "UNKNOWN"
                    else:
                        event["last_condition_bar_ms"] = check["bar_end_ms"]
                        event["condition_status"] = check["status"]
                        if (not self.critical_only and check["status"] == "CONDITIONS_LOST"
                                and check.get("failed_conditions")):
                            reasons["conditions_lost"] = "Özgün G1 yeniden kontrolü: " + "; ".join(check["failed_conditions"])
                except Exception as exc:
                    condition_errors += 1
                    event["condition_status"] = "UNKNOWN"
                    event["condition_error"] = type(exc).__name__
                    market_blocked = type(exc).__name__ in {"MarketRateLimitError", "MarketTransientError"}
            if reasons:
                item = self._watch_item(event, reasons, now_ms)
                if self.critical_only:
                    item.update(alert_policy=CRITICAL_POLICY,
                                expires_ms=min(event["end_ms"], (now_ms//BAR+1)*BAR))
                updates.append((item, self.recipients(event["event_id"])))
        subscribers, groups = set(self.subscribers()), {}
        for item, recipients in updates:
            for cid in sorted(set(recipients) & subscribers):
                groups.setdefault(cid, []).append(item)
        if groups:
            self.outbox.enqueue_groups(groups, now_ms)
        for item, _ in updates:
            event = events.get(item.get("signal_id"))
            if event:
                event["warned"] = sorted(set(event["warned"]) | set(item["details"]))
        self.status.update(active_signals=len(events), price_errors=price_errors,
                           condition_errors=condition_errors,
                           price_backlog=sum(e["last_checked_ms"] != now_ms
                                             and (CRITICAL_REASON if self.critical_only else "structure") not in e["warned"]
                                             for e in events.values()),
                           fast_error=self.fast.get("last_error"))

    @staticmethod
    def _watch_item(event, reasons, now_ms, *, kind="signal", expires_ms=None):
        return dict(kind=kind, signal_id=event["event_id"], strategy=event["strategy"],
            symbol=event["symbol"], direction=event["direction"], delivered_ms=event["delivered_ms"],
            end_ms=event["end_ms"], details=dict(reasons), observed_ms=now_ms,
            expires_ms=expires_ms if expires_ms is not None else event["end_ms"])
