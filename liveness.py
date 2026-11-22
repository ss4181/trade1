"""Tablet canlilik sinyali: hizli dis bekci pingi + yeniden ayaga kalkma bildirimi.

Neden var: 2026-11-22'de tablet bir Android guncellemesiyle kapandi; GitHub
zamanlanmis bekcisi (watchdog.py) uyariyi ancak 5,1 saat sonra gonderdi, cunku
GitHub cron isleri yogunlukta saatlerce gecikir. Iki eksik kapatilir:

1. `HEARTBEAT_PING_URL` (istege bagli): her BASARILI taramadan sonra bu adrese
   kisa bir GET atilir. healthchecks.io gibi bir "dead man's switch" servisi,
   ping belirli sure gelmezse kendi Telegram/e-posta entegrasyonuyla haber verir.
   Tespit GitHub zamanlayicisina bagli degildir (~20 dk).
2. Acilista, onceki kalici taramadan bu yana uzun bir bosluk varsa bot
   "yeniden ayakta" mesaji atar: bosluk suresi ve cihazin ne zamandir acik
   oldugu (tablet yeniden basladi mi?) gorulur.

Binance'e istek atmaz, tarama/strateji davranisini degistirmez; hatalar
yutulur ve URL (gizli UUID icerir) loga yazilmaz.
"""
from __future__ import annotations

import json
import os
import sys
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

STATE_FILE = Path(__file__).parent / ".liveness_state.json"
PING_TIMEOUT_SECONDS = 10


def valid_ping_url(url: str) -> bool:
    """Yalnizca https; bos veya baska sema sessizce kapali sayilir."""
    url = (url or "").strip()
    return url.startswith("https://") and len(url) > len("https://") + 3


def ping(url: str, session_get=None) -> bool:
    """Tek ping; ASLA istisna firlatmaz, URL'yi loga yazmaz."""
    if not valid_ping_url(url):
        return False
    if session_get is None:
        import requests
        session_get = requests.get
    try:
        response = session_get(url.strip(), timeout=PING_TIMEOUT_SECONDS)
        status = getattr(response, "status_code", 0)
        if 200 <= int(status) < 300:
            return True
        print(f"uyari: canlilik pingi HTTP {status}", file=sys.stderr, flush=True)
    except Exception as e:                                  # noqa: BLE001
        print(f"uyari: canlilik pingi gonderilemedi ({type(e).__name__})",
              file=sys.stderr, flush=True)
    return False


def ping_async(url: str) -> bool:
    """Tarama dongusunu bloklamadan ping atar. Thread basladiysa True."""
    if not valid_ping_url(url):
        return False
    threading.Thread(target=ping, args=(url,), name="liveness-ping",
                     daemon=True).start()
    return True


def load_last_scan(path: Path | None = None) -> datetime | None:
    path = path or STATE_FILE
    try:
        raw = json.loads(path.read_text(encoding="utf-8")).get("last_scan_at")
        ts = datetime.fromisoformat(str(raw))
    except (OSError, ValueError, TypeError, AttributeError):
        return None
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


def save_last_scan(when: datetime, path: Path | None = None) -> None:
    path = path or STATE_FILE
    tmp = path.with_name(path.name + ".tmp")
    try:
        tmp.write_text(json.dumps({"last_scan_at": when.isoformat()}),
                       encoding="utf-8")
        os.replace(tmp, path)
    except OSError as e:
        print(f"uyari: canlilik durumu yazilamadi: {e}", file=sys.stderr,
              flush=True)


def device_uptime(proc_uptime: Path = Path("/proc/uptime")) -> timedelta | None:
    """Cihaz acik kalma suresi; Android okumayi engellerse None."""
    try:
        return timedelta(seconds=float(proc_uptime.read_text().split()[0]))
    except (OSError, ValueError, IndexError):
        return None


def fmt_duration(delta: timedelta) -> str:
    minutes = max(0, int(delta.total_seconds() // 60))
    if minutes < 120:
        return f"{minutes} dakika"
    hours = minutes / 60
    if hours < 48:
        return f"{hours:.1f} saat"
    return f"{hours / 24:.1f} gün"


def recovery_message(previous_scan: datetime | None, now: datetime,
                     uptime: timedelta | None, min_gap_minutes: float) -> str | None:
    """Uzun bosluktan sonraki ilk tarama icin mesaj; gerekmiyorsa None.

    Ilk kurulum (onceki kayit yok) ve kisa yeniden baslatmalar (ornegin widget
    ile guncelleme) sessiz kalir; aksi halde her guncelleme bildirim uretir.
    """
    if previous_scan is None:
        return None
    gap = now - previous_scan
    if gap < timedelta(minutes=min_gap_minutes):
        return None
    lines = ["🟢 <b>Bot yeniden ayakta</b>",
             f"Tarama boşluğu: {fmt_duration(gap)}",
             f"Önceki son tarama: {previous_scan:%Y-%m-%d %H:%M} UTC"]
    if uptime is not None:
        lines.append(f"Cihaz açık kalma süresi: {fmt_duration(uptime)}")
        if uptime <= gap:
            lines.append("→ Tablet bu boşlukta yeniden başlamış; bot otomatik kalktı.")
        else:
            lines.append("→ Tablet açıktı; yalnızca bot durmuştu.")
    lines.append("Bu arada oluşan sinyaller kaçmış olabilir.")
    return "\n".join(lines)
