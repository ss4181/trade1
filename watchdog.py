"""Bekci: tablet susarsa Telegram'dan haber verir.

Neden var: 2026-08-01'de tablette Python 3.14 yukseltmesi tum pip paketlerini
sildi, bot 3 GUN ayakta degildi ve HICBIR SEY haber vermedi. Bulut yedegi
arada sinyal gondermeye devam ettigi icin "calisiyor" izlenimi bile verdi.
Ariza ancak Telegram komutlari cevapsiz kalinca fark edildi.

Ne yapar: botun gh-pages'e yayimladigi `data.json` icindeki
`status.last_scan` zaman damgasina bakar. Belirlenen suredan eskiyse uyari,
yeniden tazelendiginde "toparladi" mesaji gonderir.

Ne YAPMAZ: Binance'e hic istek atmaz (IP yasagi riski yok), tarama yapmaz,
bot durumunu degistirmez. Yalnizca okur ve mesaj atar.

Kullanim:
    python watchdog.py --data gh-pages/data.json
    python watchdog.py --data gh-pages/data.json --state .watchdog_state.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
MAX_AGE_MIN = int(os.environ.get("WATCHDOG_MAX_AGE_MIN", "60"))
REALERT_HOURS = float(os.environ.get("WATCHDOG_REALERT_HOURS", "6"))
TABLET_DOC = "TABLET.md > 'Boot servisini guvenli durdur / guncelle / baslat'"


def _redact(text: str) -> str:
    """Token log'a/hata mesajina ASLA sizmasin."""
    if TELEGRAM_BOT_TOKEN and TELEGRAM_BOT_TOKEN in text:
        text = text.replace(TELEGRAM_BOT_TOKEN, "***TOKEN***")
    return text


def send_telegram(text: str) -> bool:
    if not (TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID):
        print("uyari: TELEGRAM_BOT_TOKEN/CHAT_ID yok — mesaj gonderilmedi",
              file=sys.stderr)
        return False
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": text,
                  "parse_mode": "HTML", "disable_web_page_preview": True},
            timeout=30)
        r.raise_for_status()
        return True
    except Exception as e:                                  # noqa: BLE001
        print(f"uyari: telegram gonderilemedi: {_redact(str(e))}",
              file=sys.stderr)
        return False


def load_state(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_state(path: Path, state: dict) -> None:
    try:
        path.write_text(json.dumps(state), encoding="utf-8")
    except OSError as e:
        print(f"uyari: bekci durumu yazilamadi: {e}", file=sys.stderr)


def read_last_scan(data_path: Path) -> datetime | None:
    """data.json -> status.last_scan (ISO, UTC). Okunamazsa None."""
    try:
        data = json.loads(data_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        print(f"uyari: {data_path} okunamadi: {e}", file=sys.stderr)
        return None
    raw = (data.get("status") or {}).get("last_scan")
    if not raw:
        return None
    try:
        ts = datetime.fromisoformat(str(raw))
    except ValueError:
        print(f"uyari: last_scan cozumlenemedi: {raw!r}", file=sys.stderr)
        return None
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


def _fmt_age(delta: timedelta) -> str:
    total_min = int(delta.total_seconds() // 60)
    if total_min < 120:
        return f"{total_min} dakika"
    hours = total_min / 60
    if hours < 48:
        return f"{hours:.1f} saat"
    return f"{hours / 24:.1f} gun"


def main() -> int:
    ap = argparse.ArgumentParser(description="trade1 tablet bekcisi")
    ap.add_argument("--data", required=True,
                    help="gh-pages data.json yolu")
    ap.add_argument("--state", default=".watchdog_state.json")
    ap.add_argument("--dry-run", action="store_true",
                    help="mesaj GONDERME, ne yapacagini yaz")
    args = ap.parse_args()

    now = datetime.now(timezone.utc)
    state = load_state(Path(args.state))
    last_scan = read_last_scan(Path(args.data))

    if last_scan is None:
        # Veri yoksa SESSIZ kal: yayin hic kurulmamis olabilir; yanlis alarm
        # uretmek bekciye olan guveni bitirir.
        print("last_scan okunamadi — sessiz kaliniyor (yanlis alarm uretme)")
        return 0

    age = now - last_scan
    healthy = age <= timedelta(minutes=MAX_AGE_MIN)
    print(f"son tarama: {last_scan.isoformat()} · yas: {_fmt_age(age)} · "
          f"esik: {MAX_AGE_MIN} dk · durum: {'SAGLIKLI' if healthy else 'SESSIZ'}")

    if healthy:
        if state.get("alerted_at"):
            msg = ("✅ <b>Tablet toparladı</b>\n"
                   f"Son tarama: {last_scan:%Y-%m-%d %H:%M} UTC "
                   f"({_fmt_age(age)} önce).")
            if args.dry_run:
                print(f"[dry-run] toparlama mesaji:\n{msg}")
            else:
                send_telegram(msg)
            save_state(Path(args.state), {})
        return 0

    last_alert_raw = state.get("alerted_at")
    if last_alert_raw:
        try:
            last_alert = datetime.fromisoformat(last_alert_raw)
            if last_alert.tzinfo is None:
                last_alert = last_alert.replace(tzinfo=timezone.utc)
            if now - last_alert < timedelta(hours=REALERT_HOURS):
                print(f"zaten uyarildi ({last_alert.isoformat()}); "
                      f"{REALERT_HOURS} saat dolmadan tekrar edilmez")
                return 0
        except ValueError:
            pass

    msg = (f"🔴 <b>Tablet {_fmt_age(age)}dır tarama yapmadı</b>\n"
           f"Son tarama: {last_scan:%Y-%m-%d %H:%M} UTC\n"
           f"Eşik: {MAX_AGE_MIN} dakika\n\n"
           "Bot muhtemelen ayakta değil — Telegram komutları da cevapsız "
           "kalacaktır (komut dinleyicisi botun içinde çalışır).\n\n"
           "Kontrol:\n"
           "<code>pgrep -af \"signal_bot.py|uvicorn server:app\"</code>\n"
           "<code>tail -n 40 ~/trade1/bot.out.log</code>\n\n"
           f"Yeniden başlatma: {TABLET_DOC}")
    if args.dry_run:
        print(f"[dry-run] uyari mesaji:\n{msg}")
        return 0
    if send_telegram(msg):
        save_state(Path(args.state), {"alerted_at": now.isoformat()})
    return 0


if __name__ == "__main__":
    sys.exit(main())
