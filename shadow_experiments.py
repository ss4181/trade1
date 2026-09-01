"""İleriye dönük G1/DL1 gölge olay taraması ve yerel araştırma arşivi.

Bu modül emir açmaz. G1 tarihsel train kapısını geçmemiştir; DL1-PRE deliste
kadar tutma kuralı tarihsel olarak reddedilmiştir ve DL1-POST için henüz
point-in-time dış borsa verisi yoktur. Bildirimlerin amacı bu hipotezleri
seçim yapmadan ileriye dönük toplamaktır.
"""

from __future__ import annotations

import json
import math
import re
import statistics
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable


BINANCE_DELIST_LIST = (
    "https://www.binance.com/bapi/composite/v1/public/cms/article/list/query")
BINANCE_DELIST_DETAIL = (
    "https://www.binance.com/bapi/composite/v1/public/cms/article/detail/query")
BYBIT_TICKER = "https://api.bybit.com/v5/market/tickers"
OKX_TICKER = "https://www.okx.com/api/v5/market/ticker"

G1_RETURN_24H_MIN = 0.05
G1_TOP_N = 10
G1_VOLUME_RATIO_MIN = 2.0
G1_OI_CHANGE_1H_MIN = 0.02
G1_LONG_SHORT_MAX = 1.0
G1_COOLDOWN_HOURS = 24
G1_HORIZON_HOURS = 4

TITLE_RE = re.compile(
    r"^Binance Will Delist (?P<tokens>.+?) on (?P<date>\d{4}-\d{2}-\d{2})$")
DEADLINE_RE = re.compile(r"(20\d{2}-\d{2}-\d{2})\s+(\d{2}:\d{2})\s*\(UTC\)")
STATE_SCHEMA_VERSION = 1
_archive_lock = threading.Lock()


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds")


def _float(value) -> float | None:
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError, OverflowError):
        return None


def _response_json(response) -> object:
    response.raise_for_status()
    return response.json()


def empty_state() -> dict:
    return {
        "schema_version": STATE_SCHEMA_VERSION,
        "s7_last_hour": None,
        "s7_prev_condition": {},
        "s7_last_fire": {},
        "delist_last_poll": None,
        "seen_articles": [],
        "delist_events": {},
    }


def load_state(path: Path) -> dict:
    if not path.exists():
        return empty_state()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return empty_state()
    state = empty_state()
    if isinstance(data, dict):
        for key in state:
            if key in data:
                state[key] = data[key]
    return state


def save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, sort_keys=True,
                              separators=(",", ":")), encoding="utf-8")
    tmp.replace(path)


def append_jsonl(archive_dir: Path, prefix: str, rows: list[dict],
                 now: datetime | None = None) -> None:
    if not rows:
        return
    now = now or _utc_now()
    archive_dir.mkdir(parents=True, exist_ok=True)
    path = archive_dir / f"{prefix}_{now:%Y-%m}.jsonl"
    payload = "\n".join(json.dumps(row, ensure_ascii=False,
                                    sort_keys=True, separators=(",", ":"))
                          for row in rows) + "\n"
    with _archive_lock, path.open("a", encoding="utf-8") as stream:
        stream.write(payload)


def _closed_klines(raw: list, now_ms: int) -> list:
    return [row for row in raw if isinstance(row, list) and len(row) > 7
            and int(row[6]) < now_ms]


def evaluate_g1_snapshot(klines: list, oi_rows: list, ls_rows: list,
                         rank: int, ticker_return_pct: float,
                         now_ms: int) -> dict:
    """Yalnız kapanmış 1h verisini kullanarak G1 koşullarını hesaplar."""
    closed = _closed_klines(klines, now_ms)
    if len(closed) < 25:
        raise ValueError(f"G1 için kapanmış 1h mum yetersiz: {len(closed)}")
    closed = closed[-25:]
    close_now = float(closed[-1][4])
    close_24 = float(closed[0][4])
    prior_volumes = [float(row[7]) for row in closed[:-1]]
    prior_median = statistics.median(prior_volumes)
    current_volume = float(closed[-1][7])
    volume_ratio = current_volume / prior_median if prior_median > 0 else None
    cutoff_ms = int(closed[-1][6])

    usable_oi = sorted(
        [row for row in oi_rows if isinstance(row, dict)
         and int(row.get("timestamp") or 0) <= cutoff_ms],
        key=lambda row: int(row.get("timestamp") or 0))
    if len(usable_oi) < 2:
        raise ValueError("G1 için kapanmış iki OI snapshot'ı yok")
    oi_prev = _float(usable_oi[-2].get("sumOpenInterest"))
    oi_now = _float(usable_oi[-1].get("sumOpenInterest"))
    if oi_prev is None or oi_now is None or oi_prev <= 0:
        raise ValueError("G1 OI değeri geçersiz")
    oi_change = oi_now / oi_prev - 1

    usable_ls = sorted(
        [row for row in ls_rows if isinstance(row, dict)
         and int(row.get("timestamp") or 0) <= cutoff_ms],
        key=lambda row: int(row.get("timestamp") or 0))
    if not usable_ls:
        raise ValueError("G1 kapanmış global long/short snapshot'ı yok")
    long_short = _float(usable_ls[-1].get("longShortRatio"))
    if long_short is None:
        raise ValueError("G1 global long/short oranı geçersiz")

    return_24h = close_now / close_24 - 1
    condition = (
        return_24h >= G1_RETURN_24H_MIN
        and rank <= G1_TOP_N
        and volume_ratio is not None and volume_ratio >= G1_VOLUME_RATIO_MIN
        and oi_change >= G1_OI_CHANGE_1H_MIN
        and long_short < G1_LONG_SHORT_MAX
    )
    return {
        "bar_open_ms": int(closed[-1][0]), "bar_close_ms": cutoff_ms,
        "close": close_now, "return_24h": return_24h,
        "ticker_return_24h": ticker_return_pct / 100.0,
        "rank": rank, "quote_volume_1h": current_volume,
        "prior_24h_volume_median": prior_median,
        "volume_ratio": volume_ratio, "open_interest": oi_now,
        "oi_change_1h": oi_change, "global_long_short_ratio": long_short,
        "global_long_account": _float(usable_ls[-1].get("longAccount")),
        "global_short_account": _float(usable_ls[-1].get("shortAccount")),
        "condition": condition,
    }


def scan_g1(futures_get: Callable, state_path: Path, archive_dir: Path,
            now: datetime | None = None) -> list[dict]:
    """Tüm aktif USD-M perpleri sıralar, ilk 10'u ayrıntılı gölge tarar."""
    now = now or _utc_now()
    now_ms = int(now.timestamp() * 1000)
    hour_key = (now.replace(minute=0, second=0, microsecond=0) -
                timedelta(hours=1)).isoformat()
    state = load_state(state_path)
    if state.get("s7_last_hour") == hour_key:
        return []

    exchange = _response_json(futures_get("/fapi/v1/exchangeInfo"))
    active = {
        str(row.get("symbol")) for row in exchange.get("symbols", [])
        if row.get("contractType") == "PERPETUAL"
        and row.get("status") == "TRADING"
        and row.get("quoteAsset") == "USDT"
    }
    tickers = _response_json(futures_get("/fapi/v1/ticker/24hr"))
    ranked = []
    for ticker in tickers if isinstance(tickers, list) else []:
        symbol = str(ticker.get("symbol") or "")
        change = _float(ticker.get("priceChangePercent"))
        if symbol in active and change is not None:
            ranked.append((change, symbol, ticker))
    ranked.sort(key=lambda item: (-item[0], item[1]))
    top = ranked[:G1_TOP_N]

    snapshots, evaluated = [], {}
    for rank, (ticker_change, symbol, ticker) in enumerate(top, 1):
        try:
            klines = _response_json(futures_get("/fapi/v1/klines", {
                "symbol": symbol, "interval": "1h", "limit": 26,
            }))
            oi_rows = _response_json(futures_get(
                "/futures/data/openInterestHist", {
                    "symbol": symbol, "period": "1h", "limit": 3,
                }))
            ls_rows = _response_json(futures_get(
                "/futures/data/globalLongShortAccountRatio", {
                    "symbol": symbol, "period": "1h", "limit": 2,
                }))
            metrics = evaluate_g1_snapshot(
                klines, oi_rows, ls_rows, rank, ticker_change, now_ms)
            # Koşul yalnız kapanmış 1s mumla hesaplanır; kullanıcıya gösterilen
            # fiyat ise tarama anındaki USD-M ticker fiyatıdır. Böylece bot saat
            # içinde gecikmeli çalışırsa eski mum kapanışı "giriş fiyatı" gibi
            # görünmez. Ticker yoksa açıkça işaretli kapanış fallback'i kalır.
            metrics["observed_price"] = _float(ticker.get("lastPrice"))
            evaluated[symbol] = metrics
            snapshots.append({
                "schema_version": "shadow-market-v1", "kind": "G1_SNAPSHOT",
                "source": "binance_public_usdm", "observed_at": _iso(now),
                "universe": "all_active_usdm_perpetuals",
                "active_universe_size": len(active), "symbol": symbol,
                **metrics,
            })
        except Exception as exc:
            snapshots.append({
                "schema_version": "shadow-market-v1", "kind": "G1_SNAPSHOT",
                "source": "binance_public_usdm", "observed_at": _iso(now),
                "symbol": symbol, "rank": rank, "condition": None,
                "unavailable_reason": f"{type(exc).__name__}: {str(exc)[:160]}",
            })
    append_jsonl(archive_dir, "shadow_market", snapshots, now)
    if not evaluated:
        return []

    previous = state.setdefault("s7_prev_condition", {})
    last_fire = state.setdefault("s7_last_fire", {})
    current_true = {symbol for symbol, row in evaluated.items()
                    if row["condition"]}
    signals = []
    for symbol, metrics in evaluated.items():
        was_true = bool(previous.get(symbol))
        fire_ok = True
        if last_fire.get(symbol):
            try:
                fired_at = datetime.fromisoformat(last_fire[symbol])
                fire_ok = now - fired_at >= timedelta(hours=G1_COOLDOWN_HOURS)
            except (TypeError, ValueError):
                pass
        if metrics["condition"] and not was_true and fire_ok:
            bar_time = datetime.fromtimestamp(
                metrics["bar_open_ms"] / 1000, tz=timezone.utc)
            condition_close = datetime.fromtimestamp(
                metrics["bar_close_ms"] / 1000, tz=timezone.utc)
            measurement_entry = datetime.fromtimestamp(
                (metrics["bar_close_ms"] + 1) / 1000, tz=timezone.utc)
            observed_price = metrics.get("observed_price")
            has_observed_price = (observed_price is not None
                                  and observed_price > 0)
            display_price = (observed_price if has_observed_price
                             else metrics["close"])
            delay_minutes = max(
                0.0, (now_ms - (metrics["bar_close_ms"] + 1)) / 60_000)
            signal = {
                "strategy": "G1", "symbol": symbol, "direction": "LONG",
                "strength": "RESEARCH", "confidence": "GOZLEM",
                "confidence_note": "Tarihsel train kapısı RED; ileri ölçüm",
                "bar_time": _iso(bar_time), "price": display_price,
                "observed_at": _iso(now),
                "condition_bar_close_utc": _iso(condition_close),
                "measurement_entry_time_utc": _iso(measurement_entry),
                "condition_price": metrics["close"],
                "notification_delay_minutes": round(delay_minutes, 2),
                "horizon_hours": G1_HORIZON_HOURS,
                "rank_24h": metrics["rank"],
                "return_24h_pct": round(metrics["return_24h"] * 100, 3),
                "volume_ratio": round(metrics["volume_ratio"], 3),
                "oi_change_1h_pct": round(metrics["oi_change_1h"] * 100, 3),
                "global_long_short_ratio": round(
                    metrics["global_long_short_ratio"], 4),
                "global_short_account_pct": (round(
                    metrics["global_short_account"] * 100, 2)
                    if metrics["global_short_account"] is not None else None),
                "note": ("İlk-10 yükselen + hacim/OI artışı + short hesap "
                         "çoğunluğu. Tarihsel 4h train: N=401, net medyan "
                         "−%0,30, isabet %45,9; doğrulanmadı, yalnız gölge takip."),
                "observe": True, "experimental": True,
                "universe": "all_active_usdm_perpetuals",
                "signal_market": "usd_m_perp",
                "performance_market": "um_perp",
                "performance_symbol": symbol,
                "price_source": ("usdm_24h_ticker_last_at_scan"
                                 if has_observed_price
                                 else "closed_usdm_1h_fallback"),
                "push_policy_enabled": True,
                "config_version": "G1-prereg-2026-09-01-v2-price-fix",
            }
            signals.append(signal)
            last_fire[symbol] = _iso(now)
        previous[symbol] = bool(metrics["condition"])
    for symbol in list(previous):
        if symbol not in current_true and symbol not in evaluated:
            previous[symbol] = False
    state["s7_last_hour"] = hour_key
    save_state(state_path, state)
    append_jsonl(archive_dir, "shadow_events", [
        {"schema_version": "shadow-event-v1", "kind": "G1_EVENT",
         "recorded_at": _iso(now), **signal} for signal in signals
    ], now)
    return signals


def title_tokens(title: str) -> list[str]:
    match = TITLE_RE.fullmatch(str(title).strip())
    if not match:
        return []
    raw = re.sub(r"\s+(?:and|&)\s+", ",", match.group("tokens"),
                 flags=re.IGNORECASE)
    return [part.strip().upper() for part in raw.split(",")
            if re.fullmatch(r"[A-Z0-9]{2,15}", part.strip().upper())]


def _texts(node) -> list[str]:
    if isinstance(node, dict):
        own = [str(node["text"])] if "text" in node else []
        return own + [text for value in node.values() for text in _texts(value)]
    if isinstance(node, list):
        return [text for value in node for text in _texts(value)]
    return []


def parse_delist_detail(article: dict, detail_payload: dict) -> dict | None:
    tokens = title_tokens(article.get("title", ""))
    if not tokens:
        return None
    data = detail_payload.get("data") or {}
    body = data.get("body") or "{}"
    try:
        body = json.loads(body) if isinstance(body, str) else body
    except json.JSONDecodeError:
        body = {}
    text = " ".join(_texts(body)).replace("&nbsp;", " ")
    phrase = "delist and cease trading on all spot trading pairs"
    pos = text.lower().find(phrase)
    if pos < 0:
        return None
    deadline = DEADLINE_RE.search(text[pos:])
    if not deadline:
        return None
    released_ms = int(article.get("releaseDate") or data.get("publishDate") or 0)
    return {
        "article_code": str(article.get("code") or data.get("code") or ""),
        "title": str(article.get("title") or data.get("title") or ""),
        "announcement_at": _iso(datetime.fromtimestamp(
            released_ms / 1000, tz=timezone.utc)),
        "delist_at": _iso(datetime.strptime(
            f"{deadline.group(1)} {deadline.group(2)}", "%Y-%m-%d %H:%M"
        ).replace(tzinfo=timezone.utc)),
        "tokens": tokens,
        "article_url": ("https://www.binance.com/en/support/announcement/detail/"
                        f"{article.get('code', '')}"),
    }


def _public_get(http_get: Callable, url: str, params: dict) -> object:
    return _response_json(http_get(url, params=params, timeout=30))


def _spot_snapshot(spot_get: Callable, symbol: str) -> dict:
    try:
        payload = _response_json(spot_get("/api/v3/ticker/24hr",
                                          {"symbol": symbol}))
        return {"available": True, "symbol": symbol,
                "last": _float(payload.get("lastPrice")),
                "bid": _float(payload.get("bidPrice")),
                "ask": _float(payload.get("askPrice")),
                "quote_volume_24h": _float(payload.get("quoteVolume")),
                "change_24h_pct": _float(payload.get("priceChangePercent"))}
    except Exception as exc:
        return {"available": False, "symbol": symbol,
                "unavailable_reason": f"{type(exc).__name__}: {str(exc)[:120]}"}


def _bybit_snapshot(http_get: Callable, token: str) -> dict:
    for symbol in (f"{token}USDT", f"1000{token}USDT"):
        try:
            payload = _public_get(http_get, BYBIT_TICKER,
                                  {"category": "linear", "symbol": symbol})
            rows = ((payload.get("result") or {}).get("list") or [])
            if rows:
                row = rows[0]
                return {"available": True, "symbol": symbol,
                        "last": _float(row.get("lastPrice")),
                        "mark": _float(row.get("markPrice")),
                        "bid": _float(row.get("bid1Price")),
                        "ask": _float(row.get("ask1Price")),
                        "open_interest": _float(row.get("openInterest")),
                        "funding_rate": _float(row.get("fundingRate"))}
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {str(exc)[:120]}"
    return {"available": False, "symbol": f"{token}USDT",
            "unavailable_reason": locals().get("last_error", "not_listed")}


def _okx_snapshot(http_get: Callable, token: str) -> dict:
    symbol = f"{token}-USDT-SWAP"
    try:
        payload = _public_get(http_get, OKX_TICKER, {"instId": symbol})
        rows = payload.get("data") or []
        if rows:
            row = rows[0]
            return {"available": True, "symbol": symbol,
                    "last": _float(row.get("last")),
                    "bid": _float(row.get("bidPx")),
                    "ask": _float(row.get("askPx")),
                    "quote_volume_24h": _float(row.get("volCcy24h"))}
        return {"available": False, "symbol": symbol,
                "unavailable_reason": "not_listed"}
    except Exception as exc:
        return {"available": False, "symbol": symbol,
                "unavailable_reason": f"{type(exc).__name__}: {str(exc)[:120]}"}


def poll_dl1(http_get: Callable, spot_get: Callable, state_path: Path,
            archive_dir: Path, poll_minutes: int = 30,
            now: datetime | None = None) -> list[dict]:
    """Resmî tam-token delist olaylarını bulur ve 72h sonrasına dek arşivler."""
    now = now or _utc_now()
    state = load_state(state_path)
    if state.get("delist_last_poll"):
        try:
            last = datetime.fromisoformat(state["delist_last_poll"])
            if now - last < timedelta(minutes=max(5, poll_minutes)):
                return []
        except (TypeError, ValueError):
            pass
    listing = _public_get(http_get, BINANCE_DELIST_LIST, {
        "type": 1, "catalogId": 161, "pageNo": 1, "pageSize": 20,
    })
    catalogs = ((listing.get("data") or {}).get("catalogs") or [])
    articles = (catalogs[0].get("articles") or []) if catalogs else []
    seen = set(str(code) for code in state.get("seen_articles", []))
    tracked = state.setdefault("delist_events", {})
    for article in articles:
        code = str(article.get("code") or "")
        if not code:
            continue
        if title_tokens(article.get("title", "")):
            try:
                detail = _public_get(http_get, BINANCE_DELIST_DETAIL,
                                     {"articleCode": code})
                event = parse_delist_detail(article, detail)
                if event:
                    deadline = datetime.fromisoformat(event["delist_at"])
                    if deadline + timedelta(hours=72) > now:
                        old = tracked.get(code, {})
                        event["notified_tokens"] = list(
                            old.get("notified_tokens", []))
                        tracked[code] = event
            except Exception:
                pass
        seen.add(code)
    state["seen_articles"] = sorted(seen)[-500:]

    snapshots, signals = [], []
    for code, event in list(tracked.items()):
        try:
            deadline = datetime.fromisoformat(event["delist_at"])
        except (KeyError, TypeError, ValueError):
            continue
        if now > deadline + timedelta(hours=72):
            continue
        notified = set(event.get("notified_tokens", []))
        for token in event.get("tokens", []):
            spot = _spot_snapshot(spot_get, f"{token}USDT")
            bybit = _bybit_snapshot(http_get, token)
            okx = _okx_snapshot(http_get, token)
            snapshot = {
                "schema_version": "shadow-market-v1", "kind": "DL1_SNAPSHOT",
                "source": "binance_announcement_plus_public_venues",
                "observed_at": _iso(now), "article_code": code,
                "announcement_at": event["announcement_at"],
                "delist_at": event["delist_at"], "token": token,
                "binance_spot": spot, "bybit_linear": bybit,
                "okx_usdt_swap": okx,
            }
            snapshots.append(snapshot)
            # Token fiyatı ilk denemede yoksa sonraki poll'da yeniden dene;
            # notified_tokens kalıcı olduğu için başarılı teslim adayı bir kez
            # üretilir. Geçmiş olaylar deadline>now kapısından geçemez.
            should_notify = deadline > now and token not in notified
            price = spot.get("last") or bybit.get("last") or okx.get("last")
            if should_notify and price and price > 0:
                remaining = max(1, math.ceil((deadline - now).total_seconds() / 3600))
                signals.append({
                    "strategy": "DL1", "symbol": f"{token}USDT",
                    "direction": "EVENT", "strength": "RESEARCH",
                    "confidence": "GOZLEM",
                    "confidence_note": "Deliste kadar tutma tarihsel olarak RED",
                    "bar_time": _iso(now), "price": price,
                    "horizon_hours": remaining,
                    "announcement_at": event["announcement_at"],
                    "delist_at": event["delist_at"],
                    "article_url": event["article_url"],
                    "bybit_perp_available": bool(bybit.get("available")),
                    "bybit_perp_symbol": bybit.get("symbol"),
                    "okx_perp_available": bool(okx.get("available")),
                    "okx_perp_symbol": okx.get("symbol"),
                    "note": ("Resmî Binance tam-token delist olayı. Tarihsel "
                             "duyuru→delist bekletme: N=107, medyan −%53,6, "
                             "isabet %8,4; AL/TUT sinyali değildir. Dış borsa "
                             "short hipotezi henüz yalnız arşivleniyor."),
                    "observe": True, "experimental": True,
                    "performance_excluded": True,
                    "universe": "binance_full_token_delists",
                    "signal_market": "event",
                    "performance_market": "not_yet_validated",
                    "price_source": ("binance_spot_ticker" if spot.get("last")
                                     else "external_ticker"),
                    "push_policy_enabled": True,
                    "config_version": "DL1-prereg-2026-08-31-v1",
                })
                notified.add(token)
        event["notified_tokens"] = sorted(notified)
    append_jsonl(archive_dir, "shadow_market", snapshots, now)
    append_jsonl(archive_dir, "shadow_events", [
        {"schema_version": "shadow-event-v1", "kind": "DL1_EVENT",
         "recorded_at": _iso(now), **signal} for signal in signals
    ], now)
    state["delist_last_poll"] = _iso(now)
    save_state(state_path, state)
    return signals


def summarize_archive(archive_dir: Path) -> dict:
    result = {"schema_version": STATE_SCHEMA_VERSION, "files": [],
              "rows": 0, "g1_events": 0, "dl1_events": 0,
              "first_at": None, "last_at": None}
    stamps = []
    for path in sorted(archive_dir.glob("shadow_*.jsonl")):
        count = 0
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
            except ValueError:
                continue
            count += 1
            kind = str(row.get("kind") or "")
            result["g1_events"] += int(kind == "G1_EVENT")
            result["dl1_events"] += int(kind == "DL1_EVENT")
            stamp = row.get("recorded_at") or row.get("observed_at")
            if stamp:
                stamps.append(str(stamp))
        result["files"].append({"name": path.name, "rows": count,
                                "bytes": path.stat().st_size})
        result["rows"] += count
    if stamps:
        result["first_at"], result["last_at"] = min(stamps), max(stamps)
    return result
