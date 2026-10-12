"""Private, restart-safe forward study storage; fetches run outside its lock."""
from __future__ import annotations

import copy
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import threading
import time

import execution_shadow as engine
from atomic_state import replace_state


class ShadowStore:
    def __init__(self, path, archive_dir, now_ms=None):
        self.path = Path(path)
        self.archive_dir = Path(archive_dir)
        self.lock = threading.RLock()
        self.poll_lock = threading.Lock()
        now_ms = int(time.time()*1000) if now_ms is None else int(now_ms)
        if self.path.exists():
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if (not isinstance(data, dict) or data.get("study_version") != engine.VERSION
                    or data.get("plan_hash") != engine.PLAN_HASH
                    or not isinstance(data.get("events"), dict)
                    or not isinstance(data.get("activated_ms"), int)):
                raise ValueError("execution_shadow_state_incompatible")
            for key, event in data["events"].items():
                engine.validate_persisted(event, key, data["activated_ms"])
            self.data = data
        else:
            self.data = {"study_version": engine.VERSION, "plan_hash": engine.PLAN_HASH,
                         "activated_ms": now_ms, "events": {}}
            self._save(self.data)

    def _save(self, data):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix+".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, sort_keys=True, allow_nan=False),
                       encoding="utf-8")
        replace_state(tmp, self.path)

    def enroll(self, record, event_id, now_ms=None):
        now_ms = int(time.time()*1000) if now_ms is None else int(now_ms)
        with self.lock:
            if event_id in self.data["events"]:
                return False
            event = engine.create_event(record, event_id, self.data["activated_ms"], now_ms)
            if event is None:
                return False
            # Commit to disk before replacing memory, so a failed save is retryable.
            data = {**self.data, "events": {**self.data["events"], event_id: event}}
            self._save(data)
            self.data = data
            return True

    def _journal(self, event, bars, now_ms):
        rows = []
        for bar in bars:
            try:
                t = int(bar["open_time"])
                values = {k: float(bar[k]) for k in ("open", "high", "low", "close")}
                close_time = int(bar["close_time"])
                if (t < event["next_start_ms"] or t >= event["end_ms"]
                        or t+engine.STEP > now_ms or t % engine.STEP
                        or close_time != t+engine.STEP-1
                        or not all(math.isfinite(v) and v > 0 for v in values.values())):
                    continue
            except (KeyError, TypeError, ValueError, OverflowError):
                continue
            rows.append({"study_version": engine.VERSION, "plan_hash": engine.PLAN_HASH,
                         "event_id": event["event_id"], "symbol": event["symbol"],
                         "market": event["market"], "fetched_at_ms": now_ms,
                         "source": "binance_rest_closed_5m", "open_time": t,
                         "close_time": close_time, **values})
        if rows:
            month = datetime.fromtimestamp(now_ms/1000, timezone.utc).strftime("%Y-%m")
            self.archive_dir.mkdir(parents=True, exist_ok=True)
            with (self.archive_dir/f"execution_shadow_bars_{month}.jsonl").open("a", encoding="utf-8") as f:
                for row in rows:
                    f.write(json.dumps(row, sort_keys=True, allow_nan=False)+"\n")

    def poll(self, fetch, now_ms=None, stop_event=None, max_events=20):
        """fetch(event,start,end) -> closed5m bars. Failure never becomes a loss."""
        now_ms = int(time.time()*1000) if now_ms is None else int(now_ms)
        if not self.poll_lock.acquire(blocking=False):
            return
        try:
            with self.lock:
                pending = [copy.deepcopy(e) for e in self.data["events"].values()
                           if e.get("status") == "active"
                           and e["next_start_ms"] < min(now_ms//engine.STEP*engine.STEP, e["end_ms"])]
            pending.sort(key=lambda e: (e.get("last_poll_ms", 0), e["anchor_ms"], e["event_id"]))
            for event in pending[:max_events]:
                if stop_event is not None and stop_event.is_set():
                    break
                try:
                    end = min(now_ms//engine.STEP*engine.STEP, event["end_ms"])
                    bars = fetch(event, event["next_start_ms"], end)
                    self._journal(event, bars, now_ms)
                    engine.advance(event, bars, now_ms)
                    event.pop("fetch_error", None)
                except Exception:
                    # HTTP errors may contain tokens/URLs; persist a fixed code only.
                    event["data_status"] = "UNKNOWN"
                    event["fetch_error"] = "fetch_or_archive_failed"
                event["last_poll_ms"] = now_ms
                with self.lock:
                    data = {**self.data, "events": {**self.data["events"], event["event_id"]: event}}
                    self._save(data)
                    self.data = data
        finally:
            self.poll_lock.release()

    def snapshot(self):
        with self.lock:
            return {"study_version": engine.VERSION, "plan_hash": engine.PLAN_HASH,
                    "activated_ms": self.data["activated_ms"],
                    "events": {k: engine.public_event(v) for k, v in self.data["events"].items()}}

    def status(self):
        with self.lock:
            events = list(self.data["events"].values())
            return {"study_version": engine.VERSION, "plan_hash": engine.PLAN_HASH,
                    "research_only": True, "activated_ms": self.data["activated_ms"],
                    "n_events": len(events),
                    "n_active": sum(e.get("status") == "active" for e in events),
                    "n_complete": sum(e.get("status") == "complete" for e in events),
                    "n_unknown": sum(e.get("data_status") == "UNKNOWN" for e in events),
                    "last_poll_ms": max((e.get("last_poll_ms", 0) for e in events), default=None)}
