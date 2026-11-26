"""G1 güç puanı (g1-strength-v1) — sonuçlara bakılmadan dondurulmuş sabit formül.

Ön kayıt: research/PREREG_G1_STRENGTH_2026-11-26.md. Puan, G1'in dört koşulunun
eşiklerini ne kadar aştığını ölçer; ağırlıklar ve tavanlar sonuç verisine göre
seçilmedi. Doğrulanmadı: bildirimde gösterilir ama giriş filtresi değildir.

Bileşenler (her biri 0..1, eşit ağırlık, toplam 0..100):
- sıra:        24 saatlik yükselen sırası; 1. = 1.0, 10. = 0.1
- hacim:       1s hacim / önceki 24s medyan; eşik 2x = 0, 8x ve üstü = 1 (log ölçek)
- OI:          1s OI değişimi; eşik %2 = 0, %8 ve üstü = 1 (log ölçek)
- short payı:  global short hesap payı; %50 = 0, %65 ve üstü = 1
"""
from __future__ import annotations

import math

VERSION = "g1-strength-v1"
TOP_N = 10
VOLUME_MIN, VOLUME_FULL = 2.0, 8.0
OI_MIN_PCT, OI_FULL_PCT = 2.0, 8.0
SHORT_MIN_PCT, SHORT_FULL_PCT = 50.0, 65.0


def _num(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _clamp(x: float) -> float:
    return max(0.0, min(1.0, x))


def _log_part(value: float, low: float, full: float) -> float:
    if value <= low:
        return 0.0
    return _clamp(math.log(value / low) / math.log(full / low))


def score(sig: dict) -> dict | None:
    """G1 sinyal alanlarından puan; alan eksik/bozuksa None (uydurma yok)."""
    rank = sig.get("rank_24h")
    volume = sig.get("volume_ratio")
    oi = sig.get("oi_change_1h_pct")
    short = sig.get("global_short_account_pct")
    if not all(_num(v) for v in (rank, volume, oi, short)) or not 1 <= rank <= TOP_N:
        return None
    parts = {
        "rank": round(_clamp((TOP_N + 1 - rank) / TOP_N), 4),
        "volume": round(_log_part(volume, VOLUME_MIN, VOLUME_FULL), 4),
        "oi": round(_log_part(oi, OI_MIN_PCT, OI_FULL_PCT), 4),
        "short": round(_clamp((short - SHORT_MIN_PCT) / (SHORT_FULL_PCT - SHORT_MIN_PCT)), 4),
    }
    total = round(25 * sum(parts.values()), 1)
    return {"version": VERSION, "score": total, "parts": parts}
