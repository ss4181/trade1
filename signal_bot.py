"""Kripto sinyal botu — veri-dogrulanmis esiklerle.

Uc strateji + bir confluence etiketi (esik gerekceleri: research/REPORT.md):

  S1  RSI Uyumsuzlugu (SADECE LONG)
      RSI(14) <= RSI_OVERSOLD iken fiyat yeni dip yapar ama RSI onceki
      dipten yuksek kalirsa (bullish divergence) -> LONG donus sinyali.
      Bearish (short) taraf KALDIRILDI: 2024-07..2026-06 verisinde tum
      esiklerde negatif edge uretti (asiri alim kripto'da devam sinyali).

  S2  Short Squeeze (LONG)
      Son FUNDING_PERSISTENCE settled funding orani da esikten dusukse
      -> pozisyon yiginlanmasi/squeeze sinyali. Ufuk ~72 saat.

  S3  Hacim Anomalisi (SADECE LONG / yukari-bar)
      log-hacim Z-skoru esigi asar VE bar yukariysa -> kisa vadeli (4-12h)
      momentum devami. Ham hacim z-skoru ve asagi-bar (short) tarafi
      kaldirildi: ham z spam uretiyordu, short tarafi test doneminde
      negatif edge verdi.

  S4  Confluence etiketi
      S1 tetiklendiginde son CONFLUENCE_LOOKBACK_HOURS icinde S3 duzeyinde
      hacim patlamasi varsa sinyal STRONG olarak isaretlenir
      ("hacimli kapitulasyon dibi" — testte S1'in ~2 kati edge).

Kullanim:  python signal_bot.py            # varsayilan 5dk tarama dongusu
           python signal_bot.py --once     # tek tarama (test icin)
Bagimliliklar: requests + websocket-client (pip install -r requirements.txt).
API anahtari GEREKMEZ (sadece halka acik uclar).
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import html as _html
import json
import random
import re
import subprocess
import math
import os
import statistics
import sys
import socket
import threading
import time
import traceback
from collections import deque
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import requests

from derivatives_archive import (
    DEFAULT_STREAM_URL as DEFAULT_FORCE_ORDER_STREAM_URL,
    ForceOrderArchiveWorker,
    summarize_archive as summarize_derivatives_archive,
)
from shadow_experiments import (
    poll_dl1 as poll_shadow_delists,
    scan_g1 as scan_shadow_gainers,
    summarize_archive as summarize_shadow_archive,
)
from research_monitor import (
    build_research_readiness,
    format_research_readiness,
    weekly_slot as research_weekly_slot,
)

# --------------------------------------------------------------------------
# konfigurasyon (.env ile ezilebilir; gerekceler .env.example ve README'de)
# --------------------------------------------------------------------------

_ENV_PATH = Path(__file__).parent / ".env"
_ENV_FOUND = _ENV_PATH.exists()


def _load_env(path: str = ".env") -> None:
    p = Path(__file__).parent / path
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip())


_load_env()

def _env(name: str, default, cast=None):
    raw = os.environ.get(name)
    if raw is None:
        return default
    return (cast or type(default))(raw)


DEFAULT_SYMBOLS = (
    "BTCUSDT,ETHUSDT,BNBUSDT,SOLUSDT,XRPUSDT,DOGEUSDT,ADAUSDT,TRXUSDT,"
    "LINKUSDT,AVAXUSDT,LTCUSDT,DOTUSDT,BCHUSDT,UNIUSDT,ATOMUSDT,NEARUSDT,"
    "APTUSDT,ARBUSDT,OPUSDT,FILUSDT,SUIUSDT,INJUSDT,SEIUSDT,TIAUSDT,"
    "AAVEUSDT,ETCUSDT,XLMUSDT,SANDUSDT,GALAUSDT,PEPEUSDT"
)
# Genisletilmis evren (Ek G, 2026-07): 2024-07'den beri KESINTISIZ verisi olan
# 89 coin'de donmus konfigurasyonlar dogrulandi. Kademeli sonuc:
#   - S1+S4 yeni coinlerde train+test her ikisinde saglam -> tam yetki
#   - sade S1 yeni coinlerde test guclu (p<0.001) / train notr -> ORTA guven
#   - S2 ve S3 yeni coinlerde OOS BASARISIZ -> yeni coinlerde CALISMAZ
# Bu liste STATIK ve dogrulanmis — gunluk hacim siralamasi DEGIL (Ek F dersi).
EXTENDED_SYMBOLS_DEFAULT = (
    "RIFUSDT,ZECUSDT,WLDUSDT,ENAUSDT,TAOUSDT,SHIBUSDT,HBARUSDT,BONKUSDT,"
    "STXUSDT,JTOUSDT,TLMUSDT,LDOUSDT,ACEUSDT,WIFUSDT,VANRYUSDT,DASHUSDT,"
    "FETUSDT,XECUSDT,ICPUSDT,ZILUSDT,SKLUSDT,ZROUSDT,ORDIUSDT,JUPUSDT,"
    "ETHFIUSDT,RENDERUSDT,CRVUSDT,CHRUSDT,TUSDT,PENDLEUSDT,ALGOUSDT,"
    "LUNCUSDT,QTUMUSDT,APEUSDT,ONEUSDT,BOMEUSDT,AXSUSDT,ZENUSDT,TNSRUSDT,"
    "CHZUSDT,HOTUSDT,DYDXUSDT,LISTAUSDT,PYTHUSDT,IDUSDT,FLOKIUSDT,"
    "1INCHUSDT,GRTUSDT,LSKUSDT,COMPUSDT,ALICEUSDT,SNXUSDT,ARUSDT,RSRUSDT,"
    "STRKUSDT,ENSUSDT,BLURUSDT,AGLDUSDT,CAKEUSDT"
)
_SYMBOLS_ENV = os.environ.get("SYMBOLS", "").strip()
_EXT_ENV = os.environ.get("EXTENDED_SYMBOLS")
EXTENDED_SET = {s.strip() for s in
                (EXTENDED_SYMBOLS_DEFAULT if _EXT_ENV is None else _EXT_ENV
                 ).split(",") if s.strip()}
if _SYMBOLS_ENV:
    SYMBOLS = [s.strip() for s in _SYMBOLS_ENV.split(",") if s.strip()]
else:
    SYMBOLS = [s.strip() for s in DEFAULT_SYMBOLS.split(",") if s.strip()] + \
              sorted(EXTENDED_SET)

# --- sembol evreni ---
# VARSAYILAN: 30 cekirdek + Ek G'de donmus ayarlarla dogrulanan 59 genis coin.
# Genis grupta yalniz S1 ailesi calisir; S2/S3 cekirdek-30 ile sinirlidir.
# UYARI — dinamik evren neden VARSAYILAN DEGIL: 2026-07 canli takibinde (Ek F)
# dinamik hacim-sirali evren (top ~120), ayi piyasasinda tasfiye/pump-dump
# hacmi yuksek COP coinleri iceri aliyordu (TRUMP/BONK/PENGU/... 54 dogrulanmamis
# coin). S1 (dip al) ve S2 (kalabalik short) bunlarda -22%/-80% verdi; canli
# S1 medyani -22% (backtest +0.93%) cikti. Bu yuzden dinamik mod artik ACIK
# OPT-IN: SYMBOL_AUTO=true dersen acilir, riski senindir.
def _flag(v) -> bool:
    return str(v).strip().lower() in ("1", "true", "yes", "on")


SYMBOL_AUTO = _env("SYMBOL_AUTO", False, cast=_flag)
SYMBOL_MAX_COUNT = _env("SYMBOL_MAX_COUNT", 120)
SYMBOL_MIN_PERP_VOLUME_M = _env("SYMBOL_MIN_PERP_VOLUME_M", 10.0)  # milyon $/24h, perp
SYMBOL_MIN_SPOT_VOLUME_M = _env("SYMBOL_MIN_SPOT_VOLUME_M", 1.0)   # milyon $/24h, spot
UNIVERSE_REFRESH_HOURS = _env("UNIVERSE_REFRESH_HOURS", 24)

# --- GOZLEM KANALI (2026-08-03) -------------------------------------------
# BU BIR STRATEJI DEGILDIR. Dogrulanmis S1/S2/S3 yoluna dokunmaz; hicbir esik
# degismedi. Yaptigi tek sey: EVREN DISI (dogrulanmamis) coinlerde S1 ailesini
# AYRI bir kanalda calistirmak.
#
# NEDEN VAR: evren disi coinlerde secilmis birkac kurulumun sonucu ile Ek F'nin
# olcumu celisiyor. Ek F, o evrenin URETTIGI TUM sinyalleri 24s zaman-cikisiyla
# olctu (canli S1 medyani -22%); tekil olumlu ornekler ise hem kucuk sayida hem
# de secim etkisi tasiyor (hangi sinyallerin ATLANDIGI bilinmiyor) — yani kanit
# degil. Celiskiyi kapatmanin tek yolu bu coinleri AYRI kovada, sistematik
# olarak, 2-3 ay olcmek. Bu kanalin varlik sebebi budur.
#
# EK F'NIN HATASINI TEKRARLAMAMA GARANTISI: sinyaller "GOZLEM-" onekli
# strateji adiyla uretilir. Boylece /performans ve qc_export'ta AYRI kovada
# dururlar ve dogrulanmis S1 istatistigini KIRLETMEZLER — Ek F'de asil zarar
# dogrulanmamis coinlerin ana akisa karismasiydi. Guven kademesi "GOZLEM"
# (tum kademelerin altinda) ve bildirimler DOGRULANMAMIS uyarisi tasir.
# Backtest referans seviyeleri BILEREK gosterilmez: o dagilimlar (S1 medyan
# +0.93% vb.) cekirdek-30'da olculdu, bu coinler icin gecerli DEGIL.
#
# Kapatmak: OBSERVE_ENABLED=false · Sadece sessize almak: OBSERVE_PUSH=false
# (sinyaller yine loglanir ve olculur, sadece Telegram'a gitmez).
OBSERVE_ENABLED = _env("OBSERVE_ENABLED", True, cast=_flag)
OBSERVE_PUSH = _env("OBSERVE_PUSH", True, cast=_flag)
# 0 = sinir yok: fetch_universe()'un likidite suzgecinden gecen TUM evren-disi
# semboller (dinamik evren). Pozitif sayi verirsen hacim sirasina gore ilk N.
OBSERVE_TOP_N = _env("OBSERVE_TOP_N", 0)
OBSERVE_MAX_PUSH_PER_SCAN = _env("OBSERVE_MAX_PUSH_PER_SCAN", 3)
# Gozlem sinyalleri AYRI strateji adlariyla yayinlanir; boylece /performans ve
# pano onlari dogrulanmis S1/S1+S4 ile ayni kovaya KOYAMAZ.
#   S5 = dinamik evrende S1+S4 (hacimli kapitulasyon)
#   S6 = dinamik evrende sade S1
# Izolasyonu saglayan sey ISIM DEGIL, kayittaki `observe: true` bayragidir —
# qc_export ve performans filtreleri onu okur. Isimler yalnizca kullanicinin
# bildirimleri ayirt edebilmesi icin.
OBSERVE_STRATEGY_NAMES = {"S1+S4": "S5", "S1": "S6"}
OBSERVE_STRATEGIES = set(OBSERVE_STRATEGY_NAMES.values())
OBSERVE_BASE_OF = {v: k for k, v in OBSERVE_STRATEGY_NAMES.items()}

# --- ON-KAYITLI GOLGE DENEYLER (G1/DL1) -----------------------------------
# G1 tarihsel train kapisini, DL1-PRE ise deliste kadar bekleme kapisini
# GECEMEDI. Kullanici talebiyle tum aktif USD-M evreninde/duyurulan tokenlarda
# olay bildirimi ve ileri veri toplama aciktir; mevcut S1..S6 kararlarini etkilemez.
SHADOW_EXPERIMENTS_ENABLED = _env(
    "SHADOW_EXPERIMENTS_ENABLED", True, cast=_flag)
SHADOW_PUSH_ENABLED = _env("SHADOW_PUSH_ENABLED", True, cast=_flag)
SHADOW_MAX_PUSH_PER_RUN = _env("SHADOW_MAX_PUSH_PER_RUN", 20, cast=int)
SHADOW_DELIST_POLL_MINUTES = _env(
    "SHADOW_DELIST_POLL_MINUTES", 30, cast=int)
SHADOW_STRATEGIES = {"G1", "DL1"}

# Haftalık döngü yalnız arşiv kalitesini/örnek hazırlığını raporlar. Strateji
# eşiklerini otomatik optimize ETMEZ: 90 gün keşif sonunda kural ayrıca ön
# kaydedilir, RESEARCH_OOS_START_UTC o anda yazılır ve 90 gün dokunulmaz OOS
# verisi beklenir.
RESEARCH_WEEKLY_SUMMARY_ENABLED = _env(
    "RESEARCH_WEEKLY_SUMMARY_ENABLED", True, cast=_flag)
RESEARCH_WEEKLY_WEEKDAY = _env("RESEARCH_WEEKLY_WEEKDAY", 0, cast=int)
RESEARCH_WEEKLY_HOUR_UTC = _env("RESEARCH_WEEKLY_HOUR_UTC", 6, cast=int)
RESEARCH_WEEKLY_REQUIRE_DATA = _env(
    "RESEARCH_WEEKLY_REQUIRE_DATA", True, cast=_flag)
RESEARCH_DISCOVERY_DAYS = _env("RESEARCH_DISCOVERY_DAYS", 90, cast=int)
RESEARCH_OOS_DAYS = _env("RESEARCH_OOS_DAYS", 90, cast=int)
RESEARCH_OOS_START_UTC = _env("RESEARCH_OOS_START_UTC", "").strip()


def _default_research_report_source() -> str:
    """Scheduled raporun hangi çalışma ortamından geldiğini sır sızdırmadan yaz."""
    if os.getenv("RENDER") or os.getenv("RENDER_SERVICE_NAME"):
        return "Render / bulut"
    if (os.getenv("TERMUX_VERSION") or "com.termux" in sys.prefix.lower()
            or "com.termux" in os.getenv("PREFIX", "").lower()):
        return "Termux / tablet"
    return "yerel süreç"


RESEARCH_REPORT_SOURCE = _env(
    "RESEARCH_REPORT_SOURCE", _default_research_report_source()).strip()

# 5dk tarama: sinyaller 1h bar KAPANISINDA dogar — daha sik tarama sinyal
# setini DEGISTIRMEZ (kenar-tetikleme ayni kosulu tekrar bildirmez); kazanci
# S2'nin (8h'lik funding) tespiti ve restart sonrasi yakalama icindir.
# Pano fiyati son KAPANMIS 1h mumun gercek kapanis zamanini tasir; indirme
# zamani "fiyat gozlemi" gibi gosterilmez. "Scalping sinyali" DEGILDIR —
# 15m/5m ufuklarinda edge olmadigi olculdu (research/REPORT.md Ek A/B).
SCAN_INTERVAL_MINUTES = _env("SCAN_INTERVAL_MINUTES", 5)
KLINE_LIMIT = _env("KLINE_LIMIT", 250)          # >= VOLUME_ZSCORE_WINDOW + 24 olmali
SIGNAL_LOG = _env("SIGNAL_LOG", "signals.log")

# Kullaniciya ozel fiyat-hedefi gozlem katmani. Sinyal kosullarini, guven
# kademesini veya dogrulanmis zaman-cikisini DEGISTIRMEZ. Yalniz Telegram'a
# gercekten teslim edilen sinyallerde, bildirim fiyatindan itibaren coinin
# gercek fiyat hareketinde hedef seviyelerine dokunmayi izler.
PRICE_TARGET_TRACKING_ENABLED = _env(
    "PRICE_TARGET_TRACKING_ENABLED", True, cast=_flag)
PRICE_TARGET_NOTIFY = _env("PRICE_TARGET_NOTIFY", True, cast=_flag)


def _parse_price_target_levels(raw: str) -> tuple[float, ...]:
    levels = []
    for item in str(raw).split(","):
        try:
            level = float(item.strip())
        except ValueError:
            continue
        if math.isfinite(level) and 0 < level <= 100:
            levels.append(level)
    return tuple(sorted(set(levels)))


# Kullanici panoda bu dort seviyeyi birlikte istiyor. Eski .env'de yalnız 2,3
# yazsa bile analiz 5/10'u da toplar; Telegram hedef bildirimi varsayilan olarak
# 2/3 ile sinirlidir ve boylece mevcut bildirim davranisi degismez.
PRICE_TARGET_ANALYTICS_LEVELS_PCT = _parse_price_target_levels(
    _env("PRICE_TARGET_ANALYTICS_LEVELS_PCT", "2,3,5,10"))
PRICE_TARGET_NOTIFY_LEVELS_PCT = _parse_price_target_levels(
    _env("PRICE_TARGET_NOTIFY_LEVELS_PCT", "2,3"))
USER_SUCCESS_TARGET_PCT = _env("USER_SUCCESS_TARGET_PCT", 2.0)
if (not math.isfinite(USER_SUCCESS_TARGET_PCT)
        or not 0 < USER_SUCCESS_TARGET_PCT <= 100):
    USER_SUCCESS_TARGET_PCT = 2.0
PRICE_TARGET_LEVELS_PCT = tuple(sorted(set(
    _parse_price_target_levels(_env("PRICE_TARGET_LEVELS_PCT", "2,3"))
) | set(PRICE_TARGET_ANALYTICS_LEVELS_PCT)
    | set(PRICE_TARGET_NOTIFY_LEVELS_PCT)
    | {USER_SUCCESS_TARGET_PCT}))
PRICE_TARGET_RETENTION_DAYS = _env("PRICE_TARGET_RETENTION_DAYS", 365)
PRICE_TARGET_MAX_EVENTS_PER_SCAN = max(
    1, _env("PRICE_TARGET_MAX_EVENTS_PER_SCAN", 20, cast=int))

# --- S1: RSI uyumsuzlugu (long-only) ---
RSI_PERIOD = _env("RSI_PERIOD", 14)
RSI_OVERSOLD = _env("RSI_OVERSOLD", 22.5)       # 20 -> 22.5 (train taramasi; test edge +0.31 vol, p=0.006)
DIVERGENCE_LOOKBACK = _env("DIVERGENCE_LOOKBACK", 60)
DIVERGENCE_GAP = _env("DIVERGENCE_GAP", 5)
S1_COOLDOWN_HOURS = _env("S1_COOLDOWN_HOURS", 12)
# RSI_OVERBOUGHT kaldirildi: short sinyali her esikte zarardaydi (bkz. REPORT.md)

# --- S2: funding squeeze ---
FUNDING_SQUEEZE_THRESHOLD_PCT = _env("FUNDING_SQUEEZE_THRESHOLD_PCT", -0.03)  # -0.02 -> -0.03
FUNDING_PERSISTENCE = _env("FUNDING_PERSISTENCE", 2)   # ustuste kac settled funding esik altinda olmali
S2_COOLDOWN_HOURS = _env("S2_COOLDOWN_HOURS", 24)

# --- S3: hacim anomalisi (log-z, yukari-bar, long-only) ---
VOLUME_ZSCORE_THRESHOLD = _env("VOLUME_ZSCORE_THRESHOLD", 3.0)  # log-hacim z'si (ham degil!)
VOLUME_ZSCORE_WINDOW = _env("VOLUME_ZSCORE_WINDOW", 168)
S3_COOLDOWN_HOURS = _env("S3_COOLDOWN_HOURS", 12)

# --- S4: confluence ---
CONFLUENCE_LOOKBACK_HOURS = _env("CONFLUENCE_LOOKBACK_HOURS", 24)

# Spot piyasa verisi icin sirali hostlar. api.binance.com bulut saglayicilarin
# PAYLASIMLI cikis IP'lerini sik sik yasaklar (418) / ABD'yi geo-bloklar (451);
# data-api.binance.vision ayni /api/v3 yuzeyini CDN uzerinden sunan resmi
# halka-acik aynadir. Yasak gorulunce kalici olarak sonraki hosta gecilir.
SPOT_HOSTS = ["https://api.binance.com", "https://data-api.binance.vision"]
_spot_host_idx = 0
FUT_API = "https://fapi.binance.com"   # fapi'nin aynasi yok (S2 + evren bagimli)
_HOST_SWITCH_CODES = (403, 418, 451)
_TRANSIENT_CODES = (429, 500, 502, 503, 504)
SPOT_MAX_RETRIES = _env("SPOT_MAX_RETRIES", 4)
FUTURES_MAX_RETRIES = _env("FUTURES_MAX_RETRIES", SPOT_MAX_RETRIES)
HTTP_BACKOFF_BASE_SECONDS = _env("HTTP_BACKOFF_BASE_SECONDS", 1.0)
HTTP_MAX_RETRY_AFTER_SECONDS = _env("HTTP_MAX_RETRY_AFTER_SECONDS", 60.0)
_spot_blocked_until = 0.0
_futures_blocked_until = 0.0


class MarketRateLimitError(requests.RequestException):
    """Bir sonraki sembole gecmenin rate-limit firtinasi yaratacagi durum."""


class MarketTransientError(requests.RequestException):
    """Ortak piyasa servisinin retry sonrasi da gecici olarak kullanilamamasi."""


def _retry_after_seconds(response: requests.Response | None) -> float | None:
    if response is None:
        return None
    raw = str(response.headers.get("Retry-After", "")).strip()
    if not raw:
        return None
    try:
        return max(0.0, float(raw))
    except ValueError:
        try:
            when = parsedate_to_datetime(raw)
            if when.tzinfo is None:
                when = when.replace(tzinfo=timezone.utc)
            return max(
                0.0, (when.astimezone(timezone.utc)
                      - datetime.now(timezone.utc)).total_seconds())
        except (TypeError, ValueError, OverflowError):
            return None


def _retry_delay(response: requests.Response | None, attempt: int) -> float:
    """Sunucunun Retry-After degerini koru; yoksa sinirli backoff + jitter."""
    retry_after = _retry_after_seconds(response)
    if retry_after is not None:
        return retry_after
    base = min(HTTP_BACKOFF_BASE_SECONDS * (2 ** attempt),
               HTTP_MAX_RETRY_AFTER_SECONDS)
    return max(0.0, base + random.uniform(0.0, base * 0.25))


def _wait_for_market_gate(kind: str) -> None:
    blocked_until = (
        _spot_blocked_until if kind == "spot" else _futures_blocked_until)
    delay = max(0.0, blocked_until - time.time())
    if delay:
        time.sleep(delay)


def _spot_get(path: str, params: dict | None = None) -> requests.Response:
    """Spot GET; 429/5xx'te backoff, erisim engelinde resmi host fallback'i."""
    global _spot_host_idx, _spot_blocked_until
    last_exc: Exception | None = None
    retries = max(1, int(SPOT_MAX_RETRIES))
    for attempt in range(retries):
        _wait_for_market_gate("spot")
        host = SPOT_HOSTS[_spot_host_idx]
        try:
            r = requests.get(host + path, params=params, timeout=30)
            r.raise_for_status()
            return r
        except requests.RequestException as e:
            last_exc = e
            code = e.response.status_code if e.response is not None else 0
            retryable = (not code) or code in _TRANSIENT_CODES or \
                        code in _HOST_SWITCH_CODES
            if not retryable:
                raise
            if code in _HOST_SWITCH_CODES:
                _spot_host_idx = (_spot_host_idx + 1) % len(SPOT_HOSTS)
                print(f"uyari: spot API {code} verdi -> "
                      f"{SPOT_HOSTS[_spot_host_idx]} hostuna geciliyor",
                      file=sys.stderr, flush=True)
            delay = _retry_delay(e.response, attempt)
            if code == 429:
                _spot_blocked_until = max(
                    _spot_blocked_until, time.time() + delay)
                print(f"uyari: spot API 429 rate-limit; "
                      f"{delay:.1f}s geri cekilme uygulanacak",
                      file=sys.stderr, flush=True)
            elif code in (500, 502, 503, 504) or not code:
                print(f"uyari: spot API gecici hata ({code or 'ag'}); "
                      f"{delay:.1f}s sonra tekrar denenecek",
                      file=sys.stderr, flush=True)
            if attempt >= retries - 1:
                if code == 429:
                    raise MarketRateLimitError(
                        f"spot API 429; yeniden deneme {delay:.1f}s sonra") from e
                if code in (500, 502, 503, 504) or not code:
                    raise MarketTransientError(
                        f"spot API gecici hata ({code or 'ag'})") from e
                raise
            if code == 429:
                _wait_for_market_gate("spot")
            elif delay:
                time.sleep(delay)
    raise last_exc  # type: ignore[misc]


def _futures_get(path: str, params: dict | None = None) -> requests.Response:
    """USD-M GET; 429 kapisini tum futures cagrilari arasinda paylastirir."""
    global _futures_blocked_until
    retries = max(1, int(FUTURES_MAX_RETRIES))
    last_exc: Exception | None = None
    for attempt in range(retries):
        _wait_for_market_gate("futures")
        try:
            r = requests.get(FUT_API + path, params=params, timeout=30)
            r.raise_for_status()
            return r
        except requests.RequestException as e:
            last_exc = e
            code = e.response.status_code if e.response is not None else 0
            retryable = (not code) or code in _TRANSIENT_CODES
            if not retryable:
                raise
            delay = _retry_delay(e.response, attempt)
            if code == 429:
                _futures_blocked_until = max(
                    _futures_blocked_until, time.time() + delay)
                print(f"uyari: futures API 429 rate-limit; "
                      f"{delay:.1f}s geri cekilme uygulanacak",
                      file=sys.stderr, flush=True)
            else:
                print(f"uyari: futures API gecici hata ({code or 'ag'}); "
                      f"{delay:.1f}s sonra tekrar denenecek",
                      file=sys.stderr, flush=True)
            if attempt >= retries - 1:
                if code == 429:
                    raise MarketRateLimitError(
                        f"futures API 429; yeniden deneme {delay:.1f}s sonra") from e
                if code in (500, 502, 503, 504) or not code:
                    raise MarketTransientError(
                        f"futures API gecici hata ({code or 'ag'})") from e
                raise
            if code == 429:
                _wait_for_market_gate("futures")
            elif delay:
                time.sleep(delay)
    raise last_exc  # type: ignore[misc]

# --- Telegram bildirim kanali ---
# Degerler .env dosyasindan (yerel) veya platform secret yonetiminden (bulut)
# okunur. ASLA koda gomulu deger yazilmaz. Anahtar yoksa ilgili kanal sessizce
# devre disi kalir (bot yine calisir, sadece o kanaldan gondermez).
TELEGRAM_BOT_TOKEN = _env("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = _env("TELEGRAM_CHAT_ID", "")

ENABLE_TELEGRAM = bool(TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID)

# Telegram'dan komut dinleme (/start /check /status). getUpdates long-polling
# ile — dis-baglanti oldugu icin ev NAT'i arkasinda public URL olmadan calisir.
_truthy = lambda v: str(v).strip().lower() in ("1", "true", "yes", "on")
TELEGRAM_COMMANDS = _env("TELEGRAM_COMMANDS", True, cast=_truthy)

# Komut verebilecek + otomatik sinyalleri alacak EK chat'ler (arkadaslar).
# Virgullu chat id listesi. Arkadasin ID'sini ogrenmesi icin: bota /myid yazsin.
_allow_raw = _env("TELEGRAM_ALLOWED_CHAT_IDS", "")
TELEGRAM_ALLOWED = [c.strip() for c in _allow_raw.split(",") if c.strip()]
# Aboneler = sahip + izinli arkadaslar (otomatik sinyaller bunlara gider).
TELEGRAM_SUBSCRIBERS: list[str] = []
for _c in [str(TELEGRAM_CHAT_ID)] + TELEGRAM_ALLOWED:
    if _c and _c not in TELEGRAM_SUBSCRIBERS:
        TELEGRAM_SUBSCRIBERS.append(_c)
# Acik mod: HERKES komut verebilir (ama otomatik sinyaller yine sadece abonelere;
# yabancilar botu spamlarsa /check tarama kilidi korur).
TELEGRAM_OPEN = _env("TELEGRAM_OPEN", False, cast=_truthy)
_check_lock = threading.Lock()

# --- GitHub Pages yayini (panoyu her yerden erisilebilir yapar) ---
# Bot, pano verisini periyodik olarak GitHub'a data.json olarak yazar; statik
# sayfa onu ceker. Kurulum: TABLET.md "Her yerden erisim (GitHub Pages)".
# GITHUB_TOKEN: fine-grained PAT (yalniz bu repoda Contents: read/WRITE).
# Kolaylik: repo adi ve (URL'e gomuluyse) token, git remote'undan otomatik
# turetilir — boylece cogu durumda sadece yazma-yetkili token yeter.


def _git_remote_info() -> tuple[str, str]:
    """(repo 'sahip/ad', token) — git remote origin URL'inden turetir.
    Basarisiz olursa ('', '') doner. Token'i ASLA loglamaz."""
    try:
        out = subprocess.run(
            ["git", "-C", str(Path(__file__).parent),
             "config", "--get", "remote.origin.url"],
            capture_output=True, text=True, timeout=5)
        url = (out.stdout or "").strip()
    except (OSError, subprocess.SubprocessError):
        return "", ""
    if not url:
        return "", ""
    token = ""
    m = re.search(r"https://([^@/]+)@", url)     # https://[user:]token@github...
    if m:
        token = m.group(1).split(":")[-1]
    path = re.sub(r"\.git$", "", re.sub(r"^.*github\.com[:/]", "", url)).strip("/")
    parts = path.split("/")
    repo = "/".join(parts[-2:]) if len(parts) >= 2 else ""
    return repo, token


_git_repo, _git_token = _git_remote_info()
GITHUB_TOKEN = _env("GITHUB_TOKEN", "") or _git_token
GITHUB_REPO = _env("GITHUB_REPO", "") or _git_repo
GITHUB_PAGES_BRANCH = _env("GITHUB_PAGES_BRANCH", "gh-pages")
# Statik sayfa ile sik degisen veriyi ayir: data branch'indeki commit'ler Pages
# build'i tetiklemez. Boylece 15 dakikada bir gereksiz Pages kuyrugu olusmaz.
GITHUB_DATA_BRANCH = _env("GITHUB_DATA_BRANCH", "trade1-data")
PUBLISH_INTERVAL_MIN = _env("PUBLISH_INTERVAL_MIN", 15)
# Yayin, ancak token ACIKCA verildiyse (env ya da URL'e gomulu) acilir.
PUBLISH_ENABLED = _env("PUBLISH_ENABLED", bool(GITHUB_TOKEN and GITHUB_REPO),
                       cast=_truthy)
_last_publish = 0.0
_gh_sha: str | None = None
_publish_worker_lock = threading.Lock()
PUBLISH_WORKER_ACTIVE = False
PUBLISH_WORKER_LAST_ERROR: str | None = None


# --- kalici abone deposu (Telegram icinden onay ile eklenenler) ---
# .env'i elle duzenleyip botu yeniden baslatmaya gerek kalmasin: sahip
# /onayla ile ekler, dosyaya yazilir, ANINDA gecerli olur. env listesi
# (TELEGRAM_ALLOWED_CHAT_IDS) sabit taban olarak kalir; buradan silinemez.
SUBSCRIBERS_FILE = Path(__file__).parent / _env(
    "SUBSCRIBERS_FILE", ".subscribers.json")
_subs_lock = threading.Lock()
DYNAMIC_SUBSCRIBERS: dict[str, str] = {}     # chat_id -> etiket (ad)
PENDING_JOINS: dict[str, str] = {}           # chat_id -> etiket (ad)


def _load_subscribers() -> None:
    """Diskteki onayli aboneleri yukler ve yayin listesine ekler."""
    if not SUBSCRIBERS_FILE.exists():
        return
    try:
        data = json.loads(SUBSCRIBERS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        print(f"uyari: abone dosyasi okunamadi: {e}", file=sys.stderr,
              flush=True)
        return
    for cid, label in (data.get("subscribers") or {}).items():
        DYNAMIC_SUBSCRIBERS[str(cid)] = str(label or "")
        if str(cid) not in TELEGRAM_SUBSCRIBERS:
            TELEGRAM_SUBSCRIBERS.append(str(cid))
    if DYNAMIC_SUBSCRIBERS:
        print(f"abone dosyasi: {len(DYNAMIC_SUBSCRIBERS)} onayli chat yuklendi",
              flush=True)


def _save_subscribers() -> None:
    try:
        tmp = SUBSCRIBERS_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps({"subscribers": DYNAMIC_SUBSCRIBERS},
                                  ensure_ascii=False, indent=1),
                       encoding="utf-8")
        tmp.replace(SUBSCRIBERS_FILE)
    except OSError as e:
        print(f"uyari: abone dosyasi yazilamadi: {e}", file=sys.stderr,
              flush=True)


def add_subscriber(chat_id: str, label: str = "") -> bool:
    """Chat'i kalici aboneler listesine ekler. True = yeni eklendi."""
    chat_id = str(chat_id).strip()
    if not chat_id:
        return False
    with _subs_lock:
        already = chat_id in TELEGRAM_SUBSCRIBERS
        DYNAMIC_SUBSCRIBERS[chat_id] = label
        if not already:
            TELEGRAM_SUBSCRIBERS.append(chat_id)
        PENDING_JOINS.pop(chat_id, None)
        _save_subscribers()
    return not already


def remove_subscriber(chat_id: str) -> bool:
    """Aboneligi kaldirir. env tabanindaki ve SAHIP chat'i KALDIRILAMAZ."""
    chat_id = str(chat_id).strip()
    with _subs_lock:
        if chat_id == str(TELEGRAM_CHAT_ID) or chat_id in TELEGRAM_ALLOWED:
            return False                     # env/sahip korumali
        removed = DYNAMIC_SUBSCRIBERS.pop(chat_id, None) is not None
        if chat_id in TELEGRAM_SUBSCRIBERS:
            TELEGRAM_SUBSCRIBERS.remove(chat_id)
            removed = True
        if removed:
            _save_subscribers()
    return removed


def _is_owner(chat_id: str) -> bool:
    """Yalnizca yapilandirilmis SAHIP chat'i yonetim komutu verebilir —
    onayli arkadaslar baska arkadas EKLEYEMEZ."""
    return str(chat_id) == str(TELEGRAM_CHAT_ID)


def _chat_allowed(chat_id: str) -> bool:
    return TELEGRAM_OPEN or chat_id in TELEGRAM_SUBSCRIBERS


_load_subscribers()

# JSON endpoint (server.py) icin son sinyaller — thread-guvenli halka tampon.
RECENT_MAXLEN = _env("RECENT_MAXLEN", 100)
RECENT_SIGNALS: deque[dict] = deque(maxlen=RECENT_MAXLEN)
_recent_lock = threading.Lock()
SIGNAL_SCHEMA_VERSION = 2
SIGNAL_CONFIG_VERSION = _env("SIGNAL_CONFIG_VERSION", "2026-07-24-v2")


def valid_signal_record(sig: object) -> bool:
    """Persisted/API tamponuna yalniz temel sinyal kontrati tasiyan kayit girsin."""
    if not isinstance(sig, dict):
        return False
    for key in ("strategy", "symbol", "direction", "bar_time"):
        if not isinstance(sig.get(key), str) or not sig[key].strip():
            return False
    try:
        datetime.fromisoformat(sig["bar_time"].replace("Z", "+00:00"))
        price = float(sig["price"])
        horizon = float(sig["horizon_hours"])
    except (KeyError, TypeError, ValueError, OverflowError):
        return False
    return math.isfinite(price) and price > 0 and \
        math.isfinite(horizon) and horizon > 0


# Piyasa arsivi: her saat evrenin OI + bazis + fiyat fotografi. Amac gelecek
# arastirma: Binance OI gecmisi ~30 gunle sinirli oldugu icin OI-tabanli
# hipotezler (REPORT Ek C: S8) test EDILEMIYORDU — kendi arsivimiz 3-6 ayda
# bunu test edilebilir yapar. Kapatmak: ARCHIVE_MARKET_DATA=false
ARCHIVE_MARKET_DATA = _env("ARCHIVE_MARKET_DATA", True,
                           cast=lambda v: str(v).strip().lower()
                           in ("1", "true", "yes", "on"))
LAST_SPOT_CLOSE: dict[str, float] = {}   # scan_symbol doldurur (arsiv/pano icin)
LAST_SPOT_AT: dict[str, float] = {}      # son mumun gercek kapanis epoch'u
LAST_PERP_PRICE: dict[str, float] = {}   # archive ticker snapshot'i
LAST_PERP_AT: dict[str, float] = {}      # futures ticker alinma epoch'u
PRICE_STALE_AFTER_MINUTES = _env(
    "PRICE_STALE_AFTER_MINUTES", max(15.0, SCAN_INTERVAL_MINUTES * 3.0))
# Canli karne icin yalnizca tek, acik bir round-trip maliyet varsayimi. Bu
# sinyal uretimini/bildirim politikasini ETKILEMEZ; sadece raporlanan net
# performanstan dusulur. S2 funding maliyeti ayrica modellenmez.
LIVE_ROUND_TRIP_COST_BPS = _env("LIVE_ROUND_TRIP_COST_BPS", 12.0)

# S3 icin ileriye donuk GOZLEM etiketi: son kapanmis BTC gunluk mumu 200 gunluk
# SMA'nin ustunde mi? Etiket sinyali FILTRELEMEZ ve guven/push kararina girmez;
# yeterli canli ornek birikince rejim hipotezini yeniden test etmeyi saglar.
MARKET_REGIME_REFRESH_HOURS = _env("MARKET_REGIME_REFRESH_HOURS", 6.0)
MARKET_REGIME = {
    "label": "UNKNOWN",
    "source": "btc_1d_close_vs_sma200_shadow",
    "as_of": None,
    "btc_close": None,
    "sma200": None,
    "last_error": None,
}
_market_regime_lock = threading.Lock()
_last_market_regime_refresh = 0.0
_last_archive_hour: str | None = None
ARCHIVE_DIR = Path(_env("ARCHIVE_DIR", str(Path(__file__).parent))).expanduser()
RESEARCH_MONITOR_STATE_FILE = Path(__file__).parent / _env(
    "RESEARCH_MONITOR_STATE_FILE", ".research_monitor_state.json")
# Birikimli Forward-OI hedef/stop matrisi ayda bir ayrı bir süreçte yenilenir.
# Bu yalnız araştırma raporudur: canlı sinyal, eşik, güven veya push kapısını
# değiştirmez. İlk çalışma etkinleştirmeden INTERVAL_DAYS sonra yapılır.
FORWARD_OI_30D_REPORT_ENABLED = _env(
    "FORWARD_OI_30D_REPORT_ENABLED", True, cast=_flag)
FORWARD_OI_REPORT_INTERVAL_DAYS = max(
    1, _env("FORWARD_OI_REPORT_INTERVAL_DAYS", 30, cast=int))
FORWARD_OI_REPORT_WORKERS = max(
    1, min(12, _env("FORWARD_OI_REPORT_WORKERS", 4, cast=int)))
FORWARD_OI_REPORT_STATE_FILE = Path(__file__).parent / _env(
    "FORWARD_OI_REPORT_STATE_FILE", ".forward_oi_report_state.json")
FORWARD_OI_5M_CACHE_DIR = Path(_env(
    "FORWARD_OI_5M_CACHE_DIR",
    str(Path(__file__).parent / "research" / "data" / "forward_oi_5m"),
)).expanduser()
_archive_worker_lock = threading.Lock()
ARCHIVE_WORKER_ACTIVE = False
ARCHIVE_WORKER_LAST_ERROR: str | None = None
SHADOW_STATE_FILE = Path(__file__).parent / _env(
    "SHADOW_STATE_FILE", ".experiment_state.json")
_shadow_worker_lock = threading.Lock()
SHADOW_WORKER_ACTIVE = False
SHADOW_WORKER_LAST_ERROR: str | None = None

# Gerceklesen USD-M force-order snapshot'lari Binance tarafinda geriye donuk
# oynatilamaz. Bu nedenle surekli modda ayri WebSocket thread'i tum piyasayi
# ileriye dogru kaydeder. Akis "tam tape" degildir: sembol basina 1000 ms'deki
# son likidasyon snapshot'ini verir. Strateji/sinyal kararlarinda KULLANILMAZ.
ARCHIVE_FORCE_ORDERS = _env("ARCHIVE_FORCE_ORDERS", True, cast=_flag)
FORCE_ORDER_STREAM_URL = _env(
    "FORCE_ORDER_STREAM_URL", DEFAULT_FORCE_ORDER_STREAM_URL)
if FORCE_ORDER_STREAM_URL.rstrip("/") == \
        "wss://fstream.binance.com/ws/!forceOrder@arr":
    # Binance legacy yolu 2026-04-23'te kapattı. Eski .env override'i sessiz
    # heartbeat üretip sıfır olay bırakmasın; bilinen eski değeri güvenle taşı.
    FORCE_ORDER_STREAM_URL = DEFAULT_FORCE_ORDER_STREAM_URL
_force_order_archive_worker: ForceOrderArchiveWorker | None = None
_force_order_archive_lock = threading.Lock()


def start_force_order_archive() -> bool:
    """Non-replayable liquidation stream'ini tek, izole worker'da baslat."""
    global _force_order_archive_worker
    if not ARCHIVE_FORCE_ORDERS:
        return False
    with _force_order_archive_lock:
        if _force_order_archive_worker is None:
            _force_order_archive_worker = ForceOrderArchiveWorker(
                ARCHIVE_DIR, stream_url=FORCE_ORDER_STREAM_URL)
        return _force_order_archive_worker.start()


def force_order_archive_status() -> dict:
    if not ARCHIVE_FORCE_ORDERS:
        return {"enabled": False, "active": False, "connected": False}
    if _force_order_archive_worker is None:
        return {"enabled": True, "active": False, "connected": False,
                "last_error": None}
    return _force_order_archive_worker.snapshot()


def archive_market_state() -> None:
    """Saatte bir piyasa-baglami fotografi kaydet.

    OI/fiyat/bazisa ek olarak son 5m genel hesap long-short orani, taker
    buy-sell akisi ve mark/funding goruntusu tutulur. Bunlar salt arastirma
    verisidir; strateji kosullarina veya bildirim kararina girmez. Basarisizlik
    tarama dongusunu ASLA aksatmamalidir.
    """
    global _last_archive_hour, ARCHIVE_WORKER_LAST_ERROR
    if not ARCHIVE_MARKET_DATA:
        return
    now = datetime.now(timezone.utc)
    hour_key = now.strftime("%Y-%m-%dT%H")
    if _last_archive_hour == hour_key:
        return

    def optional_float(value):
        try:
            result = float(value)
            return result if math.isfinite(result) else None
        except (TypeError, ValueError, OverflowError):
            return None

    def latest_metric(path: str, symbol: str) -> dict:
        response = _futures_get(path, params={
            "symbol": symbol, "period": "5m", "limit": 1,
        })
        payload = response.json()
        return payload[-1] if isinstance(payload, list) and payload else {}

    try:
        r = _futures_get("/fapi/v1/ticker/price")
        perp_px = {}
        for t in r.json():
            try:
                perp_px[t["symbol"]] = float(t["price"])
            except (TypeError, ValueError, KeyError):
                continue
    except requests.RequestException as e:
        ARCHIVE_WORKER_LAST_ERROR = f"{type(e).__name__}: {e}"
        print(f"uyari: arsiv perp fiyatlari alinamadi: {e}",
              file=sys.stderr, flush=True)
        return

    # Tek toplu istek: mark/index fiyati, funding goruntusu ve sonraki funding
    # zamani. Hata olursa diger arsiv alanlari yine yazilir.
    premium_by_symbol: dict[str, dict] = {}
    try:
        payload = _futures_get("/fapi/v1/premiumIndex").json()
        if isinstance(payload, list):
            premium_by_symbol = {
                str(item.get("symbol")): item for item in payload
                if isinstance(item, dict) and item.get("symbol")
            }
    except requests.RequestException:
        pass
    lines = []
    for sym in list(SYMBOLS):
        perp = perp_symbol(sym)
        oi = None
        oi_at = None
        try:
            r = _futures_get(
                "/fapi/v1/openInterest", params={"symbol": perp})
            oi_payload = r.json()
            oi = optional_float(oi_payload.get("openInterest"))
            oi_at = oi_payload.get("time")
        except (MarketRateLimitError, MarketTransientError) as e:
            ARCHIVE_WORKER_LAST_ERROR = f"{type(e).__name__}: {e}"
            print("uyari: piyasa arsivi ortak API hatasi nedeniyle erken kesildi",
                  file=sys.stderr, flush=True)
            return
        except (requests.RequestException, TypeError, ValueError):
            pass

        global_ls: dict = {}
        taker_flow: dict = {}
        try:
            global_ls = latest_metric(
                "/futures/data/globalLongShortAccountRatio", perp)
            taker_flow = latest_metric(
                "/futures/data/takerlongshortRatio", perp)
        except (MarketRateLimitError, MarketTransientError) as e:
            ARCHIVE_WORKER_LAST_ERROR = f"{type(e).__name__}: {e}"
            print("uyari: piyasa arsivi oran API hatasi nedeniyle erken kesildi",
                  file=sys.stderr, flush=True)
            return
        except (requests.RequestException, TypeError, ValueError):
            # Sembol-bazli eksik alan tum saatlik fotografi kaybettirmesin.
            pass

        spot_at = LAST_SPOT_AT.get(sym)
        spot_age_s = (max(0.0, time.time() - spot_at)
                      if spot_at is not None else None)
        spot_fresh = (spot_age_s is not None
                      and spot_age_s <= PRICE_STALE_AFTER_MINUTES * 60)
        spot = LAST_SPOT_CLOSE.get(sym) if spot_fresh else None
        px = perp_px.get(perp)
        if px is not None:
            LAST_PERP_PRICE[sym] = px
            LAST_PERP_AT[sym] = time.time()
        scale = 1000.0 if perp.startswith("1000") and not \
            sym.startswith("1000") else 1.0
        basis = (round(px / (spot * scale) - 1, 6)
                 if spot and px and spot > 0 else None)
        premium = premium_by_symbol.get(perp, {})
        lines.append(json.dumps(
            {"schema_version": "market-context-v2",
             "source": "binance_public_market_data",
             "t": now.isoformat(timespec="minutes"), "sym": sym,
             "perp_sym": perp,
             "spot": spot, "spot_at": (datetime.fromtimestamp(
                 spot_at, tz=timezone.utc).isoformat() if spot_at else None),
             "spot_age_s": (round(spot_age_s, 1)
                             if spot_age_s is not None else None),
             "perp_px": px, "basis": basis, "oi": oi, "oi_at": oi_at,
             # Hesap oranidir; pozisyon buyuklugu/notional orani DEGILDIR.
             "global_ls_ratio": optional_float(global_ls.get("longShortRatio")),
             "global_long_account": optional_float(global_ls.get("longAccount")),
             "global_short_account": optional_float(global_ls.get("shortAccount")),
             "global_ls_at": global_ls.get("timestamp"),
             "taker_buy_sell_ratio": optional_float(
                 taker_flow.get("buySellRatio")),
             "taker_buy_vol": optional_float(taker_flow.get("buyVol")),
             "taker_sell_vol": optional_float(taker_flow.get("sellVol")),
             "taker_at": taker_flow.get("timestamp"),
             "mark_px": optional_float(premium.get("markPrice")),
             "index_px": optional_float(premium.get("indexPrice")),
             "funding_rate_snapshot": optional_float(
                 premium.get("lastFundingRate")),
             "next_funding_at": premium.get("nextFundingTime"),
             "premium_at": premium.get("time")},
            ensure_ascii=False))
        time.sleep(0.1)
    try:
        path = ARCHIVE_DIR / f"market_archive_{now.strftime('%Y-%m')}.jsonl"
        with open(path, "a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        _last_archive_hour = hour_key
        ARCHIVE_WORKER_LAST_ERROR = None
        print(f"piyasa arsivi: {len(lines)} sembol kaydedildi", flush=True)
    except OSError as e:
        ARCHIVE_WORKER_LAST_ERROR = f"{type(e).__name__}: {e}"
        print(f"uyari: arsiv yazilamadi: {e}", file=sys.stderr, flush=True)


def _start_archive_worker() -> bool:
    """Yavas OI arsivini ana tarama/health heartbeat'inden ayir."""
    global ARCHIVE_WORKER_ACTIVE
    if not ARCHIVE_MARKET_DATA:
        return False
    if not _archive_worker_lock.acquire(blocking=False):
        return False
    ARCHIVE_WORKER_ACTIVE = True

    def work() -> None:
        global ARCHIVE_WORKER_ACTIVE, ARCHIVE_WORKER_LAST_ERROR
        try:
            archive_market_state()
        except Exception as e:
            ARCHIVE_WORKER_LAST_ERROR = f"{type(e).__name__}: {e}"
            print(f"uyari: arsiv iscisinde beklenmeyen hata: {e}",
                  file=sys.stderr, flush=True)
            traceback.print_exc(file=sys.stderr)
        finally:
            ARCHIVE_WORKER_ACTIVE = False
            _archive_worker_lock.release()

    threading.Thread(target=work, name="market-archive", daemon=True).start()
    return True


def run_shadow_experiments() -> int:
    """G1/DL1'i ana taramadan izole çalıştır; hata çekirdeği bozmasın."""
    global SHADOW_WORKER_LAST_ERROR
    if not SHADOW_EXPERIMENTS_ENABLED:
        return 0
    signals: list[dict] = []
    errors = []
    try:
        signals.extend(scan_shadow_gainers(
            _futures_get, SHADOW_STATE_FILE, ARCHIVE_DIR))
    except Exception as e:
        errors.append(f"G1 {type(e).__name__}: {_redact(str(e))}")
    try:
        signals.extend(poll_shadow_delists(
            requests.get, _spot_get, SHADOW_STATE_FILE, ARCHIVE_DIR,
            poll_minutes=SHADOW_DELIST_POLL_MINUTES))
    except Exception as e:
        errors.append(f"DL1 {type(e).__name__}: {_redact(str(e))}")
    signals.sort(key=lambda sig: (sig.get("strategy", ""),
                                  sig.get("symbol", "")))
    for index, sig in enumerate(signals):
        sig["push_policy_enabled"] = SHADOW_PUSH_ENABLED
        notify(sig, push=(SHADOW_PUSH_ENABLED and
                          index < SHADOW_MAX_PUSH_PER_RUN))
    if errors:
        SHADOW_WORKER_LAST_ERROR = " | ".join(errors)[:500]
        print(f"uyari: golge deney: {SHADOW_WORKER_LAST_ERROR}",
              file=sys.stderr, flush=True)
    else:
        SHADOW_WORKER_LAST_ERROR = None
    if signals:
        print(f"golge deney: {len(signals)} yeni olay (G1/DL1)", flush=True)
    return len(signals)


def _start_shadow_worker() -> bool:
    """Ağır tüm-perp/delist gözlemini ayrı thread'de çalıştır."""
    global SHADOW_WORKER_ACTIVE
    if not SHADOW_EXPERIMENTS_ENABLED:
        return False
    if not _shadow_worker_lock.acquire(blocking=False):
        return False
    SHADOW_WORKER_ACTIVE = True

    def work() -> None:
        global SHADOW_WORKER_ACTIVE, SHADOW_WORKER_LAST_ERROR
        try:
            run_shadow_experiments()
        except Exception as e:
            SHADOW_WORKER_LAST_ERROR = f"{type(e).__name__}: {_redact(str(e))}"
            print(f"uyari: golge deney iscisinde hata: {SHADOW_WORKER_LAST_ERROR}",
                  file=sys.stderr, flush=True)
        finally:
            SHADOW_WORKER_ACTIVE = False
            _shadow_worker_lock.release()

    threading.Thread(target=work, name="shadow-experiments", daemon=True).start()
    return True


# Servis saglik durumu (server.py /health endpoint'i okur).
STARTED_AT = datetime.now(timezone.utc).isoformat()
LAST_SCAN_AT: str | None = None
LAST_SCAN_STARTED_AT: str | None = None
LAST_SCAN_FINISHED_AT: str | None = None
LAST_SCAN_SUCCESS_AT: str | None = None
LAST_SCAN_FAILURE_AT: str | None = None
LAST_LOOP_HEARTBEAT_AT: str | None = None
LAST_LOOP_ERROR: str | None = None
SCAN_IN_PROGRESS = False
INSTANCE_LOCK_HELD = False
LAST_SCAN_COUNT = 0
SCANS_COMPLETED = 0
LAST_SCAN_ERRORS = 0                 # son taramada kac sembol hata verdi
LAST_SCAN_ATTEMPTED = 0
LAST_SCAN_SUCCEEDED_SYMBOLS = 0
LAST_SCAN_ERROR_RATIO = 0.0
CONSECUTIVE_SCAN_FAILURES = 0
ERROR_SAMPLES: deque[str] = deque(maxlen=5)   # son hata mesajlari (teshis)
UNIVERSE_LAST_ERROR: str | None = None

# --------------------------------------------------------------------------
# gostergeler
# --------------------------------------------------------------------------

def calc_rsi(closes: list[float], period: int = RSI_PERIOD) -> list[float]:
    """Wilder RSI serisi (ilk `period` eleman NaN)."""
    n = len(closes)
    rsi = [math.nan] * n
    if n <= period:
        return rsi
    gains = losses = 0.0
    for i in range(1, period + 1):
        d = closes[i] - closes[i - 1]
        gains += max(d, 0.0)
        losses += max(-d, 0.0)
    avg_g, avg_l = gains / period, losses / period
    rsi[period] = 100.0 if avg_l == 0 else 100 - 100 / (1 + avg_g / avg_l)
    for i in range(period + 1, n):
        d = closes[i] - closes[i - 1]
        avg_g = (avg_g * (period - 1) + max(d, 0.0)) / period
        avg_l = (avg_l * (period - 1) + max(-d, 0.0)) / period
        rsi[i] = 100.0 if avg_l == 0 else 100 - 100 / (1 + avg_g / avg_l)
    return rsi


def calc_volume_zscore(volumes: list[float], window: int = VOLUME_ZSCORE_WINDOW) -> list[float]:
    """LOG-hacim Z-skoru serisi. Ham hacim yerine log1p(hacim) kullanilir:
    saatlik hacim asiri kalin kuyruklu; ham z=3 'anomali' degildi (arastirmada
    ayda sembol basina ~10 sinyal ve zayif edge uretti)."""
    logs = [math.log1p(v) for v in volumes]
    n = len(logs)
    z = [math.nan] * n
    half = window // 2
    for i in range(n):
        lo = max(0, i - window + 1)
        w = logs[lo:i + 1]
        if len(w) < half:
            continue
        mu = sum(w) / len(w)
        squared_diffs = [(x - mu) ** 2 for x in w]
        var = (sum(squared_diffs) / (len(w) - 1)
               if len(w) > 1 else 0.0)
        sd = math.sqrt(var)
        if sd > 0:
            z[i] = (logs[i] - mu) / sd
    return z


# --------------------------------------------------------------------------
# referans seviyeleri (mekanik; tavsiye DEGIL)
# --------------------------------------------------------------------------
# 24 aylik backtest'in (2024-07 -> 2026-06, research/REPORT.md) dogrulanmis
# ufuktaki HAM getiri dagilimlari. Onemli durustluk notu: backtest'te tek
# dogrulanan cikis kurali ZAMAN cikisidir (ufuk sonunda kapat). Fiyat-yolu
# hedef/stop dokunmalari Ek B2'de test edildi, fakat bracket cikislari zaman
# cikisini istikrarli bicimde yenemedi. q10/q90 sadece tarihsel dagilimin uc
# yuzdelik dilimleri — "buradan kes/su fiyattan al" talimati degildir.
# "bracket": Ek B2'nin (results/bracket_analysis_console.txt, all-sample, 5m yol
# cozunurlugu, 10bp RT ucret) KUCUK-HEDEF olcumu. "Kucuk kar hedefiyle daha cok
# islem" fikri tam olarak burada olculdu: kucuk hedef ISABETI yukseltir
# (+1%'e dokunma %87) ama beklenen NET getiriyi yukseltmez, cunku ayni
# donemde -1%'e dokunma da %84'tur. Bildirimlerde gosterilir ki karar aninda
# gorulsun.
STRATEGY_STATS = {
    "S1": {"h": 24, "med": 0.93, "q10": -4.49, "q90": 8.83, "wr": 62, "n": 316,
           "touch": ((1, 87), (2, 71), (3, 62)), "stopt": ((2, 69), (5, 37)),
           "bracket": "+1%/-1% E[net] -9bp · en iyi bracket (+2/-3) +3bp · "
                      "zaman cikisi ~+150bp"},
    "S2": {"h": 72, "med": 0.24, "q10": -9.09, "q90": 12.73, "wr": 52, "n": 339,
           "touch": ((1, 88), (2, 76), (3, 65)), "stopt": ((2, 74), (5, 47)),
           "bracket": "+1%/-1% E[net] +5bp · train'in en iyisi TESTTE -61bp"},
    "S3": {"h": 4,  "med": 0.16, "q10": -2.84, "q90": 4.16, "wr": 53, "n": 1015,
           "touch": ((1, 67), (2, 42), (3, 27)), "stopt": ((2, 33), (5, 6)),
           "bracket": "+1%/-1% E[net] +0bp · en iyisi GENIS (+5/-5) +26bp, "
                      "dar hedef degil"},
}
# Canli karne karsilastirmasi icin deployment'la eslesen cekirdek-30 TEST
# kohortu. Referans fiyat dagilimlari yukaridaki 24-ay all-sample tablosundan
# gelir; performans kartlari ise secim sonrasi test kohortunu kullanir.
STRATEGY_TEST_STATS = {
    "S1+S4": {"h": 24, "med": 0.86, "wr": 64, "n": 50,
              "scope": "core30 test 2026H1"},
    "S1": {"h": 24, "med": 0.67, "q10": -3.58, "q90": 8.94,
           "wr": 59, "n": 111, "scope": "core30 test 2026H1"},
    "S2": {"h": 72, "med": -0.36, "q10": -9.36, "q90": 8.55,
           "wr": 47, "n": 111, "scope": "core30 test 2026H1"},
    "S3": {"h": 4, "med": 0.00, "wr": 49, "n": 246,
           "scope": "core30 test 2026H1; second-look"},
}
# Guven kademeleri (arastirma kanitina gore) + bildirim esigi:
# COK YUKSEK: S1+S4 (test p=0.006, 72h WR %66) | YUKSEK: S1 (p=0.006, 4/4
# rejim) | ORTA: S3 (4h p<0.001 ama test'e 2. bakis serhi) | DUSUK: S2
# (p=0.08 marjinal + sembol yogunlasmasi). NOTIFY_MIN_CONFIDENCE altindaki
# sinyaller LOGLANIR ve API/tamponda gorunur ama Telegram'a GITMEZ.
CONF_RANK = {"GOZLEM": -1, "DUSUK": 0, "ORTA": 1, "YUKSEK": 2, "COK YUKSEK": 3}
STRATEGY_CONF = {
    "S1+S4": ("COK YUKSEK", "test p=0.006, 72h WR %66; en guclu sinyal"),
    "S1":    ("YUKSEK", "olay p=0.006; gun-kumesi p=0.080, kanit sinirda"),
    "S3":    ("ORTA", "test 4h p<0.001; nihai secimde 2. bakis serhi"),
    "S2":    ("DUSUK", "test p=0.08 marjinal; sinyaller ~5 sembolde yogun"),
    # Gozlem kanali: kademe yok cunku bu coinlerde HIC backtest yapilmadi.
    # CONF_RANK -1 -> her NOTIFY_MIN_CONFIDENCE degerinin altinda kalir;
    # push'u ayrica OBSERVE_PUSH kontrol eder (bkz. _delivery_record).
    "S5": ("GOZLEM", "dinamik evren S1+S4 — DOGRULANMAMIS coin, backtest yok"),
    "S6": ("GOZLEM", "dinamik evren S1 — DOGRULANMAMIS coin, backtest yok"),
    "G1": ("GOZLEM", "gainer+OI+short kalabaligi; tarihsel train kapisi RED"),
    "DL1": ("GOZLEM", "delist olay arsivi; PRE bekletme RED, POST henuz testsiz"),
}
NOTIFY_MIN_CONFIDENCE = _env("NOTIFY_MIN_CONFIDENCE", "ORTA").strip().upper()

# S2'nin kaniti DUSUK kalir; bu anahtar guven kademesini veya strateji
# matematigini degistirmeden yalniz ileri olcum icin Telegram push'una izin
# verir. Boylece tum bildirim esigini DUSUK'e indirip diger zayif kanallari
# istemeden acmayiz. Mesajda acikca ARASTIRMA olarak etiketlenir.
S2_RESEARCH_PUSH = _env("S2_RESEARCH_PUSH", True, cast=_flag)

# Bir stratejiyi TAMAMEN kapatmak icin (taranmaz, loglanmaz, API cagrisi da
# yapilmaz): DISABLED_STRATEGIES=S2 gibi virgullu liste. NOT: varsayilan bos.
# S2_RESEARCH_PUSH=false yapilirsa S2 sessiz-kayitta kalir; tamamen kapatmak
# canli performans kanitinin birikmesini de durdurur.
DISABLED_STRATEGIES = {s.strip().upper()
                       for s in _env("DISABLED_STRATEGIES", "").split(",")
                       if s.strip()}


def signal_confidence(strategy: str) -> tuple[str, str]:
    return STRATEGY_CONF.get(strategy,
                             STRATEGY_CONF.get(strategy.split("+")[0],
                                               ("YUKSEK", "")))

# "touch"/"stopt": 5m yol analiziyle olculen tarihsel DOKUNMA olasiliklari
# (research/results/bracket_analysis_console.txt): ufuk icinde +x% hedefe /
# -y% seviyeye en az bir kez dokunma yuzdesi. Onemli bulgu: hedef/stop emirleri
# (bracket) backtest'te zaman cikisini YENEMEDI (S1'de belirgin zarar) — bu
# olasiliklar bilgi amaclidir, bracket onerisi degildir.


def _sig6(x: float) -> float:
    """Fiyati 6 anlamli haneye yuvarla (PEPE gibi cok kucuk fiyatlar icin)."""
    return float(f"{x:.6g}")


def _fmt_price(x) -> str:
    """Fiyati OKUNUR bicimde yazar — bilimsel gosterim ASLA kullanilmaz.
    (2.79e-06 yerine 0.00000279; kullanicilar e-06'yi 'hata' saniyordu.)"""
    if x is None:
        return "?"
    try:
        x = float(x)
    except (TypeError, ValueError):
        return str(x)
    if x >= 1:
        return f"{x:.6g}"
    return f"{x:.10f}".rstrip("0").rstrip(".") or "0"


def realized_sigma1h(closes: list[float], window: int = 168) -> float | None:
    """Son `window` saatlik log-getirinin std'si (arastirmadaki vol tanimi)."""
    lo = max(1, len(closes) - window)
    rets = [math.log(closes[i] / closes[i - 1])
            for i in range(lo, len(closes)) if closes[i - 1] > 0]
    if len(rets) < 30:
        return None
    mu = sum(rets) / len(rets)
    var = sum((r - mu) ** 2 for r in rets) / (len(rets) - 1)
    return math.sqrt(var)


def build_ref_levels(strategy: str, price: float,
                     sigma1h: float | None) -> dict | None:
    """Sinyal icin mekanik referans paketi: giris referansi, zaman cikisi,
    tarihsel dagilimin fiyat karsiliklari, tipik dalgalanma bandi."""
    base_strategy = strategy.split("+")[0]
    exact = STRATEGY_STATS.get(strategy)
    st = exact or STRATEGY_STATS.get(base_strategy)
    if st is None:
        return None
    ref = {
        "entry_ref": _sig6(price),
        "time_exit_hours": st["h"],
        "hist_n": st["n"], "hist_winrate_pct": st["wr"],
        "hist_median_pct": st["med"],
        "hist_q10_pct": st["q10"], "hist_q90_pct": st["q90"],
        "median_price": _sig6(price * (1 + st["med"] / 100)),
        "q10_price": _sig6(price * (1 + st["q10"] / 100)),
        "q90_price": _sig6(price * (1 + st["q90"] / 100)),
        "touch": st.get("touch"), "stopt": st.get("stopt"),
        "bracket": st.get("bracket"),
        "stats_scope": (
            f"{strategy} cekirdek-30, 24 ay all-sample"
            if exact is not None else
            f"{base_strategy} ailesi cekirdek-30, 24 ay all-sample "
            f"(bu strateji icin proxy)"),
    }
    if sigma1h is not None:
        ref["sigma_h_pct"] = round(sigma1h * math.sqrt(st["h"]) * 100, 2)
    return ref


def bullish_divergence(closes, lows, rsi, i: int) -> bool:
    """Bar i icin: fiyat onceki dipten dusuk AMA RSI o dipten yuksek mi?
    Onceki dip: son DIVERGENCE_GAP bar haric tutulup ondan onceki
    DIVERGENCE_LOOKBACK barin min low'u ([i-gap-lookback+1, i-gap])."""
    hi = i - DIVERGENCE_GAP
    lo = hi - DIVERGENCE_LOOKBACK + 1
    if lo < 0 or hi <= lo:
        return False
    window = lows[lo:hi + 1]
    pmin = min(window)
    pidx = lo + window.index(pmin)
    return (lows[i] < pmin and not math.isnan(rsi[pidx]) and rsi[i] > rsi[pidx])

# --------------------------------------------------------------------------
# veri cekme (halka acik uclar, anahtar gerekmez)
# --------------------------------------------------------------------------

def fetch_klines(symbol: str, limit: int = KLINE_LIMIT) -> list[dict]:
    """Kapanmis son barlar (Binance son barin acik halini dondurur -> atilir)."""
    r = _spot_get("/api/v3/klines",
                  {"symbol": symbol, "interval": "1h", "limit": limit})
    rows = r.json()[:-1]          # son (henuz kapanmamis) bari at
    return [{"open_time": k[0], "open": float(k[1]), "high": float(k[2]),
             "low": float(k[3]), "close": float(k[4]), "volume": float(k[5])}
            for k in rows]


def refresh_market_regime_if_due(force: bool = False) -> bool:
    """BTC 1d kapanis/SMA200 GOZLEM etiketini yeniler.

    Yalniz kapanmis gunluk mumlari kullanir; hata ana taramaya yayilmaz. Donen
    bool etiketin bu cagrida basariyla yenilenip yenilenmedigini belirtir.
    """
    global _last_market_regime_refresh
    now_s = time.time()
    with _market_regime_lock:
        if (not force and _last_market_regime_refresh
                and now_s - _last_market_regime_refresh
                < MARKET_REGIME_REFRESH_HOURS * 3600):
            return False
        # Ag hatasinda her sembolde/scan'de yeniden denememek icin deneme anini
        # cagridan once kaydet. Bir sonraki periyotta otomatik tekrar denenir.
        _last_market_regime_refresh = now_s
    try:
        raw = _spot_get("/api/v3/klines", {
            "symbol": "BTCUSDT", "interval": "1d", "limit": 201,
        }).json()
        now_ms = int(now_s * 1000)
        closed = [row for row in raw if len(row) > 6 and int(row[6]) < now_ms]
        if len(closed) < 200:
            raise ValueError(f"SMA200 icin yetersiz kapanmis gunluk mum: {len(closed)}")
        closes = [float(row[4]) for row in closed[-200:]]
        latest = closes[-1]
        sma200 = sum(closes) / len(closes)
        as_of = datetime.fromtimestamp(
            int(closed[-1][6]) / 1000, tz=timezone.utc).isoformat()
        with _market_regime_lock:
            MARKET_REGIME.update({
                "label": "BULL" if latest > sma200 else "BEAR",
                "as_of": as_of,
                "btc_close": round(latest, 8),
                "sma200": round(sma200, 8),
                "last_error": None,
            })
        return True
    except Exception as e:
        # Bu salt meta-veri kanali oldugu icin piyasa taramasini durduramaz.
        with _market_regime_lock:
            MARKET_REGIME["last_error"] = f"{type(e).__name__}: {_redact(str(e))}"
        print(f"uyari: piyasa rejimi etiketi yenilenemedi: {_redact(str(e))}",
              file=sys.stderr, flush=True)
        return False


def market_regime_snapshot() -> dict:
    with _market_regime_lock:
        return dict(MARKET_REGIME)


def fetch_funding(symbol: str, limit: int = 3) -> list[dict]:
    """Son settled funding kayitlari (eskiden yeniye)."""
    r = _futures_get(
        "/fapi/v1/fundingRate", {"symbol": symbol, "limit": limit})
    return [{"time": int(x["fundingTime"]), "rate": float(x["fundingRate"])}
            for x in sorted(r.json(), key=lambda x: x["fundingTime"])]


def fetch_futures_price(symbol: str) -> float:
    r = _futures_get("/fapi/v1/ticker/price", {"symbol": symbol})
    return float(r.json()["price"])


# spot sembolu -> perp sembolu eslemesi (dusuk fiyatli coinlerde 1000x kontrat).
# Otomatik evren modunda fetch_universe() doldurur; statik modda bilinen istisna.
PERP_MAP: dict[str, str] = {"PEPEUSDT": "1000PEPEUSDT"}
_last_universe_refresh = 0.0
_last_perp_map_refresh = 0.0
PERP_MAP_LAST_ERROR: str | None = None

# Sabit/pegli varliklar evren disi: fiyat dinamikleri kripto degil (stable, altin,
# wrapped) — S1/S3 varsayimlari bunlarda gecerli degil.
STABLE_OR_PEGGED = {
    "USDC", "FDUSD", "TUSD", "DAI", "USDP", "PYUSD", "BUSD", "AEUR", "EUR",
    "EURI", "USDE", "USD1", "BFUSD", "XUSD", "USDF", "PAXG", "XAUT",
    "WBTC", "WBETH",
}


def perp_symbol(spot: str) -> str:
    return PERP_MAP.get(spot, spot)


def _map_perp_symbols(spot_symbols: list[str] | set[str],
                      active_perps: set[str]) -> dict[str, str]:
    """Spot sembollerini exact veya sayisal-carpanli USD-M kontrata esle."""
    out: dict[str, str] = {}
    for spot in spot_symbols:
        if spot in active_perps:
            out[spot] = spot
            continue
        candidates = [
            perp for perp in active_perps
            if perp.endswith(spot)
            and perp[:-len(spot)].isdigit()
        ]
        if len(candidates) == 1:
            out[spot] = candidates[0]
    return out


def _active_perpetual_symbols() -> set[str]:
    r = _futures_get("/fapi/v1/exchangeInfo")
    return {
        s["symbol"] for s in r.json()["symbols"]
        if s.get("contractType") == "PERPETUAL"
        and s.get("status") == "TRADING"
        and s.get("quoteAsset") == "USDT"
    }


def refresh_perp_map_if_due(force: bool = False) -> None:
    """Statik evrende de 1000/1000000 kontrat eslemesini gunluk yenile."""
    global PERP_MAP, _last_perp_map_refresh, PERP_MAP_LAST_ERROR
    if (not force and time.time() - _last_perp_map_refresh
            < UNIVERSE_REFRESH_HOURS * 3600):
        return
    try:
        mapping = _map_perp_symbols(set(SYMBOLS), _active_perpetual_symbols())
        PERP_MAP.update(mapping)
        _last_perp_map_refresh = time.time()
        PERP_MAP_LAST_ERROR = None
    except Exception as e:
        PERP_MAP_LAST_ERROR = (
            f"{datetime.now(timezone.utc).isoformat()} {type(e).__name__}: {e}")
        print(f"uyari: perp sembol eslemesi yenilenemedi; mevcut harita "
              f"kullaniliyor: {e}", file=sys.stderr, flush=True)


def fetch_universe() -> tuple[list[str], dict[str, str]]:
    """Likidite-filtreli evren: USDT spot cifti + aktif USDⓈ-M perp'i olan
    semboller; PERP 24h hacmine gore azalan sirali ilk N. Spot tarafina
    kucuk bir veri-kalitesi tabani uygulanir."""
    perps = _active_perpetual_symbols()
    r = _futures_get("/fapi/v1/ticker/24hr")
    perp_vol = {}
    for t in r.json():
        try:
            perp_vol[t["symbol"]] = float(t.get("quoteVolume") or 0.0)
        except (TypeError, ValueError, KeyError):
            continue
    r = _spot_get("/api/v3/ticker/24hr")
    rows = []
    for t in r.json():
        sym = t.get("symbol", "")
        if not sym.endswith("USDT") or sym[:-4] in STABLE_OR_PEGGED:
            continue
        try:
            spot_qv = float(t.get("quoteVolume") or 0.0)
        except (TypeError, ValueError):
            continue
        if spot_qv < SYMBOL_MIN_SPOT_VOLUME_M * 1e6:
            continue
        perp = _map_perp_symbols({sym}, perps).get(sym)
        if perp is None:
            continue
        pv = perp_vol.get(perp, 0.0)
        if pv < SYMBOL_MIN_PERP_VOLUME_M * 1e6:
            continue
        rows.append((pv, sym, perp))
    rows.sort(reverse=True)
    rows = rows[:SYMBOL_MAX_COUNT]
    if len(rows) < 5:      # API bozuk cevap verdiyse eski listeyi koru
        raise RuntimeError(f"evren suphe verecek kadar kucuk: {len(rows)}")
    return [s for _, s, _ in rows], {s: p for _, s, p in rows}


def refresh_universe_if_due(force: bool = False) -> None:
    """SYMBOL_AUTO aciksa evreni periyodik yeniler; hata olursa eski liste kalir."""
    global SYMBOLS, PERP_MAP, _last_universe_refresh
    if not SYMBOL_AUTO:
        return
    if not force and time.time() - _last_universe_refresh < UNIVERSE_REFRESH_HOURS * 3600:
        return
    try:
        syms, pmap = fetch_universe()
        added = len(set(syms) - set(SYMBOLS))
        removed = len(set(SYMBOLS) - set(syms))
        SYMBOLS, PERP_MAP = syms, pmap
        _last_universe_refresh = time.time()
        print(f"evren guncellendi: {len(syms)} sembol "
              f"(perp>={SYMBOL_MIN_PERP_VOLUME_M:g}M$, "
              f"spot>={SYMBOL_MIN_SPOT_VOLUME_M:g}M$, +{added}/-{removed})",
              flush=True)
    except Exception as e:
        global UNIVERSE_LAST_ERROR
        UNIVERSE_LAST_ERROR = f"{datetime.now(timezone.utc).isoformat()} {e}"
        print(f"uyari: evren guncellenemedi, mevcut {len(SYMBOLS)} sembol "
              f"kullanilmaya devam: {e}", file=sys.stderr, flush=True)


# --- gozlem evreni (dogrulanmamis; ayri kovada olculur) -------------------
OBSERVE_SYMBOLS: list[str] = []
_last_observe_refresh = 0.0
OBSERVE_LAST_ERROR: str | None = None


def fetch_observe_universe() -> tuple[list[str], dict[str, str]]:
    """Yapilandirilmis evrenin DISINDA kalan, perp 24h hacmine gore en likit
    ilk OBSERVE_TOP_N sembol. fetch_universe()'un likidite/veri-kalitesi
    filtrelerini aynen kullanir (spot cifti + aktif perp + hacim tabanlari);
    tek farki sonucu evren disiyla sinirlayip N ile kesmesi."""
    syms, pmap = fetch_universe()
    configured = set(SYMBOLS)
    picked = [s for s in syms if s not in configured]
    if OBSERVE_TOP_N > 0:
        picked = picked[:OBSERVE_TOP_N]
    return picked, {s: pmap[s] for s in picked if s in pmap}


def refresh_observe_universe_if_due(force: bool = False) -> None:
    """Gozlem evrenini periyodik yeniler. Hata olursa eski liste korunur ve
    ANA tarama etkilenmez — bu kanal her zaman en iyi cabadir."""
    global OBSERVE_SYMBOLS, _last_observe_refresh, OBSERVE_LAST_ERROR
    if not OBSERVE_ENABLED:
        return
    if (not force and time.time() - _last_observe_refresh
            < UNIVERSE_REFRESH_HOURS * 3600):
        return
    try:
        syms, pmap = fetch_observe_universe()
        PERP_MAP.update(pmap)
        added = len(set(syms) - set(OBSERVE_SYMBOLS))
        OBSERVE_SYMBOLS = syms
        _last_observe_refresh = time.time()
        OBSERVE_LAST_ERROR = None
        print(f"gozlem evreni: {len(syms)} dogrulanmamis sembol "
              f"(+{added}) — AYRI kovada olculur", flush=True)
    except Exception as e:
        OBSERVE_LAST_ERROR = (
            f"{datetime.now(timezone.utc).isoformat()} {type(e).__name__}: {e}")
        print(f"uyari: gozlem evreni yenilenemedi, mevcut "
              f"{len(OBSERVE_SYMBOLS)} sembol kalir: {e}",
              file=sys.stderr, flush=True)

# --------------------------------------------------------------------------
# tarama
# --------------------------------------------------------------------------

STATE_FILE = Path(__file__).parent / ".bot_state.json"


class ScanState:
    """Kenar-tetikleme + cooldown icin bellek: ayni kosul streak'i tek sinyal.
    Restart'ta kaybolmasin diye diske yazilir/yuklenir (save/load)."""

    def __init__(self):
        self.prev_cond: dict[tuple[str, str], bool] = {}
        self.last_fire: dict[tuple[str, str], float] = {}

    def save(self) -> None:
        try:
            data = {
                "prev_cond": {f"{k[0]}|{k[1]}": v
                              for k, v in self.prev_cond.items()},
                "last_fire": {f"{k[0]}|{k[1]}": v
                              for k, v in self.last_fire.items()},
                "recent": list(RECENT_SIGNALS),
                # Gozlem evrenini de tasi: --once modu (bulut, 5dk'da bir)
                # her calismada sifirdan baslar; kalici olmazsa her turda
                # fetch_universe() 3 AGIR cagri yapar (biri tum spot
                # sembollerin 24s ticker'i, agirlik 80) — gunde ~864 kez.
                "observe_symbols": list(OBSERVE_SYMBOLS),
                "observe_refreshed_at": _last_observe_refresh,
                # Listeyi hangi ayarla urettigimizi de tasi: ayar degisince
                # 24 saat beklemeden yenilensin (bkz. ScanState.load).
                "observe_top_n": OBSERVE_TOP_N,
            }
            tmp = STATE_FILE.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False),
                           encoding="utf-8")
            tmp.replace(STATE_FILE)          # atomik: yarim dosya kalmaz
        except OSError as e:
            print(f"uyari: durum kaydedilemedi: {e}", file=sys.stderr, flush=True)

    @classmethod
    def load(cls) -> "ScanState":
        global OBSERVE_SYMBOLS, _last_observe_refresh
        st = cls()
        if not STATE_FILE.exists():
            return st
        try:
            data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
            saved = data.get("observe_symbols")
            if isinstance(saved, list) and saved:
                OBSERVE_SYMBOLS = [str(s) for s in saved]
                try:
                    _last_observe_refresh = float(
                        data.get("observe_refreshed_at") or 0.0)
                except (TypeError, ValueError):
                    _last_observe_refresh = 0.0
                # Ayar degistiyse onbellek GECERSIZ: aksi halde OBSERVE_TOP_N'i
                # degistirmek 24 saat boyunca hicbir sey yapmaz ve kullanici
                # eski evrenle kaldigini fark etmez (2026-08-04'te yasandi).
                if data.get("observe_top_n") != OBSERVE_TOP_N:
                    print("gozlem evreni ayari degismis "
                          f"({data.get('observe_top_n')} -> {OBSERVE_TOP_N}); "
                          "liste yeniden kurulacak", flush=True)
                    _last_observe_refresh = 0.0
            for k, v in data.get("prev_cond", {}).items():
                a, _, b = k.partition("|")
                st.prev_cond[(a, b)] = bool(v)
            for k, v in data.get("last_fire", {}).items():
                a, _, b = k.partition("|")
                st.last_fire[(a, b)] = float(v)
            dropped = 0
            with _recent_lock:
                for sig in data.get("recent", []):
                    if valid_signal_record(sig):
                        RECENT_SIGNALS.append(sig)  # kayit sirasi: yeni->eski
                    else:
                        dropped += 1
            print(f"durum yuklendi: {len(st.prev_cond)} kosul, "
                   f"{len(st.last_fire)} cooldown, "
                   f"{len(RECENT_SIGNALS)} tamponlanmis sinyal"
                   + (f", {dropped} bozuk kayit atlandi" if dropped else ""),
                   flush=True)
        except (OSError, ValueError, KeyError) as e:
            print(f"uyari: durum dosyasi okunamadi, sifirdan: {e}",
                  file=sys.stderr, flush=True)
        return st

    def should_fire(self, strategy: str, symbol: str, cond: bool,
                    cooldown_hours: float, now_s: float) -> bool:
        key = (strategy, symbol)
        prev = self.prev_cond.get(key)
        self.prev_cond[key] = cond
        if not cond:
            return False
        if prev is None:          # ilk taramada streak ortasinda ates etme
            return False
        if prev:                  # kosul zaten dogruydu -> kenar degil
            return False
        last = self.last_fire.get(key, 0.0)
        if now_s - last < cooldown_hours * 3600:
            return False
        self.last_fire[key] = now_s
        return True


def scan_symbol(symbol: str, state: ScanState,
                snapshot: bool = False, observe: bool = False) -> list[dict]:
    """Bir sembolu tarar, sinyal listesini dondurur.

    snapshot=False (canli mod): kenar-tetikleme + cooldown uygulanir — sinyal
      SADECE kosul False->True gectiginde uretilir (bildirim spam'i olmasin).
    snapshot=True (--check modu): geciş aranmaz, o an AKTIF olan tum kosullar
      raporlanir. state'e dokunmaz. "Su an uygun kurulum var mi?" sorusu icin.
    observe=True (gozlem kanali): sembol DOGRULANMAMIS evrendendir. Yalniz S1
      ailesi hesaplanir (S2/S3 yeni coinlerde OOS basarisiz — Ek G), strateji
      adi "GOZLEM-" onekli uretilir ve backtest referans seviyeleri
      EKLENMEZ."""
    signals = []
    now_s = time.time()
    # Genis evren VE gozlem kanali: yalniz S1 ailesi (Ek G).
    extended = observe or symbol in EXTENDED_SET

    def include(strategy: str, cond: bool, cooldown: float) -> bool:
        if snapshot:
            return cond
        return state.should_fire(strategy, symbol, cond, cooldown, now_s)

    klines = fetch_klines(symbol)
    if len(klines) < max(DIVERGENCE_LOOKBACK + DIVERGENCE_GAP,
                         VOLUME_ZSCORE_WINDOW // 2) + RSI_PERIOD:
        return signals
    closes = [k["close"] for k in klines]
    lows = [k["low"] for k in klines]
    opens = [k["open"] for k in klines]
    vols = [k["volume"] for k in klines]
    i = len(klines) - 1                       # son KAPANMIS bar
    LAST_SPOT_CLOSE[symbol] = closes[i]       # saatlik piyasa arsivi icin
    # open_time + 1h: indirme zamani degil, fiyat gozleminin gercek zamani.
    LAST_SPOT_AT[symbol] = (klines[i]["open_time"] + 3_600_000) / 1000
    rsi = calc_rsi(closes)
    zs = calc_volume_zscore(vols)
    bar_ts = datetime.fromtimestamp(klines[i]["open_time"] / 1000, tz=timezone.utc)

    # ---- S1: oversold bullish divergence (long) ----
    s1_cond = ("S1" not in DISABLED_STRATEGIES
               and not math.isnan(rsi[i]) and rsi[i] <= RSI_OVERSOLD
               and bullish_divergence(closes, lows, rsi, i))
    if "S1" not in DISABLED_STRATEGIES and include("S1", s1_cond,
                                                   S1_COOLDOWN_HOURS):
        recent_spike = any(
            (not math.isnan(z)) and z >= VOLUME_ZSCORE_THRESHOLD
            for z in zs[max(0, i - CONFLUENCE_LOOKBACK_HOURS):i + 1])
        _base = "S1" + ("+S4" if recent_spike else "")
        signals.append({
            "strategy": OBSERVE_STRATEGY_NAMES[_base] if observe else _base,
            "symbol": symbol, "direction": "LONG",
            "signal_market": "spot", "performance_market": "spot",
            "strength": "STRONG" if recent_spike else "NORMAL",
            "bar_time": bar_ts.isoformat(),
            "price": closes[i], "rsi": round(rsi[i], 1),
            "note": ("oversold divergence + hacimli kapitulasyon (24h icinde "
                     "log-z>=%.1f)" % VOLUME_ZSCORE_THRESHOLD) if recent_spike
                    else "oversold bullish divergence",
            "horizon_hours": 24,
        })

    # ---- S3: hacim anomalisi, yukari-bar (long momentum) ----
    # Kenar-tetikleme yon gozetmeksizin hacim patlamasi uzerinde calisir
    # (arastirmada dogrulanan kompozisyon); yon filtresi SONRA uygulanir.
    s3_spike = (not math.isnan(zs[i]) and zs[i] >= VOLUME_ZSCORE_THRESHOLD)
    if (not extended and "S3" not in DISABLED_STRATEGIES
            and include("S3", s3_spike, S3_COOLDOWN_HOURS)
            and closes[i] > opens[i]):
        regime = market_regime_snapshot()
        signals.append({
            "strategy": "S3", "symbol": symbol, "direction": "LONG",
            "signal_market": "spot", "performance_market": "spot",
            "strength": "NORMAL", "bar_time": bar_ts.isoformat(),
            "price": closes[i], "volume_logz": round(zs[i], 2),
            "market_regime": regime.get("label", "UNKNOWN"),
            "market_regime_source": regime.get("source"),
            "market_regime_as_of": regime.get("as_of"),
            "note": "yukari-bar hacim patlamasi (momentum devami)",
            "horizon_hours": 4,
        })

    # ---- S2: funding squeeze (long) ----
    if extended or "S2" in DISABLED_STRATEGIES:
        fr = []                    # genis evrende S2 OOS basarisiz (Ek G) / kapali
    else:
        try:
            fr = fetch_funding(perp_symbol(symbol),
                               limit=FUNDING_PERSISTENCE + 1)
        except (MarketRateLimitError, MarketTransientError):
            raise
        except requests.RequestException:
            fr = []                            # perp yoksa/ulasilamazsa atla
    if len(fr) >= FUNDING_PERSISTENCE:
        thr = FUNDING_SQUEEZE_THRESHOLD_PCT / 100.0
        last_n = fr[-FUNDING_PERSISTENCE:]
        intervals = [
            (fr[j]["time"] - fr[j - 1]["time"]) / 3_600_000
            for j in range(1, len(fr))
            if fr[j]["time"] > fr[j - 1]["time"]
        ]
        funding_interval_h = (statistics.median(intervals)
                              if intervals else None)
        s2_cond = all(x["rate"] <= thr for x in last_n)
        if include("S2", s2_cond, S2_COOLDOWN_HOURS):
            contract = perp_symbol(symbol)
            multiplier = contract[:-len(symbol)] if contract.endswith(symbol) \
                else ""
            scale = float(multiplier) if multiplier.isdigit() else 1.0
            price_source = "futures_ticker"
            try:
                signal_price = fetch_futures_price(contract)
                LAST_PERP_PRICE[symbol] = signal_price
                LAST_PERP_AT[symbol] = time.time()
            except (MarketRateLimitError, MarketTransientError):
                raise
            except (requests.RequestException, TypeError, ValueError, KeyError):
                # Sinyali veri-kanali hatasiyla kaybetme; olceklenmis spot
                # yalnizca acikca etiketli gecici referanstir.
                signal_price = closes[i] * scale
                price_source = "spot_scaled_proxy"
            signals.append({
                "strategy": "S2", "symbol": symbol, "direction": "LONG",
                "signal_market": "um_perp", "performance_market": "um_perp",
                "performance_symbol": contract,
                "strength": "NORMAL",
                "bar_time": datetime.fromtimestamp(
                    last_n[-1]["time"] / 1000, tz=timezone.utc).isoformat(),
                "price": signal_price, "price_source": price_source,
                "spot_price_at_scan": closes[i],
                "funding_pct": [round(x["rate"] * 100, 4) for x in last_n],
                "funding_interval_hours": (round(funding_interval_h, 2)
                                           if funding_interval_h else None),
                "funding_window_hours": (
                    round(funding_interval_h * len(last_n), 2)
                    if funding_interval_h else None),
                "note": ("negatif funding yiginlanmasi (short squeeze adayi)"
                         + (f" — perp kontrati {contract}"
                            if contract != symbol else "")),
                "horizon_hours": 72,
            })

    if signals:
        sigma = realized_sigma1h(closes)
        for sig in signals:
            if observe:
                # Gozlem kanali: kademe yok, referans seviyesi YOK. Backtest
                # dagilimlari cekirdek-30'da olculdu; bu coinler icin
                # gosterilmesi yaniltici olurdu (Ek F dersi).
                sig["universe"] = "observe"
                sig["observe"] = True
                sig["confidence"], sig["confidence_note"] = \
                    signal_confidence(sig["strategy"])
                continue
            sig["universe"] = "extended59" if extended else "core30"
            conf, evid = signal_confidence(sig["strategy"])
            if extended and sig["strategy"].startswith("S1"):
                # Ek G kademeleri: genis evrende S1+S4 iki donemde saglam
                # (YUKSEK); sade S1 yalniz testte guclu (ORTA)
                if "+S4" in sig["strategy"]:
                    conf, evid = "YUKSEK", ("genis evren (Ek G): train+test "
                                            "her ikisinde saglam")
                else:
                    conf, evid = "ORTA", ("genis evren (Ek G): test +0.43 "
                                          "p<0.001, train notr")
            sig["confidence"] = conf
            sig["confidence_note"] = evid
            ref = build_ref_levels(sig["strategy"], sig["price"], sigma)
            if ref:
                if extended:
                    ref["stats_scope"] += "; extended evren icin proxy"
                try:
                    base = datetime.fromisoformat(sig["bar_time"])
                    ref["exit_by"] = (base + timedelta(
                        hours=1 + ref["time_exit_hours"])
                    ).strftime("%Y-%m-%d %H:%M UTC")
                except ValueError:
                    pass
                sig["ref"] = ref
    return signals

# --------------------------------------------------------------------------
# bildirim / dongu
# --------------------------------------------------------------------------

def _signal_detail_rows(sig: dict) -> list[tuple[str, str]]:
    """Stratejiye ozel ek alanlari (etiket, deger) olarak dondurur; her iki
    bildirim kanali da ayni bilgiyi gostersin diye ortak."""
    rows = []
    if "rsi" in sig:
        rows.append(("RSI", str(sig["rsi"])))
    if "volume_logz" in sig:
        rows.append(("Hacim log-Z", str(sig["volume_logz"])))
    if "market_regime" in sig:
        rows.append(("Piyasa rejimi (gözlem)", str(sig["market_regime"])))
    if "funding_pct" in sig:
        rows.append(("Funding %", ", ".join(str(x) for x in sig["funding_pct"])))
    if sig.get("performance_symbol"):
        rows.append(("Performans piyasası",
                     f"USD-M perp ({sig['performance_symbol']})"))
    if sig.get("price_source") == "spot_scaled_proxy":
        rows.append(("Fiyat kaynağı",
                     "futures ticker alınamadı; ölçeklenmiş spot proxy"))
    elif sig.get("price_source") == "usdm_24h_ticker_last_at_scan":
        rows.append(("Fiyat kaynağı", "bildirim anındaki USD-M ticker"))
    elif sig.get("price_source") == "closed_usdm_1h_fallback":
        rows.append(("Fiyat kaynağı",
                     "ticker yok; son kapanmış USD-M 1s mum fallback"))
    if sig.get("funding_interval_hours"):
        rows.append(("Funding aralığı",
                     f"{sig['funding_interval_hours']:g} saat "
                      f"(yaklasik {sig.get('funding_window_hours', '?')} saatlik pencere)"))
    if "rank_24h" in sig:
        rows.append(("24s yükselen sırası", f"#{sig['rank_24h']}"))
    if "return_24h_pct" in sig:
        rows.append(("Kapanmış mum 24s getirisi", f"{sig['return_24h_pct']:+.3f}%"))
    if "volume_ratio" in sig:
        rows.append(("1s hacim / önceki 24s medyan", f"{sig['volume_ratio']:.3f}x"))
    if "oi_change_1h_pct" in sig:
        rows.append(("Open interest 1s", f"{sig['oi_change_1h_pct']:+.3f}%"))
    if "global_long_short_ratio" in sig:
        rows.append(("Global hesap long/short", str(sig["global_long_short_ratio"])))
    if sig.get("global_short_account_pct") is not None:
        rows.append(("Short hesap payi", f"%{sig['global_short_account_pct']:.2f}"))
    if sig.get("strategy") == "G1" and sig.get("condition_price") is not None:
        rows.append(("Koşul mumu kapanışı", _fmt_price(sig["condition_price"])))
    if sig.get("strategy") == "G1" and sig.get("notification_delay_minutes") is not None:
        rows.append(("Bildirim gecikmesi",
                     f"{float(sig['notification_delay_minutes']):.1f} dakika"))
    if sig.get("strategy") == "G1" and sig.get("measurement_entry_time_utc"):
        rows.append(("Ölçüm girişi",
                     f"sonraki 1s açılışı · {sig['measurement_entry_time_utc']}"))
    if sig.get("announcement_at"):
        rows.append(("Resmî duyuru", str(sig["announcement_at"])))
    if sig.get("delist_at"):
        rows.append(("Binance spot durdurma", str(sig["delist_at"])))
    if "bybit_perp_available" in sig:
        rows.append(("Bybit linear perp", "VAR" if sig["bybit_perp_available"]
                     else "YOK"))
    if "okx_perp_available" in sig:
        rows.append(("OKX USDT swap", "VAR" if sig["okx_perp_available"]
                     else "YOK"))
    if sig.get("article_url"):
        rows.append(("Resmî makale", str(sig["article_url"])))
    return rows


OBSERVE_WARNING = (
    "S5/S6 = DINAMIK EVREN, DOGRULANMAMIS. Bu sembol botun 89-coin "
    "dogrulanmis evreninde DEGIL; bu coinde hicbir backtest yapilmadi. "
    "Referans seviyeleri bilerek gosterilmiyor (S1'in +0.93% medyani "
    "cekirdek-30'da olculdu, burada gecerli degil). Ek F'de ayni tur evrende "
    "canli S1 medyani -22% cikmisti. Bu bildirim, kanali OLCEBILMEK icin "
    "uretiliyor; guven kademesi atanmadi."
)


def _observe_lines(sig: dict) -> list[str]:
    if not sig.get("observe"):
        return []
    if sig.get("strategy") == "G1":
        return [
            "G1 DOGRULANMADI: tarihsel train'de N=401, 4s net medyan -%0,30 "
            "ve isabet %45,9. Bu bildirim tum aktif USD-M evreninde ileri "
            "olcum/inceleme icindir; otomatik islem gerekcesi degildir."
        ]
    if sig.get("strategy") == "DL1":
        return [
            "DL1 BIR OLAY ALARMIDIR: duyurudan deliste kadar bekletme tarihsel "
            "olarak cok zararliydi (N=107, medyan -%53,6). Diger borsada short "
            "hipotezi henuz backtest edilmedi; VAR/YOK yalniz anlik bulunabilirliktir."
        ]
    return [OBSERVE_WARNING]


def _ref_lines(sig: dict) -> list[str]:
    """Referans seviyeleri — iki kanal icin ortak duz-metin satirlar."""
    ref = sig.get("ref")
    if not ref:
        return []
    conf = sig.get("confidence")
    lines = ["— Referans seviyeleri (mekanik; tavsiye degil) —"]
    if conf:
        lines.append(f"Guven: {conf} — {sig.get('confidence_note', '')}")
    exit_by = f" (son: {ref['exit_by']})" if ref.get("exit_by") else ""
    lines += [
        f"Giris ref: {_fmt_price(ref['entry_ref'])} (sinyal barinin kapanisi; "
        "fiyat buradan belirgin uzaklastiysa sinyal 'kacmistir')",
        f"Zaman cikisi: ~{ref['time_exit_hours']}h{exit_by} — "
        "backtest'te dogrulanan tek cikis kurali",
        f"Tarihsel kaynak: {ref.get('stats_scope', 'cekirdek-30 all-sample')}",
        f"24 ay tarihce (N={ref['hist_n']}, kazanma %{ref['hist_winrate_pct']}):",
        f"  medyan → {_fmt_price(ref['median_price'])} ({ref['hist_median_pct']:+.2f}%)",
        f"  kotu %10 → {_fmt_price(ref['q10_price'])} ({ref['hist_q10_pct']:+.2f}%)",
        f"  iyi %10 → {_fmt_price(ref['q90_price'])} ({ref['hist_q90_pct']:+.2f}%)",
    ]
    if "sigma_h_pct" in ref:
        lines.append(f"Tipik dalgalanma (±1σ, {ref['time_exit_hours']}h): "
                     f"±{ref['sigma_h_pct']}%")
    if ref.get("touch"):
        t = " · ".join(f"+{x}% %{p}" for x, p in ref["touch"])
        s = " · ".join(f"-{y}% %{p}" for y, p in ref["stopt"])
        lines.append(f"Dokunma olasiliklari ({ref['time_exit_hours']}h, "
                     f"tarihsel): {t} | {s}")
    if ref.get("bracket"):
        lines.append(f"Kucuk-hedef olcumu (Ek B2): {ref['bracket']}. Kucuk "
                     "hedef ISABETI yukseltir, beklenen getiriyi yukseltmez "
                     "(ayni pencerede stop'a dokunma olasiligi da yuksek).")
    lines.append("Bracket (hedef/stop emri) backtest'te zaman cikisini "
                 "YENEMEDI; dokunma olasiliklari bilgi amaclidir. Kaldirac "
                 "kayiplari ve tasfiye riskini buyutur.")
    return lines


def _price_target_lines(sig: dict) -> list[str]:
    profile = sig.get("price_target")
    if not isinstance(profile, dict):
        return []
    targets = profile.get("targets") or []
    if not targets:
        return []
    prices = " · ".join(
        f"TP{float(t['level_pct']):g} {_fmt_price(t.get('price'))}"
        for t in targets)
    direction_text = ("yukari" if str(sig.get("direction")).upper() == "LONG"
                      else "asagi")
    return [
        "— Kisisel fiyat-hedefi takibi (sinyal kuralini degistirmez) —",
        f"{prices} (coin fiyatinda lehte {direction_text} hareket; "
        "kaldirac ROE'si degil)",
        "Ilk tam kapanmis 5dk mumdan itibaren izlenir; hedef gorulurse "
        "bir kez Telegram mesaji gelir. Brut dokunmadir; ucret/slippage "
        "dusulmez. Bot emir acmaz veya kapatmaz.",
    ]


_TELEGRAM_DETAIL_ICONS = {
    "RSI": "🧭",
    "Hacim log-Z": "📊",
    "Piyasa rejimi (gözlem)": "🌐",
    "Funding %": "💸",
    "Performans piyasası": "🏦",
    "Fiyat kaynağı": "🔎",
    "Funding aralığı": "🔁",
    "24s yükselen sırası": "🔟",
    "Kapanmış mum 24s getirisi": "📈",
    "1s hacim / önceki 24s medyan": "📊",
    "Open interest 1s": "🔥",
    "Global hesap long/short": "🌍",
    "Short hesap payi": "🎯",
    "Koşul mumu kapanışı": "🕯️",
    "Bildirim gecikmesi": "⏳",
    "Ölçüm girişi": "📐",
    "Resmî duyuru": "📣",
    "Binance spot durdurma": "⏳",
    "Bybit linear perp": "🏦",
    "OKX USDT swap": "🏦",
    "Resmî makale": "🔗",
}


def _display_confidence(confidence: str | None) -> str:
    return {
        "COK YUKSEK": "ÇOK YÜKSEK", "YUKSEK": "YÜKSEK",
        "DUSUK": "DÜŞÜK", "GOZLEM": "GÖZLEM",
    }.get(str(confidence or ""), str(confidence or "—"))


def _telegram_reason(sig: dict) -> str:
    """Sinyalin matematiksel tetigini tek, jargon-aciklayici cumleye indir."""
    strategy = str(sig.get("strategy") or "")
    base = OBSERVE_BASE_OF.get(strategy, strategy).split("+")[0]
    if base == "S1":
        reason = (f"RSI(14) {sig.get('rsi', '—')} ile {RSI_OVERSOLD} eşiğinin "
                  "altında; fiyat yeni dip yaparken RSI daha yüksek dip yaptı.")
        if "+S4" in strategy or strategy == "S5":
            reason += (f" Son 24 saatte log-hacim Z≥"
                       f"{VOLUME_ZSCORE_THRESHOLD:g} teyidi de var.")
        return reason
    if base == "S2":
        values = ", ".join(f"{float(x):g}%" for x in sig.get("funding_pct", []))
        return (f"Son {FUNDING_PERSISTENCE} kapanmış funding ({values or '—'}) "
                f"≤ {FUNDING_SQUEEZE_THRESHOLD_PCT:g}%; short kalabalığı "
                "sıkışma adayıdır, fakat funding tek başına yön teyidi değildir.")
    if base == "S3":
        return (f"Log-hacim Z={sig.get('volume_logz', '—')} ile "
                f"{VOLUME_ZSCORE_THRESHOLD:g} eşiğini geçti ve mum yeşil "
                "kapandı; kısa vadeli alıcı momentumu adayıdır.")
    if strategy == "G1":
        return ("İlk-10 günlük yükselen, hacim ve OI artışı ile short hesap "
                "çoğunluğu aynı kapanmış veride birlikte görüldü.")
    if strategy == "DL1":
        return ("Resmî Binance tam-token delist duyurusu tespit edildi; bu "
                "bir piyasa olayı alarmıdır, giriş sinyali değildir.")
    return str(sig.get("note") or "Stratejinin tanımlı koşulları birlikte sağlandı.")


def _telegram_compact_warning(sig: dict) -> str | None:
    strategy = str(sig.get("strategy") or "")
    if strategy == "S2":
        return ("S2 düşük kanıtlı araştırma kanalıdır. Dondurulmuş test medyanı "
                "negatif ve ters fiyat hareketi kuyruğu geniştir; işlem teyidi "
                "olarak yorumlanmamalıdır.")
    if strategy == "G1":
        delay = float(sig.get("notification_delay_minutes") or 0)
        late = (f" Bildirim koşul kapanışından {delay:.1f} dakika sonra üretildi; "
                "gösterilen fiyat tarama-anı ticker fiyatıdır."
                if delay >= 10 else "")
        return ("G1 doğrulanmadı: train N=401, net medyan -%0,30 ve isabet "
                f"%45,9. Yalnız ileri gözlem içindir.{late}")
    if strategy == "DL1":
        return ("DL1 olay alarmıdır. Deliste kadar bekletme tarihsel olarak "
                "zararlı; dış-borsa short hipotezi henüz doğrulanmadı.")
    if sig.get("observe"):
        return ("Dinamik gözlem evrenindeki bu coin için backtest yok; ana "
                "S1/S1+S4 istatistikleri burada geçerli değildir.")
    return None


def _telegram_evidence_lines(sig: dict) -> list[str]:
    """Test, dokunma ve canli kişisel karneyi birbirine karistirmadan ozetle."""
    strategy = str(sig.get("strategy") or "")
    lines: list[str] = []
    bt = STRATEGY_TEST_STATS.get(strategy)
    if bt:
        med = f"{float(bt['med']):+.2f}%" if bt.get("med") is not None else "—"
        wr = f"%{float(bt['wr']):g}" if bt.get("wr") is not None else "—"
        lines.append(f"🧪 <b>Dondurulmuş test:</b> {bt.get('h', '?')} saat · "
                     f"N={bt.get('n', 0)} · medyan {med} · isabet {wr}")
    ref = sig.get("ref") or {}
    touch = ref.get("touch") or ()
    stops = ref.get("stopt") or ()
    if touch:
        text = " · ".join(f"+%{x:g}: %{p:g}" for x, p in touch)
        lines.append(f"🎯 <b>24 aylık hedef dokunması:</b> {text}")
    if stops:
        text = " · ".join(f"-%{x:g}: %{p:g}" for x, p in stops)
        lines.append(f"🛑 <b>Aynı ufukta ters dokunma:</b> {text}")
    live = price_target_summary().get(strategy, {}).get(
        _target_level_key(USER_SUCCESS_TARGET_PCT), {})
    if live.get("resolved"):
        small = " · küçük N" if live.get("sample_warning") else ""
        lines.append(
            f"📡 <b>Canlı kişisel TP{USER_SUCCESS_TARGET_PCT:g}:</b> "
            f"%{live['hit_rate_pct']:g} ({live['hit']}/{live['resolved']}{small})")
    return lines


def _telegram_signal_text(sig: dict) -> str:
    """Okunabilir, bolumlu ve Telegram HTML sinirina uygun sinyal metni."""
    strategy = str(sig.get("strategy") or "?")
    direction = str(sig.get("direction") or "")
    conf = str(sig.get("confidence") or signal_confidence(strategy)[0])
    if strategy == "S2":
        mode, marker = "ARAŞTIRMA", "🧪"
    elif sig.get("observe") or strategy in SHADOW_STRATEGIES:
        mode, marker = "GÖZLEM", "🔬"
    elif sig.get("strength") == "STRONG":
        mode, marker = "SİNYAL", "✅"
    else:
        mode, marker = "SİNYAL", "🟦"
    price_label = ("Tarama anı fiyatı" if strategy == "G1" else "Fiyat")
    lines = [
        f"🔔 <b>{_html.escape(strategy)} — "
        f"{_html.escape(str(sig.get('symbol') or '?'))} "
        f"{_html.escape(direction)}</b> {marker}",
        f"<i>({mode} · Güven: {_display_confidence(conf)})</i>",
        "",
        f"💰 <b>{price_label}:</b> {_fmt_price(sig.get('price'))}",
        f"⏱️ <b>Beklenen ufuk:</b> ~{sig.get('horizon_hours', '?')} saat",
    ]
    for label, value in _signal_detail_rows(sig):
        icon = _TELEGRAM_DETAIL_ICONS.get(label, "•")
        lines.append(f"{icon} <b>{_html.escape(label)}:</b> "
                     f"{_html.escape(str(value))}")
    lines += ["", f"💡 <b>Neden geldi?</b> "
              f"{_html.escape(_telegram_reason(sig))}"]
    warning = _telegram_compact_warning(sig)
    if warning:
        lines.append(f"⚠️ <b>Dikkat:</b> {_html.escape(warning)}")
    evidence = _telegram_evidence_lines(sig)
    if evidence:
        lines += ["", "<b>📚 Kanıt ve risk</b>", *evidence]
    ref = sig.get("ref") or {}
    if ref:
        lines += [
            "", "<b>📌 Mekanik referanslar</b>",
            f"• Giriş ref: <b>{_fmt_price(ref.get('entry_ref'))}</b> "
            "(sinyal mumu kapanışı)",
            f"• Zaman çıkışı: <b>~{ref.get('time_exit_hours', '?')} saat</b>"
            + (f" · son { _html.escape(str(ref['exit_by']))}"
               if ref.get("exit_by") else ""),
            f"• Kötü %10 / medyan / iyi %10: "
            f"{_fmt_price(ref.get('q10_price'))} / "
            f"{_fmt_price(ref.get('median_price'))} / "
            f"{_fmt_price(ref.get('q90_price'))}",
        ]
    profile = sig.get("price_target") or {}
    targets = profile.get("targets") or []
    if targets:
        target_text = " · ".join(
            f"TP{float(t['level_pct']):g} {_fmt_price(t.get('price'))}"
            for t in targets)
        lines += ["", f"🎯 <b>Kişisel fiyat takibi:</b> {target_text}"]
    try:
        stamp = _target_dt(sig.get("bar_time")).strftime("%Y-%m-%d %H:%M UTC")
    except (TypeError, ValueError):
        stamp = str(sig.get("bar_time") or "—")
    lines += [
        "", "ℹ️ Yüzdeler coin fiyatına aittir; kaldıraçlı ROI değildir. "
        "Bot emir açmaz veya kapatmaz.",
        f"🕒 <i>Sinyal mumu: {_html.escape(stamp)}</i>",
    ]
    return "\n".join(lines)


def send_telegram_message(sig: dict) -> bool:
    """Telegram Bot API ile sinyal gonderir. Anahtar yoksa sessizce atlar;
    hata olursa uyarir ama tarama dongusunu ASLA durdurmaz."""
    if not ENABLE_TELEGRAM:
        return False
    text = _telegram_signal_text(sig)
    delivered = False
    for cid in TELEGRAM_SUBSCRIBERS:          # sahip + izinli arkadaslar
        delivered = _telegram_send_text(text, chat_id=cid) or delivered
    return delivered


def _redact(text: str) -> str:
    """Hata mesajlarindan sirlari temizler — loglara/ekrana ASLA token
    yazilmamali (URL/header icinde gelebiliyor)."""
    for secret in (TELEGRAM_BOT_TOKEN, GITHUB_TOKEN):
        if secret:
            text = text.replace(secret, "***TOKEN***")
    # Bilinmeyen/rotate edilmis anahtarlar hata metninde key=value veya
    # Authorization: value biciminde gorunurse de loga sizmasin.
    text = re.sub(
        r"(?i)\b(token|api[_-]?key|authorization|secret)"
        r"(\s*[:=]\s*)(?:bearer\s+)?([^\s,;]+)",
        r"\1\2***REDACTED***",
        text,
    )
    return text


# --- bildirim saglik izleme ---
# Sinyal uretilip "gonderilecek" isaretlendigi halde gonderim sessizce
# basarisiz olabiliyordu (hata yalniz tabletin stderr'ine yaziliyordu ve
# uzaktan gorunmuyordu — 2026-07-26 teshisinde bu yasandi). Artik kanal
# sagligi /health ve panoda gorunur.
NOTIFY_HEALTH = {
    "telegram": {"ok": 0, "fail": 0, "last_ok": None, "last_error": None},
}
TELEGRAM_IDENTITY: str | None = None       # getMe sonucu (@botadi) ya da hata


def _note_notify(channel: str, ok: bool, error: str = "") -> None:
    h = NOTIFY_HEALTH.setdefault(
        channel, {"ok": 0, "fail": 0, "last_ok": None, "last_error": None})
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    if ok:
        h["ok"] += 1
        h["last_ok"] = now
    else:
        h["fail"] += 1
        h["last_error"] = f"{now} {_redact(error)[:200]}"


def telegram_preflight() -> None:
    """Baslangicta token'i getMe ile dogrular (mesaj GONDERMEZ). Gecersiz
    token'i sessiz basarisizlik yerine aciktan gorunur yapar."""
    global TELEGRAM_IDENTITY
    if not ENABLE_TELEGRAM:
        TELEGRAM_IDENTITY = "kapali (anahtar yok)"
        return
    try:
        r = requests.get(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getMe",
            timeout=15)
        r.raise_for_status()
        uname = (r.json().get("result") or {}).get("username") or "?"
        TELEGRAM_IDENTITY = f"@{uname}"
        print(f"telegram token gecerli: {TELEGRAM_IDENTITY}", flush=True)
    except requests.RequestException as e:
        TELEGRAM_IDENTITY = f"GECERSIZ: {_redact(str(e))[:120]}"
        print(f"HATA: Telegram token DOGRULANAMADI -> bildirimler GITMEZ. "
              f"{TELEGRAM_IDENTITY}\n"
              f"     Cozum: BotFather'dan token'i kontrol et, .env'deki "
              f"TELEGRAM_BOT_TOKEN'i guncelle, botu yeniden baslat.",
              file=sys.stderr, flush=True)


def _telegram_send_text(text: str, chat_id: str | None = None,
                        reply_markup: dict | None = None) -> bool:
    """Ham HTML metni Telegram'a gonderir (sinyaller + komut cevaplari ortak).
    `reply_markup` verilirse dugme klavyesi eklenir. Anahtar yoksa sessizce
    atlar; hata olursa uyarir, ASLA istisna firlatmaz."""
    if not ENABLE_TELEGRAM:
        return False
    payload = {"chat_id": chat_id or TELEGRAM_CHAT_ID, "text": text,
               "parse_mode": "HTML", "disable_web_page_preview": True}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json=payload, timeout=15)
        r.raise_for_status()
        _note_notify("telegram", True)
        return True
    except requests.RequestException as e:
        _note_notify("telegram", False, str(e))
        print(f"uyari: Telegram gonderilemedi: {_redact(str(e))}",
              file=sys.stderr, flush=True)
        return False


# --- dugmeler ---
# 1) Kalici MENU klavyesi: yazi alaninin altinda durur, dokununca komut metni
#    gonderilir (kod tarafinda MENU_BUTTONS ile komuta cevrilir).
# 2) SATIR-ICI dugmeler: mesaja bagli (katilim onayi gibi tek-dokunus islemler);
#    callback_query ile gelir.
MENU_BUTTONS = {
    "🔎 Kontrol": "/check",
    "📊 Performans": "/performans",
    "🧪 Araştırma": "/arastirma",
    "ℹ️ Durum": "/status",
    "❓ Yardim": "/help",
    "👥 Aboneler": "/aboneler",
}


def _menu_keyboard(owner: bool = False) -> dict:
    """Kalici menu klavyesi. Sahibe ekstra 'Aboneler' dugmesi gosterilir."""
    rows = [["🔎 Kontrol", "📊 Performans"],
            ["🧪 Araştırma", "ℹ️ Durum"], ["❓ Yardim"]]
    if owner:
        rows.append(["👥 Aboneler"])
    return {"keyboard": rows, "resize_keyboard": True,
            "input_field_placeholder": "Bir dugmeye dokun ya da komut yaz"}


def _telegram_answer_callback(callback_id: str, text: str = "") -> None:
    """Dugmeye basildiginda Telegram'daki bekleme animasyonunu kapatir
    (yapilmazsa kullanici 'takildi' saniyor)."""
    if not ENABLE_TELEGRAM:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/answerCallbackQuery",
            json={"callback_query_id": callback_id, "text": text[:200]},
            timeout=15)
    except requests.RequestException as e:
        print(f"uyari: callback yanitlanamadi: {_redact(str(e))}",
              file=sys.stderr, flush=True)


def _signal_event_id(sig: dict) -> str:
    """Ayni strateji/bar olayi icin restart ve kanallar boyunca sabit kimlik.

    Algoritma qc_export.canonical_event_id ile BIREBIR aynidir (32 hex):
    strategy|symbol|direction|bar_time(ISO,Z,saniye)|horizon -> sha256[:32].
    Bu sart bilerek korunur cunku qc_export yalnizca 32-hex kimlikleri kabul
    eder; farkli olsalar QC paketi botun kimligini atip kendi hesaplar ve
    signals.log <-> QC capraz eslestirmesi kirilir (2026-07-26 denetimi).
    config/schema surumleri kimlige DAHIL EDILMEZ — ayar degisiminde ayni bar
    olayinin kimligi degismemeli; o bilgi ayri alanlarda tasiniyor.
    """
    if sig.get("event_id"):
        return str(sig["event_id"])
    bar_raw = str(sig.get("bar_time") or "").strip()
    try:
        if bar_raw.endswith("Z"):
            bar_raw = bar_raw[:-1] + "+00:00"
        dt = datetime.fromisoformat(bar_raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        bar_time = dt.astimezone(timezone.utc).isoformat(
            timespec="seconds").replace("+00:00", "Z")
    except (TypeError, ValueError):
        bar_time = str(sig.get("bar_time") or "")
    canonical = "|".join((
        str(sig.get("strategy") or "").strip().upper(),
        str(sig.get("symbol") or "").strip().upper(),
        str(sig.get("direction") or "").strip().upper(),
        bar_time,
        str(sig.get("horizon_hours") or ""),
    ))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:32]


PRICE_TARGET_STATE_FILE = Path(__file__).parent / ".price_target_state.json"
PRICE_TARGET_STATE_SCHEMA_VERSION = 2
_price_target_lock = threading.RLock()


def _target_dt(raw) -> datetime:
    text = str(raw or "").strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _target_level_key(level: float) -> str:
    return f"{float(level):g}"


def _empty_price_target_state() -> dict:
    return {"schema_version": PRICE_TARGET_STATE_SCHEMA_VERSION, "events": {}}


def _load_price_target_state() -> dict:
    if not PRICE_TARGET_STATE_FILE.exists():
        return _empty_price_target_state()
    try:
        data = json.loads(PRICE_TARGET_STATE_FILE.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not isinstance(data.get("events"), dict):
            raise ValueError("gecersiz hedef state semasi")
        return {"schema_version": int(data.get("schema_version") or 1),
                "events": data["events"]}
    except (OSError, ValueError, TypeError) as e:
        print(f"uyari: fiyat-hedefi durumu okunamadi, sifirdan: {e}",
              file=sys.stderr, flush=True)
        return _empty_price_target_state()


PRICE_TARGET_STATE = _load_price_target_state()


def _save_price_target_state() -> None:
    try:
        tmp = PRICE_TARGET_STATE_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(PRICE_TARGET_STATE, ensure_ascii=False,
                                  sort_keys=True), encoding="utf-8")
        tmp.replace(PRICE_TARGET_STATE_FILE)
    except OSError as e:
        print(f"uyari: fiyat-hedefi durumu kaydedilemedi: {e}",
              file=sys.stderr, flush=True)


def _price_target_public(event: dict, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    expired = event.get("status") == "expired"
    targets = []
    for key, target in sorted((event.get("targets") or {}).items(),
                              key=lambda item: float(item[0])):
        hit_at = target.get("hit_at")
        targets.append({
            "level_pct": float(key),
            "price": target.get("price"),
            "hit_at": hit_at,
            "status": "HIT" if hit_at else "MISSED" if expired else "PENDING",
            "max_adverse_before_hit_pct": (
                target.get("max_adverse_before_hit_pct") if hit_at else None),
            "minutes_to_hit_upper": (
                target.get("minutes_to_hit_upper") if hit_at else None),
        })
    criterion_key = _target_level_key(USER_SUCCESS_TARGET_PCT)
    criterion = (event.get("targets") or {}).get(criterion_key) or {}
    success_status = ("SUCCESS" if criterion.get("hit_at") else
                      "FAILED" if expired else "PENDING")
    return {
        "basis": "signal_notification_price",
        "entry_ref": event.get("entry_ref"),
        "started_at": event.get("started_at"),
        "expires_at": event.get("expires_at"),
        "status": event.get("status", "active"),
        "targets": targets,
        "max_favorable_pct": event.get("max_favorable_pct"),
        "max_adverse_pct": event.get("max_adverse_pct"),
        "path_complete": expired,
        "success_target_pct": USER_SUCCESS_TARGET_PCT,
        "success_status": success_status,
        "adverse_before_hit_policy": "same_5m_bar_full_range_conservative",
        "last_error": event.get("last_error"),
        "as_of": now.isoformat(timespec="seconds"),
    }


def _register_price_targets(record: dict, persist: bool = True) -> dict | None:
    """Teslim edilen sinyali fiyat-hedefi gozlemine bir kez kaydeder.

    Referans, kullanicinin Telegram'da gordugu sinyal fiyatidir. Bu katman emir
    acmaz ve kanonik next-bar-open performans tanimini degistirmez.
    """
    if (not PRICE_TARGET_TRACKING_ENABLED or not PRICE_TARGET_LEVELS_PCT
            or not record.get("push_allowed")
            or str(record.get("strategy", "")).startswith("TEST")):
        return None
    try:
        entry = float(record["price"])
        horizon = float(record["horizon_hours"])
        notified = _target_dt(record["notified_at"])
    except (KeyError, TypeError, ValueError, OverflowError):
        return None
    direction = str(record.get("direction") or "").upper()
    if (not math.isfinite(entry) or entry <= 0 or not math.isfinite(horizon)
            or horizon <= 0 or direction not in ("LONG", "SHORT")):
        return None
    event_id = _signal_event_id(record)
    with _price_target_lock:
        events = PRICE_TARGET_STATE.setdefault("events", {})
        event = events.get(event_id)
        if not isinstance(event, dict):
            start_ms = ((int(notified.timestamp() * 1000) + 299_999)
                        // 300_000) * 300_000
            expires = notified + timedelta(hours=horizon)
            targets = {}
            for level in PRICE_TARGET_LEVELS_PCT:
                factor = (1 + level / 100.0 if direction == "LONG"
                          else 1 - level / 100.0)
                targets[_target_level_key(level)] = {
                    # Karsilastirmada yuvarlama yapma; yalniz sunum _fmt_price
                    # ile kisaltilir. Boylece dusuk fiyatli coinlerde esik kaymaz.
                    "price": entry * factor, "hit_at": None,
                    "max_adverse_before_hit_pct": 0.0,
                    "minutes_to_hit_upper": None,
                }
            strategy = str(record.get("strategy") or "?")
            market = record.get("performance_market") or (
                "um_perp" if strategy == "S2" else "spot")
            event = {
                "event_id": event_id,
                "strategy": strategy,
                "symbol": str(record.get("symbol") or ""),
                "direction": direction,
                "market": market,
                "performance_symbol": record.get("performance_symbol"),
                "entry_ref": entry,
                "started_at": notified.isoformat(),
                "expires_at": expires.isoformat(),
                "next_start_ms": start_ms,
                "status": "active",
                "targets": targets,
                "max_favorable_pct": 0.0,
                "max_adverse_pct": 0.0,
                "last_error": None,
                "replay_silent_before_ms": start_ms,
            }
            if persist:
                events[event_id] = event
                _save_price_target_state()
        return _price_target_public(event, notified)


def fetch_price_target_klines(event: dict, start_ms: int,
                              end_ms: int) -> list[dict]:
    """Hedef izlemesi icin kapanmis 5dk mumlari (spot veya USD-M perp)."""
    if end_ms <= start_ms:
        return []
    market = event.get("market") or "spot"
    symbol = (event.get("performance_symbol") or perp_symbol(event["symbol"])) \
        if market == "um_perp" else event["symbol"]
    params = {"symbol": symbol, "interval": "5m", "startTime": start_ms,
              "endTime": end_ms - 1, "limit": 1000}
    response = (_futures_get("/fapi/v1/klines", params)
                if market == "um_perp" else
                _spot_get("/api/v3/klines", params))
    return [{"open_time": int(k[0]), "high": float(k[2]),
             "low": float(k[3]), "close_time": int(k[6])}
            for k in response.json()]


def _apply_price_target_bars(event: dict, bars: list[dict],
                             coverage_end_ms: int) -> list[str]:
    """Saf cekirdek: mumlari uygular, ilk dokunulan hedef anahtarlarini verir."""
    entry = float(event["entry_ref"])
    direction = event["direction"]
    next_start = int(event.get("next_start_ms") or 0)
    tracking_start = ((int(_target_dt(event["started_at"]).timestamp() * 1000)
                       + 299_999) // 300_000) * 300_000
    silent_before = int(event.get("replay_silent_before_ms") or tracking_start)
    newly_hit = []
    for bar in sorted(bars, key=lambda b: int(b["open_time"])):
        open_ms = int(bar["open_time"])
        if open_ms < next_start:
            continue
        # Bir bosluk varsa sonraki mumu isleyip aradaki bilinmeyen fiyat yolunu
        # "hedefe degmedi" sayma. Bir sonraki tur ayni noktadan yeniden dener.
        if open_ms > next_start or open_ms >= coverage_end_ms:
            break
        high, low = float(bar["high"]), float(bar["low"])
        if not all(math.isfinite(x) and x > 0 for x in (high, low)):
            break
        if direction == "LONG":
            favorable = (high / entry - 1) * 100
            adverse = (low / entry - 1) * 100
        else:
            favorable = (1 - low / entry) * 100
            adverse = (1 - high / entry) * 100
        event["max_favorable_pct"] = round(max(
            float(event.get("max_favorable_pct") or 0.0), favorable), 4)
        event["max_adverse_pct"] = round(min(
            float(event.get("max_adverse_pct") or 0.0), adverse), 4)
        for key, target in event["targets"].items():
            if target.get("hit_at"):
                continue
            # OHLC aynı mum içinde hedef ile dip/tepenin sırasını söylemez.
            # Bu yüzden hedef mumu dahil tam ters ekstremi kullanmak bilinçli,
            # muhafazakâr bir üst sınırdır; panoda açıkça etiketlenir.
            target["max_adverse_before_hit_pct"] = round(min(
                float(target.get("max_adverse_before_hit_pct") or 0.0),
                adverse), 4)
            touched = (high >= float(target["price"]) if direction == "LONG"
                       else low <= float(target["price"]))
            if touched:
                target["hit_at"] = datetime.fromtimestamp(
                    open_ms / 1000, tz=timezone.utc).isoformat()
                target["minutes_to_hit_upper"] = round(max(
                    0.0, (open_ms + 300_000 - tracking_start) / 60_000), 1)
                if open_ms >= silent_before:
                    newly_hit.append(key)
        next_start = max(next_start, open_ms + 300_000)
    event["next_start_ms"] = next_start
    return newly_hit


def _send_price_target_alert(event: dict, hit_keys: list[str]) -> None:
    notify_keys = [key for key in hit_keys
                   if float(key) in PRICE_TARGET_NOTIFY_LEVELS_PCT]
    if not PRICE_TARGET_NOTIFY or not ENABLE_TELEGRAM or not notify_keys:
        return
    levels = sorted((float(k) for k in notify_keys))
    sign = "+" if event.get("direction") == "LONG" else "-"
    level_text = " ve ".join(f"{sign}%{x:g}" for x in levels)
    target_rows = []
    for level in levels:
        target = event["targets"][_target_level_key(level)]
        target_rows.append(
            f"• {sign}%{level:g}: <b>{_fmt_price(target['price'])}</b>")
    text = "\n".join([
        "🎯 <b>FİYAT HEDEFİ DOKUNDU</b>",
        f"<i>{_html.escape(str(event.get('strategy') or '?'))} · "
        f"{_html.escape(str(event.get('symbol') or '?'))} · "
        f"{_html.escape(str(event.get('direction') or ''))}</i>",
        "",
        f"💰 <b>Bildirim referansı:</b> {_fmt_price(event['entry_ref'])}",
        f"🎯 <b>Ulaşılan seviye:</b> {level_text}",
        *target_rows,
        f"⚠️ <b>Hedef öncesi ters hareket:</b> "
        f"{float(event.get('max_adverse_pct') or 0):+.2f}%",
        "",
        "ℹ️ Kapanmış 5dk mumuyla ölçülen brüt fiyat dokunmasıdır; "
        "ücret/slippage düşülmez, kaldıraçlı ROI değildir ve bot emir vermez.",
    ])
    for cid in TELEGRAM_SUBSCRIBERS:
        _telegram_send_text(text, chat_id=cid)


def update_price_target_tracking(now: datetime | None = None) -> dict:
    """Aktif hedefleri gunceller; hata ana tarama dongusune ASLA yayilmaz."""
    if not PRICE_TARGET_TRACKING_ENABLED:
        return {"checked": 0, "hits": 0, "errors": 0, "backlog": 0}
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    now_ms = int(now.timestamp() * 1000)
    checked = hits = errors = backlog = 0
    alerts: list[tuple[dict, list[str]]] = []
    changed = False
    with _price_target_lock:
        event_ids = list(PRICE_TARGET_STATE.get("events", {}))
    for event_id in event_ids:
        with _price_target_lock:
            event = PRICE_TARGET_STATE.get("events", {}).get(event_id)
            if not isinstance(event, dict) or event.get("status") != "active":
                continue
            try:
                expires_ms = int(_target_dt(event["expires_at"]).timestamp() * 1000)
            except (KeyError, TypeError, ValueError):
                event["status"] = "invalid"
                changed = True
                continue
            # Yalniz tam kapanmis 5dk mumlar; bildirimden onceki mumun yuksegi
            # basari sayilmaz. Ufkun sonundaki parcali mum da muhafazakar atilir.
            closed_end_ms = (now_ms // 300_000) * 300_000
            horizon_end_ms = (expires_ms // 300_000) * 300_000
            coverage_end_ms = min(closed_end_ms, horizon_end_ms)
            start_ms = int(event.get("next_start_ms") or 0)
        if start_ms < coverage_end_ms:
            if checked >= PRICE_TARGET_MAX_EVENTS_PER_SCAN:
                backlog += 1
                continue
            checked += 1
            try:
                bars = fetch_price_target_klines(event, start_ms,
                                                  coverage_end_ms)
                if not bars:
                    raise ValueError("kapanmis 5dk mum verisi bos")
                with _price_target_lock:
                    current = PRICE_TARGET_STATE["events"].get(event_id)
                    if not isinstance(current, dict):
                        continue
                    new_hits = _apply_price_target_bars(
                        current, bars, coverage_end_ms)
                    current["last_error"] = None
                    if new_hits:
                        hits += len(new_hits)
                        alerts.append((dict(current), new_hits))
                    changed = True
            except Exception as e:
                errors += 1
                with _price_target_lock:
                    current = PRICE_TARGET_STATE["events"].get(event_id)
                    if isinstance(current, dict):
                        current["last_error"] = _redact(
                            f"{type(e).__name__}: {e}")[:200]
                        changed = True
                print(f"uyari: fiyat-hedefi izlenemedi ({event.get('symbol')}): "
                      f"{_redact(str(e))}", file=sys.stderr, flush=True)
                continue
        with _price_target_lock:
            current = PRICE_TARGET_STATE.get("events", {}).get(event_id)
            if (isinstance(current, dict) and current.get("status") == "active"
                    and now_ms >= expires_ms
                    and int(current.get("next_start_ms") or 0) >= horizon_end_ms):
                current["status"] = "expired"
                changed = True
    with _price_target_lock:
        if PRICE_TARGET_RETENTION_DAYS > 0:
            cutoff = now - timedelta(days=PRICE_TARGET_RETENTION_DAYS)
            events = PRICE_TARGET_STATE.get("events", {})
            for event_id, event in list(events.items()):
                if not isinstance(event, dict) or event.get("status") == "active":
                    continue
                try:
                    event_time = _target_dt(
                        event.get("expires_at") or event.get("started_at"))
                except (TypeError, ValueError):
                    event_time = datetime.min.replace(tzinfo=timezone.utc)
                if event_time < cutoff:
                    del events[event_id]
                    changed = True
        if changed:
            _save_price_target_state()
    for event, new_hits in alerts:
        _send_price_target_alert(event, new_hits)
    return {"checked": checked, "hits": hits, "errors": errors,
            "backlog": backlog}


def price_target_summary() -> dict:
    """Yalnız ufku tamamlanmış olaylarda hedef-dokunma karnesi.

    Aktif olayda hedef görülmüş olsa bile aynı kohortun henüz hedef görmeyen
    üyeleri sansürlüdür; oranı yapay yükseltmemek için ikisi de ``pending``
    kalır. Satır bazında anlık HIT yine görünür.
    """
    grouped: dict[str, dict[str, dict]] = {}
    with _price_target_lock:
        events = list(PRICE_TARGET_STATE.get("events", {}).values())
    for event in events:
        if not isinstance(event, dict):
            continue
        strategy = str(event.get("strategy") or "?")
        status = event.get("status")
        if status not in ("active", "expired"):
            continue
        matured = status == "expired"
        for key, target in (event.get("targets") or {}).items():
            row = grouped.setdefault(strategy, {}).setdefault(
                key, {"hit": 0, "missed": 0, "pending": 0,
                      "pending_hit": 0, "adverse": [], "minutes": []})
            if matured:
                if target.get("hit_at"):
                    row["hit"] += 1
                    adverse = target.get("max_adverse_before_hit_pct")
                    minutes = target.get("minutes_to_hit_upper")
                    if adverse is not None:
                        row["adverse"].append(float(adverse))
                    if minutes is not None:
                        row["minutes"].append(float(minutes))
                else:
                    row["missed"] += 1
            else:
                row["pending"] += 1
                if target.get("hit_at"):
                    row["pending_hit"] += 1
    out = {}
    for strategy, levels in sorted(grouped.items()):
        out[strategy] = {}
        for key, row in sorted(levels.items(), key=lambda item: float(item[0])):
            resolved = row["hit"] + row["missed"]
            lo, hi = _wilson_interval(row["hit"], resolved)
            adverse = row.pop("adverse")
            minutes = row.pop("minutes")
            out[strategy][key] = {
                **row, "resolved": resolved,
                "hit_rate_pct": (round(100 * row["hit"] / resolved, 1)
                                 if resolved else None),
                "hit_rate_ci95_low_pct": (round(lo, 1)
                                           if lo is not None else None),
                "hit_rate_ci95_high_pct": (round(hi, 1)
                                            if hi is not None else None),
                "median_adverse_before_hit_pct": (
                    round(statistics.median(adverse), 2) if adverse else None),
                "worst_adverse_before_hit_pct": (
                    round(min(adverse), 2) if adverse else None),
                "median_minutes_to_hit_upper": (
                    round(statistics.median(minutes), 1) if minutes else None),
                "sample_warning": "small_sample" if resolved < 30 else None,
            }
    return out


def price_path_summary() -> dict:
    """Strateji bazında ufuk içi MFE/MAE; yalnız tamamlanmış fiyat yolları."""
    grouped: dict[str, dict[str, list[float] | int]] = {}
    with _price_target_lock:
        events = list(PRICE_TARGET_STATE.get("events", {}).values())
    for event in events:
        if not isinstance(event, dict):
            continue
        strategy = str(event.get("strategy") or "?")
        row = grouped.setdefault(strategy, {"mfe": [], "mae": [],
                                            "pending": 0})
        if event.get("status") == "active":
            row["pending"] = int(row["pending"]) + 1
            continue
        if event.get("status") != "expired":
            continue
        try:
            mfe = float(event["max_favorable_pct"])
            mae = float(event["max_adverse_pct"])
        except (KeyError, TypeError, ValueError, OverflowError):
            continue
        if math.isfinite(mfe) and math.isfinite(mae):
            row["mfe"].append(mfe)  # type: ignore[union-attr]
            row["mae"].append(mae)  # type: ignore[union-attr]
    out = {}
    for strategy, row in grouped.items():
        mfe = list(row["mfe"])
        mae = list(row["mae"])
        n = len(mfe)
        out[strategy] = {
            "n_matured": n,
            "n_pending": int(row["pending"]),
            "median_mfe_pct": (round(statistics.median(mfe), 2)
                               if mfe else None),
            "q10_mfe_pct": (round(_percentile(mfe, .10), 2)
                            if mfe else None),
            "q90_mfe_pct": (round(_percentile(mfe, .90), 2)
                            if mfe else None),
            "median_mae_pct": (round(statistics.median(mae), 2)
                               if mae else None),
            "worst_mae_pct": round(min(mae), 2) if mae else None,
            "sample_warning": "small_sample" if n < 30 else None,
        }
    return out


def price_target_for_event(event_id: str) -> dict | None:
    """Pano icin event_id bazli, salt-okunur fiyat-hedefi gorunumu."""
    with _price_target_lock:
        event = PRICE_TARGET_STATE.get("events", {}).get(event_id)
        return _price_target_public(event) if isinstance(event, dict) else None


def _ensure_price_target_state_schema() -> int:
    """Eski 2/3 kayıtlarını 2/3/5/10 yol analizine kayıpsız hazırlar.

    Eski kapsama yeniden oynatılır; geçmişte görülmüş hedefler için gecikmiş
    Telegram alarmı üretilmez. Yeniden hesaplama 5dk API bütçesiyle parça parça
    tamamlanır ve canlı sinyal mantığına dokunmaz.
    """
    changed = 0
    expected = {_target_level_key(level) for level in PRICE_TARGET_LEVELS_PCT}
    with _price_target_lock:
        version = int(PRICE_TARGET_STATE.get("schema_version") or 1)
        events = PRICE_TARGET_STATE.setdefault("events", {})
        for event in events.values():
            if not isinstance(event, dict):
                continue
            targets = event.get("targets") or {}
            needs_replay = (version < PRICE_TARGET_STATE_SCHEMA_VERSION
                            or set(targets) != expected
                            or any("max_adverse_before_hit_pct" not in target
                                   for target in targets.values()
                                   if isinstance(target, dict)))
            if not needs_replay:
                continue
            try:
                entry = float(event["entry_ref"])
                direction = str(event["direction"]).upper()
                started = _target_dt(event["started_at"])
                expires = _target_dt(event["expires_at"])
                if entry <= 0 or direction not in ("LONG", "SHORT"):
                    raise ValueError("gecersiz fiyat/yon")
                start_ms = ((int(started.timestamp() * 1000) + 299_999)
                            // 300_000) * 300_000
                horizon_end_ms = (int(expires.timestamp() * 1000)
                                  // 300_000) * 300_000
            except (KeyError, TypeError, ValueError, OverflowError):
                event["status"] = "invalid"
                changed += 1
                continue
            old_status = str(event.get("status") or "active")
            old_next = int(event.get("next_start_ms") or start_ms)
            # Tamamlanmış eski olayın tüm geçmişi sessiz; aktif olayda yalnız
            # daha önce işlenmiş bölüm sessizdir, gelecekteki 2/3 alarmı sürer.
            silent_before = (horizon_end_ms if old_status != "active"
                             else max(start_ms, old_next))
            rebuilt = {}
            for level in PRICE_TARGET_LEVELS_PCT:
                factor = (1 + level / 100 if direction == "LONG"
                          else 1 - level / 100)
                rebuilt[_target_level_key(level)] = {
                    "price": entry * factor,
                    "hit_at": None,
                    "max_adverse_before_hit_pct": 0.0,
                    "minutes_to_hit_upper": None,
                }
            event.update({
                "targets": rebuilt,
                "next_start_ms": start_ms,
                "replay_silent_before_ms": silent_before,
                "status": "active",
                "max_favorable_pct": 0.0,
                "max_adverse_pct": 0.0,
                "last_error": None,
            })
            changed += 1
        if version != PRICE_TARGET_STATE_SCHEMA_VERSION:
            PRICE_TARGET_STATE["schema_version"] = \
                PRICE_TARGET_STATE_SCHEMA_VERSION
            changed += 1
        if changed:
            _save_price_target_state()
    return changed


def _backfill_price_targets_from_signal_log() -> int:
    """State kaybolsa bile teslim edilmiş geçmiş sinyalleri logdan geri kur."""
    if not PRICE_TARGET_TRACKING_ENABLED:
        return 0
    path = Path(__file__).parent / SIGNAL_LOG
    if not path.exists():
        return 0
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(
        days=max(1, PRICE_TARGET_RETENTION_DAYS))
    now_closed_ms = (int(now.timestamp() * 1000) // 300_000) * 300_000
    added = 0
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return 0
    for line in lines:
        try:
            record = json.loads(line)
            notified = _target_dt(record.get("notified_at"))
        except (TypeError, ValueError):
            continue
        if (notified < cutoff or record.get("performance_excluded")
                or str(record.get("strategy") or "").startswith("TEST")):
            continue
        delivered = record.get("push_allowed")
        if delivered is None:
            delivered = not bool(record.get("suppressed"))
        if not delivered:
            continue
        event_id = _signal_event_id(record)
        with _price_target_lock:
            exists = event_id in PRICE_TARGET_STATE.setdefault("events", {})
        if exists:
            continue
        record["event_id"] = event_id
        record["push_allowed"] = True
        if _register_price_targets(record, persist=True):
            # Logdan geri kurulan olayda geçmiş mumlar henüz işlenmemiştir.
            # Bunların hedeflerini analitiğe kat, fakat kullanıcıya saatler/günler
            # gecikmiş Telegram alarmı gönderme. Olay hâlâ aktifse bu andan
            # sonraki gerçek zamanlı hedefler normal şekilde bildirilebilir.
            with _price_target_lock:
                event = PRICE_TARGET_STATE["events"].get(event_id)
                if isinstance(event, dict):
                    horizon_end_ms = (int(_target_dt(
                        event["expires_at"]).timestamp() * 1000)
                                      // 300_000) * 300_000
                    event["replay_silent_before_ms"] = min(
                        now_closed_ms, horizon_end_ms)
                    _save_price_target_state()
            added += 1
    return added


def _delivery_record(sig: dict, push: bool) -> dict:
    conf = sig.get("confidence", "YUKSEK")
    strategy = str(sig.get("strategy") or "")
    reasons = []
    if sig.get("observe"):
        # Gozlem sinyalinin push'unu CONF_RANK degil OBSERVE_PUSH belirler:
        # "GOZLEM" kademesi bilerek tum esiklerin altindadir, yoksa
        # NOTIFY_MIN_CONFIDENCE bu kanali her zaman susturur.
        observe_push = sig.get("push_policy_enabled", OBSERVE_PUSH)
        if not observe_push:
            reasons.append("observe_channel_silent")
    elif strategy == "S2" and S2_RESEARCH_PUSH:
        # Guven DUSUK kalir; yalniz kullanicinin talep ettigi arastirma
        # bildirimi genel NOTIFY_MIN_CONFIDENCE kapisini kontrollu asar.
        pass
    elif CONF_RANK.get(conf, 2) < CONF_RANK.get(NOTIFY_MIN_CONFIDENCE, 1):
        reasons.append("confidence_below_threshold")
    if not push:
        reasons.append("scan_push_cap")
    suppressed = bool(reasons)
    return {
        **sig,
        "schema_version": SIGNAL_SCHEMA_VERSION,
        "config_version": sig.get("config_version", SIGNAL_CONFIG_VERSION),
        "event_id": _signal_event_id(sig),
        "notified_at": datetime.now(timezone.utc).isoformat(),
        "push_requested": bool(push),
        "push_allowed": not suppressed,
        "suppressed": suppressed,
        "suppression_reason": ",".join(reasons) if reasons else None,
    }


def notify(sig: dict, push: bool = True) -> dict:
    """Tek sinyal cikis noktasi: stdout + JSONL log + API tamponu + Telegram.

    Anti-spam UST AKISTA yapilir (ScanState.should_fire — kenar-tetikleme +
    strateji-basi cooldown): buraya ulasan her sinyal zaten tekillestirilmistir."""
    record = _delivery_record(sig, push)
    # Mesajda hedef fiyatlari gorunsun; kalici karneye ise ancak Telegram API'si
    # en az bir aboneye basariyla teslim ettikten sonra eklenir.
    target_profile = _register_price_targets(record, persist=False)
    if target_profile:
        record["price_target"] = target_profile
    conf = record.get("confidence", "YUKSEK")
    reason = record.get("suppression_reason") or ""
    tag = ("  [ARASTIRMA PUSH]"
           if record.get("strategy") == "S2" and record["push_allowed"]
           and S2_RESEARCH_PUSH else
           ("  [SESSIZ: guven esigi alti]"
           if "confidence_below_threshold" in reason else
           ("  [TOPLU OZETTE: tarama-basi tavan]"
            if "scan_push_cap" in reason else "")))
    line = (f"[{record['bar_time']}] {record['strategy']:<6} "
            f"{record['symbol']:<12} {record['direction']} "
            f"({record['strength']}/{conf}) "
            f"fiyat={_fmt_price(record['price'])} "
            f"~{record['horizon_hours']}h | {record['note']}" + tag)
    print(line, flush=True)
    try:
        with open(Path(__file__).parent / SIGNAL_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError as e:
        # Kanal teslimi, yerel diskin gecici hatasi yuzunden tamamen kaybolmasin.
        print(f"uyari: sinyal logu yazilamadi: {e}", file=sys.stderr, flush=True)
    with _recent_lock:
        RECENT_SIGNALS.appendleft(record)
    if record["suppressed"]:
        return record
    if send_telegram_message(record):
        _register_price_targets(record, persist=True)
    return record


def _send_overflow_summary(overflow: list[dict]) -> None:
    """Tarama tavanini asan sinyalleri Telegram'a tek ozetle iletir."""
    if not overflow:
        return
    lines = ["📚 <b>TOPLU SİNYAL ÖZETİ</b>",
             f"<i>Aynı taramada ayrıntı sınırını aşan {len(overflow)} olay</i>",
             "⚠️ Piyasa geneli hareket olabilir; aşağıdaki liste yalnız kısa "
             "referanstır.", ""]
    for s in overflow[:20]:
        lines.append(
            f"• <b>{_html.escape(str(s.get('strategy') or '?'))}</b> · "
            f"{_html.escape(str(s.get('symbol') or '?'))} · "
            f"{_html.escape(str(s.get('direction') or ''))} · "
            f"{_fmt_price(s.get('price'))} · ~{s.get('horizon_hours', '?')}s")
    if len(overflow) > 20:
        lines.append(f"… ayrıca {len(overflow) - 20} olay")
    lines += ["", "📌 Detaylar signals.log ve /signals/latest içinde.",
              "<i>Bot emir açmaz; yatırım tavsiyesi değildir.</i>"]
    tg_text = "\n".join(lines)
    for cid in TELEGRAM_SUBSCRIBERS:
        _telegram_send_text(tg_text, chat_id=cid)


# Firtina gunu duzeni: tek taramada en fazla bu kadar sinyal AYRINTILI push
# edilir (oncelik sirasiyla); fazlasi tek toplu mesajda ozetlenir. Piyasa
# geneli cokuslerde 10+ ayri bildirim yerine duzenli akis.
MAX_PUSH_PER_SCAN = _env("MAX_PUSH_PER_SCAN", 6)
# Bu oranda veya daha fazla sembol veri hatasi verirse tarama "basarili"
# sayilmaz; /health onceki basari taze olsa bile degraded olur.
SCAN_FAILURE_ERROR_RATIO = _env("SCAN_FAILURE_ERROR_RATIO", 0.8)


def scan_all(state: ScanState) -> int:
    global LAST_SCAN_ERRORS, LAST_SCAN_ATTEMPTED
    global LAST_SCAN_SUCCEEDED_SYMBOLS, LAST_SCAN_ERROR_RATIO
    errors = 0
    collected: list[dict] = []
    market_error: MarketRateLimitError | MarketTransientError | None = None
    attempted = len(SYMBOLS)
    for index, sym in enumerate(SYMBOLS):
        try:
            collected += scan_symbol(sym, state)
        except (MarketRateLimitError, MarketTransientError) as e:
            # Ayni ortak API kapisina kalan tum sembollerle yuklenme. Onceki
            # sembollerde bulunan gecerli sinyaller yine teslim edilir.
            errors += len(SYMBOLS) - index
            market_error = e
            ERROR_SAMPLES.append(f"{sym}: {e}")
            print(f"uyari: {sym} sonrasinda tarama ortak API hatasi nedeniyle "
                  "erken kesildi", file=sys.stderr, flush=True)
            break
        except Exception as e:
            errors += 1
            ERROR_SAMPLES.append(f"{sym}: {e}")
            print(f"uyari: {sym} taranamadi: {e}", file=sys.stderr, flush=True)
        time.sleep(0.25)          # nazik olalim (limitin cok altindayiz)
    LAST_SCAN_ERRORS = errors
    LAST_SCAN_ATTEMPTED = attempted
    LAST_SCAN_SUCCEEDED_SYMBOLS = max(0, attempted - errors)
    LAST_SCAN_ERROR_RATIO = errors / attempted if attempted else 1.0
    if errors:
        print(f"uyari: taramada {errors}/{len(SYMBOLS)} sembol hata verdi",
              file=sys.stderr, flush=True)
    # GOZLEM KANALI — dogrulanmis taramadan SONRA, AYRI hata muhasebesiyle.
    # Buradaki hatalar LAST_SCAN_* saglik olcumlerine KARISMAZ: bu kanal
    # dogrulanmamis ve her zaman en iyi cabadir, /health'i bozmamali.
    observed: list[dict] = []
    if OBSERVE_ENABLED and market_error is None:
        for sym in OBSERVE_SYMBOLS:
            try:
                observed += scan_symbol(sym, state, observe=True)
            except (MarketRateLimitError, MarketTransientError) as e:
                print(f"uyari: gozlem taramasi {sym} sonrasi kesildi: {e}",
                      file=sys.stderr, flush=True)
                break
            except Exception as e:
                print(f"uyari: gozlem sembolu {sym} taranamadi: {e}",
                      file=sys.stderr, flush=True)
            time.sleep(0.25)

    collected.sort(key=lambda s: (_priority(s), s["symbol"]))
    observed.sort(key=lambda s: (_priority(s), s["symbol"]))
    overflow = []
    pushed = 0
    for sig in collected:
        conf_ok = (CONF_RANK.get(sig.get("confidence", "YUKSEK"), 2)
                   >= CONF_RANK.get(NOTIFY_MIN_CONFIDENCE, 1))
        policy_push = (conf_ok or (sig.get("strategy") == "S2"
                                   and S2_RESEARCH_PUSH))
        if policy_push and pushed >= MAX_PUSH_PER_SCAN:
            overflow.append(sig)
            notify(sig, push=False)
        else:
            notify(sig)
            if policy_push:
                pushed += 1
    # Gozlem sinyalleri kendi push tavanina tabidir; dogrulanmis sinyallerin
    # MAX_PUSH_PER_SCAN butcesini TUKETMEZ (onlarin onune de gecemez).
    observe_pushed = 0
    for sig in observed:
        allow = OBSERVE_PUSH and observe_pushed < OBSERVE_MAX_PUSH_PER_SCAN
        notify(sig, push=allow)
        if allow:
            observe_pushed += 1
    if overflow:
        _send_overflow_summary(overflow)
    state.save()                  # restart'ta cooldown/tampon kaybolmasin
    threshold = min(1.0, max(0.01, float(SCAN_FAILURE_ERROR_RATIO)))
    if market_error is not None:
        raise market_error
    if attempted == 0 or LAST_SCAN_ERROR_RATIO >= threshold:
        raise RuntimeError(
            "yetersiz piyasa veri kapsami: "
            f"{LAST_SCAN_SUCCEEDED_SYMBOLS}/{attempted} sembol basarili "
            f"(hata orani %{LAST_SCAN_ERROR_RATIO * 100:.1f}, "
            f"esik %{threshold * 100:.1f})")
    return len(collected)


# Gunluk yasam sinyali: her gun bu UTC saatinden sonraki ilk taramada tek
# satirlik ozet gonderilir. Gelmezse botun oldugunu anlarsin (sessiz olum
# sigortasi). Kapatmak: DAILY_SUMMARY_HOUR_UTC=-1
DAILY_SUMMARY_HOUR_UTC = _env("DAILY_SUMMARY_HOUR_UTC", 6)   # 06 UTC = 09 TR
_last_summary_day: str | None = None
_last_research_summary_week: str | None = None
_forward_oi_report_worker_lock = threading.Lock()
_forward_oi_report_state_lock = threading.Lock()
FORWARD_OI_REPORT_WORKER_ACTIVE = False
FORWARD_OI_REPORT_WORKER_LAST_ERROR: str | None = None


def research_readiness_report() -> dict:
    """Yerel ileri arşivin OI araştırmasına hazır oluşunu ağsız ölç."""
    report = build_research_readiness(
        ARCHIVE_DIR, discovery_days=RESEARCH_DISCOVERY_DAYS,
        oos_days=RESEARCH_OOS_DAYS,
        oos_start_utc=RESEARCH_OOS_START_UTC or None)
    # Dizin yolu yayımlanmaz; yalnız güvenli ortam etiketi çoklu süreçleri
    # (özellikle eski Render kopyası ile Termux) ayırt etmeyi sağlar.
    report["source_label"] = RESEARCH_REPORT_SOURCE or "tanımsız süreç"
    return report


def _format_missing_research_archive(report: dict) -> str:
    source = _html.escape(str(report.get("source_label") or "tanımsız süreç"))
    return (
        "⚠️ <b>HAFTALIK ARAŞTIRMA ARŞİVİ BULUNAMADI</b>\n"
        f"🖥️ <b>Kaynak:</b> {source}\n\n"
        "Bu bot süreci hiçbir <code>market_archive_*.jsonl</code> kaydı "
        "görmüyor. Sıfırlardan oluşan normal rapor gönderilmedi.\n\n"
        "Muhtemel neden: süreç, doğru <code>ARCHIVE_DIR</code> yazılmadan önce "
        "başlatıldı veya arşivi olmayan ikinci bir bulut kopyası aynı Telegram "
        "tokenını kullanıyor. <code>/arastirma</code> komutundaki Kaynak satırını "
        "ve çalışan süreçleri kontrol et."
    )


def _saved_research_week() -> str | None:
    try:
        data = json.loads(RESEARCH_MONITOR_STATE_FILE.read_text(
            encoding="utf-8"))
        return str(data.get("last_week") or "") or None
    except (OSError, TypeError, ValueError):
        return None


def _save_research_week(slot: str) -> None:
    try:
        tmp = RESEARCH_MONITOR_STATE_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps({"last_week": slot}, separators=(",", ":")),
                       encoding="utf-8")
        tmp.replace(RESEARCH_MONITOR_STATE_FILE)
    except OSError as exc:
        print(f"uyari: haftalik arastirma durumu kaydedilemedi: {exc}",
              file=sys.stderr, flush=True)


def _maybe_weekly_research_summary() -> None:
    """Haftanın zamanından sonraki ilk turda sahibine tek hazırlık raporu."""
    global _last_research_summary_week
    if not RESEARCH_WEEKLY_SUMMARY_ENABLED or not ENABLE_TELEGRAM:
        return
    slot = research_weekly_slot(
        datetime.now(timezone.utc), RESEARCH_WEEKLY_WEEKDAY,
        RESEARCH_WEEKLY_HOUR_UTC)
    if not slot:
        return
    if _last_research_summary_week is None:
        _last_research_summary_week = _saved_research_week()
    if _last_research_summary_week == slot:
        return
    # Aynı süreçte Telegram hatası her 5 dakikada bir tekrar denenmesin.
    _last_research_summary_week = slot
    try:
        report = research_readiness_report()
        no_market_data = int(report.get("market", {}).get("rows") or 0) == 0
        message = (_format_missing_research_archive(report)
                   if RESEARCH_WEEKLY_REQUIRE_DATA and no_market_data
                   else format_research_readiness(report))
        if _telegram_send_text(message,
                               chat_id=TELEGRAM_CHAT_ID):
            _save_research_week(slot)
    except Exception as exc:
        print(f"uyari: haftalik arastirma raporu olusturulamadi: "
              f"{type(exc).__name__}: {_redact(str(exc))}",
              file=sys.stderr, flush=True)


def _parse_forward_oi_report_time(value) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError, OverflowError):
        return None


def _read_forward_oi_report_state_unlocked() -> dict:
    try:
        data = json.loads(FORWARD_OI_REPORT_STATE_FILE.read_text(
            encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, TypeError, ValueError):
        return {}


def _write_forward_oi_report_state_unlocked(state: dict) -> bool:
    try:
        FORWARD_OI_REPORT_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = FORWARD_OI_REPORT_STATE_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, ensure_ascii=False,
                                  separators=(",", ":")), encoding="utf-8")
        tmp.replace(FORWARD_OI_REPORT_STATE_FILE)
        return True
    except OSError as exc:
        print(f"uyari: 30 gunluk OI rapor durumu kaydedilemedi: "
              f"{_redact(str(exc))}", file=sys.stderr, flush=True)
        return False


def _forward_oi_report_due(state: dict, now: datetime) -> bool:
    due = _parse_forward_oi_report_time(state.get("next_due_at_utc"))
    if due is None:
        return True
    if state.get("last_status") == "running":
        started = _parse_forward_oi_report_time(
            state.get("last_started_at_utc"))
        # Süreç analiz sırasında kapanırsa kalıcı "running" kaydı raporu
        # sonsuza kadar kilitlemesin. Yaşayan worker ayrıca süreç-içi lock tutar.
        if started is not None and now - started < timedelta(hours=6):
            return False
        return True
    return now >= due


def _initialize_forward_oi_report_schedule(now: datetime) -> bool:
    """İlk aktivasyonda hemen test koşmaz; ilk raporu N gün sonrasına kurar."""
    with _forward_oi_report_state_lock:
        state = _read_forward_oi_report_state_unlocked()
        if state.get("activated_at_utc"):
            return False
        due = now + timedelta(days=FORWARD_OI_REPORT_INTERVAL_DAYS)
        state = {
            "schema_version": "forward-oi-periodic-report-v1",
            "activated_at_utc": now.isoformat(timespec="seconds"),
            "next_due_at_utc": due.isoformat(timespec="seconds"),
            "last_status": "scheduled",
        }
        if _write_forward_oi_report_state_unlocked(state):
            print("30 gunluk Forward OI raporu planlandi: "
                  f"ilk calisma {due.isoformat(timespec='minutes')}",
                  flush=True)
        return True


def _metric_text(value, digits: int = 1, signed: bool = False) -> str:
    if value is None:
        return "—"
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return "—"
    if not math.isfinite(number):
        return "—"
    return f"{number:+.{digits}f}" if signed else f"{number:.{digits}f}"


def format_forward_oi_30d_report(report: dict) -> str:
    """Forward OI raporunu Telegram'da kolay taranır bir karta dönüştür."""
    data = report.get("data") or {}
    download = data.get("download") or {}
    rules = report.get("rules") or {}
    generated = _parse_forward_oi_report_time(report.get("generated_at_utc"))
    generated_text = (generated.strftime("%Y-%m-%d %H:%M UTC")
                      if generated else "bilinmiyor")
    first = _parse_forward_oi_report_time(data.get("feature_first_utc"))
    last = _parse_forward_oi_report_time(data.get("feature_last_utc"))
    period = (f"{first:%Y-%m-%d} → {last:%Y-%m-%d}"
              if first and last else "arşivdeki tüm olgun dönem")

    labels = (
        "P0_top10_gainer5", "P1_plus_volume2x", "P2_plus_any_oi_up",
        "P3_plus_oi_2pct", "P4_plus_short_majority",
        "P5_plus_funding_rise", "Q1_squeeze_proxy_oi_down",
    )
    table = ["Kural N/gün | +2% H/S net med p | +3% H/S net med p"]
    for full_name in labels:
        code = full_name.split("_", 1)[0]
        result = rules.get(full_name) or {}
        tp2 = result.get("tp2_sl1.5_4h") or {}
        tp3 = result.get("tp3_sl1.5_4h") or {}
        n = int(tp2.get("n") or 0)
        days = int(tp2.get("independent_days") or 0)

        def compact(row: dict) -> str:
            return (f"{_metric_text(row.get('target_first_pct_lower'))}/"
                    f"{_metric_text(row.get('stop_first_pct'))} "
                    f"{_metric_text(row.get('mean_net_pct'), 3, True)} "
                    f"{_metric_text(row.get('median_net_pct'), 2, True)} "
                    f"{_metric_text(row.get('bootstrap_p_mean_nonpositive'), 3)}")

        small = " KÜÇÜK" if tp2.get("sample_warning") else ""
        table.append(
            f"{code:<2} {n:>3}/{days:<2} | {compact(tp2)} | {compact(tp3)}{small}")

    accepted = int(data.get("accepted") or 0)
    symbols = int(data.get("symbols") or 0)
    feature_rows = int(data.get("feature_rows") or 0)
    message = (
        "🧪 <b>30 GÜNLÜK FORWARD OI RAPORU</b>\n"
        "<i>Birikimli keşif tekrarı · canlı strateji ve eşikler değişmez</i>\n\n"
        "📦 <b>Veri kapsamı</b>\n"
        f"• Üretim: {generated_text}\n"
        f"• Dönem: {period}\n"
        f"• Arşiv: {accepted:,} satır · {symbols} sembol\n"
        f"• Olgun özellik: {feature_rows:,}\n"
        f"• 5dk veri: {int(download.get('requested') or 0)} gereken · "
        f"{int(download.get('cached') or 0)} önbellek · "
        f"{int(download.get('downloaded') or 0)} yeni · "
        f"{int(download.get('missing') or 0)} eksik · "
        f"{int(download.get('errors') or 0)} hata\n\n"
        "📊 <b>Kural karşılaştırması</b>\n"
        f"<pre>{_html.escape(chr(10).join(table))}</pre>\n"
        "<i>H/S = 4 saatte hedefin / stopun önce görülmesi. "
        "net/med = 12 bp maliyet sonrası ortalama / medyan getiri. "
        "p = günlük bootstrap'ta ortalamanın pozitif olmama oranı.</i>\n\n"
        "🗂 <b>Kural sözlüğü</b>\n"
        "P0 top-10 yükselen · P1 +hacim · P2 +OI · P3 +OI≥%2\n"
        "P4 +short çoğunluğu · P5 +funding artışı · Q1 OI düşüşlü squeeze\n\n"
        "⚠️ <b>Karar</b>\n"
        "Bu bir keşif raporudur; OOS güven oranı veya işlem çağrısı değildir. "
        "90 günlük keşif ve ardından dondurulmuş OOS tamamlanmadan kural açılmaz.\n"
        "📌 Değerlendirme için bu mesajı Claude'a aynen ilet.")
    if len(message) > 4000:
        raise ValueError("30 gunluk Telegram raporu 4000 karakteri asti")
    return message


def _generate_forward_oi_30d_report() -> dict:
    """Ağır 5m analizi alt süreçte çalıştır; tarama/GIL heartbeat'ini ayır."""
    script = Path(__file__).parent / "research" / "eval_forward_oi_barriers.py"
    command = [
        sys.executable, str(script), "--dir", str(ARCHIVE_DIR),
        "--cache-dir", str(FORWARD_OI_5M_CACHE_DIR),
        "--workers", str(FORWARD_OI_REPORT_WORKERS), "--json",
    ]
    result = subprocess.run(
        command, cwd=str(Path(__file__).parent), capture_output=True,
        text=True, encoding="utf-8", errors="replace", timeout=4 * 60 * 60,
        check=False)
    if result.returncode != 0:
        detail = _redact((result.stderr or result.stdout or "bilinmeyen hata"))
        raise RuntimeError(
            f"Forward OI alt sureci kod {result.returncode}: {detail[-500:]}")
    try:
        report = json.loads(result.stdout)
    except (TypeError, ValueError) as exc:
        raise RuntimeError("Forward OI alt sureci gecerli JSON dondurmedi") from exc
    if not isinstance(report, dict) or not isinstance(report.get("rules"), dict):
        raise RuntimeError("Forward OI rapor semasi gecersiz")
    return report


def _finish_forward_oi_30d_report(success: bool, error: str | None = None) -> None:
    now = datetime.now(timezone.utc)
    with _forward_oi_report_state_lock:
        state = _read_forward_oi_report_state_unlocked()
        state["last_completed_at_utc"] = now.isoformat(timespec="seconds")
        if success:
            state["last_status"] = "sent"
            state["last_sent_at_utc"] = now.isoformat(timespec="seconds")
            state.pop("last_error", None)
        else:
            state["last_status"] = "error"
            state["last_error"] = _redact(error or "bilinmeyen hata")[:300]
            # Geçici ağ/Telegram hatası yüzünden bir sonraki ayı bekleme.
            state["next_due_at_utc"] = (
                now + timedelta(hours=24)).isoformat(timespec="seconds")
        _write_forward_oi_report_state_unlocked(state)


def _start_forward_oi_30d_report_worker(now: datetime | None = None) -> bool:
    """Zamanı gelen bir raporu süreçler ve yeniden başlatmalar arasında sahiplenir."""
    global FORWARD_OI_REPORT_WORKER_ACTIVE, FORWARD_OI_REPORT_WORKER_LAST_ERROR
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if not _forward_oi_report_worker_lock.acquire(blocking=False):
        return False
    with _forward_oi_report_state_lock:
        state = _read_forward_oi_report_state_unlocked()
        if not state.get("activated_at_utc") or not _forward_oi_report_due(state, now):
            _forward_oi_report_worker_lock.release()
            return False
        state["last_status"] = "running"
        state["last_started_at_utc"] = now.isoformat(timespec="seconds")
        state["next_due_at_utc"] = (
            now + timedelta(days=FORWARD_OI_REPORT_INTERVAL_DAYS)
        ).isoformat(timespec="seconds")
        if not _write_forward_oi_report_state_unlocked(state):
            _forward_oi_report_worker_lock.release()
            return False
    FORWARD_OI_REPORT_WORKER_ACTIVE = True

    def work() -> None:
        global FORWARD_OI_REPORT_WORKER_ACTIVE, FORWARD_OI_REPORT_WORKER_LAST_ERROR
        try:
            report = _generate_forward_oi_30d_report()
            message = format_forward_oi_30d_report(report)
            if not _telegram_send_text(message, chat_id=TELEGRAM_CHAT_ID):
                raise RuntimeError("Telegram teslimi basarisiz")
            FORWARD_OI_REPORT_WORKER_LAST_ERROR = None
            _finish_forward_oi_30d_report(True)
            print("30 gunluk Forward OI raporu Telegram'a gonderildi",
                  flush=True)
        except Exception as exc:
            safe = f"{type(exc).__name__}: {_redact(str(exc))}"
            FORWARD_OI_REPORT_WORKER_LAST_ERROR = safe[:300]
            _finish_forward_oi_30d_report(False, safe)
            print(f"uyari: 30 gunluk Forward OI raporu basarisiz: {safe}",
                  file=sys.stderr, flush=True)
            _telegram_send_text(
                "⚠️ <b>FORWARD OI RAPORU TAMAMLANAMADI</b>\n"
                "<i>Canlı tarama etkilenmedi.</i>\n"
                "Bot 24 saat sonra otomatik olarak yeniden deneyecek.",
                chat_id=TELEGRAM_CHAT_ID)
        finally:
            FORWARD_OI_REPORT_WORKER_ACTIVE = False
            _forward_oi_report_worker_lock.release()

    try:
        threading.Thread(target=work, name="forward-oi-30d-report",
                         daemon=True).start()
    except Exception as exc:
        safe = f"{type(exc).__name__}: {_redact(str(exc))}"
        FORWARD_OI_REPORT_WORKER_LAST_ERROR = safe[:300]
        FORWARD_OI_REPORT_WORKER_ACTIVE = False
        _forward_oi_report_worker_lock.release()
        _finish_forward_oi_30d_report(False, safe)
        print(f"uyari: 30 gunluk OI rapor iscisi baslatilamadi: {safe}",
              file=sys.stderr, flush=True)
        return False
    return True


def _maybe_forward_oi_30d_report(now: datetime | None = None) -> bool:
    """Her turda ucuz zaman kontrolü; ağır iş yalnız 30 günlük kapıda başlar."""
    if (not FORWARD_OI_30D_REPORT_ENABLED or not ENABLE_TELEGRAM
            or not ARCHIVE_MARKET_DATA):
        return False
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if _initialize_forward_oi_report_schedule(now):
        return False
    with _forward_oi_report_state_lock:
        state = _read_forward_oi_report_state_unlocked()
        due = _forward_oi_report_due(state, now)
    return _start_forward_oi_30d_report_worker(now) if due else False


def _maybe_daily_summary() -> None:
    global _last_summary_day
    if DAILY_SUMMARY_HOUR_UTC < 0 or not ENABLE_TELEGRAM:
        return
    now = datetime.now(timezone.utc)
    today = now.strftime("%Y-%m-%d")
    if now.hour < DAILY_SUMMARY_HOUR_UTC or _last_summary_day == today:
        return
    _last_summary_day = today
    cutoff = now - timedelta(hours=24)
    by_strat: dict[str, int] = {}
    push_by_strat: dict[str, int] = {}
    silent_by_strat: dict[str, int] = {}
    with _recent_lock:
        for s in RECENT_SIGNALS:
            try:
                notified_at = _target_dt(s.get("notified_at"))
                if notified_at < cutoff:
                    continue
                strategy = str(s.get("strategy") or "?")
                by_strat[strategy] = by_strat.get(strategy, 0) + 1
                delivered = bool(s.get("push_allowed")) and not bool(
                    s.get("suppressed"))
                bucket = push_by_strat if delivered else silent_by_strat
                bucket[strategy] = bucket.get(strategy, 0) + 1
            except (TypeError, ValueError, OverflowError):
                continue
    perf: dict = {}
    try:
        perf = realized_performance(max_signals=30, fetch_missing=False) or {}
    except Exception:
        perf = {}
    _telegram_send_text(_format_daily_summary(
        day=today, signal_counts=by_strat, push_counts=push_by_strat,
        silent_counts=silent_by_strat, perf=perf))
    if now.weekday() == 0:                  # pazartesi: tam karne
        try:
            _telegram_send_text(
                "📅 <b>HAFTALIK PERFORMANS KARNESİ</b>\n"
                "<i>Sonuçlar olgunlaşmış sinyaller üzerinden</i>\n\n"
                + _format_performance(realized_performance()))
        except Exception:
            pass


INSTANCE_LOCK_PATH = Path(__file__).parent / _env(
    "INSTANCE_LOCK_FILE", ".signal_bot.lock")
_run_guard = threading.Lock()


def _acquire_instance_file_lock():
    """CLI ve FastAPI dahil ayni makinede yalniz bir tarama lideri tut."""
    handle = open(INSTANCE_LOCK_PATH, "a+b")
    handle.seek(0, os.SEEK_END)
    if handle.tell() == 0:
        handle.write(b"0")
        handle.flush()
    handle.seek(0)
    try:
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (OSError, IOError):
        handle.close()
        return None
    return handle


def _release_instance_file_lock(handle) -> None:
    if handle is None:
        return
    try:
        handle.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    except (OSError, IOError):
        pass
    finally:
        handle.close()


def run_forever(once: bool = False, state: ScanState | None = None) -> None:
    """Tek lider garantili tarama giris noktasi."""
    global INSTANCE_LOCK_HELD, LAST_LOOP_ERROR
    if not _run_guard.acquire(blocking=False):
        LAST_LOOP_ERROR = "bu proseste baska bir tarama dongusu zaten calisiyor"
        raise RuntimeError(LAST_LOOP_ERROR)
    handle = None
    try:
        try:
            handle = _acquire_instance_file_lock()
        except OSError as e:
            LAST_LOOP_ERROR = f"instance kilit dosyasi acilamadi: {e}"
            raise RuntimeError(LAST_LOOP_ERROR) from e
        if handle is None:
            LAST_LOOP_ERROR = (
                f"baska bir bot instance'i aktif veya kilit alinamadi: "
                f"{INSTANCE_LOCK_PATH}")
            raise RuntimeError(LAST_LOOP_ERROR)
        INSTANCE_LOCK_HELD = True
        LAST_LOOP_ERROR = None
        _run_forever_locked(once=once, state=state)
    except Exception as e:
        if not LAST_LOOP_ERROR:
            LAST_LOOP_ERROR = f"{type(e).__name__}: {e}"
        raise
    finally:
        INSTANCE_LOCK_HELD = False
        _release_instance_file_lock(handle)
        _run_guard.release()


def _run_forever_locked(once: bool = False,
                        state: ScanState | None = None) -> None:
    """Tarama dongusu. CLI dogrudan cagirir; server.py bir arka plan
    thread'inde cagirir (web servisini bloklamadan). Bir tarama cyklusundeki
    beklenmeyen hata dongusu OLDURMEZ — 7/24 servis icin dayaniklilik."""
    global LAST_SCAN_AT, LAST_SCAN_COUNT, SCANS_COMPLETED
    global LAST_SCAN_STARTED_AT, LAST_SCAN_FINISHED_AT, LAST_SCAN_SUCCESS_AT
    global LAST_SCAN_FAILURE_AT, LAST_LOOP_HEARTBEAT_AT, LAST_LOOP_ERROR
    global SCAN_IN_PROGRESS, CONSECUTIVE_SCAN_FAILURES
    state = state or ScanState.load()       # restart sonrasi kaldigi yerden
    migrated_targets = _ensure_price_target_state_schema()
    backfilled_targets = _backfill_price_targets_from_signal_log()
    if migrated_targets or backfilled_targets:
        print("fiyat-hedefi analitigi hazirlandi: "
              f"{migrated_targets} kayit guncellendi, "
              f"{backfilled_targets} log olayi geri kuruldu", flush=True)
    LAST_LOOP_HEARTBEAT_AT = datetime.now(timezone.utc).isoformat()
    refresh_universe_if_due(force=True)     # otomatik moddaysa evreni kur
    refresh_perp_map_if_due(force=True)     # statik modda da kontrat esle
    # force=True DEGIL: liste state'ten yuklendiyse yasina bakilir. --once
    # (bulut, 5dk) her turda yeniden indirmesin diye kritik.
    refresh_observe_universe_if_due()
    telegram_preflight()                    # token gecerli mi? (mesaj atmaz)
    # Telegram komut dinleyicisini yalnizca surekli modda baslat (--once'ta degil)
    if ENABLE_TELEGRAM and TELEGRAM_COMMANDS and not once:
        threading.Thread(target=telegram_command_loop, name="tg-commands",
                         daemon=True).start()
    if not once:
        if start_force_order_archive():
            print("USD-M likidasyon arsivi basladi "
                  "(!forceOrder@arr; tum piyasa, snapshot akisi)", flush=True)
        start_dashboard()
        if PUBLISH_ENABLED:
            user = GITHUB_REPO.split("/")[0]
            repo = GITHUB_REPO.split("/")[-1]
            print(f"GitHub Pages yayini ACIK ({PUBLISH_INTERVAL_MIN}dk'da bir): "
                  f"https://{user}.github.io/{repo}/", flush=True)
    print(f"signal_bot basladi: {len(SYMBOLS)} sembol "
          f"({'otomatik evren' if SYMBOL_AUTO else 'statik liste'}), "
          f"{SCAN_INTERVAL_MINUTES}dk aralik "
           f"(telegram={'acik' if ENABLE_TELEGRAM else 'kapali'})", flush=True)
    print(f"arastirma raporu kaynagi: {RESEARCH_REPORT_SOURCE or 'tanimsiz'} "
          f"(bos arsiv={'uyari' if RESEARCH_WEEKLY_REQUIRE_DATA else 'rapor'})",
          flush=True)
    if S2_RESEARCH_PUSH:
        print("S2 arastirma bildirimleri acik (guven DUSUK kalir; genel push "
              "esigi degismez)", flush=True)
    if SHADOW_EXPERIMENTS_ENABLED:
        print("golge deneyler acik: G1 tum aktif USD-M + DL1 resmi tam-token "
              f"delist (push={'acik' if SHADOW_PUSH_ENABLED else 'sessiz'})",
              flush=True)
    if not ENABLE_TELEGRAM:
        if not _ENV_FOUND:
            print(f"NOT: Telegram KAPALI cunku .env bulunamadi.\n"
                  f"     Aranan yer: {_ENV_PATH}\n"
                  f"     Cozum: bu klasorde `cp .env.example .env` yapip "
                  f"TELEGRAM_BOT_TOKEN ve TELEGRAM_CHAT_ID alanlarini doldur.",
                  file=sys.stderr,
                  flush=True)
        else:
            print(f"NOT: .env bulundu ({_ENV_PATH}) ama anahtarlar bos/eksik. "
                  f"Telegram'a ait iki alanin dolu oldugundan emin ol.",
                  file=sys.stderr, flush=True)
    while True:
        started = datetime.now(timezone.utc)
        t0 = started.strftime("%Y-%m-%d %H:%M")
        LAST_SCAN_STARTED_AT = started.isoformat()
        LAST_LOOP_HEARTBEAT_AT = LAST_SCAN_STARTED_AT
        SCAN_IN_PROGRESS = True
        try:
            refresh_universe_if_due()
            refresh_perp_map_if_due()
            refresh_observe_universe_if_due()
            refresh_market_regime_if_due()  # salt S3 meta-verisi; hata icerde tutulur
            n = scan_all(state)
            target_result = update_price_target_tracking()
            completed = datetime.now(timezone.utc).isoformat()
            LAST_SCAN_AT = completed
            LAST_SCAN_SUCCESS_AT = completed
            LAST_SCAN_COUNT = n
            SCANS_COMPLETED += 1
            CONSECUTIVE_SCAN_FAILURES = 0
            LAST_LOOP_ERROR = None
            target_note = (f", fiyat-hedefi {target_result['hits']} yeni dokunus"
                           if target_result.get("hits") else "")
            print(f"[{t0}] tarama bitti: {n} sinyal{target_note}", flush=True)
            if once:
                archive_market_state()
            else:
                _start_archive_worker()
            if once:
                run_shadow_experiments()
            else:
                _start_shadow_worker()
            if once:
                publish_to_github()
            else:
                _start_publish_worker()
            if SCANS_COMPLETED % 12 == 0:
                _start_performance_worker(max_signals=40)
            _maybe_daily_summary()
            _maybe_weekly_research_summary()
            if not once:
                _maybe_forward_oi_30d_report()
        except Exception as e:  # tek dongu hatasi 7/24 servisi dusurmemeli
            LAST_SCAN_FAILURE_AT = datetime.now(timezone.utc).isoformat()
            CONSECUTIVE_SCAN_FAILURES += 1
            LAST_LOOP_ERROR = f"{type(e).__name__}: {e}"
            print(f"hata: tarama dongusunde beklenmeyen hata: {e}",
                   file=sys.stderr, flush=True)
            traceback.print_exc(file=sys.stderr)
        finally:
            LAST_SCAN_FINISHED_AT = datetime.now(timezone.utc).isoformat()
            LAST_LOOP_HEARTBEAT_AT = LAST_SCAN_FINISHED_AT
            SCAN_IN_PROGRESS = False
        if once:
            break
        # bir sonraki bar kapanisindan ~90sn sonrasina hizalan
        period = SCAN_INTERVAL_MINUTES * 60
        now = time.time()
        time.sleep(period - (now % period) + 90)


def _priority(sig: dict) -> int:
    return {"S1+S4": 0, "S1": 1, "S3": 2, "S2": 3,
            "S5": 8, "S6": 9, "G1": 10, "DL1": 11}.get(
                sig["strategy"], 12)


def collect_active_setups() -> tuple[list[dict], int]:
    """O an aktif olan tum kurulumlari (snapshot) toplar, oncelige gore
    siralar. (found, hata_sayisi) doner. Yazdirmaz — hem --check hem Telegram
    /check bunu kullanir. Evreni yenilemez (cagiran karar verir)."""
    state = ScanState()
    found: list[dict] = []
    errors = 0
    for index, sym in enumerate(SYMBOLS):
        try:
            found += scan_symbol(sym, state, snapshot=True)
        except (MarketRateLimitError, MarketTransientError) as e:
            errors += len(SYMBOLS) - index
            print(f"  uyari: ortak piyasa API hatasi; kontrol erken kesildi: {e}",
                  file=sys.stderr, flush=True)
            break
        except Exception as e:
            errors += 1
            print(f"  uyari: {sym} taranamadi: {e}", file=sys.stderr, flush=True)
        time.sleep(0.15)
    # Gozlem kanali: en iyi caba, hatalari ana sayaca YAZILMAZ (kurulumun
    # kendisi dogrulanmamis; --check saglik gostergesini bozmamali).
    if OBSERVE_ENABLED:
        for sym in OBSERVE_SYMBOLS:
            try:
                found += scan_symbol(sym, state, snapshot=True, observe=True)
            except (MarketRateLimitError, MarketTransientError):
                break
            except Exception as e:
                print(f"  uyari: gozlem sembolu {sym} taranamadi: {e}",
                      file=sys.stderr, flush=True)
            time.sleep(0.15)
    found.sort(key=lambda s: (_priority(s), s["symbol"]))
    return found, errors


def run_check() -> int:
    """--check: O AN aktif olan tum kurulumlarin anlik goruntusu. Bildirim
    GONDERMEZ, sadece terminale yazar; state'i kirletmez. "Istedigim an uygun
    strateji var mi?" sorusunun dogru araci (--once degil — o kenar-tetikleme
    oldugu icin soguk baslangicta hicbir sey gostermez)."""
    refresh_universe_if_due(force=True)
    refresh_perp_map_if_due(force=True)
    refresh_observe_universe_if_due(force=True)
    obs_note = (f" + {len(OBSERVE_SYMBOLS)} gozlem (DOGRULANMAMIS)"
                if OBSERVE_ENABLED and OBSERVE_SYMBOLS else "")
    print(f"anlik kontrol: {len(SYMBOLS)} sembol{obs_note} taraniyor "
          f"({'otomatik evren' if SYMBOL_AUTO else 'statik liste'})...",
          flush=True)
    found, errors = collect_active_setups()

    print("=" * 66)
    if not found:
        print("Su an AKTIF kurulum YOK. Kosullarin hicbiri saglanmiyor — bu "
              "normaldir; guclu kurulumlar seyrektir.")
    else:
        print(f"Su an AKTIF {len(found)} kurulum "
              f"(oncelik: S1+S4 > S1 > S3 > S2):\n")
        for sig in found:
            print(f"● {sig['strategy']:<6} {sig['symbol']:<13}"
                  f"{sig['direction']} ({sig['strength']})  "
                  f"fiyat={_fmt_price(sig['price'])}")
            for label, val in _signal_detail_rows(sig):
                print(f"    {label}: {val}")
            print(f"    {sig['note']}")
            for w in _observe_lines(sig):
                print(f"    !! {w}")
            for l in _ref_lines(sig):
                print(f"    {l}")
            print()
    if errors:
        print(f"(not: {errors}/{len(SYMBOLS)} sembol veri cekilemedi)")
    print("=" * 66)
    print("Not: bunlar 'su an kosul aktif' demektir, canli bildirim degil. "
          "Yatirim tavsiyesi degildir.")
    return len(found)


# --------------------------------------------------------------------------
# canli performans takibi (REPORT §10.1): gerceklesen sonuc vs backtest
# --------------------------------------------------------------------------
PERF_CACHE_FILE = Path(__file__).parent / ".perf_cache.json"
PERF_MAX_SIGNALS = _env("PERF_MAX_SIGNALS", 60)
PERF_CACHE_SCHEMA_VERSION = 2
_performance_worker_lock = threading.Lock()
_performance_data_lock = threading.RLock()
PERFORMANCE_WORKER_ACTIVE = False
PERFORMANCE_WORKER_LAST_ERROR: str | None = None


def _perf_key(sig: dict) -> str:
    market = sig.get("performance_market") or (
        "um_perp" if sig.get("strategy") == "S2" else "spot")
    return (f"v{PERF_CACHE_SCHEMA_VERSION}|{market}|{sig['bar_time']}|"
            f"{sig['symbol']}|{sig['strategy']}")


def _signal_universe(sig: dict) -> str:
    """Eski kayitlarda eksik universe alanini deterministik olarak tamamla."""
    if sig.get("observe") or sig.get("strategy") in OBSERVE_STRATEGIES:
        return "observe"
    if sig.get("universe"):
        return str(sig["universe"])
    symbol = str(sig.get("symbol") or "")
    core = {s.strip() for s in DEFAULT_SYMBOLS.split(",") if s.strip()}
    if symbol in core:
        return "core30"
    if symbol in EXTENDED_SET:
        return "extended59"
    return "legacy_unknown"


def _live_cohort_key(sig: dict) -> tuple[str, str, str, str, str]:
    strategy = str(sig.get("strategy") or "?")
    market = sig.get("performance_market") or (
        "um_perp" if strategy == "S2" else "spot")
    confidence = sig.get("confidence") or signal_confidence(strategy)[0]
    return (strategy, _signal_universe(sig), str(confidence),
            str(sig.get("config_version") or "legacy"), str(market))


def _percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    arr = sorted(values)
    if len(arr) == 1:
        return arr[0]
    pos = (len(arr) - 1) * q
    lo, hi = math.floor(pos), math.ceil(pos)
    if lo == hi:
        return arr[lo]
    return arr[lo] + (arr[hi] - arr[lo]) * (pos - lo)


def _wilson_interval(wins: int, n: int, z: float = 1.96) -> tuple[float | None,
                                                                    float | None]:
    if n <= 0:
        return None, None
    p = wins / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    margin = z * math.sqrt((p * (1 - p) + z * z / (4 * n)) / n) / denom
    return max(0.0, centre - margin) * 100, min(1.0, centre + margin) * 100


def _summarize_live_returns(rets: list[float]) -> dict:
    """Ham getiriyi acik maliyet varsayimiyla nete cevirip kuyruk/CI raporla."""
    gross = [float(x) for x in rets if math.isfinite(float(x))]
    net = [x - LIVE_ROUND_TRIP_COST_BPS / 100.0 for x in gross]
    n = len(net)
    wins = sum(1 for x in net if x > 0)
    lo, hi = _wilson_interval(wins, n)
    q10 = _percentile(net, 0.10)
    q90 = _percentile(net, 0.90)
    tail = [x for x in net if q10 is not None and x <= q10]
    return {
        "n": n,
        "gross_median_pct": round(statistics.median(gross), 2) if gross else None,
        "gross_mean_pct": round(statistics.mean(gross), 2) if gross else None,
        "net_median_pct": round(statistics.median(net), 2) if net else None,
        "net_mean_pct": round(statistics.mean(net), 2) if net else None,
        "net_winrate_pct": round(100 * wins / n, 1) if n else None,
        "net_winrate_ci95_low_pct": round(lo, 1) if lo is not None else None,
        "net_winrate_ci95_high_pct": round(hi, 1) if hi is not None else None,
        "q10_net_return_pct": round(q10, 2) if q10 is not None else None,
        "q90_net_return_pct": round(q90, 2) if q90 is not None else None,
        "expected_shortfall_q10_pct": round(statistics.mean(tail), 2) if tail else None,
        "round_trip_cost_bps": LIVE_ROUND_TRIP_COST_BPS,
        "sample_warning": "small_sample" if n < 30 else None,
    }


def _cohort_record(key: tuple[str, str, str, str, str], rets: list[float]) -> dict:
    strategy, universe, confidence, config_version, market = key
    return {
        "strategy": strategy,
        "universe": universe,
        "confidence": confidence,
        "config_version": config_version,
        "performance_market": market,
        "funding_cost_status": "not_modeled" if market == "um_perp" else "not_applicable",
        **_summarize_live_returns(rets),
    }


def _load_perf_cache() -> dict:
    if PERF_CACHE_FILE.exists():
        try:
            return json.loads(PERF_CACHE_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
    return {}


def fetch_klines_at(symbol: str, start_ms: int, limit: int) -> list[dict]:
    r = _spot_get("/api/v3/klines", {"symbol": symbol, "interval": "1h",
                                     "startTime": start_ms, "limit": limit})
    return [{"open_time": k[0], "open": float(k[1]), "close": float(k[4])}
            for k in r.json()]


def fetch_futures_klines_at(symbol: str, start_ms: int, limit: int) -> list[dict]:
    """USD-M perp saatlik mumlari; S2 canli olcumu arastirmayla ayni enstruman."""
    r = _futures_get(
        "/fapi/v1/klines",
        {"symbol": perp_symbol(symbol), "interval": "1h",
         "startTime": start_ms, "limit": limit})
    return [{"open_time": k[0], "open": float(k[1]), "close": float(k[4])}
            for k in r.json()]


def realized_performance(max_signals: int = None,
                         fetch_missing: bool = True) -> dict:
    """Performans cache okuma/hesaplama/yazma islemini proses icinde serilestir."""
    with _performance_data_lock:
        return _realized_performance_unlocked(max_signals, fetch_missing)


def _realized_performance_unlocked(max_signals: int = None,
                                   fetch_missing: bool = True) -> dict:
    """signals.log'daki OLGUNLASMIS sinyallerin gerceklesen getirisini olcer
    (giris: sinyal barindan sonraki barin acilisi; cikis: ufuk sonundaki
    kapanis — arastirmayla birebir ayni tanim). `max_signals` her strateji
    icin ayri tavandir; seyrek stratejiler sik stratejilerce dislanmaz."""
    max_signals = max_signals or PERF_MAX_SIGNALS
    log_path = Path(__file__).parent / SIGNAL_LOG
    if not log_path.exists():
        return {"error": "signals.log yok — henuz sinyal uretilmedi",
                "price_targets": price_target_summary()}
    cache = _load_perf_cache()
    now = datetime.now(timezone.utc)
    universe = set(SYMBOLS)
    excluded_out_of_universe = 0
    rows_by_strategy: dict[str, list[tuple[datetime, dict]]] = {}
    seen: set[str] = set()
    for line in log_path.read_text(encoding="utf-8").splitlines():
        try:
            sig = json.loads(line)
        except ValueError:
            continue
        if sig.get("strategy", "").startswith("TEST"):
            continue
        if sig.get("performance_excluded"):
            continue
        # EVREN FILTRESI (2026-07-26): yalnizca YAPILANDIRILMIS evrendeki
        # semboller olculur. Ek F'de dinamik evren doneminde uretilen cop-coin
        # sinyalleri (TRUMP/BONK/...) aksi halde haftalarca canli medyani
        # asagi ceker ve karar verirken yanlis yonlendirir. qc_export ayni
        # kayitlari "symbol_not_in_configured_universe" ile karantinaya alir;
        # iki arac tutarli olmali. Sayilari raporda gorunur tutuyoruz.
        # Gozlem kayitlari bilerek MUAF: zaten "GOZLEM-" onekli AYRI strateji
        # kovasinda dururlar, dogrulanmis S1/S2/S3 istatistigine karismazlar.
        # Ek F'nin zarari kirlenmeydi; ayri kovada olcmek tam tersi — kanali
        # veriyle degerlendirmenin tek yolu.
        if not sig.get("observe") and sig.get("symbol") not in universe:
            excluded_out_of_universe += 1
            continue
        try:
            bar_t = datetime.fromisoformat(sig["bar_time"])
        except (KeyError, ValueError):
            continue
        h = int(sig.get("horizon_hours") or 0)
        if h <= 0 or bar_t + timedelta(hours=h + 2) > now:
            continue                       # henuz olgunlasmadi
        key = _perf_key(sig)
        if key in seen:
            continue
        seen.add(key)
        rows_by_strategy.setdefault(sig["strategy"], []).append((bar_t, sig))
    rows = []
    for strategy_rows in rows_by_strategy.values():
        strategy_rows.sort(key=lambda item: item[0])
        rows.extend(strategy_rows[-max_signals:])
    rows.sort(key=lambda item: item[0])
    per_strat: dict[str, list[float]] = {}
    per_market: dict[str, str] = {}
    per_cohort: dict[tuple[str, str, str, str, str], list[float]] = {}
    fetch_errors = 0
    for bar_t, sig in rows:
        key = _perf_key(sig)
        h = int(sig["horizon_hours"])
        market = sig.get("performance_market") or (
            "um_perp" if sig.get("strategy") == "S2" else "spot")
        if key in cache:
            cached = cache[key]
            ret = (float(cached["return_pct"]) if isinstance(cached, dict)
                   else float(cached))
        else:
            if not fetch_missing:
                continue
            try:
                fetcher = (fetch_futures_klines_at
                           if market == "um_perp" else fetch_klines_at)
                ks = fetcher(sig["symbol"],
                             int(bar_t.timestamp() * 1000), h + 2)
                if len(ks) < h + 1:
                    continue
                ret = (ks[h]["close"] / ks[1]["open"] - 1) * 100
                cache[key] = {
                    "return_pct": ret,
                    "entry": ks[1]["open"],
                    "exit": ks[h]["close"],
                    "market": market,
                }
                time.sleep(0.1)
            except (MarketRateLimitError, MarketTransientError):
                raise
            except (requests.RequestException, ValueError, KeyError, IndexError):
                fetch_errors += 1
                continue
        strategy = sig["strategy"]
        per_strat.setdefault(strategy, []).append(ret)
        per_market[strategy] = market
        per_cohort.setdefault(_live_cohort_key(sig), []).append(ret)
    try:
        tmp = PERF_CACHE_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(cache), encoding="utf-8")
        tmp.replace(PERF_CACHE_FILE)
    except OSError:
        pass
    out = {"n_total": sum(len(v) for v in per_strat.values()),
           "fetch_errors": fetch_errors,
           "excluded_out_of_universe": excluded_out_of_universe,
           "round_trip_cost_bps": LIVE_ROUND_TRIP_COST_BPS,
           "funding_cost_status": "not_modeled",
           "strategies": {},
           "price_targets": price_target_summary(),
           "cohorts": []}
    for s, rets in sorted(per_strat.items()):
        med = statistics.median(rets)
        bt = STRATEGY_TEST_STATS.get(s, {})
        out["strategies"][s] = {
            "n": len(rets),
            "median_pct": round(med, 2),
            "mean_pct": round(sum(rets) / len(rets), 2),
            "winrate_pct": round(100 * sum(1 for r in rets if r > 0) / len(rets)),
            "bt_median_pct": bt.get("med"), "bt_winrate_pct": bt.get("wr"),
            "bt_scope": bt.get("scope"),
            "performance_market": per_market.get(s, "spot"),
            **_summarize_live_returns(rets),
        }
    out["cohorts"] = [
        _cohort_record(key, rets)
        for key, rets in sorted(per_cohort.items(), key=lambda item: item[0])
    ]
    return out


def _start_performance_worker(max_signals: int = 40) -> bool:
    """API kullanan performans cache tazelemesini tarama heartbeat'inden ayir."""
    global PERFORMANCE_WORKER_ACTIVE
    if not _performance_worker_lock.acquire(blocking=False):
        return False
    PERFORMANCE_WORKER_ACTIVE = True

    def work() -> None:
        global PERFORMANCE_WORKER_ACTIVE, PERFORMANCE_WORKER_LAST_ERROR
        try:
            realized_performance(max_signals=max_signals, fetch_missing=True)
            PERFORMANCE_WORKER_LAST_ERROR = None
        except Exception as e:
            PERFORMANCE_WORKER_LAST_ERROR = f"{type(e).__name__}: {e}"
            print(f"uyari: performans iscisinde hata: {e}",
                  file=sys.stderr, flush=True)
            traceback.print_exc(file=sys.stderr)
        finally:
            PERFORMANCE_WORKER_ACTIVE = False
            _performance_worker_lock.release()

    threading.Thread(target=work, name="performance-refresh", daemon=True).start()
    return True


def _format_price_target_summary(summary: dict) -> list[str]:
    """Coin fiyatindaki +% hedef dokunmalarini kanonik getiriden ayri yazar."""
    if not summary:
        return []
    lines = ["\n🎯 <b>KİŞİSEL FİYAT HEDEFİ KARNESİ</b>",
             "<i>Bildirim fiyatından sonraki kapanmış 5dk mumlar · "
             "kaldıraçsız coin fiyatı</i>"]
    for strategy, levels in sorted(summary.items()):
        for level, row in sorted(levels.items(), key=lambda item: float(item[0])):
            rate = (f"%{row['hit_rate_pct']:g}"
                    if row.get("hit_rate_pct") is not None else "—")
            warning = " · ⚠ küçük N" if row.get("sample_warning") else ""
            lines.append(
                f"• <b>{_html.escape(str(strategy))} TP{float(level):g}</b> · "
                f"{row['hit']}/{row['resolved']} isabet = {rate} · "
                f"{row['pending']} bekliyor{warning}")
    lines.append("<i>TP dokunması ücret/slippage düşülmemiş coin fiyatıdır; ROE "
                 "değildir. Kullanıcının erken çıkış alışkanlığını ölçer; kanonik "
                 "next-bar-open/zaman-çıkışı performansının yerine geçmez.</i>")
    return lines


def _format_daily_performance(perf: dict) -> list[str]:
    """Günlük özete performansın kısa, karşılaştırılabilir görünümünü ekle."""
    if not perf or perf.get("error"):
        return []
    if not perf.get("n_total"):
        return ["• Henüz olgunlaşmış sinyal yok; ufuk süresi dolunca ölçülecek."]
    rows: list[str] = []
    cohorts = perf.get("cohorts") or []
    if cohorts:
        for d in cohorts:
            strategy = _html.escape(str(d.get("strategy") or "?"))
            market = "perp" if d.get("performance_market") == "um_perp" else "spot"
            warning = " · küçük N" if d.get("sample_warning") else ""
            rows.append(
                f"• <b>{strategy}</b> · N={d.get('n', 0)} · "
                f"medyan {float(d.get('net_median_pct', 0)):+.2f}% · "
                f"isabet %{d.get('net_winrate_pct', '—')} · {market}{warning}")
    else:
        for strategy, d in sorted((perf.get("strategies") or {}).items()):
            bt_med = (f" · backtest medyan {float(d['bt_median_pct']):+.2f}%"
                      if d.get("bt_median_pct") is not None else "")
            bt_wr = (f" · backtest isabet %{d['bt_winrate_pct']}"
                     if d.get("bt_winrate_pct") is not None else "")
            rows.append(
                f"• <b>{_html.escape(str(strategy))}</b> · N={d.get('n', 0)} · "
                f"medyan {float(d.get('median_pct', 0)):+.2f}% · "
                f"isabet %{d.get('winrate_pct', '—')}"
                f"{bt_med}{bt_wr}")
    return rows or ["• Performans satırı oluşmadı."]


def _format_daily_summary(*, day: str, signal_counts: dict[str, int],
                          push_counts: dict[str, int],
                          silent_counts: dict[str, int],
                          perf: dict | None = None) -> str:
    """Günlük Telegram mesajını diğer raporlarla aynı kart düzeninde üret."""
    total = sum(signal_counts.values())
    push_total = sum(push_counts.values())
    silent_total = sum(silent_counts.values())
    lines = [
        "☀️ <b>Gunluk ozet</b>",
        f"<i>{_html.escape(day)} · son 24 saat</i>",
        "",
        "🔔 <b>Sinyal olayları</b>",
        f"• Toplam: <b>{total}</b> olay · {push_total} bildirim · "
        f"{silent_total} sessiz kayıt",
    ]
    if signal_counts:
        for strategy in sorted(signal_counts):
            label = _html.escape(str(strategy))
            detail = f"{signal_counts[strategy]} olay"
            if push_counts.get(strategy):
                detail += f" · {push_counts[strategy]} bildirim"
            if silent_counts.get(strategy):
                detail += f" · {silent_counts[strategy]} sessiz"
            lines.append(f"• <b>{label}</b>: {detail}")
    else:
        lines.append("• Yeni sinyal olayı yok.")
    lines += ["", "📡 <b>Tarama</b>",
              f"• Tamamlanan tur: {SCANS_COMPLETED}",
              f"• Evren: {len(SYMBOLS)} sembol",
              f"• Son tarama hatası: {LAST_SCAN_ERRORS}",
              "", "📊 <b>Olgun canlı sonuçlar / karne</b>"]
    lines += _format_daily_performance(perf or {})
    lines += ["", "ℹ️ <b>Hızlı erişim</b>",
              "• /check — şu an aktif koşullar (bildirim göndermez)",
              "• /performans — ayrıntılı canlı karne ve hedef dokunmaları",
              "<i>Bu özet olayları ve ölçümleri gösterir; emir açmaz. "
              "Yatırım tavsiyesi değildir.</i>"]
    return "\n".join(lines)


def _telegram_fit_report(text: str, label: str) -> str:
    """Uzun raporu HTML etiketlerini bozmayacak satır sınırında kısalt."""
    limit = 3900
    if len(text) <= limit:
        return text
    note = (f"\n\n⚠️ <b>{_html.escape(label)}</b> Telegram sınırına sığmadığı "
            "için kısaltıldı; tam ayrıntı web panosunda ve signals.log'da.\n"
            "<i>Bot emir açmaz; yatırım tavsiyesi değildir.</i>")
    kept: list[str] = []
    for line in text.splitlines():
        candidate = "\n".join(kept + [line]) + note
        if len(candidate) > limit:
            break
        kept.append(line)
    return "\n".join(kept) + note


def _format_performance(perf: dict) -> str:
    if "error" in perf:
        lines = ["⚠️ <b>PERFORMANS ÖLÇÜMÜ BAŞARISIZ</b>",
                 _html.escape(str(perf["error"]))]
        lines += _format_price_target_summary(perf.get("price_targets") or {})
        return _telegram_fit_report("\n".join(lines), "Performans raporu")
    excluded = perf.get("excluded_out_of_universe") or 0
    excl_note = (f"\n<i>{excluded} eski kayit guncel evren disinda oldugu icin "
                 "olcume katilmadi (Ek F kontaminasyon donemi).</i>"
                 if excluded else "")
    if perf["n_total"] == 0:
        lines = ["📊 <b>CANLI PERFORMANS</b>",
                 "<i>Henüz olgunlaşmış sinyal yok; ufuk süresi dolunca "
                 "ölçülebilir hale gelir (olgunlasmis = kapanmış).</i>"]
        if excl_note:
            lines.append(excl_note.strip())
        lines += _format_price_target_summary(perf.get("price_targets") or {})
        return _telegram_fit_report("\n".join(lines), "Performans raporu")
    lines = ["📊 <b>CANLI PERFORMANS</b>",
             f"<i>Son {perf['n_total']} olgun sinyal · giriş/çıkış tanımı "
             "backtest ile aynı</i>", "", "✅ <b>DOĞRULANMIŞ KOHORTLAR</b>"]
    observe_lines: list[str] = []
    validated_lines: list[str] = []
    cohorts = perf.get("cohorts") or []
    if cohorts:
        for d in cohorts:
            s = str(d["strategy"])
            market = ("USD-M perp" if d.get("performance_market") == "um_perp"
                      else "spot")
            lo, hi = d.get("net_winrate_ci95_low_pct"), d.get(
                "net_winrate_ci95_high_pct")
            ci = f"%{lo:g}–%{hi:g}" if lo is not None and hi is not None else "—"
            warning = " · ⚠ 작은 N" if d.get("sample_warning") else ""
            bt = STRATEGY_TEST_STATS.get(s) if s not in OBSERVE_STRATEGIES else None
            bt_text = (f" · backtest medyan {bt['med']:+.2f}% · "
                       f"isabet %{bt['wr']}" if bt else "")
            row = (f"• <b>{_html.escape(s)}</b> · N={d['n']} · "
                   f"net medyan {d['net_median_pct']:+.2f}% · "
                   f"net isabet %{d['net_winrate_pct']:g} · 95% GA {ci}"
                   f"{bt_text}\n"
                   f"  {d['universe']} · {d['confidence']} · "
                   f"{d['config_version']} · ort {d['net_mean_pct']:+.2f}% · "
                   f"q10/q90 {d['q10_net_return_pct']:+.2f}% / "
                   f"{d['q90_net_return_pct']:+.2f}% · "
                   f"{market}{warning}")
            # Gozlem kovasi AYRI blokta: dogrulanmis satirlarla ayni listede
            # gorunmesi "ayni statude" izlenimi verirdi.
            (observe_lines if s in OBSERVE_STRATEGIES else validated_lines).append(row)
    else:
        # Eski test/entegrasyon cagiricilari icin geriye uyumlu bicim.
        for s, d in perf["strategies"].items():
            market = ("USD-M perp" if d.get("performance_market") == "um_perp"
                      else "spot")
            cmp_med = (f" (backtest medyan {d['bt_median_pct']:+.2f}%)"
                       if d.get("bt_median_pct") is not None else "")
            cmp_wr = (f" (backtest %{d['bt_winrate_pct']})"
                      if d.get("bt_winrate_pct") is not None else "")
            row = (f"• <b>{_html.escape(str(s))}</b>: N={d['n']} medyan {d['median_pct']:+.2f}%"
                   f"{cmp_med} · isabet %{d['winrate_pct']}{cmp_wr} · "
                   f"ort {d['mean_pct']:+.2f}% · {market}")
            (observe_lines if s in OBSERVE_STRATEGIES else validated_lines).append(row)
    lines += validated_lines or ["• Bu dönemde doğrulanmış kohort yok."]
    if observe_lines:
        lines += ["", "🔬 <b>Gozlem kanali — S5/S6</b>",
                  "<i>DOGRULANMAMIS coinler · karşılaştırılacak backtest yok · "
                  "yalnız kanalı ölçmek için</i>"] + observe_lines
    lines += _format_price_target_summary(perf.get("price_targets") or {})
    if perf["fetch_errors"]:
        lines.append(f"⚠️ {perf['fetch_errors']} sinyal veri hatası nedeniyle ölçülemedi.")
    if excl_note:
        lines.append(excl_note.strip())
    lines.append(f"\n<i>Net = ham getiri − {LIVE_ROUND_TRIP_COST_BPS:g}bp round-trip "
                 "maliyet varsayımı. S2 funding maliyeti modellenmedi. Küçük N'de "
                 "medyan/isabet çok oynaktır; 30+ sinyalden önce hüküm verme. "
                 "Yatırım tavsiyesi değildir.</i>")
    return _telegram_fit_report("\n".join(lines), "Performans raporu")


# --------------------------------------------------------------------------
# web panosu (stdlib http.server — Termux'ta ek kurulum gerektirmez)
# --------------------------------------------------------------------------
DASHBOARD_ENABLED = _env("DASHBOARD_ENABLED", True,
                         cast=lambda v: str(v).strip().lower()
                         in ("1", "true", "yes", "on"))
DASHBOARD_PORT = _env("DASHBOARD_PORT", 8181)

# Strateji ansiklopedisi — panoda karta tiklayinca acilan detay. S1-S4 24 aylik
# backtest'e dayanir; S5/S6 ayri ve acikca "gozlem/backtest yok" etiketlidir.
STRATEGY_DOCS = {
    "S1+S4": {
        "title": "S1+S4 — Hacimli Kapitulasyon Dibi (en guclu sinyal)",
        "how": "S1'in (RSI asiri satim + bullish divergence donusu) uzerine, "
               "son 24 saatte S3 duzeyinde (log-hacim z>=3) bir hacim "
               "patlamasi eklendiginde olusur. Yani hem satis ivmesi tukeniyor "
               "hem de olaganustu hacimle 'teslimiyet' yasaniyor — panik dibi.",
        "entry": "RSI(14)<=22.5 + fiyat yeni dip ama RSI daha yuksek "
                 "(divergence) + son 24s icinde log-hacim z>=3.0.",
        "exit": "Zaman cikisi ~24-72 saat. Backtest'te dogrulanan TEK cikis "
                "kurali budur; fiyat-bazli stop/hedef edge'i azaltir (Ek B).",
        "stats": "Test (ayi rejimi): edge +0.38 vol, p=0.006, 72h kazanma %66. "
                 "Dort rejimin dordunde pozitif. Seyrek: ayda ~6 kez.",
        "risk": "En guvenilir kurulum ama yine de garanti degil. Kotu %10 icin "
                "gosterilen seviye S1 ailesi 24-ay proxy'sidir; S1+S4'e ozel "
                "quantile degildir. Kaldirac kaybi carpar.",
    },
    "S1": {
        "title": "S1 — RSI Asiri Satim + Bullish Divergence (donus)",
        "how": "Bir coin sert satildiginda RSI 'asiri satim' bolgesine iner. "
               "Fiyat yeni bir dip yaparken RSI onceki dipten YUKSEK kalirsa, "
               "buna 'bullish divergence' denir: satici gucu tukeniyor demektir "
               "-> yukari donus adayi.",
        "entry": "RSI(14) <= 22.5 VE fiyat son ~60 barin dibinin altinda VE o "
                 "eski dibe gore RSI daha yuksek (uyumsuzluk).",
        "exit": "Zaman cikisi ~24 saat.",
        "stats": "Cekirdek test: edge +0.31 vol, p=0.006, kazanma %59, "
                 "medyan +0.67%. 24 ay all-sample: kazanma %62, medyan +0.93%. "
                 "Gun-kumesi test p=0.080; bagimlilik altinda kanit sinirda.",
        "risk": "Kotu %10: -4.5%. Dusen bicaga erken girmek — divergence sarti "
                "tam bunu suzmek icin var ama kusursuz degil.",
    },
    "S3": {
        "title": "S3 — Hacim Anomalisi (kisa vadeli momentum)",
        "how": "Olaganustu hacimle gelen bir YESIL mum, kisa vadede alicilarin "
               "kontrolu ele aldigini gosterir; momentumun birkac saat devam "
               "etme egilimi vardir. Hacim, ham degil LOG-donusumlu z-skorla "
               "olculur (ham hacim asiri gurultuluydu).",
        "entry": "log1p(hacim) z-skoru >= 3.0 (168 saatlik pencereye gore) VE "
                 "bar yesil (kapanis > acilis).",
        "exit": "Zaman cikisi ~4 saat (kisa ufuk).",
        "stats": "Cekirdek test: 4h edge +0.25 vol, p<0.001, medyan ~0.00%, "
                 "kazanma %49. Nihai secimde test'e 2. bakis serhi vardir.",
        "risk": "Kotu %10: -2.8%. Tek basina zayif bir islem; daha cok "
                "'momentum var' bilgisidir. Pump'in tepesine girme riski.",
    },
    "S2": {
        "title": "S2 — Funding Squeeze (en dusuk guven)",
        "how": "Vadeli piyasada short'lar cok kalabaliksa, 'funding' negatif "
               "olur: short'lar long'lara para oder. Bu kalabalik bazen "
               "sikisip fiyati yukari iter (short squeeze). Ust uste 2 negatif "
               "funding, kaliciligi teyit eder.",
        "entry": "Son 2 funding orani <= -0.03%.",
        "exit": "Zaman cikisi ~72 saat.",
        "stats": "Cekirdek test: edge +0.14, olay p=0.08, gun-kumesi p=0.347, "
                 "medyan -0.36%, kazanma %47. Sinyaller ~5 sembolde yogunlasiyor.",
        "risk": "EN RISKLI: kotu %10 = -9.1% (en derin kuyruk). Istege gore "
                "yalniz ARASTIRMA etiketiyle push edilir; bu guven seviyesini "
                "yukseltmez. Panoda ve /performans'ta ayri izlenir. "
                "Iyilestirme yollari tukendi "
                 "(REPORT Ek D); canli veri birikince kaldir/tut karari verilecek.",
    },
    "S5": {
        "title": "S5 — Dinamik Evren S1+S4 Gozlem Kanali",
        "how": "S1+S4 ile ayni matematiksel kosulu, dogrulanmis 89 coin disinda "
               "likidite filtresinden gecen dinamik sembollerde izler. Ayri "
               "strateji adi, bu olaylarin dogrulanmis S1+S4 karnesine "
               "karismasini engeller.",
        "entry": "RSI(14)<=22.5 + bullish divergence + son 24 saatte "
                 "log-hacim z>=3.0; yalniz dinamik gozlem evreninde.",
        "exit": "Olcum ufku 24 saat; giris sonraki saatlik bar acilisi, cikis "
                "ufuk kapanisi. Bot emir vermez.",
        "stats": "Bu sembol grubunda secimden once yapilmis backtest YOK. Canli "
                 "sonuclar yalniz observe/config kohortunda birikir; N<30 kucuk "
                 "ornek olarak isaretlenir.",
        "risk": "DOGRULANMAMIS kanal. Dinamik evren gecmiste cop-coin ve "
                "survivorship/selection riski tasidi; bildirim merak/olcum "
                "amacli olup guven kademesi degildir.",
    },
    "S6": {
        "title": "S6 — Dinamik Evren S1 Gozlem Kanali",
        "how": "S1'in RSI asiri satim + bullish divergence kosulunu, "
               "dogrulanmis evren disindaki likit sembollerde ayri kovada izler.",
        "entry": "RSI(14)<=22.5 ve bullish divergence; dinamik gozlem evreni.",
        "exit": "Olcum ufku 24 saat; giris sonraki saatlik bar acilisi, cikis "
                "ufuk kapanisi. Bot emir vermez.",
        "stats": "Backtest YOK. Ek F benzeri dinamik evrende sade S1'in kotu "
                 "canli gecmisi nedeniyle sonuclar dogrulanmis S1 ile asla "
                 "birlestirilmez.",
        "risk": "En yuksek belirsizlikteki gozlem kanali. N>=30 ve farkli "
                "rejimler gorulmeden guvenilirlik cikarimi yapilamaz.",
    },
    "G1": {
        "title": "G1 — Gunluk Yukselen + Hacim/OI + Short Kalabaligi",
        "how": "Tum aktif Binance USD-M perpetual sozlesmeleri 24 saatlik "
               "getiriye gore siralanir. Ilk 10'da, kapanmis saatlik hacmi "
               "onceki 24 saatin medyaninin en az 2 kati, OI artisi en az %2 "
               "ve global hesap long/short orani 1'in altindaysa golge LONG "
               "olayi uretilir.",
        "entry": "Olcum girisi sonraki 1s mum acilisidir. Canli bildirimde "
                 "tarama anindaki USD-M ticker fiyati gosterilir; kosulu "
                 "doguran kapanmis 1s mum fiyati ve bildirim gecikmesi ayri "
                 "satirlarda verilir.",
        "exit": "Dondurulmus sonuc ufku 4 saattir; +%2/+%3 dokunma ayrica "
                "kisisel hedef karnesinde izlenir. Bot emir vermez.",
        "stats": "Tarihsel train RED: N=401, 4s net ortalama -%0,13, medyan "
                 "-%0,30, isabet %45,9. Bu nedenle guven puani degil GOZLEM.",
        "risk": "Yukselen coin kovalamak ters donus, spread ve tasfiye riski "
                "tasir. Long/short verisi hesap sayisidir, para buyuklugu degil.",
    },
    "DL1": {
        "title": "DL1 — Resmi Binance Tam-Token Delist Olay Arsivi",
        "how": "Yalniz Binance Delisting katalogundaki tam-token spot delist "
               "duyurularini kabul eder; pair/margin/futures kaldirmalarini "
               "dislar. Binance spot ile Bybit/OKX perpetual bulunabilirligini "
               "zaman damgali arşivler.",
        "entry": "Bu bir giris sinyali degil olay alarmidir. Duyuru, tespit ve "
                 "delist saatleri ayri kaydedilir.",
        "exit": "PRE olcumu duyuru sonrasi ilk 1s acilistan delist oncesi son "
                "kapanisa; POST olcumu dis borsada 4/24/72s short getirisine "
                "bakacak. POST icin veri yeni birikiyor.",
        "stats": "DL1-PRE RED: N=107, net medyan -%53,58, isabet %8,4. Donem "
                 "ici MFE medyani +%18,58 olsa da deliste kadar tutmak cok zararli.",
        "risk": "Delist varliklarda likidite kaybi, spread, kontratin erken "
                "kapanmasi ve short edememe riski cok yuksektir; VAR etiketi "
                "yalniz anlik bulunabilirliktir.",
    },
}


def _signal_why(sig: dict) -> str:
    """Bu sinyalin TAM OLARAK hangi kosullarla tetiklendigini duz Turkce anlatir
    (panoda satira tiklayinca acilir)."""
    strat = sig.get("strategy", "")
    # Gozlem sinyali (S5/S6) ayni S1 mantigiyle uretilir; taban stratejiye
    # cevirip ayni aciklamayi ver, ama basina DOGRULANMAMIS uyarisini koy.
    base = OBSERVE_BASE_OF.get(strat, strat).split("+")[0]
    p = list(_observe_lines(sig))
    if base == "S1":
        rsi = sig.get("rsi")
        p.append(f"RSI(14) = {rsi}: asiri satim esigi {RSI_OVERSOLD}'in altinda.")
        p.append("Fiyat son ~60 barin dibinin altina indi ama RSI o dipten "
                 "daha yuksek kaldi (bullish divergence = satis ivmesi tukeniyor).")
        if "+S4" in strat:
            p.append(f"AYRICA son {CONFLUENCE_LOOKBACK_HOURS}s icinde log-hacim "
                     f"z >= {VOLUME_ZSCORE_THRESHOLD} hacim patlamasi vardi "
                     "(hacimli kapitulasyon) -> STRONG'a yukseltildi.")
    elif base == "S3":
        z = sig.get("volume_logz")
        p.append(f"Log-hacim z-skoru = {z}: {VOLUME_ZSCORE_THRESHOLD} esigini "
                 f"asti ({VOLUME_ZSCORE_WINDOW}s ortalamasina gore olaganustu "
                 "hacim).")
        p.append("Bar YESIL kapandi (kapanis > acilis) -> alici yonlu momentum, "
                 "kisa vadeli devam beklentisi.")
    elif base == "S2":
        fp = sig.get("funding_pct") or []
        vals = ", ".join(f"{x}%" for x in fp)
        window = (f", yaklasik {sig['funding_window_hours']:g}s pencere"
                  if sig.get("funding_window_hours") else "")
        p.append(f"Son {FUNDING_PERSISTENCE} funding orani ({vals}) "
                 f"{FUNDING_SQUEEZE_THRESHOLD_PCT}% esiginin altinda{window}: "
                 "short'lar "
                  "long'lara oduyor -> kalabalik short, sikisma adayi.")
    elif strat == "G1":
        p.append(f"24s sirasi #{sig.get('rank_24h')}, getiri "
                 f"{sig.get('return_24h_pct')}%; 1s hacim "
                 f"{sig.get('volume_ratio')}x ve OI "
                 f"{sig.get('oi_change_1h_pct')}% artti.")
        p.append(f"Global hesap long/short={sig.get('global_long_short_ratio')} "
                 "(<1 = short hesap sayisi fazla). Tum kosullar kapanmis 1s "
                 "verisinde birlikte ilk kez saglandi.")
    elif strat == "DL1":
        p.append("Resmi Binance tam-token delist duyurusu bulundu; spot pair "
                 "kaldirma veya margin duyurusu degildir.")
        p.append(f"Duyuru {sig.get('announcement_at')}; spot islemler "
                 f"{sig.get('delist_at')} aninda duracak. Bybit perp="
                 f"{sig.get('bybit_perp_available')}, OKX swap="
                 f"{sig.get('okx_perp_available')} anlik snapshot olarak kaydedildi.")
    conf = sig.get("confidence")
    evid = sig.get("confidence_note")
    if not conf:
        conf, fallback_evid = signal_confidence(strat)
        evid = evid or fallback_evid
    elif not evid:
        evid = signal_confidence(strat)[1]
    p.append(f"Guven: {conf} — {evid}.")
    return " ".join(p)


def _lan_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return "127.0.0.1"


def build_dashboard_data(max_rows: int = 400) -> dict:
    """Pano JSON'u: sinyal gecmisi (aktiflerde guncel fiyata gore anlik K/Z,
    olgunlarda gerceklesen sonuc), strateji karneleri (backtest vs canli),
    bot durumu. Ag cagrisi YAPMAZ — fiyatlar son taramadan (<=tarama araligi
    eski), gerceklesenler perf cache'ten."""
    now = datetime.now(timezone.utc)
    cache = _load_perf_cache()
    target_summary = price_target_summary()
    path_summary = price_path_summary()
    rows = []
    log_path = Path(__file__).parent / SIGNAL_LOG
    lines = []
    if log_path.exists():
        try:
            lines = log_path.read_text(encoding="utf-8").splitlines()[-max_rows:]
        except OSError:
            lines = []
    live_rets: dict[str, list[float]] = {}  # geriye uyumlu strateji toplami
    cohort_rets: dict[tuple[str, str, str, str, str], list[float]] = {}
    seen_events: set[str] = set()
    for line in lines:
        try:
            sig = json.loads(line)
            bar_t = datetime.fromisoformat(sig["bar_time"])
        except (ValueError, KeyError):
            continue
        strat = sig.get("strategy", "?")
        if strat.startswith("TEST"):
            continue
        event_id = _signal_event_id(sig)
        if event_id in seen_events:
            continue
        seen_events.add(event_id)
        h = int(sig.get("horizon_hours") or 0)
        ref = sig.get("ref") or {}
        provisional_entry = ref.get("entry_ref") or sig.get("price")
        deadline = bar_t + timedelta(hours=1 + h)
        performance_excluded = bool(sig.get("performance_excluded"))
        matured = (not performance_excluded and h > 0
                   and now >= bar_t + timedelta(hours=h + 2))
        conf = sig.get("confidence") or signal_confidence(strat)[0]
        cached_perf = cache.get(_perf_key(sig)) if matured else None
        if isinstance(cached_perf, dict):
            realized = cached_perf.get("return_pct")
            entry = cached_perf.get("entry") or provisional_entry
        else:
            realized = cached_perf
            entry = provisional_entry
        symbol = sig.get("symbol", "")
        performance_market = sig.get("performance_market") or (
            "um_perp" if strat == "S2" else "spot")
        entry_market = sig.get("signal_market") or "spot"
        same_market = entry_market == performance_market
        if performance_market == "um_perp":
            observed_at = LAST_PERP_AT.get(symbol)
            observed_price = LAST_PERP_PRICE.get(symbol)
        else:
            observed_at = LAST_SPOT_AT.get(symbol)
            observed_price = LAST_SPOT_CLOSE.get(symbol)
        price_age_s = (max(0.0, time.time() - observed_at)
                       if observed_at is not None else None)
        price_stale = (price_age_s is None
                       or price_age_s > PRICE_STALE_AFTER_MINUTES * 60)
        cur = None if price_stale or not same_market else observed_price
        gross = None
        if not matured and cur and entry:
            gross = round((cur / entry - 1) * 100, 4)
        elif matured and realized is not None:
            gross = float(realized)
        net = (round(gross - LIVE_ROUND_TRIP_COST_BPS / 100.0, 4)
               if gross is not None else None)
        if matured and realized is not None:
            live_rets.setdefault(strat, []).append(float(realized))
            cohort_rets.setdefault(_live_cohort_key(sig), []).append(float(realized))
        stored_suppressed = sig.get("suppressed")
        silenced = (bool(stored_suppressed)
                    if stored_suppressed is not None else
                    CONF_RANK.get(conf, 2) < CONF_RANK.get(
                        NOTIFY_MIN_CONFIDENCE, 1))
        rows.append({
            "t": sig["bar_time"], "event_id": event_id,
            "strategy": strat, "symbol": sig.get("symbol"),
            "direction": sig.get("direction"),
            "confidence": conf, "strength": sig.get("strength"),
            "universe": _signal_universe(sig),
            "config_version": sig.get("config_version") or "legacy",
            "entry": entry, "horizon_h": h,
            "entry_basis": ("next_bar_open" if matured
                            and isinstance(cached_perf, dict)
                            else "signal_time_provisional"),
            "entry_market": entry_market,
            "performance_market": performance_market,
            "exit_by": deadline.strftime("%Y-%m-%d %H:%M"),
            "status": ("OLAY" if performance_excluded else
                       "OLGUN" if matured else "AKTIF"),
            "remaining_h": (None if matured
                            else max(0, round((deadline - now).total_seconds()
                                              / 3600, 1))),
            "cur_price": cur if not matured else None,
            "price_age_seconds": (round(price_age_s, 1)
                                  if price_age_s is not None else None),
            "price_stale": price_stale,
            "pnl_unavailable_reason": (
                "event_only_no_trade_outcome" if performance_excluded else
                "entry_and_performance_market_mismatch"
                if not matured and not same_market else
                "market_price_stale_or_missing"
                if not matured and price_stale else None),
            "gross_pnl_pct": gross,
            "net_pnl_pct": net,
            "pnl_pct": net,  # pano/UI icin geriye uyumlu ad artik NET getiridir
            "round_trip_cost_bps": LIVE_ROUND_TRIP_COST_BPS,
            "funding_cost_status": ("not_modeled"
                                    if performance_market == "um_perp"
                                    else "not_applicable"),
            "pnl_kind": ("event_only_no_trade_outcome" if performance_excluded
                          else "gerceklesen_next_open_net_cost_assumption"
                          if matured else
                          "tahmini_sinyal_kapanisi_net_cost_assumption"),
            "market_regime": sig.get("market_regime"),
            "market_regime_source": sig.get("market_regime_source"),
            "market_regime_as_of": sig.get("market_regime_as_of"),
            "silenced": silenced,
            "push_allowed": sig.get("push_allowed", not silenced),
            "notification_status": ("SESSIZ" if silenced else "GONDERILDI"),
            "suppression_reason": sig.get("suppression_reason"),
            "note": sig.get("note", ""),
            "why": _signal_why(sig),
            "detail": _signal_detail_rows(sig),      # (etiket, deger) ciftleri
            "price_target": price_target_for_event(event_id),
            "ref": {k: ref.get(k) for k in
                    ("median_price", "q10_price", "q90_price", "sigma_h_pct",
                      "hist_median_pct", "hist_q10_pct", "hist_q90_pct",
                     "touch", "stopt", "stats_scope")} if ref else None,
        })
    rows.reverse()
    strategies = []
    for key in ("S1+S4", "S1", "S3", "S2", "S5", "S6", "G1", "DL1"):
        bt = STRATEGY_TEST_STATS.get(key, {})
        conf, evid = signal_confidence(key)
        lr = live_rets.get(key, [])
        summary = _summarize_live_returns(lr)
        cohorts = [
            _cohort_record(cohort_key, rets)
            for cohort_key, rets in sorted(cohort_rets.items(),
                                           key=lambda item: item[0])
            if cohort_key[0] == key
        ]
        strategies.append({
            "name": key, "confidence": conf, "evidence": evid,
            "pushed": (S2_RESEARCH_PUSH if key == "S2" else
                       SHADOW_PUSH_ENABLED if key in SHADOW_STRATEGIES else
                       OBSERVE_PUSH if key in OBSERVE_STRATEGIES else
                       CONF_RANK.get(conf, 2) >= CONF_RANK.get(
                           NOTIFY_MIN_CONFIDENCE, 1)),
            "bt_h": bt.get("h"), "bt_med": bt.get("med"), "bt_wr": bt.get("wr"),
            "bt_q10": bt.get("q10"), "bt_q90": bt.get("q90"), "bt_n": bt.get("n"),
            "bt_scope": bt.get("scope"),
            # Eski istemciler icin korunur; yeni pano asagidaki kohortlari kullanir.
            "live_n": summary["n"],
            "live_med": summary["net_median_pct"],
            "live_wr": summary["net_winrate_pct"],
            "live_cohorts": cohorts,
            "price_targets": target_summary.get(key, {}),
            "price_path": path_summary.get(key, {}),
            "user_success": target_summary.get(key, {}).get(
                _target_level_key(USER_SUCCESS_TARGET_PCT), {}),
        })
    return {
        "now": now.isoformat(timespec="seconds"),
        "status": {
            "scans": SCANS_COMPLETED, "last_scan": LAST_SCAN_AT,
            "errors": LAST_SCAN_ERRORS, "symbols": len(SYMBOLS),
            "interval_min": SCAN_INTERVAL_MINUTES,
            "min_conf": NOTIFY_MIN_CONFIDENCE,
            "s2_research_push": S2_RESEARCH_PUSH,
            "disabled": sorted(DISABLED_STRATEGIES),
            "started": STARTED_AT,
            "round_trip_cost_bps": LIVE_ROUND_TRIP_COST_BPS,
            "funding_cost_status": "not_modeled",
            "price_target_tracking_enabled": PRICE_TARGET_TRACKING_ENABLED,
            "price_target_levels_pct": list(PRICE_TARGET_LEVELS_PCT),
            "price_target_notify_levels_pct": list(
                PRICE_TARGET_NOTIFY_LEVELS_PCT),
            "user_success_target_pct": USER_SUCCESS_TARGET_PCT,
            "market_regime": market_regime_snapshot(),
            "shadow_experiments_enabled": SHADOW_EXPERIMENTS_ENABLED,
            "shadow_push_enabled": SHADOW_PUSH_ENABLED,
            "shadow_worker_active": SHADOW_WORKER_ACTIVE,
            "shadow_worker_last_error": SHADOW_WORKER_LAST_ERROR,
            # bildirim kanali sagligi: sinyal uretilse de gonderim
            # basarisiz olabilir; uzaktan gorunur olmali (2026-07-26)
            "telegram_enabled": ENABLE_TELEGRAM,
            "telegram_identity": TELEGRAM_IDENTITY,
            "notify_health": NOTIFY_HEALTH,
        },
        "strategies": strategies,
        "price_targets": target_summary,
        "price_paths": path_summary,
        "docs": STRATEGY_DOCS,
        "signals": rows,
    }


_DASHBOARD_HTML_TEMPLATE_LEGACY = """<!doctype html><html lang="tr"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Signal Bot Panosu</title><style>
:root{--bg:#0b1220;--card:#111a2e;--line:#22304f;--tx:#eaf0fb;--mut:#8aa0c6;
--up:#2ecc71;--dn:#e06c6c;--bl:#2c7be5}
*{box-sizing:border-box;margin:0}body{background:var(--bg);color:var(--tx);
font:14px/1.45 system-ui,Segoe UI,Roboto,sans-serif;padding:14px;max-width:1100px;margin:0 auto}
h1{font-size:20px;margin-bottom:4px}.sub{color:var(--mut);font-size:12px;margin-bottom:12px}
.chips{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:14px}
.chip{background:var(--card);border:1px solid var(--line);border-radius:14px;
padding:3px 10px;font-size:12px;color:var(--mut)}.chip b{color:var(--tx)}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:10px;margin-bottom:12px}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px;cursor:pointer;transition:border-color .15s}
.card:hover{border-color:var(--bl)}.card h3{font-size:15px;display:flex;justify-content:space-between;align-items:center;gap:6px}
.badge{font-size:10px;border-radius:8px;padding:2px 7px;font-weight:700;white-space:nowrap}
.b3{background:#1d4ed8}.b2{background:#0e7490}.b1{background:#a16207}.b0{background:#7f1d1d}
.bo{background:#4b5563}.cohort{border-top:1px solid var(--line);margin-top:7px;
padding-top:6px;font-size:11px;color:var(--mut);line-height:1.45}.cohort b{color:var(--tx)}
.card .row{display:flex;justify-content:space-between;font-size:12px;color:var(--mut);margin-top:5px}
.card .row b{color:var(--tx)}.off{opacity:.55}.hint{color:var(--bl);font-size:11px;margin-top:7px}
.doc{background:var(--card);border:1px solid var(--bl);border-radius:12px;padding:14px 16px;margin-bottom:14px}
.doc h2{font-size:16px;margin-bottom:8px}.doc p{font-size:13px;margin:6px 0;color:#c7d3ea}
.doc p b{color:var(--bl)}.doc .x{float:right;cursor:pointer;color:var(--mut)}
.ctrl{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:10px;align-items:center;font-size:13px}
select,input{background:var(--card);color:var(--tx);border:1px solid var(--line);
border-radius:8px;padding:6px 8px;font-size:13px}
.tablewrap{overflow-x:auto;background:var(--card);border:1px solid var(--line);border-radius:12px}
table{border-collapse:collapse;width:100%;font-size:12.5px;min-width:820px}
th,td{padding:7px 9px;text-align:left;border-bottom:1px solid var(--line);white-space:nowrap}
th{color:var(--mut);font-weight:600;position:sticky;top:0;background:var(--card)}
tr.sig{cursor:pointer}tr.sig:hover td{background:#16203a}
.up{color:var(--up);font-weight:700}.dn{color:var(--dn);font-weight:700}
.tag{font-size:10px;border:1px solid var(--line);border-radius:6px;padding:1px 5px;color:var(--mut)}
.drawer td{background:#0d1526;white-space:normal}
.why{font-size:13px;color:#c7d3ea;line-height:1.55;margin-bottom:8px}
.kv{display:grid;grid-template-columns:auto 1fr;gap:3px 14px;font-size:12px;color:var(--mut);max-width:520px}
.kv b{color:var(--tx)}
.foot{color:#5b6b88;font-size:11px;margin-top:12px;line-height:1.6}
@media(max-width:600px){body{padding:8px}}
</style></head><body>
<h1>📡 Signal Bot Panosu</h1>
<div class="sub">Karta veya sinyal satırına tıkla → nasıl çalıştığını / neden geldiğini gösterir.</div>
<div class="chips" id="chips">yükleniyor…</div>
<div class="cards" id="cards"></div>
<div id="docWrap"></div>
<div class="ctrl">
 Strateji <select id="fStrat"><option value="">hepsi</option>
 <option>S1+S4</option><option>S1</option><option>S3</option><option>S2</option>
 <option>S5</option><option>S6</option></select>
 Durum <select id="fStat"><option value="">hepsi</option>
 <option>AKTIF</option><option>OLGUN</option></select>
 Pozisyon $ <input id="fNot" type="number" value="100" min="1" style="width:84px">
 <span class="chip" id="cnt"></span>
</div>
<div class="tablewrap"><table><thead><tr>
<th>Zaman (UTC)</th><th>Strateji</th><th>Güven</th><th>Sembol</th><th>Giriş ref</th>
<th>Son çıkış</th><th>Durum</th><th>TP2 / TP3</th><th>Net K/Z %</th><th>Net K/Z $</th><th>Not</th>
</tr></thead><tbody id="rows"></tbody></table></div>
<div class="foot" id="foot"></div>
<script>
const DATA_URL="{{DATA_URL}}";
const B={3:"b3",2:"b2",1:"b1",0:"b0",[-1]:"bo"},R={"COK YUKSEK":3,"YUKSEK":2,"ORTA":1,"DUSUK":0,"GOZLEM":-1};
const esc=s=>(s==null?"":String(s)).replace(/[&<>]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;"}[c]));
const fp=x=>{if(x==null)return "—";x=Number(x);
 if(x>=1)return x.toPrecision(6).replace(/\\.?0+$/,"");
 return x.toFixed(10).replace(/0+$/,"").replace(/\\.$/,"")||"0"};
const fpc=x=>x==null?'<span class="tag">ölçülüyor</span>':
 `<span class="${x>=0?'up':'dn'}">${x>=0?'+':''}${x.toFixed(2)}%</span>`;
function tpCell(r){const p=r.price_target;if(!p)return '<span class="tag">izlenmiyor</span>';
 return (p.targets||[]).map(t=>{const mark=t.status==='HIT'?'✓':t.status==='MISSED'?'✕':'…';
  const cls=t.status==='HIT'?'up':t.status==='MISSED'?'dn':'tag';
  return `<span class="${cls}" title="hedef fiyat ${fp(t.price)}">TP${t.level_pct}${mark}</span>`}).join(' ');}
let D=null,openDoc=null,openRow=null;
function notifyChip(s){
 const h=s.notify_health||{},tg=h.telegram||{};
 const bad=(ch,on)=>on===false?"kapalı":(ch.last_error&&!ch.last_ok?"HATA":
   (ch.fail&&ch.last_error?"son hata var":"çalışıyor"));
 const tgTxt=bad(tg,s.telegram_enabled);
 const warn=(t)=>t==="çalışıyor"?"":' style="border-color:#e06c6c;color:#e06c6c"';
 return `<span class="chip"${warn(tgTxt)}>Telegram <b>${tgTxt}</b>`+
  `${tg.ok?` (${tg.ok} ok`:""}${tg.fail?`, ${tg.fail} hata`:""}${tg.ok?")":""}</span>`+
  (tg.last_error?`<span class="chip" style="border-color:#e06c6c;color:#e06c6c">son TG hatası: ${esc(tg.last_error)}</span>`:"");}
function toggleDoc(name){openDoc=openDoc===name?null:name;drawDoc();}
function drawDoc(){const w=document.getElementById("docWrap");
 if(!openDoc||!D.docs||!D.docs[openDoc]){w.innerHTML="";return;}
 const d=D.docs[openDoc];
 w.innerHTML=`<div class="doc"><span class="x" onclick="toggleDoc(null)">✕ kapat</span>
  <h2>${esc(d.title)}</h2>
  <p><b>Nasıl çalışır:</b> ${esc(d.how)}</p>
  <p><b>Giriş koşulu:</b> ${esc(d.entry)}</p>
  <p><b>Çıkış:</b> ${esc(d.exit)}</p>
  <p><b>Backtest:</b> ${esc(d.stats)}</p>
  <p><b>Risk:</b> ${esc(d.risk)}</p></div>`;
 w.scrollIntoView({behavior:"smooth",block:"nearest"});}
function drawer(r){const rf=r.ref||{};
 const touch=(rf.touch||[]).map(t=>`+${t[0]}% → %${t[1]}`).join(" · ");
 const stopt=(rf.stopt||[]).map(t=>`-${t[0]}% → %${t[1]}`).join(" · ");
 let ref="";
  if(rf.median_price!=null)ref=`<div class="kv">
   ${rf.stats_scope?`<span>Tarihsel kaynak</span><b>${esc(rf.stats_scope)}</b>`:""}
   <span>Tarihsel medyan senaryo</span><b>${fp(rf.median_price)} (${rf.hist_median_pct>=0?'+':''}${rf.hist_median_pct}%)</b>
  <span>Kötü %10 senaryo</span><b>${fp(rf.q10_price)} (${rf.hist_q10_pct}%)</b>
  <span>İyi %10 senaryo</span><b>${fp(rf.q90_price)} (+${rf.hist_q90_pct}%)</b>
  ${rf.sigma_h_pct!=null?`<span>Tipik dalgalanma (±1σ)</span><b>±${rf.sigma_h_pct}%</b>`:""}
  ${touch?`<span>Hedefe dokunma olasılığı</span><b>${touch}</b>`:""}
  ${stopt?`<span>Stop'a dokunma olasılığı</span><b>${stopt}</b>`:""}
 </div>`;
 const meta=[`Evren: <b>${esc(r.universe)}</b>`,`Config: <b>${esc(r.config_version)}</b>`,
  `Round-trip maliyet: <b>${r.round_trip_cost_bps}bp</b>`,
  r.funding_cost_status==="not_modeled"?"Funding maliyeti: <b>modellenmedi</b>":""].filter(Boolean).join(" · ");
 const det=(r.detail||[]).map(d=>`${esc(d[0])}: <b>${esc(d[1])}</b>`).join(" · ");
 const pt=r.price_target;
 const ptRows=pt?`<div class="kv" style="margin:8px 0">
  <span>Fiyat-hedefi referansı</span><b>${fp(pt.entry_ref)} (bildirim fiyatı)</b>
  ${(pt.targets||[]).map(t=>`<span>TP${t.level_pct} · ${fp(t.price)}</span><b>${esc(t.status)}${t.hit_at?' · '+esc(t.hit_at.slice(0,16)):''}</b>`).join('')}
  <span>En iyi / en ters hareket</span><b>${pt.max_favorable_pct==null?'—':pt.max_favorable_pct.toFixed(2)+'%'} / ${pt.max_adverse_pct==null?'—':pt.max_adverse_pct.toFixed(2)+'%'}</b>
  <span>İzleme aralığı</span><b>${esc((pt.started_at||'').slice(0,16))} → ${esc((pt.expires_at||'').slice(0,16))}</b>
 </div>`:'';
 return `<div class="why">🔍 <b>Neden geldi:</b> ${esc(r.why)}</div>
  <div class="kv" style="margin-bottom:8px"><span>Ölçüm kohortu</span><b>${meta}</b></div>
  ${det?`<div class="kv" style="margin-bottom:8px"><span>Ölçümler</span><b>${det}</b></div>`:""}
  ${ptRows}
  ${ref}
  <div style="font-size:11px;color:var(--mut);margin-top:8px">TP2/TP3 coinin brüt fiyat değişimidir; ücret/slippage düşülmez ve kaldıraçlı ROE değildir. Bot emir vermez. Fiyat senaryoları 24 aylık dağılımdan; emir seviyesi değildir.</div>`;}
function draw(){if(!D)return;const s=D.status;
 document.getElementById("chips").innerHTML=
  `<span class="chip">⏱ tarama <b>${s.interval_min}dk</b></span>`+
  `<span class="chip">son tarama <b>${(s.last_scan||"—").slice(11,16)}</b></span>`+
  `<span class="chip">evren <b>${s.symbols}</b></span>`+
  `<span class="chip">hata <b>${s.errors}</b></span>`+
  `<span class="chip">push eşiği <b>${s.min_conf}+</b></span>`+
  `<span class="chip">kapalı <b>${s.disabled.join(",")||"yok"}</b></span>`+
   `<span class="chip">net maliyet <b>${s.round_trip_cost_bps}bp</b></span>`+
   `<span class="chip">fiyat hedefi <b>${s.price_target_tracking_enabled?'TP '+s.price_target_levels_pct.join('/'):'kapalı'}</b></span>`+
   `<span class="chip">S3 rejim <b>${esc((s.market_regime||{}).label||"UNKNOWN")}</b></span>`+
  notifyChip(s);
 document.getElementById("cards").innerHTML=D.strategies.map(x=>{
   const live=(x.live_cohorts||[]).length?(x.live_cohorts||[]).map(c=>{
    const ci=c.net_winrate_ci95_low_pct==null?"—":`%${c.net_winrate_ci95_low_pct}–%${c.net_winrate_ci95_high_pct}`;
    return `<div class="cohort"><b>${esc(c.universe)} · ${esc(c.confidence)} · ${esc(c.config_version)}</b><br>`+
     `net med ${c.net_median_pct>=0?'+':''}${c.net_median_pct}% · isabet %${c.net_winrate_pct} `+
     `(95% GA ${ci}) · q10 ${c.q10_net_return_pct}% · N=${c.n}`+
     `${c.sample_warning?' · ⚠ küçük N':''}${c.funding_cost_status==='not_modeled'?' · funding yok':''}</div>`}).join(""):
     '<div class="cohort">henüz olgun kohort yok</div>';
   const bt=(x.bt_med==null)?"—":`${x.bt_med>=0?'+':''}${x.bt_med}% / %${x.bt_wr} (N=${x.bt_n})`;
   const tails=(x.bt_q10==null||x.bt_q90==null)?"raporlanmadı":`${x.bt_q10}% / +${x.bt_q90}%`;
   const tp=Object.entries(x.price_targets||{}).map(([level,t])=>
    `TP${level}: ${t.hit_rate_pct==null?'—':'%'+t.hit_rate_pct} (${t.hit}/${t.resolved}, ${t.pending} bekliyor)`).join(' · ');
   return `<div class="card ${x.pushed?'':'off'}" onclick="toggleDoc('${x.name}')"><h3>${x.name}
    <span class="badge ${B[R[x.confidence]]}">${x.confidence}</span></h3>
    <div class="row"><span>Tarihsel test (ham${x.bt_h?' · '+x.bt_h+'h':''})</span><b>${bt}</b></div>
     <div class="row"><span>Tarihsel kötü %10 / iyi %10</span><b>${tails}</b></div>
     ${live}
     <div class="row"><span>Canlı fiyat-hedefi</span><b>${tp||'henüz kayıt yok'}</b></div>
     <div class="row"><span>Push</span><b>${x.pushed?"açık":"SESSİZ"}</b></div>
   <div class="hint">▸ nasıl çalışır (tıkla)</div></div>`}).join("");
 drawDoc();
 const fs=document.getElementById("fStrat").value,ft=document.getElementById("fStat").value,
 not=+document.getElementById("fNot").value||100;
 const rows=D.signals.filter(r=>(!fs||r.strategy===fs)&&(!ft||r.status===ft));
 document.getElementById("cnt").textContent=rows.length+" sinyal";
 document.getElementById("rows").innerHTML=rows.map((r,i)=>{
  const usd=r.pnl_pct==null?"—":`<span class="${r.pnl_pct>=0?'up':'dn'}">${(r.pnl_pct*not/100).toFixed(2)}$</span>`;
   const noPnl=r.pnl_unavailable_reason?
    ` <span class="tag">${r.pnl_unavailable_reason==="entry_and_performance_market_mismatch"?"PİYASA UYUŞMUYOR":"FİYAT ESKİ/YOK"}</span>`:"";
   const st=r.status==="AKTIF"?`AKTİF <span class="tag">${r.remaining_h}h kaldı</span>${noPnl}`:"OLGUN";
  const main=`<tr class="sig" data-i="${i}"><td>${r.t.slice(0,16).replace("T"," ")}</td>
   <td><b>${r.strategy}</b>${r.silenced?' <span class="tag">SESSİZ</span>':''}</td>
   <td><span class="badge ${B[R[r.confidence]]}">${r.confidence}</span></td>
   <td>${r.symbol}</td><td>${fp(r.entry)}</td><td>${r.exit_by}</td><td>${st}</td><td>${tpCell(r)}</td>
   <td>${fpc(r.pnl_pct)}</td><td>${usd}</td>
   <td style="white-space:normal;min-width:170px;color:var(--mut)">▸ ${esc(r.note)}</td></tr>`;
   const dr=`<tr class="drawer" data-d="${i}" ${openRow===r.t+r.symbol?"":"hidden"}><td colspan="11">${drawer(r)}</td></tr>`;
   return main+dr}).join("")
   ||'<tr><td colspan="11" style="color:var(--mut)">kayıt yok</td></tr>';
 document.getElementById("foot").innerHTML=D.foot||FOOT;}
const FOOT=`TP2/TP3: yalnız Telegram'a gerçekten gönderilmiş sinyallerde, bildirim fiyatından sonra coinin kaldıraçsız brüt fiyatının +%2/+%3 hedefe dokunmasını gösterir; ücret/slippage düşülmez, ROE değildir ve emir kapatmaz. K/Z tanımı: <b>AKTİF</b> satırlarda sinyal anındaki aynı piyasa fiyatı geçici giriş referansıdır; gerçek gözlem zamanı tazelik sınırını aşarsa veya giriş/performans piyasası uyuşmazsa K/Z gösterilmez. <b>OLGUN</b> satırlarda gerçekleşen sonuç giriş = sonraki bar açılışı, çıkış = ufuk kapanışıyla hesaplanır. Gösterilen K/Z, açıkça yazılan round-trip maliyet varsayımı düşülmüş NET değerdir; S2 funding maliyeti modellenmemiştir. S2 sonucu USD-M perpetual, diğerleri spot mumlarından ölçülür. "SESSİZ" = teslim politikası nedeniyle loglandı ama push edilmedi. S3 BULL/BEAR etiketi salt gözlemdir, sinyali filtrelemez. Bu bir izleme panosudur; yatırım tavsiyesi değildir.`;
document.getElementById("rows").addEventListener("click",e=>{
 const tr=e.target.closest("tr.sig");if(!tr)return;
 const rows=D.signals.filter(r=>{const fs=document.getElementById("fStrat").value,
  ft=document.getElementById("fStat").value;return(!fs||r.strategy===fs)&&(!ft||r.status===ft)});
 const r=rows[+tr.dataset.i];const key=r.t+r.symbol;openRow=openRow===key?null:key;draw();});
async function load(){try{const sep=DATA_URL.includes("?")?"&":"?";
 const r=await fetch(DATA_URL+sep+"t="+Date.now(),{cache:"no-store"});D=await r.json();
 if(!D.foot)D.foot=FOOT;draw();}
 catch(e){document.getElementById("chips").innerHTML='<span class="chip">bağlantı hatası</span>';}}
["fStrat","fStat","fNot"].forEach(id=>document.getElementById(id).addEventListener("input",draw));
load();setInterval(load,60000);
</script></body></html>"""

# Arayüz ayrı dosyada tutulur; GitHub Pages yayını yine tek index.html üretir.
# Eski gömülü sürüm, paketleme hatasında yerel panonun tamamen kaybolmaması için
# salt-okunur fallback'tir.
try:
    DASHBOARD_HTML_TEMPLATE = (Path(__file__).parent / "dashboard.html").read_text(
        encoding="utf-8")
except OSError:
    DASHBOARD_HTML_TEMPLATE = _DASHBOARD_HTML_TEMPLATE_LEGACY


def dashboard_html(data_url: str = "/api/dashboard") -> str:
    return DASHBOARD_HTML_TEMPLATE.replace("{{DATA_URL}}", data_url)


class _DashHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/api/dashboard"):
            try:
                body = json.dumps(build_dashboard_data(),
                                  ensure_ascii=False).encode("utf-8")
                ct = "application/json; charset=utf-8"
            except Exception as e:
                body = json.dumps({"error": str(e)}).encode("utf-8")
                ct = "application/json; charset=utf-8"
        elif self.path in ("/", "/index.html"):
            body = dashboard_html().encode("utf-8")
            ct = "text/html; charset=utf-8"
        else:
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", ct)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):          # erisim loglariyla konsolu bogma
        pass


def start_dashboard() -> None:
    """Panoyu arka plan thread'inde baslatir (yalniz surekli modda)."""
    if not DASHBOARD_ENABLED:
        return
    try:
        srv = ThreadingHTTPServer(("0.0.0.0", DASHBOARD_PORT), _DashHandler)
    except OSError as e:
        print(f"uyari: pano baslatilamadi (port {DASHBOARD_PORT}): {e}",
              file=sys.stderr, flush=True)
        return
    threading.Thread(target=srv.serve_forever, name="dashboard",
                     daemon=True).start()
    print(f"web panosu: http://{_lan_ip()}:{DASHBOARD_PORT}  "
          f"(ayni Wi-Fi'daki telefon/bilgisayardan ac)", flush=True)


def _gh_put_file(path: str, content_b: bytes, message: str,
                 sha: str | None, branch: str | None = None) -> str | None:
    """GitHub Contents API ile dosya olustur/guncelle; yeni sha doner."""
    branch = branch or GITHUB_PAGES_BRANCH
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{path}"
    payload = {"message": message, "branch": branch,
               "content": base64.b64encode(content_b).decode("ascii")}
    if sha:
        payload["sha"] = sha
    r = requests.put(url, json=payload, timeout=30, headers={
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json"})
    r.raise_for_status()
    return r.json().get("content", {}).get("sha")


def _gh_headers() -> dict:
    return {"Authorization": f"Bearer {GITHUB_TOKEN}",
            "Accept": "application/vnd.github+json"}


def _gh_get_sha(path: str, branch: str | None = None) -> str | None:
    branch = branch or GITHUB_PAGES_BRANCH
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{path}"
    r = requests.get(url, params={"ref": branch}, timeout=30,
                     headers=_gh_headers())
    if r.status_code == 404:
        return None
    r.raise_for_status()
    return r.json().get("sha")


def _gh_ensure_branch(branch: str | None = None) -> None:
    """Pages branch'i yoksa varsayilan branch'ten olusturur (self-bootstrap —
    kullanicinin git ile branch acmasina gerek yok)."""
    branch = branch or GITHUB_PAGES_BRANCH
    base = f"https://api.github.com/repos/{GITHUB_REPO}"
    h = _gh_headers()
    r = requests.get(f"{base}/git/ref/heads/{branch}",
                     headers=h, timeout=30)
    if r.status_code == 200:
        return
    if r.status_code != 404:
        r.raise_for_status()
    repo = requests.get(base, headers=h, timeout=30)
    repo.raise_for_status()
    default = repo.json().get("default_branch", "main")
    ref = requests.get(f"{base}/git/ref/heads/{default}", headers=h, timeout=30)
    ref.raise_for_status()
    sha = ref.json()["object"]["sha"]
    cr = requests.post(f"{base}/git/refs", headers=h, timeout=30,
                       json={"ref": f"refs/heads/{branch}",
                             "sha": sha})
    cr.raise_for_status()
    print(f"GitHub: '{branch}' branch'i olusturuldu", flush=True)


def _git_blob_sha(content_b: bytes) -> str:
    header = f"blob {len(content_b)}\0".encode("ascii")
    return hashlib.sha1(header + content_b).hexdigest()


def _gh_put_if_changed(path: str, content_b: bytes, message: str,
                       branch: str, known_sha: str | None = None) -> tuple[str | None,
                                                                          bool]:
    """Icerik ayniysa commit olusturmadan mevcut blob SHA'sini dondurur."""
    remote_sha = known_sha if known_sha is not None else _gh_get_sha(path, branch)
    if remote_sha == _git_blob_sha(content_b):
        return remote_sha, False
    return _gh_put_file(path, content_b, message, remote_sha, branch), True


def _github_data_url() -> str:
    return (f"https://raw.githubusercontent.com/{GITHUB_REPO}/"
            f"{GITHUB_DATA_BRANCH}/data.json")


def publish_to_github(force: bool = False) -> None:
    """Canli veriyi data branch'ine, statik panoyu Pages branch'ine yazar.

    Sik veri commit'leri Pages build'i tetiklemez; index.html yalniz sablon
    degistiginde commit edilir. Basarisizlik tarama dongusunu ASLA aksatmaz.
    ONEMLI: yayimlanan JSON'da SIR YOK (sinyaller + fiyatlar + istatistik;
    token/chat-id/anahtar icermez)."""
    global _last_publish, _gh_sha, PUBLISH_ENABLED, PUBLISH_WORKER_LAST_ERROR
    if not PUBLISH_ENABLED:
        return
    if not force and time.time() - _last_publish < PUBLISH_INTERVAL_MIN * 60:
        return
    _last_publish = time.time()
    try:
        data = json.dumps(build_dashboard_data(), ensure_ascii=False).encode("utf-8")
        _gh_ensure_branch(GITHUB_DATA_BRANCH)
        if _gh_sha is None:
            _gh_sha = _gh_get_sha("data.json", GITHUB_DATA_BRANCH)
        _gh_sha, _ = _gh_put_if_changed(
            "data.json", data,
            f"data {datetime.now(timezone.utc):%Y-%m-%d %H:%M}",
            GITHUB_DATA_BRANCH, _gh_sha)

        _gh_ensure_branch(GITHUB_PAGES_BRANCH)
        page = dashboard_html(_github_data_url()).encode("utf-8")
        _gh_put_if_changed("index.html", page, "dashboard: index.html",
                           GITHUB_PAGES_BRANCH)
        PUBLISH_WORKER_LAST_ERROR = None
    except requests.RequestException as e:
        PUBLISH_WORKER_LAST_ERROR = f"{type(e).__name__}: {_redact(str(e))}"
        _gh_sha = None                     # sha bayatlamis olabilir -> yeniden al
        code = getattr(getattr(e, "response", None), "status_code", 0)
        if code in (401, 403, 404):
            PUBLISH_ENABLED = False        # tekrar tekrar denemesin (log spam)
            print("uyari: GitHub yayini KAPATILDI — token yetersiz. "
                  f"(HTTP {code}) Yayimlama icin token'in bu repoda "
                  "'Contents: read and WRITE' yetkisi olmali. 'git pull' icin "
                  "kullandigin okuma-yetkili token yazamaz. .env'e yazma-yetkili "
                  "bir GITHUB_TOKEN ekleyip botu yeniden baslat.",
                  file=sys.stderr, flush=True)
        else:
            print(f"uyari: GitHub Pages yayini basarisiz: {_redact(str(e))}",
                  file=sys.stderr, flush=True)


def _start_publish_worker() -> bool:
    """GitHub API yayimini ana tarama heartbeat'inden ayir."""
    global PUBLISH_WORKER_ACTIVE
    if not PUBLISH_ENABLED:
        return False
    if not _publish_worker_lock.acquire(blocking=False):
        return False
    PUBLISH_WORKER_ACTIVE = True

    def work() -> None:
        global PUBLISH_WORKER_ACTIVE, PUBLISH_WORKER_LAST_ERROR
        try:
            publish_to_github()
        except Exception as e:
            PUBLISH_WORKER_LAST_ERROR = f"{type(e).__name__}: {e}"
            print(f"uyari: GitHub yayin iscisinde beklenmeyen hata: "
                  f"{_redact(str(e))}", file=sys.stderr, flush=True)
            traceback.print_exc(file=sys.stderr)
        finally:
            PUBLISH_WORKER_ACTIVE = False
            _publish_worker_lock.release()

    threading.Thread(target=work, name="github-publish", daemon=True).start()
    return True


def _format_check_for_telegram(found: list[dict], errors: int) -> str:
    """/check cevabını sinyal kartlarıyla aynı düzende biçimlendir."""
    if not found:
        return ("🔎 <b>ANLIK KONTROL</b>\n"
                "<i>Aktif koşul aranıyor · bildirim gönderilmez</i>\n\n"
                "✅ <b>Şu an aktif kurulum yok.</b>\n"
                "Koşulların hiçbiri sağlanmıyor — güçlü kurulumların seyrek "
                "olması normaldir.")
    lines = ["🔎 <b>ANLIK KONTROL</b>",
             "<i>Aktif koşullar · bu kontrol bildirim göndermez</i>", "",
             f"✅ <b>{len(found)} aktif kurulum</b>",
             "Öncelik: S1+S4 → S1 → S3 → S2"]
    shown_count = 0
    for s in found[:25]:
        conf = s.get("confidence") or signal_confidence(s["strategy"])[0]
        direction = _html.escape(str(s.get("direction") or "LONG"))
        strategy = _html.escape(str(s.get("strategy") or "?"))
        symbol = _html.escape(str(s.get("symbol") or "?"))
        card = ["", f"• <b>{strategy} — {symbol} {direction}</b>",
                f"  💰 Fiyat: <b>{_fmt_price(s.get('price'))}</b> · "
                f"ufuk: ~{s.get('horizon_hours', '?')} saat · "
                f"güven: {_html.escape(str(conf))}"]
        detail_rows = _signal_detail_rows(s)
        if detail_rows:
            label, value = detail_rows[0]
            card.append(f"  {_html.escape(str(label))}: "
                        f"{_html.escape(str(value))}")
        card.append("  📝 Koşul şu anda aktif; giriş kararı kullanıcıya aittir.")
        # Telegram limiti: öncelikli kurulumları mümkün olduğunca göster,
        # fakat 25 adet üç satırlı kartın mesajı taşırmasına izin verme.
        if len("\n".join(lines + card)) > 3700:
            break
        lines += card
        shown_count += 1
    omitted = len(found) - shown_count
    if omitted:
        lines.append(f"\n… ayrıca {omitted} kurulum daha")
    if errors:
        lines.append(f"\n⚠️ {errors} sembol veri hatası nedeniyle atlandı.")
    lines.append("\n<i>Detay/referans: terminalde --check. Emir açılmaz; "
                 "yatırım tavsiyesi değildir.</i>")
    return "\n".join(lines)


def _format_status_for_telegram() -> str:
    """Bot durumunu tek bakışta okunabilir Telegram kartı olarak üret."""
    mode = ("otomatik evren" if SYMBOL_AUTO
            else f"çekirdek 30 + geniş {len(EXTENDED_SET)}, statik")
    disabled = ", ".join(sorted(DISABLED_STRATEGIES)) or "yok"
    observe = (f"{len(OBSERVE_SYMBOLS)} doğrulanmamış sembol · bildirim "
               f"{'AÇIK' if OBSERVE_PUSH else 'sessiz'}"
               if OBSERVE_ENABLED else "kapalı")
    return (
        "ℹ️ <b>BOT DURUMU</b>\n"
        "<i>Çalışma, bildirim ve araştırma özeti</i>\n\n"
        "📡 <b>Tarama</b>\n"
        f"• Evren: {len(SYMBOLS)} sembol · {mode}\n"
        f"• Tamamlanan tur: {SCANS_COMPLETED}\n"
        f"• Son tarama: {_html.escape(str(LAST_SCAN_AT or '(henüz yok)'))}\n"
        f"• Son tarama hatası: {LAST_SCAN_ERRORS}\n\n"
        "🔔 <b>Bildirim kapısı</b>\n"
        f"• Genel eşik: {_html.escape(str(NOTIFY_MIN_CONFIDENCE))}+\n"
        f"• Sessiz stratejiler: {_html.escape(disabled)}\n"
        f"• S2 araştırma bildirimi: {'AÇIK' if S2_RESEARCH_PUSH else 'sessiz'} "
        "(güven DÜŞÜK)\n"
        f"• Gözlem kanalı: {observe}\n\n"
        "👥 <b>Erişim</b>\n"
        f"• Telegram aboneleri: {len(TELEGRAM_SUBSCRIBERS)}\n\n"
        "<i>/check anlık koşulları, /performans olgun sonuçları gösterir. "
        "Bot emir açmaz; yatırım tavsiyesi değildir.</i>"
    )


def handle_telegram_command(text: str, chat_id: str) -> None:
    """Tek bir /komutu isler ve cevabi KOMUTU GONDEREN chat'e yollar."""
    parts = text.strip().split()
    cmd = parts[0].lower().lstrip("/").split("@")[0]
    args = parts[1:]
    owner = _is_owner(chat_id)
    if cmd in ("start", "help", "menu"):
        admin_help = ("\n<b>Yonetim (yalniz sen):</b>\n"
                      "/aboneler — abone listesi\n"
                      "/onayla &lt;id&gt; — bekleyen arkadasi ekle\n"
                      "/kaldir &lt;id&gt; — aboneligi kaldir\n") if owner else ""
        _telegram_send_text(
            "🤖 <b>SIGNAL BOT</b> ✅\n"
            "<i>Telegram bildirim ve ölçüm merkezi</i>\n\n"
            "🔎 <b>Anlık</b>\n"
            "• /check — aktif koşullar (bildirim göndermez)\n"
            "• /status — çalışma ve bildirim durumu\n\n"
            "📊 <b>Raporlar</b>\n"
            "• /performans — canlı sonuçlar ve hedef karnesi\n"
            "• /arastirma — OI/funding/likidasyon hazırlığı\n\n"
            "👤 <b>Erişim</b>\n"
            "• /myid — kendi chat ID'in\n"
            "• /katil — botu kullanmak için izin iste\n"
            "• /menu — düğmeleri yeniden göster\n"
            + admin_help +
            "\nYeni sinyaller otomatik olarak buraya düşer. "
            "Bot emir açmaz; yatırım tavsiyesi değildir.", chat_id=chat_id,
            reply_markup=_menu_keyboard(owner))
    elif cmd == "aboneler":
        if not owner:
            _telegram_send_text("Bu komut yalniz bot sahibine acik.",
                                chat_id=chat_id)
            return
        lines = ["<b>Aboneler</b> (sinyaller bunlara gider):"]
        for cid in TELEGRAM_SUBSCRIBERS:
            tag = ("sen" if str(cid) == str(TELEGRAM_CHAT_ID)
                   else ("env" if cid in TELEGRAM_ALLOWED
                         else DYNAMIC_SUBSCRIBERS.get(cid, "") or "onayli"))
            lines.append(f"• <code>{_html.escape(str(cid))}</code> — "
                         f"{_html.escape(tag)}")
        if PENDING_JOINS:
            lines.append("\n<b>Bekleyen istekler</b> (/onayla &lt;id&gt;):")
            for cid, label in PENDING_JOINS.items():
                lines.append(f"• <code>{_html.escape(cid)}</code> — "
                             f"{_html.escape(label)}")
        else:
            lines.append("\nBekleyen istek yok.")
        _telegram_send_text("\n".join(lines), chat_id=chat_id)
    elif cmd in ("onayla", "approve"):
        if not owner:
            _telegram_send_text("Bu komut yalniz bot sahibine acik.",
                                chat_id=chat_id)
            return
        if not args:
            hint = (", ".join(PENDING_JOINS) if PENDING_JOINS
                    else "bekleyen istek yok")
            _telegram_send_text(f"Kullanim: /onayla &lt;chat_id&gt;\n"
                                f"Bekleyenler: {_html.escape(hint)}",
                                chat_id=chat_id)
            return
        target = args[0].strip()
        label = PENDING_JOINS.get(target, " ".join(args[1:]) or "onayli")
        if add_subscriber(target, label):
            _telegram_send_text(
                f"✅ <code>{_html.escape(target)}</code> "
                f"({_html.escape(label)}) eklendi. Sinyaller artik ona da "
                "gidecek.", chat_id=chat_id)
            _telegram_send_text(
                "✅ Erisimin onaylandi! Artik sinyaller sana da gelecek.\n"
                "Komutlar icin /help yaz.\n\n"
                "<i>Bu bir uyari sistemidir; yatirim tavsiyesi degildir.</i>",
                chat_id=target)
        else:
            _telegram_send_text(
                f"<code>{_html.escape(target)}</code> zaten abone.",
                chat_id=chat_id)
    elif cmd in ("kaldir", "remove"):
        if not owner:
            _telegram_send_text("Bu komut yalniz bot sahibine acik.",
                                chat_id=chat_id)
            return
        if not args:
            _telegram_send_text("Kullanim: /kaldir &lt;chat_id&gt;",
                                chat_id=chat_id)
            return
        target = args[0].strip()
        if remove_subscriber(target):
            _telegram_send_text(
                f"🗑 <code>{_html.escape(target)}</code> cikarildi.",
                chat_id=chat_id)
        else:
            _telegram_send_text(
                "Cikarilamadi: ya abone degil ya da .env'deki sabit listede "
                "(onu .env'den silmen gerekir).", chat_id=chat_id)
    elif cmd == "status":
        _telegram_send_text(_format_status_for_telegram(), chat_id=chat_id)
    elif cmd in ("performans", "performance", "perf"):
        if not _check_lock.acquire(blocking=False):
            _telegram_send_text("⏳ <b>Rapor zaten hazırlanıyor.</b>\n"
                                "Biraz sonra tekrar dene.", chat_id=chat_id)
            return
        try:
            _telegram_send_text("📊 <b>PERFORMANS HESAPLANIYOR</b>\n"
                                "<i>Geçmiş mumlar ve canlı sonuçlar okunuyor…</i>",
                                chat_id=chat_id)
            _telegram_send_text(_format_performance(realized_performance()),
                                chat_id=chat_id)
        except Exception as e:
            _telegram_send_text("⚠️ <b>PERFORMANS ÖLÇÜLEMEDİ</b>\n"
                                f"{_html.escape(str(e))}", chat_id=chat_id)
        finally:
            _check_lock.release()
    elif cmd in ("arastirma", "research", "oi"):
        if not _check_lock.acquire(blocking=False):
            _telegram_send_text("⏳ <b>Başka bir rapor hazırlanıyor.</b>\n"
                                "Biraz sonra tekrar dene.", chat_id=chat_id)
            return
        try:
            _telegram_send_text(
                format_research_readiness(research_readiness_report()),
                chat_id=chat_id)
        except Exception as e:
            _telegram_send_text(
                "⚠️ <b>ARAŞTIRMA ARŞİVİ OKUNAMADI</b>\n"
                f"{_html.escape(str(e))}", chat_id=chat_id)
        finally:
            _check_lock.release()
    elif cmd == "check":
        if not _check_lock.acquire(blocking=False):
            _telegram_send_text("⏳ <b>Anlık kontrol zaten çalışıyor.</b>\n"
                                "Birkaç saniye sonra tekrar dene.", chat_id=chat_id)
            return
        try:
            _telegram_send_text("🔎 <b>ANLIK KONTROL ÇALIŞIYOR</b>\n"
                                "<i>Koşullar taranıyor…</i>", chat_id=chat_id)
            found, errors = collect_active_setups()
            _telegram_send_text(_format_check_for_telegram(found, errors),
                                chat_id=chat_id)
        except Exception as e:
            _telegram_send_text("⚠️ <b>ANLIK KONTROL BAŞARISIZ</b>\n"
                                f"{_html.escape(str(e))}", chat_id=chat_id)
        finally:
            _check_lock.release()
    else:
        _telegram_send_text(f"❓ <b>Bilinmeyen komut:</b> /{_html.escape(cmd)}\n"
                            "Komut listesi için /help yaz.", chat_id=chat_id)


def handle_callback_query(cq: dict) -> None:
    """Satir-ici dugme basimlarini isler (su an: katilim onay/red).

    GUVENLIK: eylemi YAPAN kisi (callback_query.from) SAHIP olmalidir —
    onayli bir arkadas, sahibin mesajini bir sekilde gorse bile baska
    arkadas ekleyemez. Ayrica bilinmeyen callback verisi sessizce yutulur.
    """
    cq_id = str(cq.get("id", ""))
    data = str(cq.get("data") or "")
    actor = str(((cq.get("from") or {}).get("id")) or "")
    reply_chat = str((((cq.get("message") or {}).get("chat")) or {}).get("id")
                     or actor)
    if not _is_owner(actor):
        _telegram_answer_callback(cq_id, "Bu islem yalniz bot sahibine acik.")
        return
    action, _, target = data.partition(":")
    target = target.strip()
    if not target:
        _telegram_answer_callback(cq_id, "Gecersiz istek.")
        return
    if action == "ok":
        label = PENDING_JOINS.get(target, "onayli")
        if add_subscriber(target, label):
            _telegram_answer_callback(cq_id, "Onaylandi ✅")
            _telegram_send_text(
                f"✅ <code>{_html.escape(target)}</code> "
                f"({_html.escape(label)}) eklendi.", chat_id=reply_chat)
            _telegram_send_text(
                "✅ Erisimin onaylandi! Artik sinyaller sana da gelecek.\n"
                "Dugmeler icin /start yaz.\n\n"
                "<i>Bu bir uyari sistemidir; yatirim tavsiyesi degildir.</i>",
                chat_id=target, reply_markup=_menu_keyboard(False))
        else:
            _telegram_answer_callback(cq_id, "Zaten abone.")
    elif action == "no":
        PENDING_JOINS.pop(target, None)
        _telegram_answer_callback(cq_id, "Reddedildi ❌")
        _telegram_send_text(
            f"❌ <code>{_html.escape(target)}</code> istegi reddedildi.",
            chat_id=reply_chat)
    else:
        _telegram_answer_callback(cq_id, "Bilinmeyen islem.")


def telegram_command_loop() -> None:
    """getUpdates long-polling ile /komutlari dinler. GUVENLIK: yalnizca
    yapilandirilmis TELEGRAM_CHAT_ID'den gelen mesajlara cevap verir (botu
    bulan bir yabanci komut veremez). Dis-baglanti oldugu icin ev NAT'i
    arkasinda, public URL/acik port olmadan calisir."""
    if not ENABLE_TELEGRAM:
        return
    base = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"
    offset: int | None = None
    conflict_streak = 0
    print("telegram komut dinleyici basladi "
          "(/start /check /performans /arastirma /status /myid)", flush=True)
    while True:
        try:
            params = {"timeout": 30}
            if offset is not None:
                params["offset"] = offset
            r = requests.get(f"{base}/getUpdates", params=params, timeout=45)
            r.raise_for_status()
            for upd in r.json().get("result", []):
                offset = upd["update_id"] + 1
                cq = upd.get("callback_query")
                if cq:
                    try:
                        handle_callback_query(cq)
                    except Exception as e:
                        print(f"uyari: dugme islenemedi: {_redact(str(e))}",
                              file=sys.stderr, flush=True)
                    continue
                msg = upd.get("message") or upd.get("edited_message") or {}
                text = (msg.get("text", "") or "").strip()
                chat = msg.get("chat") or {}
                chat_id = str(chat.get("id", ""))
                # Kalici menu dugmeleri komut yerine etiket metni gonderir
                if text in MENU_BUTTONS:
                    text = MENU_BUTTONS[text]
                if not text.startswith("/"):
                    continue
                cmd0 = text.strip().split()[0].lower().lstrip("/").split("@")[0]
                if cmd0 == "myid":
                    # herkese acik: arkadasin ID'sini ogrenip sana iletmesi icin
                    _telegram_send_text(
                        f"Senin chat ID'in: <code>{chat_id}</code>\n"
                        "Botu kullanmak icin /katil yaz ya da bu ID'yi bot "
                        "sahibine ilet.", chat_id=chat_id)
                    continue
                if cmd0 in ("katil", "join"):
                    # Herkese acik AMA hicbir yetki VERMEZ: sahibe onay
                    # istegi iletir. Onay yalniz sahibin /onayla komutuyla olur.
                    if _chat_allowed(chat_id):
                        _telegram_send_text("Zaten erisimin var. /help",
                                            chat_id=chat_id)
                        continue
                    label = " ".join(filter(None, [
                        chat.get("first_name"), chat.get("last_name"),
                        f"@{chat['username']}" if chat.get("username") else "",
                        f"[{chat.get('title')}]" if chat.get("title") else "",
                    ])).strip() or "isimsiz"
                    new_request = chat_id not in PENDING_JOINS
                    PENDING_JOINS[chat_id] = label
                    _telegram_send_text(
                        "📨 Istegin bot sahibine iletildi. Onaylanirsa "
                        "sinyaller sana da gelmeye baslar.", chat_id=chat_id)
                    if new_request:
                        _telegram_send_text(
                            f"📨 <b>Katilim istegi</b>\n"
                            f"{_html.escape(label)}\n"
                            f"ID: <code>{_html.escape(chat_id)}</code>\n\n"
                            f"Tek dokunusla karar ver (ya da "
                            f"<code>/onayla {chat_id}</code>):",
                            chat_id=str(TELEGRAM_CHAT_ID),
                            reply_markup={"inline_keyboard": [[
                                {"text": "✅ Onayla",
                                 "callback_data": f"ok:{chat_id}"},
                                {"text": "❌ Reddet",
                                 "callback_data": f"no:{chat_id}"},
                            ]]})
                    continue
                if not _chat_allowed(chat_id):
                    continue                    # izinsiz -> sessizce yok say
                try:
                    handle_telegram_command(text, chat_id)
                except Exception as e:
                    print(f"uyari: komut islenemedi ({text!r}): {e}",
                          file=sys.stderr, flush=True)
        except requests.RequestException as e:
            code = getattr(getattr(e, "response", None), "status_code", 0)
            if code == 409:
                conflict_streak += 1
                if conflict_streak in (1, 10):   # spam yapma, ama net soyle
                    print("uyari: getUpdates 409 CONFLICT — AYNI TOKEN'la "
                          "BASKA bir bot kopyasi daha calisiyor (eski Render "
                          "servisi silinmemis olabilir ya da tablette ikinci "
                          "bir surec var: pgrep -af signal_bot). Kopyayi "
                          "kapatana kadar komutlar guvenilir calismaz; "
                          "sinyal PUSH'lari etkilenmez.", file=sys.stderr,
                          flush=True)
                time.sleep(30)
                continue
            conflict_streak = 0
            print(f"uyari: telegram getUpdates: {_redact(str(e))}",
                  file=sys.stderr, flush=True)
            time.sleep(5)
        except Exception as e:
            print(f"uyari: komut dongusu: {_redact(str(e))}",
                  file=sys.stderr, flush=True)
            time.sleep(5)


def run_test_notify() -> None:
    """--test-notify: Telegram'i SAHTE, acikca TEST etiketli bir
    sinyalle dener. Gercek sinyal beklemeden anahtarlarin dogru kuruldugunu
    dogrulamanin tek guvenilir yolu (gercek sinyaller seyrektir)."""
    print(f"kanal: telegram={'ACIK' if ENABLE_TELEGRAM else 'KAPALI'}")
    if not ENABLE_TELEGRAM:
        print("Telegram kapali: bot klasorunde .env dosyasi yok veya "
              "anahtar alanlari bos. .env.example'i .env olarak kopyalayip "
              "TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID degerlerini doldur.",
              file=sys.stderr)
        return
    sig = {
        "strategy": "TEST", "symbol": "TESTUSDT", "direction": "LONG",
        "strength": "NORMAL", "confidence": "COK YUKSEK",
        "bar_time": datetime.now(timezone.utc).isoformat(),
        "price": 123.45,
        "note": "BU BIR TESTTIR — bildirim kanallari calisiyor. "
                "Gercek sinyal DEGILDIR.",
        "horizon_hours": 0,
    }
    notify(sig)
    print("Gonderildi. Telegram mesajini kontrol et. Gelmediyse yukaridaki "
          "kanal durumunu ve .env degerlerini kontrol et.")


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Kripto sinyal botu — 3 strateji + confluence.")
    ap.add_argument("--once", action="store_true",
                    help="tek tarama (kenar-tetikleme) yap, bildirim gonder, cik")
    ap.add_argument("--check", action="store_true",
                    help="O AN aktif kurulumlari goster (bildirim yok) — "
                         "istedigin an calistir")
    ap.add_argument("--test-notify", action="store_true",
                    help="TEST etiketli sahte sinyali Telegram'a gonder "
                         "(anahtarlarin dogru kuruldugunu 10 sn'de dogrular)")
    ap.add_argument("--archive-status", action="store_true",
                    help="likidasyon arsivi dosyalarinin kapsama ozetini yaz")
    ap.add_argument("--shadow-status", action="store_true",
                    help="G1/DL1 golge olay/snapshot arsivinin kapsama ozetini yaz")
    ap.add_argument("--research-status", action="store_true",
                    help="OI/funding/likidasyon arastirma hazirligini yaz")
    args = ap.parse_args()
    if args.test_notify:
        run_test_notify()
    elif args.archive_status:
        print(json.dumps(summarize_derivatives_archive(ARCHIVE_DIR),
                         ensure_ascii=False, indent=2))
    elif args.shadow_status:
        print(json.dumps(summarize_shadow_archive(ARCHIVE_DIR),
                         ensure_ascii=False, indent=2))
    elif args.research_status:
        print(json.dumps(research_readiness_report(),
                         ensure_ascii=False, indent=2))
    elif args.check:
        run_check()
    else:
        run_forever(once=args.once)


if __name__ == "__main__":
    main()
