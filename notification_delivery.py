"""Private durable Telegram outbox. Public summaries never contain chat IDs."""
from __future__ import annotations

import json
import statistics
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path


def utcnow():
    return datetime.now(timezone.utc)


def _aware_time(value):
    stamp = datetime.fromisoformat(value)
    if stamp.tzinfo is None:
        raise ValueError("invalid_delivery_state")
    return stamp


def _validate_events(data):
    """Fail closed; never erase a corrupt queue and resend its known events."""
    try:
        if (not isinstance(data, dict) or type(data.get("schema_version")) is not int
                or data["schema_version"] != 1
                or not isinstance(data.get("events"), dict)):
            raise ValueError("invalid_delivery_state")
        for key, item in data["events"].items():
            if (not isinstance(key, str) or not key or not isinstance(item, dict)
                    or not isinstance(item.get("record"), dict)
                    or item["record"].get("event_id") != key
                    or not isinstance(item.get("recipients"), dict)):
                raise ValueError("invalid_delivery_state")
            _aware_time(item["created_at"])
            if "first_delivered_at" in item:
                _aware_time(item["first_delivered_at"])
            for cid, recipient in item["recipients"].items():
                if (not isinstance(cid, str) or not cid or not isinstance(recipient, dict)
                        or recipient.get("status") not in ("pending", "sending", "delivered", "failed")
                        or type(recipient.get("attempts")) is not int or recipient["attempts"] < 0):
                    raise ValueError("invalid_delivery_state")
                for field in ("delivered_at", "next_attempt_at"):
                    if field in recipient:
                        _aware_time(recipient[field])
            has_delivery = any(r["status"] == "delivered" for r in item["recipients"].values())
            if has_delivery != ("first_delivered_at" in item):
                raise ValueError("invalid_delivery_state")
    except (KeyError, TypeError, ValueError):
        # No payload, chat ID, exception value or secret in this error.
        raise ValueError("invalid_delivery_state") from None
    return data["events"]


def public_delivery(item: dict | None) -> dict:
    if not item:
        return {"delivery_confirmed": False, "delivery_status": "unknown"}
    recipients = list(item.get("recipients", {}).values())
    sent = sum(r.get("status") == "delivered" for r in recipients)
    pending = sum(r.get("status") in ("pending", "sending") for r in recipients)
    status = ("delivered" if sent and sent == len(recipients) else
              "partial" if sent else "pending" if pending else "failed")
    result = {"delivery_confirmed": sent > 0, "delivery_status": status,
              "delivery_sent_count": sent, "delivery_pending_count": pending,
              "delivery_failed_count": len(recipients) - sent - pending}
    if item.get("first_delivered_at"):
        result["delivered_at"] = item["first_delivered_at"]
    result["queued_at"] = item.get("created_at")
    result["delivery_latency_seconds"] = delivery_latency(item)
    return result


def delivery_latency(item: dict) -> dict:
    """Elapsed stages to first API acknowledgement, not phone notification time.

    Older records have no detection stamp: keep missing stages unknown.
    Clock reversals/invalid optional metadata must never become zero latency.
    """
    record = item.get("record") or {}
    stamps = {"reference": record.get("signal_reference_at"),
              "detected": record.get("detected_at"),
              "queued": item.get("created_at"),
              "ack": item.get("first_delivered_at")}
    result = {}
    for name, start, end in (
            ("reference_to_detect", "reference", "detected"),
            ("detect_to_queue", "detected", "queued"),
            ("queue_to_ack", "queued", "ack"),
            ("reference_to_ack", "reference", "ack")):
        try:
            seconds = (_aware_time(stamps[end]) - _aware_time(stamps[start])).total_seconds()
            result[name] = round(seconds, 3) if seconds >= 0 else None
        except (TypeError, ValueError, OverflowError):
            result[name] = None
    return result


class DeliveryRetryWorker:
    """One leader-owned timer; a long market scan cannot delay due retries."""
    def __init__(self, callback, interval_seconds=5):
        self.callback = callback
        self.interval_seconds = interval_seconds
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self._run, name="telegram-retry", daemon=True)

    def _run(self):
        while not self.stop_event.is_set():
            self.callback(self.stop_event)
            if self.stop_event.wait(self.interval_seconds):
                break

    def start(self):
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        # Finish an in-flight HTTP request before relinquishing leadership.
        self.thread.join()


class DeliveryOutbox:
    def __init__(self, path: Path, max_attempts=4, ttl_minutes=15):
        self.path = Path(path)
        self.max_attempts = max_attempts
        self.ttl_minutes = ttl_minutes
        self.lock = threading.RLock()
        self.items = None
        self._inflight = set()

    def _load(self):
        if self.items is None:
            if not self.path.exists():
                self.items = {}
            else:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                self.items = _validate_events(data)
        return self.items

    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps({"schema_version": 1, "events": self.items},
                                  ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.path)

    def enqueue(self, record: dict, recipients: list[str], now=None):
        now = now or utcnow()
        with self.lock:
            items = self._load()
            key = record["event_id"]
            if key not in items:
                items[key] = {"record": dict(record), "created_at": now.isoformat(),
                              "recipients": {str(cid): {"status": "pending", "attempts": 0}
                                             for cid in recipients if cid}}
                self._save()
            return public_delivery(items[key])

    def get_public(self, event_id: str):
        with self.lock:
            return public_delivery(self._load().get(event_id))

    def confirmed_records(self):
        with self.lock:
            return [{**item["record"], **public_delivery(item)}
                    for item in self._load().values()
                    if item.get("first_delivered_at")]

    def pending_ids(self, due_only=False, now=None):
        now = now or utcnow()
        with self.lock:
            return [key for key, item in self._load().items()
                    if any(r.get("status") in ("pending", "sending")
                           and (not due_only or (key, cid) not in self._inflight)
                           and (not due_only or not r.get("next_attempt_at")
                                or now >= _aware_time(r["next_attempt_at"])
                                or now - _aware_time(item["created_at"])
                                > timedelta(minutes=self.ttl_minutes))
                           for cid, r in item["recipients"].items())]

    def diagnostics(self, limit=20, now=None):
        """Read-only aggregate; never expose records, recipients, tokens or paths."""
        now = now or utcnow()
        with self.lock:
            items = list(self._load().values())
            pending = [item for item in items if any(
                r["status"] in ("pending", "sending") for r in item["recipients"].values())]
            samples = sorted(items, key=lambda item: _aware_time(item["created_at"]))[-limit:]
            timings = [delivery_latency(item) for item in samples]
            stages = {}
            for name in ("reference_to_detect", "detect_to_queue", "queue_to_ack", "reference_to_ack"):
                values = [timing[name] for timing in timings if timing[name] is not None]
                stages[name] = {"n": len(values),
                                "median": round(statistics.median(values), 3) if values else None,
                                "max": max(values) if values else None}
            latest = max((item for item in items if item.get("first_delivered_at")),
                         key=lambda item: _aware_time(item["first_delivered_at"]), default=None)
            return {"pending_events": len(pending), "sample_events": len(samples),
                    "oldest_pending_age_seconds": max((max(0, (now - _aware_time(
                        item["created_at"])).total_seconds()) for item in pending), default=None),
                    "latency_seconds": stages,
                    "latest_ack_at": latest["first_delivered_at"] if latest else None,
                    "latest_ack_latency_seconds": delivery_latency(latest) if latest else None,
                    "measurement": "first_telegram_api_ack_not_device_receipt"}

    def deliver(self, event_id: str, sender, now=None, stop_event=None):
        """Retry only unsent recipients. Transport timeout can be ambiguous."""
        with self.lock:
            item = self._load()[event_id]
            recipients = list(item["recipients"])
        for cid in recipients:
            if stop_event is not None and stop_event.is_set():
                break
            attempt_at = now or utcnow()
            claim = (event_id, cid)
            with self.lock:
                recipient = item["recipients"][cid]
                # The retry time is not a lock: an HTTP request can outlive it.
                # A concurrent manual/background delivery must not send again.
                if claim in self._inflight:
                    continue
                if recipient["status"] not in ("pending", "sending"):
                    continue
                age = attempt_at - datetime.fromisoformat(item["created_at"])
                if age > timedelta(minutes=self.ttl_minutes) or recipient["attempts"] >= self.max_attempts:
                    recipient["status"] = "failed"
                    self._save()
                    continue
                due = recipient.get("next_attempt_at")
                if due and attempt_at < datetime.fromisoformat(due):
                    continue
                recipient["attempts"] += 1
                recipient["status"] = "sending"
                recipient["next_attempt_at"] = (attempt_at + timedelta(
                    seconds=min(600, 60 * 2 ** (recipient["attempts"] - 1)))).isoformat()
                self._save()
                self._inflight.add(claim)
            try:
                try:
                    delivered = bool(sender(cid, dict(item["record"])))
                except Exception:
                    delivered = False
                with self.lock:
                    recipient["status"] = ("delivered" if delivered else
                                           "failed" if recipient["attempts"] >= self.max_attempts else "pending")
                    if delivered:
                        # Record API acknowledgement time, not request-start time.
                        stamp = utcnow().isoformat()
                        recipient["delivered_at"] = stamp
                        item.setdefault("first_delivered_at", stamp)
                    self._save()
            finally:
                with self.lock:
                    self._inflight.discard(claim)
        with self.lock:
            return public_delivery(item)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Read-only Telegram latency diagnostics; no network.")
    parser.add_argument("--status", action="store_true", required=True)
    parser.add_argument("--outbox", type=Path, default=Path(__file__).parent / ".notification_outbox.json")
    args = parser.parse_args()
    try:
        print(json.dumps(DeliveryOutbox(args.outbox).diagnostics(), indent=2))
    except (OSError, ValueError, TypeError):
        print(json.dumps({"error": "delivery_state_unreadable"}))
        raise SystemExit(1)
