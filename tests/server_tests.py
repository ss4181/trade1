"""server.py readiness kontrolleri — ag/tarama dongusu baslatmadan calisir."""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from fastapi import Response

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server  # noqa: E402


def _set_bot(name: str, value, restore: list[tuple[str, bool, object]]) -> None:
    existed = hasattr(server.bot, name)
    restore.append((name, existed, getattr(server.bot, name, None)))
    setattr(server.bot, name, value)


def main() -> None:
    now = datetime.now(timezone.utc)
    old_thread = server._thread
    restore: list[tuple[str, bool, object]] = []
    old_stale = os.environ.get("HEALTH_STALE_AFTER_MINUTES")
    old_grace = os.environ.get("HEALTH_STARTUP_GRACE_MINUTES")
    try:
        os.environ["HEALTH_STALE_AFTER_MINUTES"] = "15"
        os.environ["HEALTH_STARTUP_GRACE_MINUTES"] = "15"
        server._thread = SimpleNamespace(is_alive=lambda: True)
        _set_bot("STARTED_AT", now.isoformat(), restore)
        _set_bot("LAST_SCAN_AT", None, restore)
        _set_bot("LAST_SCAN_SUCCESS_AT", None, restore)
        _set_bot("LAST_LOOP_HEARTBEAT_AT", now.isoformat(), restore)
        _set_bot("INSTANCE_LOCK_HELD", True, restore)
        _set_bot("CONSECUTIVE_SCAN_FAILURES", 0, restore)

        starting = server._readiness(now)
        assert starting["ready"] and starting["starting"]

        server.bot.LAST_SCAN_SUCCESS_AT = now.isoformat()
        healthy = server._readiness(now)
        assert healthy["ready"] and not healthy["starting"]

        server.bot.INSTANCE_LOCK_HELD = False
        no_leader = server._readiness(now)
        assert not no_leader["ready"]
        assert "instance_lock_not_held" in no_leader["reasons"]
        server.bot.INSTANCE_LOCK_HELD = True

        server.bot.CONSECUTIVE_SCAN_FAILURES = 1
        failed_scan = server._readiness(now)
        assert not failed_scan["ready"]
        assert "recent_scan_failed" in failed_scan["reasons"]
        server.bot.CONSECUTIVE_SCAN_FAILURES = 0

        server.bot.LAST_SCAN_SUCCESS_AT = (
            now - timedelta(minutes=16)).isoformat()
        stale = server._readiness(now)
        assert not stale["ready"]
        assert "successful_scan_stale" in stale["reasons"]

        response = Response()
        payload = server.health(response)
        assert response.status_code == 503
        assert payload["status"] == "degraded"

        server._thread = None
        dead = server._readiness(now)
        assert "scan_thread_dead" in dead["reasons"]

        with server.bot._recent_lock:
            old_recent = list(server.bot.RECENT_SIGNALS)
            server.bot.RECENT_SIGNALS.clear()
            server.bot.RECENT_SIGNALS.appendleft("bozuk")
            server.bot.RECENT_SIGNALS.appendleft({
                "strategy": "S1", "symbol": "BTCUSDT", "direction": "LONG",
                "bar_time": now.isoformat(), "price": 100.0,
                "horizon_hours": 24,
            })
        try:
            feed = server.signals_latest(limit=20)
            assert feed["count"] == 1 and feed["invalid_dropped"] == 1
        finally:
            with server.bot._recent_lock:
                server.bot.RECENT_SIGNALS.clear()
                server.bot.RECENT_SIGNALS.extend(old_recent)
    finally:
        server._thread = old_thread
        for name, existed, value in reversed(restore):
            if existed:
                setattr(server.bot, name, value)
            else:
                delattr(server.bot, name)
        if old_stale is None:
            os.environ.pop("HEALTH_STALE_AFTER_MINUTES", None)
        else:
            os.environ["HEALTH_STALE_AFTER_MINUTES"] = old_stale
        if old_grace is None:
            os.environ.pop("HEALTH_STARTUP_GRACE_MINUTES", None)
        else:
            os.environ["HEALTH_STARTUP_GRACE_MINUTES"] = old_grace
    print("server readiness tests: OK")


if __name__ == "__main__":
    main()
