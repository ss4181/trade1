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
from datetime import datetime, timezone
from pathlib import Path

import requests

try:
    import resend  # opsiyonel: yalnizca email etkinse gerekir
except ImportError:
    resend = None

# --------------------------------------------------------------------------
# konfigurasyon (.env ile ezilebilir; gerekceler .env.example ve README'de)
# --------------------------------------------------------------------------

def _load_env(path: str = ".env") -> None:
    p = Path(__file__).parent / path
    if not p.exists():
        return
    for line in p.read_text().splitlines():
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
SYMBOLS = [s.strip() for s in _env("SYMBOLS", DEFAULT_SYMBOLS).split(",") if s.strip()]
SCAN_INTERVAL_MINUTES = _env("SCAN_INTERVAL_MINUTES", 60)
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

SPOT_API = "https://api.binance.com"
FUT_API = "https://fapi.binance.com"

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

# Mobil endpoint (server.py) icin son sinyaller — thread-guvenli halka tampon.
RECENT_MAXLEN = _env("RECENT_MAXLEN", 100)
RECENT_SIGNALS: deque[dict] = deque(maxlen=RECENT_MAXLEN)
_recent_lock = threading.Lock()

# Servis saglik durumu (server.py /health endpoint'i okur).
STARTED_AT = datetime.now(timezone.utc).isoformat()
LAST_SCAN_AT: str | None = None
LAST_SCAN_COUNT = 0
SCANS_COMPLETED = 0

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
    r = requests.get(f"{SPOT_API}/api/v3/klines",
                     params={"symbol": symbol, "interval": "1h", "limit": limit},
                     timeout=30)
    r.raise_for_status()
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


# spot sembolu -> perp sembolu (dusuk fiyatli coinlerde 1000x kontrat)
def perp_symbol(spot: str) -> str:
    return {"PEPEUSDT": "1000PEPEUSDT"}.get(spot, spot)

# --------------------------------------------------------------------------
# tarama
# --------------------------------------------------------------------------

class ScanState:
    """Kenar-tetikleme + cooldown icin bellek: ayni kosul streak'i tek sinyal."""

    def __init__(self):
        self.prev_cond: dict[tuple[str, str], bool] = {}
        self.last_fire: dict[tuple[str, str], float] = {}

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


def scan_symbol(symbol: str, state: ScanState) -> list[dict]:
    """Bir sembolu tarar, tetiklenen sinyal listesini dondurur."""
    signals = []
    now_s = time.time()

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
    s1_cond = (not math.isnan(rsi[i]) and rsi[i] <= RSI_OVERSOLD
               and bullish_divergence(closes, lows, rsi, i))
    if state.should_fire("S1", symbol, s1_cond, S1_COOLDOWN_HOURS, now_s):
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
    if (state.should_fire("S3", symbol, s3_spike, S3_COOLDOWN_HOURS, now_s)
            and closes[i] > opens[i]):
        signals.append({
            "strategy": "S3", "symbol": symbol, "direction": "LONG",
            "strength": "NORMAL", "bar_time": bar_ts.isoformat(),
            "price": closes[i], "volume_logz": round(zs[i], 2),
            "note": "yukari-bar hacim patlamasi (momentum devami)",
            "horizon_hours": 4,
        })

    # ---- S2: funding squeeze (long) ----
    try:
        fr = fetch_funding(perp_symbol(symbol), limit=FUNDING_PERSISTENCE + 1)
    except requests.RequestException:
        fr = []                                # perp yoksa/ulasilamazsa atla
    if len(fr) >= FUNDING_PERSISTENCE:
        thr = FUNDING_SQUEEZE_THRESHOLD_PCT / 100.0
        last_n = fr[-FUNDING_PERSISTENCE:]
        s2_cond = all(x["rate"] <= thr for x in last_n)
        if state.should_fire("S2", symbol, s2_cond, S2_COOLDOWN_HOURS, now_s):
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


def send_telegram_message(sig: dict) -> None:
    """Telegram Bot API ile sinyal gonderir. Anahtar yoksa sessizce atlar;
    hata olursa uyarir ama tarama dongusunu ASLA durdurmaz."""
    if not ENABLE_TELEGRAM:
        return
    icon = "‼️" if sig.get("strength") == "STRONG" else "\U0001f514"
    lines = [
        f"{icon} <b>{_html.escape(sig['strategy'])}</b> — "
        f"<b>{_html.escape(sig['symbol'])}</b> {sig['direction']} "
        f"({sig['strength']})",
        f"Fiyat: {sig['price']}",
        f"Beklenen ufuk: ~{sig['horizon_hours']} saat",
    ]
    lines += [f"{label}: {_html.escape(val)}"
              for label, val in _signal_detail_rows(sig)]
    lines.append(_html.escape(sig["note"]))
    lines.append(f"<i>{_html.escape(sig['bar_time'])}</i>")
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": "\n".join(lines),
                  "parse_mode": "HTML", "disable_web_page_preview": True},
            timeout=15)
        r.raise_for_status()
    except requests.RequestException as e:
        print(f"uyari: Telegram gonderilemedi: {e}", file=sys.stderr, flush=True)


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


def notify(sig: dict) -> None:
    """Tek sinyal cikis noktasi: stdout + JSONL log + mobil tampon + Telegram
    + email. Sinyaller HER IKI kanala da (Telegram VE email) gonderilir.

    Anti-spam UST AKISTA yapilir (ScanState.should_fire — kenar-tetikleme +
    strateji-basi cooldown): buraya ulasan her sinyal zaten tekillestirilmistir,
    dolayisiyla iki kanal ayni deduplike sinyali alir, ayri ayri sayilmaz."""
    line = (f"[{sig['bar_time']}] {sig['strategy']:<6} {sig['symbol']:<12} "
            f"{sig['direction']} ({sig['strength']}) fiyat={sig['price']} "
            f"~{sig['horizon_hours']}h | {sig['note']}")
    print(line, flush=True)
    with open(Path(__file__).parent / SIGNAL_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(sig, ensure_ascii=False) + "\n")
    with _recent_lock:
        RECENT_SIGNALS.appendleft(
            {**sig, "notified_at": datetime.now(timezone.utc).isoformat()})
    send_telegram_message(sig)
    send_email_notification(sig)


def scan_all(state: ScanState) -> int:
    count = 0
    for sym in SYMBOLS:
        try:
            for sig in scan_symbol(sym, state):
                notify(sig)
                count += 1
        except requests.RequestException as e:
            print(f"uyari: {sym} taranamadi: {e}", file=sys.stderr, flush=True)
        time.sleep(0.25)          # nazik olalim (limitin cok altindayiz)
    return count


def run_forever(once: bool = False, state: ScanState | None = None) -> None:
    """Tarama dongusu. CLI dogrudan cagirir; server.py bir arka plan
    thread'inde cagirir (web servisini bloklamadan). Bir tarama cyklusundeki
    beklenmeyen hata dongusu OLDURMEZ — 7/24 servis icin dayaniklilik."""
    global LAST_SCAN_AT, LAST_SCAN_COUNT, SCANS_COMPLETED
    state = state or ScanState()
    print(f"signal_bot basladi: {len(SYMBOLS)} sembol, "
          f"{SCAN_INTERVAL_MINUTES}dk aralik "
          f"(telegram={'acik' if ENABLE_TELEGRAM else 'kapali'}, "
          f"email={'acik' if ENABLE_EMAIL else 'kapali'})", flush=True)
    while True:
        t0 = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
        try:
            n = scan_all(state)
            LAST_SCAN_AT = datetime.now(timezone.utc).isoformat()
            LAST_SCAN_COUNT = n
            SCANS_COMPLETED += 1
            print(f"[{t0}] tarama bitti: {n} sinyal", flush=True)
        except Exception as e:  # tek dongu hatasi 7/24 servisi dusurmemeli
            print(f"hata: tarama dongusunde beklenmeyen hata: {e}",
                  file=sys.stderr, flush=True)
        if once:
            break
        # bir sonraki bar kapanisindan ~90sn sonrasina hizalan
        period = SCAN_INTERVAL_MINUTES * 60
        now = time.time()
        time.sleep(period - (now % period) + 90)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true", help="tek tarama yap ve cik")
    args = ap.parse_args()
    run_forever(once=args.once)


if __name__ == "__main__":
    main()
