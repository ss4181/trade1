"""FastAPI web servisi — signal_bot'u 7/24 canli tutar + mobil endpoint.

Tablet/VPS mimarisi:
  * Bu FastAPI uygulamasi tek-worker bir WEB SERVISI olarak kosar.
  * signal_bot.run_forever() startup'ta bir ARKA PLAN THREAD'inde baslar,
    web katmanini bloklamaz.
  * /ping     -> dis keep-alive pinger'i icin yalnizca proses liveness.
  * /health   -> scan lideri, thread ve son basarili tarama icin readiness;
                 sorun varsa teshis JSON'i ile HTTP 503 doner.
  * /signals/latest -> iPhone (Expo Go) uygulamasi buradan son sinyalleri ceker.

Baslatma:
    uvicorn server:app --host 0.0.0.0 --port $PORT
Yerel test:
    uvicorn server:app --reload --port 8000
"""

from __future__ import annotations

import os
import threading
import time
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, PlainTextResponse

import signal_bot as bot

app = FastAPI(title="signal_bot", docs_url="/docs")

# Mobil uygulama farkli bir origin'den fetch eder. Geriye uyumluluk icin
# varsayilan "*" olsa da internete acik kurulumda CORS_ALLOW_ORIGINS ile
# bilinen origin'leri sinirla; CORS kimlik dogrulama yerine gecmez.
_cors_raw = os.getenv("CORS_ALLOW_ORIGINS", "*")
_cors_origins = [origin.strip() for origin in _cors_raw.split(",")
                 if origin.strip()]
app.add_middleware(
    CORSMiddleware, allow_origins=_cors_origins or ["*"], allow_methods=["GET"],
    allow_headers=["*"])

_thread: threading.Thread | None = None
_thread_lock = threading.Lock()
_watchdog_thread: threading.Thread | None = None
_watchdog_stop = threading.Event()


def _start_scan_thread() -> bool:
    """Tarama dongusunu bu proses icinde tek sefer baslat."""
    global _thread
    with _thread_lock:
        if _thread is not None and _thread.is_alive():
            return True
        _thread = threading.Thread(
            target=bot.run_forever, name="scan-loop", daemon=True)
        _thread.start()
        return True


def _wait_for_scan_leadership() -> None:
    """Non-leader Uvicorn worker'in bos/stale API sunmasina izin verme."""
    timeout = _positive_env_number("SCAN_STARTUP_LOCK_TIMEOUT_SECONDS", 3.0)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if getattr(bot, "INSTANCE_LOCK_HELD", False):
            return
        if _thread is not None and not _thread.is_alive():
            raise RuntimeError(
                "tarama lideri baslatilamadi: "
                f"{getattr(bot, 'LAST_LOOP_ERROR', None) or 'thread sonlandi'}")
        time.sleep(0.05)
    raise RuntimeError(
        "tarama liderligi zaman asimi; bu servis tek Uvicorn worker ile "
        "calistirilmalidir")


def _watch_scan_thread() -> None:
    interval = _positive_env_number("SCAN_WATCHDOG_INTERVAL_SECONDS", 15.0)
    while not _watchdog_stop.wait(interval):
        if not _scan_thread_alive():
            _start_scan_thread()


def _start_watchdog() -> None:
    global _watchdog_thread
    if _watchdog_thread is not None and _watchdog_thread.is_alive():
        return
    _watchdog_stop.clear()
    _watchdog_thread = threading.Thread(
        target=_watch_scan_thread, name="scan-watchdog", daemon=True)
    _watchdog_thread.start()


@app.on_event("startup")
def _on_startup() -> None:
    _start_scan_thread()
    _wait_for_scan_leadership()
    _start_watchdog()


@app.on_event("shutdown")
def _on_shutdown() -> None:
    _watchdog_stop.set()


def _scan_thread_alive() -> bool:
    return _thread is not None and _thread.is_alive()


def _parse_utc(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _positive_env_number(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def _readiness(now: datetime | None = None) -> dict:
    """Thread ve son basarili tarama zamanindan readiness durumunu uret."""
    now = now or datetime.now(timezone.utc)
    interval = max(float(bot.SCAN_INTERVAL_MINUTES), 1.0)
    stale_multiplier = _positive_env_number(
        "HEALTH_STALE_INTERVAL_MULTIPLIER", 3.0)
    stale_after_min = _positive_env_number(
        "HEALTH_STALE_AFTER_MINUTES", interval * stale_multiplier)
    startup_grace_min = _positive_env_number(
        "HEALTH_STARTUP_GRACE_MINUTES", stale_after_min)
    last_success_value = (
        getattr(bot, "LAST_SCAN_SUCCESS_AT", None) or bot.LAST_SCAN_AT)
    last_success = _parse_utc(last_success_value)
    loop_heartbeat = _parse_utc(
        getattr(bot, "LAST_LOOP_HEARTBEAT_AT", None))
    started = _parse_utc(bot.STARTED_AT)
    heartbeat_age_seconds = (
        max(0.0, (now - loop_heartbeat).total_seconds())
        if loop_heartbeat else None)
    successful_scan_age_seconds = (
        max(0.0, (now - last_success).total_seconds())
        if last_success else None)
    startup_age_seconds = (
        max(0.0, (now - started).total_seconds()) if started else None)

    reasons: list[str] = []
    if not _scan_thread_alive():
        reasons.append("scan_thread_dead")
    instance_lock_held = getattr(bot, "INSTANCE_LOCK_HELD", None)
    if instance_lock_held is False:
        reasons.append("instance_lock_not_held")
    if getattr(bot, "CONSECUTIVE_SCAN_FAILURES", 0) > 0:
        reasons.append("recent_scan_failed")
    if last_success is not None:
        if now - last_success > timedelta(minutes=stale_after_min):
            reasons.append("successful_scan_stale")
        if (
            loop_heartbeat is not None
            and now - loop_heartbeat > timedelta(minutes=stale_after_min)
        ):
            reasons.append("scan_heartbeat_stale")
    elif (
        startup_age_seconds is None
        or startup_age_seconds > startup_grace_min * 60
    ):
        reasons.append("no_successful_scan")

    return {
        "ready": not reasons,
        "reasons": reasons,
        "starting": last_success is None and not reasons,
        "heartbeat_age_seconds": heartbeat_age_seconds,
        "successful_scan_age_seconds": successful_scan_age_seconds,
        "stale_after_seconds": stale_after_min * 60,
        "startup_grace_seconds": startup_grace_min * 60,
    }


@app.get("/ping", response_class=PlainTextResponse)
def ping() -> str:
    """Keep-alive pinger'lar icin MINIMAL cevap (2 bayt). /health'in zengin
    teshis JSON'i bazi ucretsiz pinger'larin cevap-boyu limitini asabiliyor;
    uyandirmak icin tek gereken 200 donen bir istek, o yuzden bunu kullan."""
    return "ok"


@app.get("/health")
def health(response: Response) -> dict:
    """Readiness: tarama lideri/thread/heartbeat sagliksizsa HTTP 503 doner."""
    alive = _scan_thread_alive()
    readiness = _readiness()
    if not readiness["ready"]:
        response.status_code = 503
    return {
        "status": (
            "starting" if readiness["starting"]
            else "ok" if readiness["ready"]
            else "degraded"
        ),
        "ready": readiness["ready"],
        "readiness_reasons": readiness["reasons"],
        "scan_thread_alive": alive,
        "scan_in_progress": getattr(bot, "SCAN_IN_PROGRESS", False),
        "instance_lock_held": getattr(bot, "INSTANCE_LOCK_HELD", None),
        "heartbeat_age_seconds": readiness["heartbeat_age_seconds"],
        "successful_scan_age_seconds": readiness[
            "successful_scan_age_seconds"],
        "stale_after_seconds": readiness["stale_after_seconds"],
        "startup_grace_seconds": readiness["startup_grace_seconds"],
        "started_at": bot.STARTED_AT,
        "last_scan_at": bot.LAST_SCAN_AT,
        "last_scan_started_at": getattr(bot, "LAST_SCAN_STARTED_AT", None),
        "last_scan_finished_at": getattr(bot, "LAST_SCAN_FINISHED_AT", None),
        "last_scan_success_at": getattr(bot, "LAST_SCAN_SUCCESS_AT", None),
        "last_scan_failure_at": getattr(bot, "LAST_SCAN_FAILURE_AT", None),
        "last_loop_heartbeat_at": getattr(
            bot, "LAST_LOOP_HEARTBEAT_AT", None),
        "last_loop_error": getattr(bot, "LAST_LOOP_ERROR", None),
        "archive_worker_active": getattr(bot, "ARCHIVE_WORKER_ACTIVE", False),
        "archive_worker_last_error": getattr(
            bot, "ARCHIVE_WORKER_LAST_ERROR", None),
        "performance_worker_active": getattr(
            bot, "PERFORMANCE_WORKER_ACTIVE", False),
        "performance_worker_last_error": getattr(
            bot, "PERFORMANCE_WORKER_LAST_ERROR", None),
        "publish_worker_active": getattr(bot, "PUBLISH_WORKER_ACTIVE", False),
        "publish_worker_last_error": getattr(
            bot, "PUBLISH_WORKER_LAST_ERROR", None),
        "scans_completed": bot.SCANS_COMPLETED,
        "last_scan_signal_count": bot.LAST_SCAN_COUNT,
        "recent_buffered": len(bot.RECENT_SIGNALS),
        "symbols": len(bot.SYMBOLS),
        "spot_host_active": bot.SPOT_HOSTS[bot._spot_host_idx],
        "last_scan_errors": bot.LAST_SCAN_ERRORS,
        "last_scan_attempted": getattr(bot, "LAST_SCAN_ATTEMPTED", 0),
        "last_scan_succeeded_symbols": getattr(
            bot, "LAST_SCAN_SUCCEEDED_SYMBOLS", 0),
        "last_scan_error_ratio": getattr(bot, "LAST_SCAN_ERROR_RATIO", 0.0),
        "consecutive_scan_failures": getattr(
            bot, "CONSECUTIVE_SCAN_FAILURES", 0),
        "error_samples": list(bot.ERROR_SAMPLES),
        "universe_last_error": bot.UNIVERSE_LAST_ERROR,
        "perp_map_last_error": getattr(bot, "PERP_MAP_LAST_ERROR", None),
        "telegram_enabled": bot.ENABLE_TELEGRAM,
        "email_enabled": bot.ENABLE_EMAIL,
        "server_time": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/signals/latest")
def signals_latest(limit: int = 20) -> dict:
    """iPhone uygulamasinin polladigi endpoint: en yeni sinyaller once.
    `limit` 1..100 araligina sikistirilir."""
    limit = max(1, min(int(limit), bot.RECENT_MAXLEN))
    with bot._recent_lock:
        buffered = list(bot.RECENT_SIGNALS)
    valid_items = [item for item in buffered if bot.valid_signal_record(item)]
    items = valid_items[:limit]
    return {
        "count": len(items),
        "invalid_dropped": len(buffered) - len(valid_items),
        "server_time": datetime.now(timezone.utc).isoformat(),
        "last_scan_at": bot.LAST_SCAN_AT,
        "signals": items,
    }


@app.get("/", response_class=HTMLResponse)
def root() -> str:
    """Tarayicidan bakinca hizli goz kontrolu icin minik durum sayfasi."""
    alive = "evet" if _scan_thread_alive() else "HAYIR"
    readiness = _readiness()
    service_label = "hazir" if readiness["ready"] else "SORUNLU"
    reasons = ", ".join(readiness["reasons"]) or "yok"
    return f"""<!doctype html><meta charset=utf-8>
<title>signal_bot</title>
<body style="font-family:system-ui;max-width:640px;margin:40px auto;padding:0 16px">
<h1>signal_bot &mdash; {service_label}</h1>
<p>Tarama thread'i canli: <b>{alive}</b> &middot;
   readiness: <b>{readiness["ready"]}</b> &middot; neden: {reasons}<br>
   tamamlanan tarama: <b>{bot.SCANS_COMPLETED}</b> &middot;
   son tarama: {bot.LAST_SCAN_AT or "(henuz yok)"}</p>
<p>Tamponlanan sinyal: <b>{len(bot.RECENT_SIGNALS)}</b> &middot;
   Telegram: {"acik" if bot.ENABLE_TELEGRAM else "kapali"} &middot;
   Email: {"acik" if bot.ENABLE_EMAIL else "kapali"}</p>
<ul>
  <li><a href="/ping">/ping</a> &mdash; liveness / keep-alive</li>
  <li><a href="/health">/health</a> &mdash; tarama readiness / teshis</li>
  <li><a href="/signals/latest">/signals/latest</a> &mdash; mobil endpoint</li>
  <li><a href="/docs">/docs</a> &mdash; API dokumantasyonu</li>
</ul>
<p style="color:#999;font-size:12px">Otomatik uyari sistemi. Yatirim tavsiyesi degildir.</p>
</body>"""
