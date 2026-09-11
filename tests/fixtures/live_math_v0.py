"""Frozen valid-input live behavior from commit 17a346d; test oracle only.
Executed by the parity suite with a mocked bot namespace, never imported as a bot.
"""
from __future__ import annotations

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

def scan_symbol(symbol: str, state: ScanState,
                snapshot: bool = False, observe: bool = False) -> list[dict]:
    """Bir sembolu tarar, sinyal listesini dondurur.

    snapshot=False (canli mod): kenar-tetikleme + cooldown uygulanir � sinyal
      SADECE kosul False->True gectiginde uretilir (bildirim spam'i olmasin).
    snapshot=True (--check modu): geci� aranmaz, o an AKTIF olan tum kosullar
      raporlanir. state'e dokunmaz. "Su an uygun kurulum var mi?" sorusu icin.
    observe=True (gozlem kanali): sembol DOGRULANMAMIS evrendendir. Yalniz S1
      ailesi hesaplanir (S2/S3 yeni coinlerde OOS basarisiz � Ek G), strateji
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
            if not snapshot and S2_DERIVATIVES_SHADOW_ENABLED:
                try:
                    def s2_shadow_get(path, params):
                        needs_key = path.endswith(
                            "/topLongShortPositionRatio")
                        if needs_key and not BINANCE_MARKET_DATA_API_KEY:
                            raise RuntimeError(
                                "market-data API key yapilandirilmamis")
                        return _futures_get(
                            path, params, market_data_key=needs_key)

                    capture_s2_derivatives_shadow(
                        s2_shadow_get, symbol, contract, fr, ARCHIVE_DIR)
                except Exception as e:
                    # G�lge ara�t�rma asla canl� S2 olay�n� d���rmemeli.
                    print("uyari: S2 turev golge kaydi basarisiz: "
                          f"{type(e).__name__}: {_redact(str(e))}",
                          file=sys.stderr, flush=True)

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
