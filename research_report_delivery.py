"""Small durable report state; no archive payloads, paths or credentials exported."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from atomic_state import replace_state


def utc_time(value) -> datetime | None:
    try:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return result.replace(tzinfo=timezone.utc) if result.tzinfo is None else result.astimezone(timezone.utc)
    except (ValueError, TypeError, OverflowError):
        return None


def read_state(path: Path) -> dict:
    """Missing is new; corrupt/unreadable is NOT silently a new schedule."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    if not isinstance(data, dict):
        raise ValueError("invalid_report_state")
    return data


def write_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    replace_state(tmp, path)


def weekly_due(state: dict, slot: str, now: datetime) -> bool:
    if state.get("last_week") == slot:
        return False
    if state.get("last_status") == "running":
        started = utc_time(state.get("last_started_at_utc"))
        if started and now - started < timedelta(hours=6):
            return False
    retry = utc_time(state.get("retry_at_utc"))
    return retry is None or now >= retry


def archive_snapshot(report: dict) -> dict:
    """Explicit allowlist; never copy arbitrary report metadata."""
    market = report.get("market") or report.get("data") or {}
    last = utc_time(market.get("last_utc") or market.get("feature_last_utc"))
    return {
        "rows": max(0, int(market.get("rows", market.get("accepted", 0)) or 0)),
        "symbols": max(0, int(market.get("symbols") or 0)),
        "last_record_at_utc": last.isoformat() if last else None,
    }


def public_state(state: dict) -> dict:
    """Dashboard status deliberately excludes errors, paths and report bodies."""
    timestamps = ("last_started_at_utc", "last_completed_at_utc", "last_sent_at_utc",
                  "next_due_at_utc", "retry_at_utc")
    result = {key: parsed.isoformat() if (parsed := utc_time(state.get(key))) else None
              for key in timestamps}
    allowed = {"scheduled", "running", "sent", "warning", "error"}
    result["last_status"] = state.get("last_status") if state.get("last_status") in allowed else "not_run"
    result["last_archive"] = archive_snapshot({"market": state.get("archive_snapshot") or {}})
    # last_record_at_utc is the persisted snapshot spelling, not market.last_utc.
    last = utc_time((state.get("archive_snapshot") or {}).get("last_record_at_utc"))
    result["last_archive"]["last_record_at_utc"] = last.isoformat() if last else None
    result["delivery_evidence"] = "telegram_api_ack" if result["last_sent_at_utc"] else "not_confirmed"
    return result
