"""FastAPI web servisi — signal_bot'u 7/24 canli tutar + mobil endpoint.

Render'in ucretsiz katmaninda 'background worker' YOK (sadece web servisi),
bu yuzden mimari soyle:
  * Bu FastAPI uygulamasi bir WEB SERVISI olarak kosar (Render free uyumlu).
  * signal_bot.run_forever() startup'ta bir ARKA PLAN THREAD'inde baslar,
    web katmanini bloklamaz.
  * /health   -> dis pinger (cron-job.org/UptimeRobot) bunu her ~10dk vurup
                 servisin 15dk sonra uykuya dalmasini engeller; ayrica scan
                 thread'inin canli oldugunu dogrular.
  * /signals/latest -> iPhone (Expo Go) uygulamasi buradan son sinyalleri ceker.

Baslatma (Render start command / Procfile):
    uvicorn server:app --host 0.0.0.0 --port $PORT
Yerel test:
    uvicorn server:app --reload --port 8000
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

import signal_bot as bot

app = FastAPI(title="signal_bot", docs_url="/docs")

# Mobil uygulama farkli bir origin'den fetch eder; acik CORS (yalnizca okuma
# yapan, kimlik-dogrulamasiz public endpoint oldugu icin guvenli).
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["GET"],
    allow_headers=["*"])

_thread: threading.Thread | None = None
_thread_lock = threading.Lock()


def _start_scan_thread() -> None:
    """Tarama dongusunu tek sefer, daemon thread olarak baslatir."""
    global _thread
    with _thread_lock:
        if _thread is not None and _thread.is_alive():
            return
        _thread = threading.Thread(
            target=bot.run_forever, name="scan-loop", daemon=True)
        _thread.start()


@app.on_event("startup")
def _on_startup() -> None:
    _start_scan_thread()


def _scan_thread_alive() -> bool:
    return _thread is not None and _thread.is_alive()


@app.get("/health")
def health() -> dict:
    """Pinger + izleme icin. Scan thread olduyse 'degraded' doner (ama yine
    200 — pinger servisi uyandirmaya devam etsin, restart platforma kalsin)."""
    alive = _scan_thread_alive()
    return {
        "status": "ok" if alive else "degraded",
        "scan_thread_alive": alive,
        "started_at": bot.STARTED_AT,
        "last_scan_at": bot.LAST_SCAN_AT,
        "scans_completed": bot.SCANS_COMPLETED,
        "last_scan_signal_count": bot.LAST_SCAN_COUNT,
        "recent_buffered": len(bot.RECENT_SIGNALS),
        "symbols": len(bot.SYMBOLS),
        "spot_host_active": bot.SPOT_HOSTS[bot._spot_host_idx],
        "last_scan_errors": bot.LAST_SCAN_ERRORS,
        "error_samples": list(bot.ERROR_SAMPLES),
        "universe_last_error": bot.UNIVERSE_LAST_ERROR,
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
        items = list(bot.RECENT_SIGNALS)[:limit]
    return {
        "count": len(items),
        "server_time": datetime.now(timezone.utc).isoformat(),
        "last_scan_at": bot.LAST_SCAN_AT,
        "signals": items,
    }


@app.get("/", response_class=HTMLResponse)
def root() -> str:
    """Tarayicidan bakinca hizli goz kontrolu icin minik durum sayfasi."""
    alive = "evet" if _scan_thread_alive() else "HAYIR"
    return f"""<!doctype html><meta charset=utf-8>
<title>signal_bot</title>
<body style="font-family:system-ui;max-width:640px;margin:40px auto;padding:0 16px">
<h1>signal_bot &mdash; calisiyor</h1>
<p>Tarama thread'i canli: <b>{alive}</b> &middot;
   tamamlanan tarama: <b>{bot.SCANS_COMPLETED}</b> &middot;
   son tarama: {bot.LAST_SCAN_AT or "(henuz yok)"}</p>
<p>Tamponlanan sinyal: <b>{len(bot.RECENT_SIGNALS)}</b> &middot;
   Telegram: {"acik" if bot.ENABLE_TELEGRAM else "kapali"} &middot;
   Email: {"acik" if bot.ENABLE_EMAIL else "kapali"}</p>
<ul>
  <li><a href="/health">/health</a> &mdash; izleme / keep-alive</li>
  <li><a href="/signals/latest">/signals/latest</a> &mdash; mobil endpoint</li>
  <li><a href="/docs">/docs</a> &mdash; API dokumantasyonu</li>
</ul>
<p style="color:#999;font-size:12px">Otomatik uyari sistemi. Yatirim tavsiyesi degildir.</p>
</body>"""
