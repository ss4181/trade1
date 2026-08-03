"""Ek I — Funding hasadi hipotezinin testi (2026-08-03).

HIPOTEZ: S2'yi yonlu sinyal olarak degil, funding ODEMESINI toplayan bir
kurulum olarak kullan. |FR| uc degerlere ciktiginda (orn. %1.5-2) odemeyi ALAN
tarafa gec, odemeyi cebe at.

PROTOKOL (REPORT.md §10):
  train = 2024-07-01 .. 2026-01-01   |   test = 2026H1
  Once SADECE train olculur; train'de gecmezse test'e HIC bakilmaz.

KASITLI IYIMSER KURULUM — sonuc bir UST SINIRDIR:
  * Giris sinyali olarak SETTLED funding orani kullanilir. Bu LOOKAHEAD'dir;
    canlida yalnizca TAHMINI oran gorulebilir. Gercek strateji bundan KOTU
    olur.
  * Maliyet 10bp gidis-donus (taker/taker). Kayma DAHIL DEGIL — bu likiditesi
    dusuk coinlerde 5 dakikalik gir-cik icin iyimser bir varsayim.
Boyle bir ust sinirda bile negatifse, hipotez kapanmistir.

Kullanim:
    python research/sweep_funding_harvest.py            # train (varsayilan)
    python research/sweep_funding_harvest.py --test     # yalniz train gecerse

Veri onbellege alinir (funding_cache/), tekrar calistirmada indirilmez.
"""
from __future__ import annotations

import json
import os
import statistics
import sys
import time
from collections import Counter

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ENABLE_TELEGRAM", "false")
import signal_bot as bot  # noqa: E402

FAPI = "https://fapi.binance.com"
CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "funding_cache")
TRAIN = (1719792000000, 1767225600000)     # 2024-07-01 .. 2026-01-01
TEST = (1767225600000, 1782864000000)      # 2026-01-01 .. 2026-07-01
COST_BP = 10.0
FREQ_THRESHOLDS = [0.01, 0.05, 0.1, 0.3, 0.5, 0.75, 1.0, 1.5, 2.0]
THRESHOLDS = [0.5, 0.75, 1.0, 1.5, 2.0]


def _cache(name: str, build):
    os.makedirs(CACHE_DIR, exist_ok=True)
    path = os.path.join(CACHE_DIR, name)
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    data = build()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)
    return data


def universe() -> list[str]:
    return [s.strip() for s in bot.DEFAULT_SYMBOLS.split(",")] + \
        sorted(bot.EXTENDED_SET)


def funding_history() -> dict[str, list]:
    def build():
        out = {}
        syms = universe()
        for i, s in enumerate(syms):
            perp, rows, start = bot.perp_symbol(s), [], TRAIN[0]
            try:
                while True:
                    r = bot._futures_get(
                        "/fapi/v1/fundingRate",
                        {"symbol": perp, "startTime": start,
                         "endTime": TEST[1], "limit": 1000})
                    batch = r.json()
                    if not batch:
                        break
                    rows += [(int(x["fundingTime"]), float(x["fundingRate"]))
                             for x in batch]
                    if len(batch) < 1000:
                        break
                    start = int(batch[-1]["fundingTime"]) + 1
                    time.sleep(0.12)
            except Exception as e:                          # noqa: BLE001
                print(f"  ! {s}: {e}", file=sys.stderr)
            out[s] = sorted(set(rows))
            if i % 10 == 0:
                print(f"  funding {i}/{len(syms)} ...", flush=True)
            time.sleep(0.12)
        return out
    return _cache("funding_history.json", build)


# SABIT pencere: onbellek anahtari cikis uzunlugunu TASIMAZ, bu yuzden
# pencere de tasimamali. (Once kisa pencereyle onbellege alinirsa uzun
# cikislar veri bulamaz ve N satirdan satira tutarsiz olur.)
BARS_BEFORE = 6
BARS_AFTER = 16


def _klines(symbol: str, t_ms: int, interval: str, bar_ms: int,
            store: dict) -> list[dict]:
    key = f"{symbol}|{interval}|{t_ms}"
    if key in store:
        return store[key]
    try:
        r = requests.get(f"{FAPI}/fapi/v1/klines",
                         params={"symbol": symbol, "interval": interval,
                                 "startTime": t_ms - BARS_BEFORE * bar_ms,
                                 "limit": BARS_BEFORE + BARS_AFTER},
                         timeout=30)
        rows = r.json() if r.status_code == 200 else []
        store[key] = ([{"t": int(k[0]), "c": float(k[4])} for k in rows]
                      if isinstance(rows, list) else [])
    except Exception:                                       # noqa: BLE001
        store[key] = []
    time.sleep(0.08)
    return store[key]


def events(hist, lo, hi, thr):
    return sorted((t, s, r) for s, rows in hist.items() for t, r in rows
                  if lo <= t < hi and abs(r) * 100 >= thr)


def measure(evs, interval, bar_ms, exit_bars, store):
    """Giris = T'den ONCEKI barin kapanisi, cikis = T'den sonraki
    `exit_bars`. Odeme ani pozisyon acikken gecer."""
    rets, fu, px = [], [], []
    for t, sym, r in evs:
        ks = _klines(bot.perp_symbol(sym), t, interval, bar_ms, store)
        idx = next((i for i, k in enumerate(ks)
                    if k["t"] <= t < k["t"] + bar_ms), None)
        if idx is None or idx == 0 or idx + exit_bars >= len(ks):
            continue
        entry, exit_ = ks[idx - 1]["c"], ks[idx + exit_bars - 1]["c"]
        if entry <= 0:
            continue
        side = 1.0 if r < 0 else -1.0        # negatif FR -> long ALIR
        p = side * (exit_ / entry - 1) * 100
        f = abs(r) * 100
        rets.append(f + p - COST_BP / 100)
        fu.append(f)
        px.append(p)
    return rets, fu, px


def frequency_table(hist):
    total = 0
    counts = Counter()
    intervals = Counter()
    for rows in hist.values():
        total += len(rows)
        for j in range(1, len(rows)):
            dt = (rows[j][0] - rows[j - 1][0]) / 3_600_000
            if 0 < dt <= 24:
                intervals[round(dt)] += 1
        for _t, r in rows:
            pct = abs(r) * 100
            for th in FREQ_THRESHOLDS:
                if pct >= th:
                    counts[th] += 1
    print(f"\nADIM 1 — FREKANS: {total:,} funding kaydi, "
          f"{len(hist)} sembol, 24 ay")
    print(f"Funding araligi (saat): "
          f"{dict(sorted(intervals.items(), key=lambda kv: -kv[1])[:4])}")
    print(f"{'|FR| >= %':>10}{'olay':>9}{'oran %':>11}{'ayda/evren':>12}")
    for th in FREQ_THRESHOLDS:
        n = counts[th]
        print(f"{th:>10.2f}{n:>9,}{n/total*100 if total else 0:>11.4f}"
              f"{n/24:>12.1f}")


def outcome_table(hist, label, lo, hi, interval, bar_ms, exits, store):
    print(f"\n{'='*76}\n{label}\n{'='*76}")
    print(f"{'esik%':>7}{'N':>6}{'tutma':>9}{'medyan%':>10}{'ort%':>9}"
          f"{'isabet':>8}{'funding':>9}{'fiyat%':>9}")
    for thr in THRESHOLDS:
        evs = events(hist, lo, hi, thr)
        for xb in exits:
            rets, fu, px = measure(evs, interval, bar_ms, xb, store)
            if not rets:
                continue
            unit = f"{xb*5}dk" if interval == "5m" else f"{xb}h"
            wr = 100 * sum(1 for x in rets if x > 0) / len(rets)
            print(f"{thr:>7.2f}{len(rets):>6}{unit:>9}"
                  f"{statistics.median(rets):>10.3f}"
                  f"{sum(rets)/len(rets):>9.3f}{wr:>7.0f}%"
                  f"{statistics.median(fu):>9.3f}"
                  f"{statistics.median(px):>9.3f}")


def main() -> None:
    hist = funding_history()
    frequency_table(hist)
    store_1h: dict = {}
    store_5m: dict = {}
    lo, hi = TEST if "--test" in sys.argv else TRAIN
    tag = "TEST 2026H1" if "--test" in sys.argv else "TRAIN 2024-07 -> 2025-12"
    outcome_table(hist, f"ADIM 2 — 1h cozunurluk · {tag}", lo, hi,
                  "1h", 3_600_000, [1, 2, 4], store_1h)
    outcome_table(hist, f"ADIM 3 — 5m, EN DAR pencere · {tag}", lo, hi,
                  "5m", 300_000, [1, 3, 12], store_5m)
    print("\nNOT: settled oran sinyal olarak kullanildi (lookahead) ve kayma "
          "dahil degil -> bu bir UST SINIR. Yorum icin REPORT.md Ek I.")


if __name__ == "__main__":
    main()
