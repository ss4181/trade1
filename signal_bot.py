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

Kullanim:  python signal_bot.py            # saatlik dongu
           python signal_bot.py --once     # tek tarama (test icin)
Bagimliliklar: requests (pip install requests). API anahtari GEREKMEZ
(sadece halka acik uclar).
"""

from __future__ import annotations

import argparse
import html as _html
import json
import math
import os
import sys
import threading
import time
from collections import deque
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

try:
    import resend  # opsiyonel: yalnizca email etkinse gerekir
except ImportError:
    resend = None

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
_SYMBOLS_ENV = os.environ.get("SYMBOLS", "").strip()
SYMBOLS = [s.strip() for s in (_SYMBOLS_ENV or DEFAULT_SYMBOLS).split(",") if s.strip()]

# --- dinamik sembol evreni ---
# SYMBOLS env'i BOSSA bot evreni otomatik kurar: USDT spot cifti + aktif
# USDⓈ-M perp'i olan coinler, PERP 24h hacmine gore siralanir, ilk
# SYMBOL_MAX_COUNT alinir. Siralama perp hacmiyle yapilir cunku (a) islem
# perp'te acilir, (b) mutlak spot esigi rejime gore kirilir (ayi piyasasinda
# spot hacimler cokuyor). Spot tarafina kucuk bir veri-kalitesi tabani yeter
# (S1/S3 spot verisinde hesaplanir ama kendi gecmisine gore normalize).
# Arastirma evreni de ayni kuralla ("likit + hem spot hem perp") secilmisti;
# esikler likit-disi coinlerde DOGRULANMADI — filtreler bilerek var.
# SYMBOLS env'i doldurursan otomatik mod kapanir.
SYMBOL_AUTO = _env("SYMBOL_AUTO", not _SYMBOLS_ENV,
                   cast=lambda v: str(v).strip().lower() in ("1", "true", "yes"))
SYMBOL_MAX_COUNT = _env("SYMBOL_MAX_COUNT", 120)
SYMBOL_MIN_PERP_VOLUME_M = _env("SYMBOL_MIN_PERP_VOLUME_M", 10.0)  # milyon $/24h, perp
SYMBOL_MIN_SPOT_VOLUME_M = _env("SYMBOL_MIN_SPOT_VOLUME_M", 1.0)   # milyon $/24h, spot
UNIVERSE_REFRESH_HOURS = _env("UNIVERSE_REFRESH_HOURS", 24)

# 15dk tarama: sinyaller 1h bar KAPANISINDA dogar — daha sik tarama sinyal
# setini DEGISTIRMEZ (kenar-tetikleme ayni kosulu tekrar bildirmez); kazanci
# S2'nin (8h'lik funding) ve yeniden-baslatma sonrasi yakalamanin hizlanmasi.
# "15dk'lik scalping sinyali" DEGILDIR — 15m/5m umuklarinda edge olmadigi
# olculdu (research/REPORT.md Ek A/B).
SCAN_INTERVAL_MINUTES = _env("SCAN_INTERVAL_MINUTES", 15)
KLINE_LIMIT = _env("KLINE_LIMIT", 250)          # >= VOLUME_ZSCORE_WINDOW + 24 olmali
SIGNAL_LOG = _env("SIGNAL_LOG", "signals.log")

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
_BAN_CODES = (403, 418, 429, 451)


def _spot_get(path: str, params: dict | None = None) -> requests.Response:
    """Spot GET; yasak/limit kodunda bir sonraki hosta gecip tekrar dener."""
    global _spot_host_idx
    last_exc: Exception | None = None
    for attempt in range(len(SPOT_HOSTS)):
        host = SPOT_HOSTS[_spot_host_idx]
        try:
            r = requests.get(host + path, params=params, timeout=30)
            r.raise_for_status()
            return r
        except requests.HTTPError as e:
            last_exc = e
            code = e.response.status_code if e.response is not None else 0
            if code in _BAN_CODES and attempt < len(SPOT_HOSTS) - 1:
                _spot_host_idx = (_spot_host_idx + 1) % len(SPOT_HOSTS)
                print(f"uyari: spot API {code} verdi -> "
                      f"{SPOT_HOSTS[_spot_host_idx]} hostuna geciliyor",
                      file=sys.stderr, flush=True)
                continue
            raise
    raise last_exc  # type: ignore[misc]

# --- bildirim kanallari ---
# Degerler .env dosyasindan (yerel) veya platform secret yonetiminden (bulut)
# okunur. ASLA koda gomulu deger yazilmaz. Anahtar yoksa ilgili kanal sessizce
# devre disi kalir (bot yine calisir, sadece o kanaldan gondermez).
TELEGRAM_BOT_TOKEN = _env("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = _env("TELEGRAM_CHAT_ID", "")
RESEND_API_KEY = _env("RESEND_API_KEY", "")
NOTIFICATION_EMAIL = _env("NOTIFICATION_EMAIL", "")
# Resend "from": kendi dogruladigin alan adin yoksa sandbox adresini kullan
# (onboarding@resend.dev yalnizca hesabinin kendi email'ine gonderebilir).
EMAIL_FROM = _env("EMAIL_FROM", "Signal Bot <onboarding@resend.dev>")

ENABLE_TELEGRAM = bool(TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID)
ENABLE_EMAIL = bool(RESEND_API_KEY and NOTIFICATION_EMAIL)

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


def _chat_allowed(chat_id: str) -> bool:
    return TELEGRAM_OPEN or chat_id in TELEGRAM_SUBSCRIBERS

# Mobil endpoint (server.py) icin son sinyaller — thread-guvenli halka tampon.
RECENT_MAXLEN = _env("RECENT_MAXLEN", 100)
RECENT_SIGNALS: deque[dict] = deque(maxlen=RECENT_MAXLEN)
_recent_lock = threading.Lock()

# Servis saglik durumu (server.py /health endpoint'i okur).
STARTED_AT = datetime.now(timezone.utc).isoformat()
LAST_SCAN_AT: str | None = None
LAST_SCAN_COUNT = 0
SCANS_COMPLETED = 0
LAST_SCAN_ERRORS = 0                 # son taramada kac sembol hata verdi
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
        var = sum((x - mu) ** 2 for x in w) / (len(w) - 1)
        sd = math.sqrt(var)
        if sd > 0:
            z[i] = (logs[i] - mu) / sd
    return z


# --------------------------------------------------------------------------
# referans seviyeleri (mekanik; tavsiye DEGIL)
# --------------------------------------------------------------------------
# 24 aylik backtest'in (2024-07 -> 2026-06, research/REPORT.md) dogrulanmis
# ufuktaki HAM getiri dagilimlari. Onemli durustluk notu: backtest'te tek
# dogrulanan cikis kurali ZAMAN cikisidir (ufuk sonunda kapat); fiyat-bazli
# stop/hedef HIC test edilmedi. q10/q90 sadece tarihsel dagilimin uc yuzdelik
# dilimleri — "buradan kes/su fiyattan al" talimati degildir.
STRATEGY_STATS = {
    "S1": {"h": 24, "med": 0.93, "q10": -4.49, "q90": 8.83, "wr": 62, "n": 316,
           "touch": ((1, 87), (2, 71), (3, 62)), "stopt": ((2, 69), (5, 37))},
    "S2": {"h": 72, "med": 0.24, "q10": -9.09, "q90": 12.73, "wr": 52, "n": 339,
           "touch": ((1, 88), (2, 76), (3, 65)), "stopt": ((2, 74), (5, 47))},
    "S3": {"h": 4,  "med": 0.16, "q10": -2.84, "q90": 4.16, "wr": 53, "n": 1015,
           "touch": ((1, 67), (2, 42), (3, 27)), "stopt": ((2, 33), (5, 6))},
}
# Guven kademeleri (arastirma kanitina gore) + bildirim esigi:
# COK YUKSEK: S1+S4 (test p=0.006, 72h WR %66) | YUKSEK: S1 (p=0.006, 4/4
# rejim) | ORTA: S3 (4h p<0.001 ama test'e 2. bakis serhi) | DUSUK: S2
# (p=0.08 marjinal + sembol yogunlasmasi). NOTIFY_MIN_CONFIDENCE altindaki
# sinyaller LOGLANIR ve API/tamponda gorunur ama Telegram/email'e GITMEZ.
CONF_RANK = {"DUSUK": 0, "ORTA": 1, "YUKSEK": 2, "COK YUKSEK": 3}
STRATEGY_CONF = {
    "S1+S4": ("COK YUKSEK", "test p=0.006, 72h WR %66; en guclu sinyal"),
    "S1":    ("YUKSEK", "test p=0.006, 4 rejimde 4/4 pozitif"),
    "S3":    ("ORTA", "test 4h p<0.001; nihai secimde 2. bakis serhi"),
    "S2":    ("DUSUK", "test p=0.08 marjinal; sinyaller ~5 sembolde yogun"),
}
NOTIFY_MIN_CONFIDENCE = _env("NOTIFY_MIN_CONFIDENCE", "ORTA").strip().upper()

# Bir stratejiyi TAMAMEN kapatmak icin (taranmaz, loglanmaz, API cagrisi da
# yapilmaz): DISABLED_STRATEGIES=S2 gibi virgullu liste. NOT: varsayilan bos —
# S2 su an "sessiz-kayit" modunda (push edilmez ama loglanir) cunku canli
# performans olcumu (/performans) nihai kaldir/tut kararini VERIyle verecek;
# tamamen kapatirsan o kanit birikmez.
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
    st = STRATEGY_STATS.get(strategy.split("+")[0])
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


def fetch_funding(symbol: str, limit: int = 3) -> list[dict]:
    """Son settled funding kayitlari (eskiden yeniye)."""
    r = requests.get(f"{FUT_API}/fapi/v1/fundingRate",
                     params={"symbol": symbol, "limit": limit}, timeout=30)
    r.raise_for_status()
    return [{"time": int(x["fundingTime"]), "rate": float(x["fundingRate"])}
            for x in sorted(r.json(), key=lambda x: x["fundingTime"])]


# spot sembolu -> perp sembolu eslemesi (dusuk fiyatli coinlerde 1000x kontrat).
# Otomatik evren modunda fetch_universe() doldurur; statik modda bilinen istisna.
PERP_MAP: dict[str, str] = {"PEPEUSDT": "1000PEPEUSDT"}
_last_universe_refresh = 0.0

# Sabit/pegli varliklar evren disi: fiyat dinamikleri kripto degil (stable, altin,
# wrapped) — S1/S3 varsayimlari bunlarda gecerli degil.
STABLE_OR_PEGGED = {
    "USDC", "FDUSD", "TUSD", "DAI", "USDP", "PYUSD", "BUSD", "AEUR", "EUR",
    "EURI", "USDE", "USD1", "BFUSD", "XUSD", "USDF", "PAXG", "XAUT",
    "WBTC", "WBETH",
}


def perp_symbol(spot: str) -> str:
    return PERP_MAP.get(spot, spot)


def fetch_universe() -> tuple[list[str], dict[str, str]]:
    """Likidite-filtreli evren: USDT spot cifti + aktif USDⓈ-M perp'i olan
    semboller; PERP 24h hacmine gore azalan sirali ilk N. Spot tarafina
    kucuk bir veri-kalitesi tabani uygulanir."""
    r = requests.get(f"{FUT_API}/fapi/v1/exchangeInfo", timeout=30)
    r.raise_for_status()
    perps = {s["symbol"] for s in r.json()["symbols"]
             if s.get("contractType") == "PERPETUAL"
             and s.get("status") == "TRADING"
             and s.get("quoteAsset") == "USDT"}
    r = requests.get(f"{FUT_API}/fapi/v1/ticker/24hr", timeout=30)
    r.raise_for_status()
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
        perp = sym if sym in perps else (
            "1000" + sym if "1000" + sym in perps else None)
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
            }
            tmp = STATE_FILE.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False),
                           encoding="utf-8")
            tmp.replace(STATE_FILE)          # atomik: yarim dosya kalmaz
        except OSError as e:
            print(f"uyari: durum kaydedilemedi: {e}", file=sys.stderr, flush=True)

    @classmethod
    def load(cls) -> "ScanState":
        st = cls()
        if not STATE_FILE.exists():
            return st
        try:
            data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
            for k, v in data.get("prev_cond", {}).items():
                a, _, b = k.partition("|")
                st.prev_cond[(a, b)] = bool(v)
            for k, v in data.get("last_fire", {}).items():
                a, _, b = k.partition("|")
                st.last_fire[(a, b)] = float(v)
            with _recent_lock:
                for sig in data.get("recent", []):
                    RECENT_SIGNALS.append(sig)   # kayit sirasi: yeni->eski
            print(f"durum yuklendi: {len(st.prev_cond)} kosul, "
                  f"{len(st.last_fire)} cooldown, "
                  f"{len(RECENT_SIGNALS)} tamponlanmis sinyal", flush=True)
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
                snapshot: bool = False) -> list[dict]:
    """Bir sembolu tarar, sinyal listesini dondurur.

    snapshot=False (canli mod): kenar-tetikleme + cooldown uygulanir — sinyal
      SADECE kosul False->True gectiginde uretilir (bildirim spam'i olmasin).
    snapshot=True (--check modu): geciş aranmaz, o an AKTIF olan tum kosullar
      raporlanir. state'e dokunmaz. "Su an uygun kurulum var mi?" sorusu icin."""
    signals = []
    now_s = time.time()

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
        signals.append({
            "strategy": "S1" + ("+S4" if recent_spike else ""),
            "symbol": symbol, "direction": "LONG",
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
    if ("S3" not in DISABLED_STRATEGIES
            and include("S3", s3_spike, S3_COOLDOWN_HOURS)
            and closes[i] > opens[i]):
        signals.append({
            "strategy": "S3", "symbol": symbol, "direction": "LONG",
            "strength": "NORMAL", "bar_time": bar_ts.isoformat(),
            "price": closes[i], "volume_logz": round(zs[i], 2),
            "note": "yukari-bar hacim patlamasi (momentum devami)",
            "horizon_hours": 4,
        })

    # ---- S2: funding squeeze (long) ----
    if "S2" in DISABLED_STRATEGIES:
        fr = []                                # tamamen kapali: API'ye de gitme
    else:
        try:
            fr = fetch_funding(perp_symbol(symbol),
                               limit=FUNDING_PERSISTENCE + 1)
        except requests.RequestException:
            fr = []                            # perp yoksa/ulasilamazsa atla
    if len(fr) >= FUNDING_PERSISTENCE:
        thr = FUNDING_SQUEEZE_THRESHOLD_PCT / 100.0
        last_n = fr[-FUNDING_PERSISTENCE:]
        s2_cond = all(x["rate"] <= thr for x in last_n)
        if include("S2", s2_cond, S2_COOLDOWN_HOURS):
            signals.append({
                "strategy": "S2", "symbol": symbol, "direction": "LONG",
                "strength": "NORMAL",
                "bar_time": datetime.fromtimestamp(
                    last_n[-1]["time"] / 1000, tz=timezone.utc).isoformat(),
                "price": closes[i],
                "funding_pct": [round(x["rate"] * 100, 4) for x in last_n],
                "note": "negatif funding yiginlanmasi (short squeeze adayi)",
                "horizon_hours": 72,
            })

    if signals:
        sigma = realized_sigma1h(closes)
        for sig in signals:
            conf, evid = signal_confidence(sig["strategy"])
            sig["confidence"] = conf
            sig["confidence_note"] = evid
            ref = build_ref_levels(sig["strategy"], sig["price"], sigma)
            if ref:
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
    if "funding_pct" in sig:
        rows.append(("Funding %", ", ".join(str(x) for x in sig["funding_pct"])))
    return rows


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
        f"Giris ref: {ref['entry_ref']}",
        f"Zaman cikisi: ~{ref['time_exit_hours']}h{exit_by} — "
        "backtest'te dogrulanan tek cikis kurali",
        f"24 ay tarihce (N={ref['hist_n']}, kazanma %{ref['hist_winrate_pct']}):",
        f"  medyan → {ref['median_price']} ({ref['hist_median_pct']:+.2f}%)",
        f"  kotu %10 → {ref['q10_price']} ({ref['hist_q10_pct']:+.2f}%)",
        f"  iyi %10 → {ref['q90_price']} ({ref['hist_q90_pct']:+.2f}%)",
    ]
    if "sigma_h_pct" in ref:
        lines.append(f"Tipik dalgalanma (±1σ, {ref['time_exit_hours']}h): "
                     f"±{ref['sigma_h_pct']}%")
    if ref.get("touch"):
        t = " · ".join(f"+{x}% %{p}" for x, p in ref["touch"])
        s = " · ".join(f"-{y}% %{p}" for y, p in ref["stopt"])
        lines.append(f"Dokunma olasiliklari ({ref['time_exit_hours']}h, "
                     f"tarihsel): {t} | {s}")
    lines.append("Bracket (hedef/stop emri) backtest'te zaman cikisini "
                 "YENEMEDI; dokunma olasiliklari bilgi amaclidir. Kaldirac "
                 "kayiplari ve tasfiye riskini buyutur.")
    return lines


def send_telegram_message(sig: dict) -> None:
    """Telegram Bot API ile sinyal gonderir. Anahtar yoksa sessizce atlar;
    hata olursa uyarir ama tarama dongusunu ASLA durdurmaz."""
    if not ENABLE_TELEGRAM:
        return
    icon = "‼️" if sig.get("strength") == "STRONG" else "\U0001f514"
    conf = sig.get("confidence")
    head_tail = (f"({sig['strength']} · Guven: {conf})" if conf
                 else f"({sig['strength']})")
    lines = [
        f"{icon} <b>{_html.escape(sig['strategy'])}</b> — "
        f"<b>{_html.escape(sig['symbol'])}</b> {sig['direction']} "
        f"{head_tail}",
        f"Fiyat: {sig['price']}",
        f"Beklenen ufuk: ~{sig['horizon_hours']} saat",
    ]
    lines += [f"{label}: {_html.escape(val)}"
              for label, val in _signal_detail_rows(sig)]
    lines.append(_html.escape(sig["note"]))
    ref_lines = _ref_lines(sig)
    if ref_lines:
        lines.append("")
        lines += [f"<i>{_html.escape(l)}</i>" if l.startswith(("—", "Fiyat-bazli"))
                  else _html.escape(l) for l in ref_lines]
    lines.append(f"<i>{_html.escape(sig['bar_time'])}</i>")
    text = "\n".join(lines)
    for cid in TELEGRAM_SUBSCRIBERS:          # sahip + izinli arkadaslar
        _telegram_send_text(text, chat_id=cid)


def _redact(text: str) -> str:
    """Hata mesajlarindan bot token'ini temizler — loglara/ekrana ASLA
    token yazilmamali (URL icinde gelebiliyor)."""
    if TELEGRAM_BOT_TOKEN:
        text = text.replace(TELEGRAM_BOT_TOKEN, "***TOKEN***")
    return text


def _telegram_send_text(text: str, chat_id: str | None = None) -> bool:
    """Ham HTML metni Telegram'a gonderir (sinyaller + komut cevaplari ortak).
    Anahtar yoksa sessizce atlar; hata olursa uyarir, ASLA istisna firlatmaz."""
    if not ENABLE_TELEGRAM:
        return False
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={"chat_id": chat_id or TELEGRAM_CHAT_ID, "text": text,
                  "parse_mode": "HTML", "disable_web_page_preview": True},
            timeout=15)
        r.raise_for_status()
        return True
    except requests.RequestException as e:
        print(f"uyari: Telegram gonderilemedi: {_redact(str(e))}",
              file=sys.stderr, flush=True)
        return False


def _email_ref_block(sig: dict) -> str:
    ref = sig.get("ref")
    if not ref:
        return ""
    sigma = (f'<tr><td style="padding:3px 12px 3px 0;color:#666">Tipik dalgalanma (±1σ)</td>'
             f'<td style="padding:3px 0">±{ref["sigma_h_pct"]}%</td></tr>'
             if "sigma_h_pct" in ref else "")
    return f"""
    <h3 style="margin:14px 0 4px;font-size:14px;color:#333">
      Referans seviyeleri <span style="font-weight:normal;color:#888">(mekanik; tavsiye degil)</span></h3>
    <table style="font-size:13px;border-collapse:collapse">
      <tr><td style="padding:3px 12px 3px 0;color:#666">Giris ref</td>
          <td style="padding:3px 0"><b>{ref['entry_ref']}</b></td></tr>
      <tr><td style="padding:3px 12px 3px 0;color:#666">Zaman cikisi</td>
          <td style="padding:3px 0"><b>~{ref['time_exit_hours']} saat</b> (backtest'te dogrulanan tek cikis kurali)</td></tr>
      <tr><td style="padding:3px 12px 3px 0;color:#666">Medyan (24 ay, N={ref['hist_n']})</td>
          <td style="padding:3px 0">{ref['median_price']} ({ref['hist_median_pct']:+.2f}%)</td></tr>
      <tr><td style="padding:3px 12px 3px 0;color:#666">Kotu %10</td>
          <td style="padding:3px 0">{ref['q10_price']} ({ref['hist_q10_pct']:+.2f}%)</td></tr>
      <tr><td style="padding:3px 12px 3px 0;color:#666">Iyi %10</td>
          <td style="padding:3px 0">{ref['q90_price']} ({ref['hist_q90_pct']:+.2f}%)</td></tr>
      <tr><td style="padding:3px 12px 3px 0;color:#666">Kazanma orani (tarihsel)</td>
          <td style="padding:3px 0">%{ref['hist_winrate_pct']}</td></tr>
      {sigma}
    </table>
    <p style="font-size:12px;color:#a33;margin:6px 0 0">Fiyat-bazli stop/hedef
    backtest'te test edilmedi; kaldirac kayiplari ve tasfiye riskini buyutur.</p>"""


def _email_html(sig: dict) -> str:
    color = "#c0392b" if sig.get("strength") == "STRONG" else "#2c7be5"
    extra = "".join(
        f'<tr><td style="padding:4px 12px 4px 0;color:#666">{_html.escape(l)}</td>'
        f'<td style="padding:4px 0"><b>{_html.escape(v)}</b></td></tr>'
        for l, v in _signal_detail_rows(sig))
    return f"""\
<div style="font-family:-apple-system,Segoe UI,Roboto,sans-serif;max-width:480px">
  <div style="border-left:4px solid {color};padding:12px 16px;background:#f7f9fc">
    <h2 style="margin:0 0 6px;font-size:18px">
      {_html.escape(sig['strategy'])} &mdash; {_html.escape(sig['symbol'])}
      <span style="color:{color}">{sig['direction']} ({sig['strength']})</span>
    </h2>
    <table style="font-size:14px;border-collapse:collapse">
      <tr><td style="padding:4px 12px 4px 0;color:#666">Fiyat</td><td style="padding:4px 0"><b>{sig['price']}</b></td></tr>
      <tr><td style="padding:4px 12px 4px 0;color:#666">Beklenen ufuk</td><td style="padding:4px 0"><b>~{sig['horizon_hours']} saat</b></td></tr>
      {extra}
      <tr><td style="padding:4px 12px 4px 0;color:#666">Zaman</td><td style="padding:4px 0">{_html.escape(sig['bar_time'])}</td></tr>
    </table>
    <p style="font-size:13px;color:#444;margin:8px 0 0">{_html.escape(sig['note'])}</p>
    {_email_ref_block(sig)}
  </div>
  <p style="font-size:11px;color:#999;margin:8px 0 0">
    signal_bot — otomatik uyari. Yatirim tavsiyesi degildir.</p>
</div>"""


def send_email_notification(sig: dict) -> None:
    """Resend ile HTML email gonderir. Anahtar/paket yoksa sessizce atlar;
    hata olursa uyarir ama tarama dongusunu ASLA durdurmaz."""
    if not ENABLE_EMAIL:
        return
    if resend is None:
        print("uyari: 'resend' paketi kurulu degil, email atlandi "
              "(pip install resend)", file=sys.stderr, flush=True)
        return
    subject = (f"[{sig['strength']}] {sig['strategy']} {sig['symbol']} "
               f"{sig['direction']}")
    try:
        resend.api_key = RESEND_API_KEY
        resend.Emails.send({
            "from": EMAIL_FROM,
            "to": [NOTIFICATION_EMAIL],
            "subject": subject,
            "html": _email_html(sig),
        })
    except Exception as e:  # SDK cesitli hata tipleri firlatabilir; kanal opsiyonel
        print(f"uyari: email gonderilemedi: {e}", file=sys.stderr, flush=True)


def notify(sig: dict, push: bool = True) -> None:
    """Tek sinyal cikis noktasi: stdout + JSONL log + mobil tampon + Telegram
    + email. Sinyaller HER IKI kanala da (Telegram VE email) gonderilir.

    Anti-spam UST AKISTA yapilir (ScanState.should_fire — kenar-tetikleme +
    strateji-basi cooldown): buraya ulasan her sinyal zaten tekillestirilmistir,
    dolayisiyla iki kanal ayni deduplike sinyali alir, ayri ayri sayilmaz."""
    conf = sig.get("confidence", "YUKSEK")
    silenced = (CONF_RANK.get(conf, 2)
                < CONF_RANK.get(NOTIFY_MIN_CONFIDENCE, 1)) or not push
    tag = ("  [SESSIZ: guven esigi alti]" if silenced and push else
           ("  [TOPLU OZETTE: tarama-basi tavan]" if not push else ""))
    line = (f"[{sig['bar_time']}] {sig['strategy']:<6} {sig['symbol']:<12} "
            f"{sig['direction']} ({sig['strength']}/{conf}) "
            f"fiyat={sig['price']} ~{sig['horizon_hours']}h | {sig['note']}"
            + tag)
    print(line, flush=True)
    with open(Path(__file__).parent / SIGNAL_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(sig, ensure_ascii=False) + "\n")
    with _recent_lock:
        RECENT_SIGNALS.appendleft(
            {**sig, "notified_at": datetime.now(timezone.utc).isoformat()})
    if silenced:
        return
    send_telegram_message(sig)
    send_email_notification(sig)


# Firtina gunu duzeni: tek taramada en fazla bu kadar sinyal AYRINTILI push
# edilir (oncelik sirasiyla); fazlasi tek toplu mesajda ozetlenir. Piyasa
# geneli cokuslerde 10+ ayri bildirim yerine duzenli akis.
MAX_PUSH_PER_SCAN = _env("MAX_PUSH_PER_SCAN", 6)


def scan_all(state: ScanState) -> int:
    global LAST_SCAN_ERRORS
    errors = 0
    collected: list[dict] = []
    for sym in SYMBOLS:
        try:
            collected += scan_symbol(sym, state)
        except requests.RequestException as e:
            errors += 1
            ERROR_SAMPLES.append(f"{sym}: {e}")
            print(f"uyari: {sym} taranamadi: {e}", file=sys.stderr, flush=True)
        time.sleep(0.25)          # nazik olalim (limitin cok altindayiz)
    LAST_SCAN_ERRORS = errors
    if errors:
        print(f"uyari: taramada {errors}/{len(SYMBOLS)} sembol hata verdi",
              file=sys.stderr, flush=True)
    collected.sort(key=lambda s: (_priority(s), s["symbol"]))
    overflow = []
    pushed = 0
    for sig in collected:
        conf_ok = (CONF_RANK.get(sig.get("confidence", "YUKSEK"), 2)
                   >= CONF_RANK.get(NOTIFY_MIN_CONFIDENCE, 1))
        if conf_ok and pushed >= MAX_PUSH_PER_SCAN:
            overflow.append(sig)
            notify(sig, push=False)
        else:
            notify(sig)
            if conf_ok:
                pushed += 1
    if overflow:
        lines = [f"⚠️ Ayni taramada +{len(overflow)} sinyal daha "
                 f"(piyasa geneli hareket olabilir):"]
        lines += [f"• {s['strategy']} {s['symbol']} @ {s['price']} "
                  f"(~{s['horizon_hours']}h)" for s in overflow[:20]]
        lines.append("Detaylar log ve /signals/latest icinde.")
        _telegram_send_text("\n".join(_html.escape(l) if i else l
                                      for i, l in enumerate(lines)))
    state.save()                  # restart'ta cooldown/tampon kaybolmasin
    return len(collected)


# Gunluk yasam sinyali: her gun bu UTC saatinden sonraki ilk taramada tek
# satirlik ozet gonderilir. Gelmezse botun oldugunu anlarsin (sessiz olum
# sigortasi). Kapatmak: DAILY_SUMMARY_HOUR_UTC=-1
DAILY_SUMMARY_HOUR_UTC = _env("DAILY_SUMMARY_HOUR_UTC", 6)   # 06 UTC = 09 TR
_last_summary_day: str | None = None


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
    with _recent_lock:
        for s in RECENT_SIGNALS:
            try:
                if datetime.fromisoformat(s.get("notified_at", "")) >= cutoff:
                    by_strat[s["strategy"]] = by_strat.get(s["strategy"], 0) + 1
            except ValueError:
                continue
    sig_txt = (", ".join(f"{k}:{v}" for k, v in sorted(by_strat.items()))
               or "yok")
    _telegram_send_text(
        f"☀️ <b>Gunluk ozet</b> — bot calisiyor.\n"
        f"Son 24h sinyal: {sig_txt}\n"
        f"Toplam tarama: {SCANS_COMPLETED} · evren: {len(SYMBOLS)} sembol · "
        f"son taramada hata: {LAST_SCAN_ERRORS}\n"
        f"Anlik kontrol: /check · canli sonuclar: /performans")


def run_forever(once: bool = False, state: ScanState | None = None) -> None:
    """Tarama dongusu. CLI dogrudan cagirir; server.py bir arka plan
    thread'inde cagirir (web servisini bloklamadan). Bir tarama cyklusundeki
    beklenmeyen hata dongusu OLDURMEZ — 7/24 servis icin dayaniklilik."""
    global LAST_SCAN_AT, LAST_SCAN_COUNT, SCANS_COMPLETED
    state = state or ScanState.load()       # restart sonrasi kaldigi yerden
    refresh_universe_if_due(force=True)     # otomatik moddaysa evreni kur
    # Telegram komut dinleyicisini yalnizca surekli modda baslat (--once'ta degil)
    if ENABLE_TELEGRAM and TELEGRAM_COMMANDS and not once:
        threading.Thread(target=telegram_command_loop, name="tg-commands",
                         daemon=True).start()
    print(f"signal_bot basladi: {len(SYMBOLS)} sembol "
          f"({'otomatik evren' if SYMBOL_AUTO else 'statik liste'}), "
          f"{SCAN_INTERVAL_MINUTES}dk aralik "
          f"(telegram={'acik' if ENABLE_TELEGRAM else 'kapali'}, "
          f"email={'acik' if ENABLE_EMAIL else 'kapali'})", flush=True)
    if not (ENABLE_TELEGRAM or ENABLE_EMAIL):
        if not _ENV_FOUND:
            print(f"NOT: bildirim kanallari KAPALI cunku .env bulunamadi.\n"
                  f"     Aranan yer: {_ENV_PATH}\n"
                  f"     Cozum: bu klasorde `cp .env.example .env` yapip 4 "
                  f"anahtari doldur (TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, "
                  f"RESEND_API_KEY, NOTIFICATION_EMAIL).", file=sys.stderr,
                  flush=True)
        else:
            print(f"NOT: .env bulundu ({_ENV_PATH}) ama anahtarlar bos/eksik. "
                  f"Icindeki 4 anahtarin dolu oldugundan emin ol.",
                  file=sys.stderr, flush=True)
    while True:
        t0 = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
        try:
            refresh_universe_if_due()
            n = scan_all(state)
            LAST_SCAN_AT = datetime.now(timezone.utc).isoformat()
            LAST_SCAN_COUNT = n
            SCANS_COMPLETED += 1
            print(f"[{t0}] tarama bitti: {n} sinyal", flush=True)
            _maybe_daily_summary()
        except Exception as e:  # tek dongu hatasi 7/24 servisi dusurmemeli
            print(f"hata: tarama dongusunde beklenmeyen hata: {e}",
                  file=sys.stderr, flush=True)
        if once:
            break
        # bir sonraki bar kapanisindan ~90sn sonrasina hizalan
        period = SCAN_INTERVAL_MINUTES * 60
        now = time.time()
        time.sleep(period - (now % period) + 90)


def _priority(sig: dict) -> int:
    return {"S1+S4": 0, "S1": 1, "S3": 2, "S2": 3}.get(sig["strategy"], 9)


def collect_active_setups() -> tuple[list[dict], int]:
    """O an aktif olan tum kurulumlari (snapshot) toplar, oncelige gore
    siralar. (found, hata_sayisi) doner. Yazdirmaz — hem --check hem Telegram
    /check bunu kullanir. Evreni yenilemez (cagiran karar verir)."""
    state = ScanState()
    found: list[dict] = []
    errors = 0
    for sym in SYMBOLS:
        try:
            found += scan_symbol(sym, state, snapshot=True)
        except requests.RequestException as e:
            errors += 1
            print(f"  uyari: {sym} taranamadi: {e}", file=sys.stderr, flush=True)
        time.sleep(0.15)
    found.sort(key=lambda s: (_priority(s), s["symbol"]))
    return found, errors


def run_check() -> int:
    """--check: O AN aktif olan tum kurulumlarin anlik goruntusu. Bildirim
    GONDERMEZ, sadece terminale yazar; state'i kirletmez. "Istedigim an uygun
    strateji var mi?" sorusunun dogru araci (--once degil — o kenar-tetikleme
    oldugu icin soguk baslangicta hicbir sey gostermez)."""
    refresh_universe_if_due(force=True)
    print(f"anlik kontrol: {len(SYMBOLS)} sembol taraniyor "
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
                  f"{sig['direction']} ({sig['strength']})  fiyat={sig['price']}")
            for label, val in _signal_detail_rows(sig):
                print(f"    {label}: {val}")
            print(f"    {sig['note']}")
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


def fetch_klines_at(symbol: str, start_ms: int, limit: int) -> list[dict]:
    r = _spot_get("/api/v3/klines", {"symbol": symbol, "interval": "1h",
                                     "startTime": start_ms, "limit": limit})
    return [{"open_time": k[0], "open": float(k[1]), "close": float(k[4])}
            for k in r.json()]


def realized_performance(max_signals: int = None) -> dict:
    """signals.log'daki OLGUNLASMIS sinyallerin gerceklesen getirisini olcer
    (giris: sinyal barindan sonraki barin acilisi; cikis: ufuk sonundaki
    kapanis — arastirmayla birebir ayni tanim). Sonuclar diske cachelenir."""
    max_signals = max_signals or PERF_MAX_SIGNALS
    log_path = Path(__file__).parent / SIGNAL_LOG
    if not log_path.exists():
        return {"error": "signals.log yok — henuz sinyal uretilmedi"}
    cache = {}
    if PERF_CACHE_FILE.exists():
        try:
            cache = json.loads(PERF_CACHE_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            cache = {}
    now = datetime.now(timezone.utc)
    rows = []
    for line in log_path.read_text(encoding="utf-8").splitlines():
        try:
            sig = json.loads(line)
        except ValueError:
            continue
        if sig.get("strategy", "").startswith("TEST"):
            continue
        try:
            bar_t = datetime.fromisoformat(sig["bar_time"])
        except (KeyError, ValueError):
            continue
        h = int(sig.get("horizon_hours") or 0)
        if h <= 0 or bar_t + timedelta(hours=h + 2) > now:
            continue                       # henuz olgunlasmadi
        rows.append((bar_t, sig))
    rows = rows[-max_signals:]
    per_strat: dict[str, list[float]] = {}
    fetch_errors = 0
    for bar_t, sig in rows:
        key = f"{sig['bar_time']}|{sig['symbol']}|{sig['strategy']}"
        h = int(sig["horizon_hours"])
        if key in cache:
            ret = cache[key]
        else:
            try:
                ks = fetch_klines_at(sig["symbol"],
                                     int(bar_t.timestamp() * 1000), h + 2)
                if len(ks) < h + 1:
                    continue
                ret = (ks[h]["close"] / ks[1]["open"] - 1) * 100
                cache[key] = ret
                time.sleep(0.1)
            except requests.RequestException:
                fetch_errors += 1
                continue
        per_strat.setdefault(sig["strategy"].split("+")[0], []).append(ret)
    try:
        PERF_CACHE_FILE.write_text(json.dumps(cache), encoding="utf-8")
    except OSError:
        pass
    out = {"n_total": sum(len(v) for v in per_strat.values()),
           "fetch_errors": fetch_errors, "strategies": {}}
    for s, rets in sorted(per_strat.items()):
        arr = sorted(rets)
        med = arr[len(arr) // 2]
        bt = STRATEGY_STATS.get(s, {})
        out["strategies"][s] = {
            "n": len(rets),
            "median_pct": round(med, 2),
            "mean_pct": round(sum(rets) / len(rets), 2),
            "winrate_pct": round(100 * sum(1 for r in rets if r > 0) / len(rets)),
            "bt_median_pct": bt.get("med"), "bt_winrate_pct": bt.get("wr"),
        }
    return out


def _format_performance(perf: dict) -> str:
    if "error" in perf:
        return perf["error"]
    if perf["n_total"] == 0:
        return ("Henuz olgunlasmis sinyal yok (sinyaller ufuk suresi dolunca "
                "olculebilir hale gelir).")
    lines = [f"<b>Canli performans</b> (son {perf['n_total']} olgun sinyal; "
             "giris/cikis tanimi backtest ile ayni):"]
    for s, d in perf["strategies"].items():
        cmp_med = (f" (backtest medyan {d['bt_median_pct']:+.2f}%)"
                   if d.get("bt_median_pct") is not None else "")
        cmp_wr = (f" (backtest %{d['bt_winrate_pct']})"
                  if d.get("bt_winrate_pct") is not None else "")
        lines.append(f"• <b>{s}</b>: N={d['n']} medyan {d['median_pct']:+.2f}%"
                     f"{cmp_med} · isabet %{d['winrate_pct']}{cmp_wr} · "
                     f"ort {d['mean_pct']:+.2f}%")
    if perf["fetch_errors"]:
        lines.append(f"({perf['fetch_errors']} sinyal veri hatasindan olculemedi)")
    lines.append("\n<i>Kucuk N'de medyan/isabet cok oynak olur; 30+ sinyalden "
                 "once yargiya varma. Yatirim tavsiyesi degildir.</i>")
    return "\n".join(lines)


def _format_check_for_telegram(found: list[dict], errors: int) -> str:
    """/check cevabini kompakt HTML olarak bicimler (Telegram 4096 char siniri
    icin ilk 25 ile sinirli; detay/referans terminal --check'te)."""
    if not found:
        return ("Su an <b>aktif kurulum yok</b>. Kosullarin hicbiri "
                "saglanmiyor — normaldir, guclu kurulumlar seyrektir.")
    lines = [f"<b>Su an {len(found)} aktif kurulum</b> "
             f"(oncelik S1+S4&gt;S1&gt;S3&gt;S2):"]
    for s in found[:25]:
        if "rsi" in s:
            extra = f" RSI {s['rsi']}"
        elif "volume_logz" in s:
            extra = f" z {s['volume_logz']}"
        elif "funding_pct" in s:
            extra = f" fund {s['funding_pct'][-1]}%"
        else:
            extra = ""
        conf = s.get("confidence") or signal_confidence(s["strategy"])[0]
        lines.append(f"• <b>{_html.escape(s['strategy'])}</b> "
                     f"[{conf}] {_html.escape(s['symbol'])} @ "
                     f"{s['price']}{extra} → ~{s['horizon_hours']}h")
    if len(found) > 25:
        lines.append(f"…ve {len(found) - 25} tane daha")
    if errors:
        lines.append(f"(not: {errors} sembol cekilemedi)")
    lines.append("\n<i>Detay/referans: terminalde --check. "
                 "Yatirim tavsiyesi degildir.</i>")
    return "\n".join(lines)


def handle_telegram_command(text: str, chat_id: str) -> None:
    """Tek bir /komutu isler ve cevabi KOMUTU GONDEREN chat'e yollar."""
    cmd = text.strip().split()[0].lower().lstrip("/").split("@")[0]
    if cmd in ("start", "help"):
        _telegram_send_text(
            "🤖 <b>Signal Bot</b> calisiyor.\n\n"
            "Komutlar:\n"
            "/check — su an aktif kurulumlar\n"
            "/performans — canli sonuclar vs backtest\n"
            "/status — bot durumu\n"
            "/myid — kendi chat ID'in\n"
            "/help — bu mesaj\n\n"
            "Yeni sinyaller otomatik olarak buraya ve email'e dusecek. "
            "Yatirim tavsiyesi degildir.", chat_id=chat_id)
    elif cmd == "status":
        _telegram_send_text(
            "<b>Durum</b>\n"
            f"Sembol: {len(SYMBOLS)} ({'otomatik' if SYMBOL_AUTO else 'statik'})\n"
            f"Tamamlanan tarama: {SCANS_COMPLETED}\n"
            f"Son tarama: {LAST_SCAN_AT or '(henuz yok)'}\n"
            f"Son taramada hata: {LAST_SCAN_ERRORS}\n"
            f"Push esigi: {NOTIFY_MIN_CONFIDENCE}+ "
            f"(alti sessiz-kayit) · Kapali: "
            f"{', '.join(sorted(DISABLED_STRATEGIES)) or 'yok'}\n"
            f"Aboneler: {len(TELEGRAM_SUBSCRIBERS)}\n"
            f"Email: {'acik' if ENABLE_EMAIL else 'kapali'}", chat_id=chat_id)
    elif cmd in ("performans", "performance", "perf"):
        if not _check_lock.acquire(blocking=False):
            _telegram_send_text("Baska bir islem suruyor, birazdan tekrar dene.",
                                chat_id=chat_id)
            return
        try:
            _telegram_send_text("📊 Olculuyor… (gecmis veriler cekiliyor)",
                                chat_id=chat_id)
            _telegram_send_text(_format_performance(realized_performance()),
                                chat_id=chat_id)
        except Exception as e:
            _telegram_send_text(f"Olcum hatasi: {_html.escape(str(e))}",
                                chat_id=chat_id)
        finally:
            _check_lock.release()
    elif cmd == "check":
        if not _check_lock.acquire(blocking=False):
            _telegram_send_text("Zaten bir tarama suruyor, birkac saniye sonra "
                                "tekrar dene.", chat_id=chat_id)
            return
        try:
            _telegram_send_text("🔎 Taraniyor… (birkac saniye sur)",
                                chat_id=chat_id)
            found, errors = collect_active_setups()
            _telegram_send_text(_format_check_for_telegram(found, errors),
                                chat_id=chat_id)
        except Exception as e:
            _telegram_send_text(f"Tarama sirasinda hata: {_html.escape(str(e))}",
                                chat_id=chat_id)
        finally:
            _check_lock.release()
    else:
        _telegram_send_text(f"Bilinmeyen komut: /{_html.escape(cmd)}. /help yaz.",
                            chat_id=chat_id)


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
          "(/start /check /performans /status /myid)", flush=True)
    while True:
        try:
            params = {"timeout": 30}
            if offset is not None:
                params["offset"] = offset
            r = requests.get(f"{base}/getUpdates", params=params, timeout=45)
            r.raise_for_status()
            for upd in r.json().get("result", []):
                offset = upd["update_id"] + 1
                msg = upd.get("message") or upd.get("edited_message") or {}
                text = msg.get("text", "") or ""
                chat_id = str((msg.get("chat") or {}).get("id", ""))
                if not text.startswith("/"):
                    continue
                cmd0 = text.strip().split()[0].lower().lstrip("/").split("@")[0]
                if cmd0 == "myid":
                    # herkese acik: arkadasin ID'sini ogrenip sana iletmesi icin
                    _telegram_send_text(
                        f"Senin chat ID'in: <code>{chat_id}</code>\n"
                        "Botu kullanmak icin bu ID'yi bot sahibine ilet.",
                        chat_id=chat_id)
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
    """--test-notify: bildirim kanallarini SAHTE, acikca TEST etiketli bir
    sinyalle dener. Gercek sinyal beklemeden anahtarlarin dogru kuruldugunu
    dogrulamanin tek guvenilir yolu (gercek sinyaller seyrektir)."""
    print(f"kanallar: telegram={'ACIK' if ENABLE_TELEGRAM else 'KAPALI'} "
          f"email={'ACIK' if ENABLE_EMAIL else 'KAPALI'}")
    if not (ENABLE_TELEGRAM or ENABLE_EMAIL):
        print("Iki kanal da kapali: bot klasorunde .env dosyasi yok veya "
              "anahtar alanlari bos. .env.example'i .env olarak kopyalayip "
              "TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID / RESEND_API_KEY / "
              "NOTIFICATION_EMAIL degerlerini doldur.", file=sys.stderr)
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
    print("Gonderildi. Telegram mesajini ve email'i kontrol et "
          "(email icin spam klasorune de bak). Gelmediyse yukaridaki "
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
                    help="TEST etiketli sahte sinyali Telegram+email'e gonder "
                         "(anahtarlarin dogru kuruldugunu 10 sn'de dogrular)")
    args = ap.parse_args()
    if args.test_notify:
        run_test_notify()
    elif args.check:
        run_check()
    else:
        run_forever(once=args.once)


if __name__ == "__main__":
    main()
