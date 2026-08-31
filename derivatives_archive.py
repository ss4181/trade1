"""Forward archive for Binance USD-M public liquidation snapshots.

Binance's all-market ``!forceOrder@arr`` stream is non-replayable.  This
module records each received snapshot together with connection lifecycle
events so future research can distinguish "no liquidation" from "collector
was offline".  It never places orders and needs no Binance API key.

The stream is a snapshot feed: for each symbol Binance publishes at most the
latest liquidation order in a 1000 ms interval.  Records therefore must not be
described as a complete exchange liquidation tape.
"""

from __future__ import annotations

import argparse
from collections import deque
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
import re
import threading
import time
from typing import Any, Callable


SCHEMA_VERSION = "binance-force-order-v1"
DEFAULT_STREAM_URL = "wss://fstream.binance.com/market/ws/!forceOrder@arr"
ARCHIVE_PREFIX = "liquidation_archive"
MAX_MESSAGE_BYTES = 1_000_000
MAX_ERROR_CHARS = 300
DEFAULT_HEARTBEAT_SECONDS = 300.0


class ArchivePayloadError(ValueError):
    """Raised when a WebSocket payload is not a valid force-order event."""


class ArchiveIgnoredEvent(ValueError):
    """Valid merged-stream event outside the USD-M archive scope."""


def _utc_iso_from_ms(value: int) -> str:
    return datetime.fromtimestamp(value / 1000, tz=timezone.utc).isoformat()


def _decimal_text(value: Any, field: str) -> str:
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ArchivePayloadError(f"invalid numeric field: {field}") from None
    if not number.is_finite() or number < 0:
        raise ArchivePayloadError(f"invalid numeric field: {field}")
    return format(number, "f")


def _int_field(value: Any, field: str) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError, OverflowError):
        raise ArchivePayloadError(f"invalid integer field: {field}") from None
    if number <= 0:
        raise ArchivePayloadError(f"invalid integer field: {field}")
    return number


def _safe_error(value: Any) -> str:
    """Keep lifecycle diagnostics useful without leaking URL credentials."""
    text = str(value or "")[:MAX_ERROR_CHARS]
    text = re.sub(r"(https?://)[^/@\s]+@", r"\1[REDACTED]@", text)
    text = re.sub(r"(?i)(token|api[_-]?key|secret)=([^&\s]+)",
                  r"\1=[REDACTED]", text)
    return text


def normalize_force_order(payload: str | bytes | dict[str, Any],
                          *, received_at_ms: int | None = None) -> dict[str, Any]:
    """Validate and normalize one Binance USD-M force-order snapshot.

    Both raw stream messages and combined-stream wrappers are accepted.  The
    deterministic event id lets downstream research remove reconnect
    duplicates without inventing an exchange order id (the stream has none).
    """
    if isinstance(payload, bytes):
        if len(payload) > MAX_MESSAGE_BYTES:
            raise ArchivePayloadError("message too large")
        try:
            payload = payload.decode("utf-8")
        except UnicodeDecodeError:
            raise ArchivePayloadError("message is not UTF-8") from None
    if isinstance(payload, str):
        if len(payload.encode("utf-8")) > MAX_MESSAGE_BYTES:
            raise ArchivePayloadError("message too large")
        try:
            decoded = json.loads(payload)
        except json.JSONDecodeError:
            raise ArchivePayloadError("message is not JSON") from None
    else:
        decoded = payload
    if not isinstance(decoded, dict):
        raise ArchivePayloadError("message root is not an object")
    event = decoded.get("data", decoded)
    if not isinstance(event, dict) or event.get("e") != "forceOrder":
        raise ArchivePayloadError("message is not a forceOrder event")
    # 2026 CM/UM migration merged the all-market stream. Binance documents
    # st=1 as USD-M and st=2 as COIN-M. Legacy payloads have no st and remain
    # valid; explicit COIN-M events are silently excluded from this archive.
    symbol_type = event.get("st")
    if str(symbol_type) == "2":
        raise ArchiveIgnoredEvent("COIN-M event outside USD-M scope")
    order = event.get("o")
    if not isinstance(order, dict):
        raise ArchivePayloadError("forceOrder payload has no order object")

    symbol = str(order.get("s", "")).strip().upper()
    if not symbol or len(symbol) > 80 or any(ord(c) < 32 for c in symbol):
        raise ArchivePayloadError("invalid symbol")
    side = str(order.get("S", "")).strip().upper()
    if side not in {"BUY", "SELL"}:
        raise ArchivePayloadError("invalid order side")
    event_time_ms = _int_field(event.get("E"), "E")
    transaction_time_ms = _int_field(order.get("T", event_time_ms), "o.T")
    original_qty = _decimal_text(order.get("q"), "o.q")
    order_price = _decimal_text(order.get("p"), "o.p")
    average_price = _decimal_text(order.get("ap", "0"), "o.ap")
    last_filled_qty = _decimal_text(order.get("l", "0"), "o.l")
    accumulated_qty = _decimal_text(order.get("z", "0"), "o.z")

    avg = Decimal(average_price)
    price = avg if avg > 0 else Decimal(order_price)
    filled = Decimal(accumulated_qty)
    quantity = filled if filled > 0 else Decimal(original_qty)
    notional = price * quantity
    canonical = "|".join((
        "binance_usdm", symbol, str(transaction_time_ms), side,
        original_qty, order_price, average_price, accumulated_qty,
    ))
    event_id = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    received_ms = int(received_at_ms if received_at_ms is not None
                      else time.time() * 1000)
    if received_ms <= 0:
        raise ArchivePayloadError("invalid receive time")

    return {
        "schema_version": SCHEMA_VERSION,
        "record_type": "force_order",
        "event_id": event_id,
        "source": "binance_usdm_force_order_snapshot",
        "market_segment": "USD_M",
        "binance_symbol_type": symbol_type,
        "pair_symbol": str(event.get("ps") or symbol),
        "capture_semantics": "latest_per_symbol_per_1000ms_snapshot",
        "symbol": symbol,
        "liquidation_side": (
            "LONG_LIQUIDATION" if side == "SELL" else "SHORT_LIQUIDATION"),
        "order_side": side,
        "event_time_ms": event_time_ms,
        "event_time_utc": _utc_iso_from_ms(event_time_ms),
        "transaction_time_ms": transaction_time_ms,
        "transaction_time_utc": _utc_iso_from_ms(transaction_time_ms),
        "received_at_ms": received_ms,
        "received_at_utc": _utc_iso_from_ms(received_ms),
        "order_type": str(order.get("o", "")),
        "time_in_force": str(order.get("f", "")),
        "status": str(order.get("X", "")),
        "original_qty": original_qty,
        "order_price": order_price,
        "average_price": average_price,
        "last_filled_qty": last_filled_qty,
        "accumulated_qty": accumulated_qty,
        "estimated_notional_usd": format(notional, "f"),
        # Preserve the exact public exchange event for future parser audits.
        "raw_event": event,
    }


class MonthlyJsonlArchive:
    """Append-only monthly JSONL writer with reconnect duplicate protection."""

    def __init__(self, directory: str | Path, *, prefix: str = ARCHIVE_PREFIX,
                 recent_id_limit: int = 50_000) -> None:
        self.directory = Path(directory)
        self.prefix = prefix
        self.recent_id_limit = max(100, int(recent_id_limit))
        self._lock = threading.Lock()
        self._recent_ids: deque[str] = deque()
        self._recent_set: set[str] = set()
        self._loaded_paths: set[Path] = set()

    def path_for_ms(self, timestamp_ms: int) -> Path:
        month = datetime.fromtimestamp(
            timestamp_ms / 1000, tz=timezone.utc).strftime("%Y-%m")
        return self.directory / f"{self.prefix}_{month}.jsonl"

    def _remember(self, event_id: str) -> None:
        if event_id in self._recent_set:
            return
        self._recent_ids.append(event_id)
        self._recent_set.add(event_id)
        while len(self._recent_ids) > self.recent_id_limit:
            self._recent_set.discard(self._recent_ids.popleft())

    def _load_recent_ids(self, path: Path) -> None:
        if path in self._loaded_paths:
            return
        self._loaded_paths.add(path)
        if not path.exists():
            return
        # Loading only the tail keeps restart cost bounded even after months of
        # volatile markets.  Reconnect duplicates occur near the file tail.
        try:
            with path.open("rb") as handle:
                size = handle.seek(0, 2)
                handle.seek(max(0, size - 4 * 1024 * 1024))
                tail = handle.read().decode("utf-8", errors="ignore")
            if size > 4 * 1024 * 1024:
                tail = tail.partition("\n")[2]
            for line in tail.splitlines():
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(row, dict):
                    continue
                event_id = row.get("event_id")
                if row.get("record_type") == "force_order" and event_id:
                    self._remember(str(event_id))
        except OSError:
            # Append below will surface a real write failure if the path is bad.
            return

    def append(self, record: dict[str, Any]) -> bool:
        if record.get("record_type") != "force_order":
            raise ValueError("append expects a force_order record")
        event_id = str(record.get("event_id", ""))
        timestamp_ms = _int_field(record.get("transaction_time_ms"),
                                  "transaction_time_ms")
        if not event_id:
            raise ValueError("force_order record has no event_id")
        path = self.path_for_ms(timestamp_ms)
        line = json.dumps(record, ensure_ascii=False, sort_keys=True,
                          separators=(",", ":"))
        with self._lock:
            self.directory.mkdir(parents=True, exist_ok=True)
            self._load_recent_ids(path)
            if event_id in self._recent_set:
                return False
            with path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(line + "\n")
                handle.flush()
            self._remember(event_id)
        return True

    def append_status(self, status: str, *, at_ms: int | None = None,
                      detail: str = "") -> None:
        timestamp_ms = int(at_ms if at_ms is not None else time.time() * 1000)
        row = {
            "schema_version": SCHEMA_VERSION,
            "record_type": "stream_status",
            "source": "binance_usdm_force_order_snapshot",
            "status": str(status),
            "at_ms": timestamp_ms,
            "at_utc": _utc_iso_from_ms(timestamp_ms),
            "detail": _safe_error(detail),
        }
        path = self.path_for_ms(timestamp_ms)
        line = json.dumps(row, ensure_ascii=False, sort_keys=True,
                          separators=(",", ":"))
        with self._lock:
            self.directory.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(line + "\n")
                handle.flush()


class ForceOrderArchiveWorker:
    """Reconnect-capable WebSocket worker isolated from the signal scanner."""

    def __init__(self, directory: str | Path, *,
                 stream_url: str = DEFAULT_STREAM_URL,
                 websocket_app_factory: Callable[..., Any] | None = None,
                 heartbeat_seconds: float = DEFAULT_HEARTBEAT_SECONDS) -> None:
        self.writer = MonthlyJsonlArchive(directory)
        self.stream_url = stream_url
        self.websocket_app_factory = websocket_app_factory
        self.heartbeat_seconds = max(30.0, float(heartbeat_seconds))
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._status: dict[str, Any] = {
            "enabled": True,
            "active": False,
            "connected": False,
            "started_at": None,
            "connected_at": None,
            "last_message_at": None,
            "last_event_at": None,
            "events_written": 0,
            "duplicates_skipped": 0,
            "non_usdm_ignored": 0,
            "parse_errors": 0,
            "reconnects": 0,
            "last_error": None,
            "stream_semantics": "latest_per_symbol_per_1000ms_snapshot",
        }

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            result = dict(self._status)
        result["thread_alive"] = bool(
            self._thread is not None and self._thread.is_alive())
        return result

    def _set(self, **values: Any) -> None:
        with self._lock:
            self._status.update(values)

    def _increment(self, key: str) -> None:
        with self._lock:
            self._status[key] = int(self._status.get(key, 0)) + 1

    def _on_open(self, _ws: Any) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self._set(connected=True, connected_at=now, last_error=None)
        self.writer.append_status("connected")

    def _on_message(self, _ws: Any, message: str | bytes) -> None:
        now_ms = int(time.time() * 1000)
        self._set(last_message_at=_utc_iso_from_ms(now_ms))
        try:
            record = normalize_force_order(message, received_at_ms=now_ms)
            written = self.writer.append(record)
        except ArchiveIgnoredEvent:
            self._increment("non_usdm_ignored")
            return
        except (ArchivePayloadError, OSError, ValueError) as exc:
            self._increment("parse_errors")
            self._set(last_error=f"{type(exc).__name__}: {_safe_error(exc)}")
            return
        if written:
            self._increment("events_written")
            self._set(last_event_at=record["transaction_time_utc"])
        else:
            self._increment("duplicates_skipped")

    def _on_error(self, _ws: Any, error: Any) -> None:
        safe = _safe_error(error)
        self._set(last_error=f"websocket: {safe}", connected=False)
        try:
            self.writer.append_status("error", detail=safe)
        except OSError:
            pass

    def _on_close(self, _ws: Any, code: Any, message: Any) -> None:
        detail = f"code={code} message={_safe_error(message)}"
        self._set(connected=False)
        try:
            self.writer.append_status("disconnected", detail=detail)
        except OSError:
            pass

    def _factory(self) -> Callable[..., Any]:
        if self.websocket_app_factory is not None:
            return self.websocket_app_factory
        try:
            import websocket  # type: ignore[import-not-found]
        except ImportError:
            raise RuntimeError(
                "websocket-client eksik; pip install -r requirements.txt") from None
        return websocket.WebSocketApp

    def _heartbeat_loop(self) -> None:
        """Persist proof-of-life so silent markets are not mistaken for gaps."""
        while not self._stop.wait(self.heartbeat_seconds):
            status = self.snapshot()
            if not status.get("active"):
                return
            if not status.get("connected"):
                continue
            try:
                self.writer.append_status("heartbeat")
            except OSError as exc:
                self._set(last_error=f"{type(exc).__name__}: {_safe_error(exc)}")

    def run(self) -> None:
        self._set(active=True, started_at=datetime.now(timezone.utc).isoformat())
        backoff = 1.0
        try:
            factory = self._factory()
            threading.Thread(target=self._heartbeat_loop,
                             name="force-order-heartbeat", daemon=True).start()
            while not self._stop.is_set():
                opened_before = self.snapshot().get("connected_at")
                try:
                    app = factory(
                        self.stream_url,
                        on_open=self._on_open,
                        on_message=self._on_message,
                        on_error=self._on_error,
                        on_close=self._on_close,
                    )
                    app.run_forever(ping_interval=20, ping_timeout=10)
                except Exception as exc:  # network errors never reach scanner
                    safe = _safe_error(exc)
                    self._set(last_error=f"{type(exc).__name__}: {safe}",
                              connected=False)
                    try:
                        self.writer.append_status("error", detail=safe)
                    except OSError:
                        pass
                if self._stop.is_set():
                    break
                self._increment("reconnects")
                opened_after = self.snapshot().get("connected_at")
                backoff = 1.0 if opened_after != opened_before else min(60.0, backoff * 2)
                self._stop.wait(backoff)
        except Exception as exc:
            self._set(last_error=f"{type(exc).__name__}: {_safe_error(exc)}")
        finally:
            self._set(active=False, connected=False)

    def start(self) -> bool:
        if self._thread is not None and self._thread.is_alive():
            return False
        self._stop.clear()
        self._thread = threading.Thread(
            target=self.run, name="force-order-archive", daemon=True)
        self._thread.start()
        return True

    def stop(self) -> None:
        self._stop.set()


def summarize_archive(directory: str | Path) -> dict[str, Any]:
    """Read-only coverage summary used by the tablet status command."""
    root = Path(directory)
    files = sorted(root.glob(f"{ARCHIVE_PREFIX}_*.jsonl"))
    events = statuses = malformed = 0
    first_ms: int | None = None
    last_ms: int | None = None
    last_status: str | None = None
    for path in files:
        try:
            lines = path.open("r", encoding="utf-8")
        except OSError:
            continue
        with lines:
            for line in lines:
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    malformed += 1
                    continue
                if not isinstance(row, dict):
                    malformed += 1
                    continue
                if row.get("record_type") == "force_order":
                    events += 1
                    try:
                        timestamp = int(row["transaction_time_ms"])
                    except (KeyError, TypeError, ValueError):
                        malformed += 1
                        continue
                    first_ms = timestamp if first_ms is None else min(first_ms, timestamp)
                    last_ms = timestamp if last_ms is None else max(last_ms, timestamp)
                elif row.get("record_type") == "stream_status":
                    statuses += 1
                    last_status = str(row.get("status") or "")
    return {
        "files": len(files),
        "events": events,
        "status_records": statuses,
        "malformed_records": malformed,
        "first_event_utc": _utc_iso_from_ms(first_ms) if first_ms else None,
        "last_event_utc": _utc_iso_from_ms(last_ms) if last_ms else None,
        "last_stream_status": last_status,
        "directory": str(root.resolve()),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Binance USD-M force-order ileriye donuk arsivi")
    parser.add_argument("--dir", default=".", help="arsiv dizini")
    parser.add_argument("--status", action="store_true",
                        help="dosyalardan kapsama ozetini yaz ve cik")
    args = parser.parse_args()
    if args.status:
        print(json.dumps(summarize_archive(args.dir), ensure_ascii=False, indent=2))
        return
    worker = ForceOrderArchiveWorker(args.dir)
    print("Binance USD-M forceOrder arsivi basladi; durdurmak icin Ctrl+C")
    try:
        worker.run()
    except KeyboardInterrupt:
        worker.stop()


if __name__ == "__main__":
    main()
