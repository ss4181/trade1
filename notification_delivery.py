"""Private durable Telegram outbox. Public summaries never contain chat IDs."""
from __future__ import annotations

import json
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path


def utcnow():
    return datetime.now(timezone.utc)


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
    return result


class DeliveryOutbox:
    def __init__(self, path: Path, max_attempts=4, ttl_minutes=15):
        self.path = Path(path)
        self.max_attempts = max_attempts
        self.ttl_minutes = ttl_minutes
        self.lock = threading.RLock()
        self.items = None

    def _load(self):
        if self.items is None:
            if not self.path.exists():
                self.items = {}
            else:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                if not isinstance(data, dict) or not isinstance(data.get("events"), dict):
                    raise ValueError("invalid_delivery_state")
                self.items = data["events"]
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

    def pending_ids(self):
        with self.lock:
            return [key for key, item in self._load().items()
                    if any(r.get("status") in ("pending", "sending")
                           for r in item["recipients"].values())]

    def deliver(self, event_id: str, sender, now=None):
        """Retry only unsent recipients. Transport timeout can be ambiguous."""
        now = now or utcnow()
        with self.lock:
            item = self._load()[event_id]
            recipients = list(item["recipients"])
        for cid in recipients:
            with self.lock:
                recipient = item["recipients"][cid]
                if recipient["status"] not in ("pending", "sending"):
                    continue
                age = now - datetime.fromisoformat(item["created_at"])
                if age > timedelta(minutes=self.ttl_minutes) or recipient["attempts"] >= self.max_attempts:
                    recipient["status"] = "failed"
                    self._save()
                    continue
                due = recipient.get("next_attempt_at")
                if due and now < datetime.fromisoformat(due):
                    continue
                recipient["attempts"] += 1
                recipient["status"] = "sending"
                recipient["next_attempt_at"] = (now + timedelta(
                    seconds=min(600, 60 * 2 ** (recipient["attempts"] - 1)))).isoformat()
                self._save()
            try:
                delivered = bool(sender(cid, dict(item["record"])))
            except Exception:
                delivered = False
            with self.lock:
                recipient["status"] = "delivered" if delivered else "pending"
                if delivered:
                    # Record API acknowledgement time, not request-start time.
                    stamp = utcnow().isoformat()
                    recipient["delivered_at"] = stamp
                    item.setdefault("first_delivered_at", stamp)
                self._save()
        return public_delivery(item)
