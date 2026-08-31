"""Forward OI/funding/liquidation archive readiness monitor.

This module never changes a strategy or its thresholds.  It only measures
whether the point-in-time archive is complete enough to begin a pre-registered
research cycle.  The intended protocol is 90 days discovery/freeze followed
by a separately declared 90-day out-of-sample window.
"""

from __future__ import annotations

import json
import math
import statistics
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable


MARKET_FIELDS = (
    "oi", "perp_px", "basis", "global_ls_ratio",
    "taker_buy_sell_ratio", "funding_rate_snapshot",
)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _parse_time(value) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        if isinstance(value, (int, float)):
            number = float(value)
            if not math.isfinite(number):
                return None
            if number > 10_000_000_000:
                number /= 1000
            return datetime.fromtimestamp(number, tz=timezone.utc)
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return _utc(parsed)
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def _jsonl(paths: Iterable[Path]):
    for path in sorted(paths):
        try:
            with path.open("r", encoding="utf-8") as stream:
                for line in stream:
                    try:
                        row = json.loads(line)
                    except (TypeError, ValueError):
                        yield None
                        continue
                    yield row if isinstance(row, dict) else None
        except OSError:
            yield None


def _pct(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator * 100, 1) if denominator else None


def _iso(value: datetime | None) -> str | None:
    return value.isoformat(timespec="minutes") if value else None


def _parse_optional_utc(value: str | None) -> datetime | None:
    return _parse_time(value) if value else None


def weekly_slot(now: datetime, weekday: int = 0, hour_utc: int = 6) -> str | None:
    """Return this ISO week's slot after its scheduled instant, else ``None``."""
    now = _utc(now)
    weekday = min(6, max(0, int(weekday)))
    hour_utc = min(23, max(0, int(hour_utc)))
    monday = (now - timedelta(days=now.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0)
    scheduled = monday + timedelta(days=weekday, hours=hour_utc)
    if now < scheduled:
        return None
    iso_year, iso_week, _ = now.isocalendar()
    return f"{iso_year}-W{iso_week:02d}"


def build_research_readiness(
        archive_dir: str | Path, *, now: datetime | None = None,
        discovery_days: int = 90, oos_days: int = 90,
        oos_start_utc: str | None = None) -> dict:
    """Summarize archive coverage without network calls or parameter fitting."""
    root = Path(archive_dir)
    now = _utc(now or datetime.now(timezone.utc))
    market_rows = research_rows = malformed = 0
    market_times: list[datetime] = []
    hours: set[str] = set()
    research_first = research_last = None
    symbols: set[str] = set()
    rows_by_hour: dict[str, int] = {}
    research_hours: set[str] = set()
    field_counts = {name: 0 for name in MARKET_FIELDS}

    for row in _jsonl(root.glob("market_archive_*.jsonl")):
        if row is None:
            malformed += 1
            continue
        schema = row.get("schema_version")
        legacy_market_row = (schema is None and row.get("t")
                             and row.get("sym") and "oi" in row)
        if schema not in {"market-context-v1", "market-context-v2"} \
                and not legacy_market_row:
            continue
        stamp = _parse_time(row.get("t"))
        if stamp is None:
            malformed += 1
            continue
        market_rows += 1
        market_times.append(stamp)
        hour = stamp.replace(minute=0, second=0, microsecond=0).isoformat()
        hours.add(hour)
        rows_by_hour[hour] = rows_by_hour.get(hour, 0) + 1
        if row.get("sym"):
            symbols.add(str(row["sym"]))
        core_complete = all(row.get(name) is not None for name in (
            "oi", "perp_px", "global_ls_ratio", "taker_buy_sell_ratio",
            "funding_rate_snapshot"))
        if research_first is None and core_complete:
            research_first = stamp
        if research_first is not None and stamp >= research_first:
            research_rows += 1
            research_last = stamp if research_last is None else max(
                research_last, stamp)
            research_hours.add(hour)
            for name in MARKET_FIELDS:
                if row.get(name) is not None:
                    field_counts[name] += 1

    first = min(market_times) if market_times else None
    last = max(market_times) if market_times else None
    span_hours = (int((research_last - research_first).total_seconds() // 3600)
                  + 1 if research_first and research_last else 0)
    span_days = round(
        (research_last - research_first).total_seconds() / 86400, 1
    ) if research_first and research_last else 0.0
    stale_hours = round((now - research_last).total_seconds() / 3600, 1) \
        if research_last else None
    median_symbols = (round(statistics.median(rows_by_hour.values()), 1)
                      if rows_by_hour else 0.0)
    completeness = {name: _pct(count, research_rows)
                    for name, count in field_counts.items()}

    liquidation_events = liquidation_status_rows = 0
    liquidation_days: set[str] = set()
    liquidation_event_days: set[str] = set()
    liquidation_status_days: set[str] = set()
    liq_first = liq_last = None
    for row in _jsonl(root.glob("liquidation_archive_*.jsonl")):
        if row is None:
            malformed += 1
            continue
        record_type = row.get("record_type")
        stamp = _parse_time(row.get("received_at_utc") or row.get("at_utc")
                            or row.get("event_time_utc"))
        if record_type == "force_order":
            liquidation_events += 1
            if stamp:
                liquidation_event_days.add(stamp.date().isoformat())
        elif record_type == "stream_status":
            liquidation_status_rows += 1
            if stamp:
                liquidation_status_days.add(stamp.date().isoformat())
        else:
            continue
        if stamp and (research_first is None or stamp >= research_first):
            liquidation_days.add(stamp.date().isoformat())
            liq_first = stamp if liq_first is None else min(liq_first, stamp)
            liq_last = stamp if liq_last is None else max(liq_last, stamp)

    g1_events = dl1_events = 0
    event_days: set[str] = set()
    for row in _jsonl(root.glob("shadow_events_*.jsonl")):
        if row is None:
            malformed += 1
            continue
        kind = str(row.get("kind") or "")
        g1_events += int(kind == "G1_EVENT")
        dl1_events += int(kind == "DL1_EVENT")
        stamp = _parse_time(row.get("recorded_at") or row.get("bar_time"))
        if stamp:
            event_days.add(stamp.date().isoformat())

    discovery_days = max(30, int(discovery_days))
    oos_days = max(30, int(oos_days))
    oos_start = _parse_optional_utc(oos_start_utc)
    hour_coverage = _pct(len(research_hours), span_hours)
    quality_checks = {
        "market_span_days": span_days >= discovery_days - 1,
        "hour_coverage_80pct": (hour_coverage or 0) >= 80,
        "oi_completeness_90pct": (completeness["oi"] or 0) >= 90,
        "funding_completeness_80pct": (
            completeness["funding_rate_snapshot"] or 0) >= 80,
        "long_short_completeness_80pct": (
            completeness["global_ls_ratio"] or 0) >= 80,
        "recent_archive_48h": stale_hours is not None and stale_hours <= 48,
        "liquidation_event_days_30": len(liquidation_event_days) >= 30,
    }
    quality_ready = all(quality_checks.values())

    if first is None:
        phase = "NO_DATA"
        next_review = None
        action = "Tablet arşivinin çalıştığını doğrula; henüz OI satırı yok."
    elif research_first is None:
        phase = "WAITING_FOR_COMPLETE_FIELDS"
        next_review = None
        action = ("OI satırı var fakat funding/long-short/taker alanları birlikte "
                  "başlamadı; 90 günlük sayaç henüz başlatılmadı.")
    elif oos_start is None:
        next_review = research_first + timedelta(days=discovery_days)
        if now < next_review:
            phase = "DISCOVERY_COLLECTING"
            action = ("Veriyi toplamaya devam et; parametre değiştirme. "
                      "İlk incelemede aday kural dondurulacak.")
        elif quality_ready:
            phase = "INTERIM_REVIEW_DUE"
            action = ("90 günlük keşif hazır: OI adayını analiz et, kuralı ön "
                      "kaydet ve OOS başlangıç zamanını sabitle.")
        else:
            phase = "DATA_QUALITY_BLOCKED"
            action = ("90 gün doldu fakat veri kalite kapısı geçilmedi; eksik "
                      "alanları düzelt, eşik seçme.")
    else:
        next_review = oos_start + timedelta(days=oos_days)
        if now < next_review:
            phase = "OOS_COLLECTING"
            action = "Dondurulmuş kurala dokunma; ileri test verisi birikiyor."
        elif quality_ready:
            phase = "FORMAL_REVIEW_DUE"
            action = ("OOS dönemi tamam: örnek sayısı ve maliyetlerle kabul/ret "
                      "testini çalıştır.")
        else:
            phase = "OOS_QUALITY_BLOCKED"
            action = ("OOS süre doldu fakat veri kalite kapısı geçilmedi; "
                      "stratejiyi kabul etme.")

    days_to_review = (round((next_review - now).total_seconds() / 86400, 1)
                      if next_review else None)
    return {
        "schema_version": "research-readiness-v1",
        "generated_at_utc": _iso(now),
        "phase": phase,
        "next_action": action,
        "discovery_days_required": discovery_days,
        "oos_days_required": oos_days,
        "oos_start_utc": _iso(oos_start),
        "next_review_utc": _iso(next_review),
        "days_to_review": days_to_review,
        "quality_ready": quality_ready,
        "quality_checks": quality_checks,
        "market": {
            "rows": market_rows, "symbols": len(symbols),
            "first_utc": _iso(first), "last_utc": _iso(last),
            "research_rows": research_rows,
            "research_ready_first_utc": _iso(research_first),
            "research_ready_last_utc": _iso(research_last),
            "span_days": span_days, "unique_hours": len(research_hours),
            "expected_hours_between_first_last": span_hours,
            "hour_coverage_pct": hour_coverage,
            "median_symbols_per_hour": median_symbols,
            "stale_hours": stale_hours,
            "field_completeness_pct": completeness,
        },
        "liquidations": {
            "events": liquidation_events,
            "status_rows": liquidation_status_rows,
            "observed_days": len(liquidation_days),
            "event_days": len(liquidation_event_days),
            "status_days": len(liquidation_status_days),
            "first_utc": _iso(liq_first), "last_utc": _iso(liq_last),
            "stream_suspect": (
                liquidation_events == 0 and liquidation_status_rows >= 12),
        },
        "shadow": {
            "g1_events": g1_events, "dl1_events": dl1_events,
            "independent_event_days": len(event_days),
        },
        "malformed_rows": malformed,
        "interpretation": (
            "Haftalık rapor yalnız veri hazırlığını ölçer; strateji eşiklerini "
            "otomatik değiştirmez ve başarı olasılığı değildir."),
    }


def format_research_readiness(report: dict) -> str:
    """Compact Telegram-safe HTML; all content comes from numeric summaries."""
    market = report["market"]
    liq = report["liquidations"]
    shadow = report["shadow"]
    fields = market["field_completeness_pct"]
    phase_names = {
        "NO_DATA": "VERI YOK",
        "WAITING_FOR_COMPLETE_FIELDS": "TAM ALANLI ARSIV HENUZ BASLAMADI",
        "DISCOVERY_COLLECTING": "90 GUNLUK KESIF TOPLANIYOR",
        "INTERIM_REVIEW_DUE": "ARA INCELEME HAZIR",
        "DATA_QUALITY_BLOCKED": "VERI KALITESI YETERSIZ",
        "OOS_COLLECTING": "DONDURULMUS OOS TEST TOPLANIYOR",
        "FORMAL_REVIEW_DUE": "NIHAI OOS INCELEMESI HAZIR",
        "OOS_QUALITY_BLOCKED": "OOS VERI KALITESI YETERSIZ",
    }

    def shown(value, suffix=""):
        return "—" if value is None else f"{value}{suffix}"

    stream_warning = (
        "⚠️ Baglanti kaydi var ama olay yok: WebSocket akisi supheli.\n"
        if liq.get("stream_suspect") else "")
    review_suffix = (f" ({report['days_to_review']} gun)"
                     if report["days_to_review"] is not None else "")
    return (
        "🧪 <b>Haftalik arastirma hazirlik raporu</b>\n"
        f"Asama: <b>{phase_names.get(report['phase'], report['phase'])}</b>\n"
        f"OI arsivi: {market['rows']} toplam / {market['research_rows']} "
        f"tam-alanli satir · {market['symbols']} sembol · "
        f"{market['span_days']} gun · saat kapsami "
        f"%{shown(market['hour_coverage_pct'])}\n"
        f"Alan dolulugu: OI %{shown(fields['oi'])} · funding "
        f"%{shown(fields['funding_rate_snapshot'])} · long/short "
        f"%{shown(fields['global_ls_ratio'])} · basis "
        f"%{shown(fields['basis'])}\n"
        f"Likidasyon arsivi: {liq['events']} olay · {liq['event_days']} olay "
        f"gunu · {liq['status_days']} baglanti gunu\n"
        f"{stream_warning}"
        f"Golge olaylar: G1={shadow['g1_events']} · DL1={shadow['dl1_events']} · "
        f"bagimsiz gun={shadow['independent_event_days']}\n"
        f"Sonraki kontrol: {report['next_review_utc'] or 'veri baslayinca'}"
        f"{review_suffix}\n"
        f"Karar: {report['next_action']}\n"
        "<i>Bu rapor veri hazirligini olcer; otomatik esik degistirmez ve "
        "yatirim sinyali degildir.</i>"
    )
