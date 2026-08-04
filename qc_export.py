"""Olay-bazli kalite kontrol CSV paketi.

Bu modul trade journal URETMEZ. Bot gercek emir acmadigi icin qty, notional,
dolar PnL veya gerceklesmis emir kaydi gibi alanlar bilerek yoktur.

Otomatik GitHub yayini icin tum ciktilar bellekte (StringIO/bytes) uretilir.
Yalniz ``write_package()`` acikca cagirildiginda dosya sistemine yazilir.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import mean, median
from typing import Callable, Iterable, Mapping, Sequence


SCHEMA_VERSION = "1.0"
VALID_STRATEGIES = {"S1", "S1+S4", "S2", "S3"}
# signal_bot.OBSERVE_STRATEGIES ile ayni olmali. Gozlem kanali (dinamik evren)
# arastirma paketine ASLA girmez; eski "GOZLEM-" onekli kayitlar da elenir.
OBSERVE_STRATEGIES = {"S5", "S6"}
OBSERVE_PREFIX = "GOZLEM-"
EXPECTED_HORIZONS = {"S1": 24, "S1+S4": 24, "S2": 72, "S3": 4}

EVENT_FIELDS = [
    "schema_version", "config_version", "event_id", "strategy", "symbol",
    "direction", "universe", "signal_market", "performance_market",
    "bar_time_utc", "signal_price", "horizon_hours", "confidence", "strength",
    "push_allowed", "suppressed", "suppression_reason", "notified_at_utc",
    "status", "source",
]
OUTCOME_FIELDS = [
    "event_id", "strategy", "symbol", "performance_market", "bar_time_utc",
    "entry_time_utc", "entry_price", "exit_time_utc", "exit_price",
    "horizon_hours", "gross_return_pct", "round_trip_cost_bps",
    "net_return_pct", "outcome_status", "outcome_source",
    "unavailable_reason",
]
SUMMARY_FIELDS = [
    "strategy", "market", "universe", "config_version", "n_total",
    "n_matured", "n_pending", "mean_gross_return_pct",
    "median_gross_return_pct", "mean_net_return_pct",
    "median_net_return_pct", "win_rate_pct", "q10_net_return_pct",
    "q90_net_return_pct", "first_event_utc", "last_event_utc",
    "sample_warning",
]
REJECTED_FIELDS = [
    "record_number", "rejection_reason", "event_id_candidate", "strategy",
    "symbol", "bar_time_utc", "raw_sha256",
]


def _utc(value: object) -> datetime:
    if isinstance(value, datetime):
        dt = value
    else:
        raw = str(value or "").strip()
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        dt = datetime.fromisoformat(raw)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _iso(value: datetime | object) -> str:
    return _utc(value).isoformat(timespec="seconds").replace("+00:00", "Z")


def canonical_event_id(record: Mapping[str, object]) -> str:
    """Sinyalin kanonik kimligi; bildirim tekrarlarindan bagimsizdir."""
    strategy = str(record.get("strategy") or "").strip().upper()
    symbol = str(record.get("symbol") or "").strip().upper()
    direction = str(record.get("direction") or "").strip().upper()
    try:
        bar_time = _iso(record.get("bar_time") or record.get("bar_time_utc"))
    except (TypeError, ValueError):
        bar_time = str(record.get("bar_time") or record.get("bar_time_utc") or "")
    horizon = str(record.get("horizon_hours") or "")
    canonical = "|".join((strategy, symbol, direction, bar_time, horizon))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:32]


def git_blob_sha(content: bytes) -> str:
    """GitHub Contents API'nin ``content.sha`` alaninda kullandigi Git blob SHA."""
    header = f"blob {len(content)}\0".encode("ascii")
    return hashlib.sha1(header + content).hexdigest()


def _bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _bool_text(value: object) -> str:
    return "true" if _bool(value) else "false"


def _number(value: object) -> float:
    out = float(value)
    if not math.isfinite(out):
        raise ValueError("non_finite")
    return out


def _csv_bytes(fields: Sequence[str], rows: Iterable[Mapping[str, object]]) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=list(fields), lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({field: row.get(field, "") for field in fields})
    return stream.getvalue().encode("utf-8")


def _percentile(values: Sequence[float], q: float) -> float | None:
    if not values:
        return None
    arr = sorted(values)
    if len(arr) == 1:
        return arr[0]
    pos = (len(arr) - 1) * q
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return arr[lo]
    return arr[lo] + (arr[hi] - arr[lo]) * (pos - lo)


def _rounded(value: float | None) -> object:
    return "" if value is None else round(value, 8)


@dataclass(frozen=True)
class QCBuild:
    files: dict[str, bytes]
    accepted_count: int
    rejected_count: int


CandleLoader = Callable[
    [str, str, int, int], tuple[Sequence[Mapping[str, object]], str]
]


def _market_for(strategy: str) -> tuple[str, str]:
    if strategy == "S2":
        return "usd_m_perp_funding", "usd_m_perp"
    return "spot", "spot"


def _universe_for(symbol: str, core: set[str], extended: set[str]) -> str:
    if symbol in core:
        return "core_30"
    if symbol in extended:
        return "extended_59"
    return "configured_custom"


def _reject(
    rejected: list[dict[str, object]],
    number: int,
    reason: str,
    raw: str,
    record: Mapping[str, object] | None = None,
) -> None:
    record = record or {}
    candidate = ""
    try:
        candidate = canonical_event_id(record)
    except Exception:
        pass
    strategy = str(record.get("strategy") or "").strip().upper()
    safe_strategy = (
        strategy if strategy in VALID_STRATEGIES or strategy.startswith("TEST")
        else "INVALID"
    )
    symbol = str(record.get("symbol") or "").strip().upper()
    safe_symbol = (
        symbol if 0 < len(symbol) <= 20 and symbol.isalnum() else "INVALID"
    )
    try:
        safe_time = _iso(
            record.get("bar_time") or record.get("bar_time_utc"))
    except (TypeError, ValueError):
        safe_time = ""
    rejected.append({
        "record_number": number,
        "rejection_reason": reason,
        "event_id_candidate": candidate,
        "strategy": safe_strategy,
        "symbol": safe_symbol,
        "bar_time_utc": safe_time,
        "raw_sha256": hashlib.sha256(raw.encode("utf-8", "replace")).hexdigest(),
    })


def _parse_events(
    lines: Iterable[str],
    *,
    configured_symbols: set[str],
    core_symbols: set[str],
    extended_symbols: set[str],
    config_version: str,
    confidence_rank: Mapping[str, int],
    min_confidence: str,
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    accepted: list[dict[str, object]] = []
    rejected: list[dict[str, object]] = []
    seen: set[str] = set()
    min_rank = confidence_rank.get(min_confidence, 1)

    for number, raw_line in enumerate(lines, start=1):
        raw = raw_line.strip()
        if not raw:
            continue
        try:
            record = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            _reject(rejected, number, "malformed_json", raw)
            continue
        if not isinstance(record, dict):
            _reject(rejected, number, "json_not_object", raw)
            continue

        strategy = str(record.get("strategy") or "").strip().upper()
        symbol = str(record.get("symbol") or "").strip().upper()
        if strategy.startswith("TEST"):
            _reject(rejected, number, "test_strategy", raw, record)
            continue
        # Gozlem kanali (S5/S6, eskiden GOZLEM-*) arastirma paketine ASLA
        # girmez: bu coinlerde backtest yok, QC capraz dogrulamasinin
        # karsilastiracagi bir sey de. Uc ayri kapi bilerek: isim, eski onek ve
        # kayittaki `observe` bayragi — biri atlanirsa digerleri tutar.
        # "invalid_strategy" yerine ayri sebep -> denetimde sayilari gorunur.
        if (strategy in OBSERVE_STRATEGIES
                or strategy.startswith(OBSERVE_PREFIX)
                or record.get("observe")):
            _reject(rejected, number, "observation_channel", raw, record)
            continue
        if strategy not in VALID_STRATEGIES:
            _reject(rejected, number, "invalid_strategy", raw, record)
            continue
        if symbol not in configured_symbols:
            _reject(rejected, number, "symbol_not_in_configured_universe", raw, record)
            continue
        try:
            price = _number(record.get("price", record.get("signal_price")))
            if price <= 0:
                raise ValueError("non_positive")
        except (TypeError, ValueError):
            _reject(rejected, number, "invalid_signal_price", raw, record)
            continue
        try:
            bar_time = _iso(record.get("bar_time") or record.get("bar_time_utc"))
        except (TypeError, ValueError):
            _reject(rejected, number, "invalid_bar_time", raw, record)
            continue
        try:
            horizon = int(record.get("horizon_hours") or 0)
        except (TypeError, ValueError):
            horizon = 0
        if horizon != EXPECTED_HORIZONS[strategy]:
            _reject(rejected, number, "invalid_horizon", raw, record)
            continue

        supplied_event_id = str(record.get("event_id") or "").strip().lower()
        event_id = (
            supplied_event_id
            if len(supplied_event_id) == 32
            and all(ch in "0123456789abcdef" for ch in supplied_event_id)
            else canonical_event_id(record)
        )
        if event_id in seen:
            _reject(rejected, number, "duplicate_event_id", raw, record)
            continue
        seen.add(event_id)

        raw_confidence = str(
            record.get("confidence") or "YUKSEK").strip().upper()
        confidence = (
            raw_confidence if raw_confidence in confidence_rank else "UNKNOWN"
        )
        rank = confidence_rank.get(confidence, 2)
        explicit_suppressed = record.get("suppressed")
        suppressed = (rank < min_rank if explicit_suppressed is None
                      else _bool(explicit_suppressed))
        raw_reason = str(record.get("suppression_reason") or "")
        reason = (raw_reason if raw_reason in {
            "", "confidence_below_threshold", "scan_push_cap"
        } else "other")
        if suppressed and not reason:
            reason = "confidence_below_threshold"
        signal_market, performance_market = _market_for(strategy)
        notified = record.get("notified_at") or record.get("notified_at_utc") or ""
        if notified:
            try:
                notified = _iso(notified)
            except (TypeError, ValueError):
                notified = ""
        raw_config = str(record.get("config_version") or "").lower()
        if raw_config == "current":
            event_config = config_version
        elif (len(raw_config) == 16 and raw_config.startswith("cfg-")
              and all(ch in "0123456789abcdef" for ch in raw_config[4:])):
            event_config = raw_config
        else:
            event_config = "legacy-unversioned"
        raw_source = str(record.get("source") or "")
        source = raw_source if raw_source in {
            "live_scan", "signals.log", "legacy_log"
        } else "signals.log"
        accepted.append({
            "schema_version": SCHEMA_VERSION,
            "config_version": event_config,
            "event_id": event_id,
            "strategy": strategy,
            "symbol": symbol,
            "direction": "LONG",
            # Piyasa/evren kaynagi ham log degil, dogrulanan strateji ve mevcut
            # yapilandirmadir. Boylece eski/elle bozulmus metadata S2'yi spotta
            # ya da S1/S3'u perp'te olcturemez.
            "universe": _universe_for(
                symbol, core_symbols, extended_symbols),
            "signal_market": signal_market,
            "performance_market": performance_market,
            "bar_time_utc": bar_time,
            "signal_price": price,
            "horizon_hours": horizon,
            "confidence": confidence,
            "strength": (
                str(record.get("strength") or "NORMAL").upper()
                if str(record.get("strength") or "NORMAL").upper()
                in {"NORMAL", "STRONG"} else "NORMAL"
            ),
            "push_allowed": _bool_text(
                record.get("push_allowed", not suppressed)),
            "suppressed": _bool_text(suppressed),
            "suppression_reason": reason,
            "notified_at_utc": notified,
            "status": "pending",
            "source": source,
        })

    accepted.sort(key=lambda row: (str(row["bar_time_utc"]), str(row["event_id"])))
    return accepted, rejected


def _outcome_for(
    event: Mapping[str, object],
    *,
    now: datetime,
    cost_bps: float,
    candle_loader: CandleLoader | None,
) -> dict[str, object]:
    bar = _utc(event["bar_time_utc"])
    horizon = int(event["horizon_hours"])
    entry_open = bar + timedelta(hours=1)
    exit_open = bar + timedelta(hours=horizon)
    exit_close = exit_open + timedelta(hours=1)
    market = str(event["performance_market"])
    source = ("binance_usdm_perp_1h_klines;funding:not_modeled"
              if market == "usd_m_perp" else "binance_spot_1h_klines")
    base = {
        "event_id": event["event_id"],
        "strategy": event["strategy"],
        "symbol": event["symbol"],
        "performance_market": market,
        "bar_time_utc": event["bar_time_utc"],
        "entry_time_utc": _iso(entry_open),
        "entry_price": "",
        "exit_time_utc": _iso(exit_close),
        "exit_price": "",
        "horizon_hours": horizon,
        "gross_return_pct": "",
        "round_trip_cost_bps": cost_bps,
        "net_return_pct": "",
        "outcome_status": "pending",
        "outcome_source": source,
        "unavailable_reason": "",
    }
    if now < exit_close:
        return base
    if candle_loader is None:
        return {**base, "outcome_status": "unavailable",
                "unavailable_reason": "candle_loader_not_configured"}
    try:
        candles, resolved_source = candle_loader(
            market, str(event["symbol"]), int(bar.timestamp() * 1000),
            horizon + 2)
        if resolved_source:
            source = resolved_source
    except Exception as exc:
        return {**base, "outcome_status": "unavailable",
                "unavailable_reason": f"candle_fetch_error:{type(exc).__name__}"}
    by_time: dict[int, Mapping[str, object]] = {}
    for candle in candles:
        try:
            by_time[int(candle["open_time"])] = candle
        except (KeyError, TypeError, ValueError):
            continue
    entry_ms = int(entry_open.timestamp() * 1000)
    exit_ms = int(exit_open.timestamp() * 1000)
    if entry_ms not in by_time:
        return {**base, "outcome_status": "unavailable",
                "outcome_source": source,
                "unavailable_reason": "missing_entry_bar"}
    if exit_ms not in by_time:
        return {**base, "outcome_status": "unavailable",
                "outcome_source": source,
                "unavailable_reason": "missing_exit_bar"}
    try:
        entry_price = _number(by_time[entry_ms]["open"])
        exit_price = _number(by_time[exit_ms]["close"])
        if entry_price <= 0 or exit_price <= 0:
            raise ValueError("non_positive")
    except (KeyError, TypeError, ValueError):
        return {**base, "outcome_status": "unavailable",
                "outcome_source": source,
                "unavailable_reason": "invalid_entry_or_exit_price"}
    gross = (exit_price / entry_price - 1.0) * 100.0
    net = gross - cost_bps / 100.0
    return {
        **base,
        "entry_price": entry_price,
        "exit_price": exit_price,
        "gross_return_pct": round(gross, 8),
        "net_return_pct": round(net, 8),
        "outcome_status": "matured",
        "outcome_source": source,
    }


def _summaries(
    events: Sequence[Mapping[str, object]],
    outcomes: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    outcome_by_id = {str(row["event_id"]): row for row in outcomes}
    groups: dict[tuple[str, str, str, str], list[Mapping[str, object]]] = defaultdict(list)
    for event in events:
        key = (
            str(event["strategy"]), str(event["performance_market"]),
            str(event["universe"]), str(event["config_version"]),
        )
        groups[key].append(event)
    rows: list[dict[str, object]] = []
    for key in sorted(groups):
        group_events = groups[key]
        group_outcomes = [outcome_by_id[str(event["event_id"])]
                          for event in group_events]
        matured = [row for row in group_outcomes
                   if row["outcome_status"] == "matured"]
        pending = [row for row in group_outcomes
                   if row["outcome_status"] == "pending"]
        gross = [float(row["gross_return_pct"]) for row in matured]
        net = [float(row["net_return_pct"]) for row in matured]
        times = sorted(str(event["bar_time_utc"]) for event in group_events)
        rows.append({
            "strategy": key[0],
            "market": key[1],
            "universe": key[2],
            "config_version": key[3],
            "n_total": len(group_events),
            "n_matured": len(matured),
            "n_pending": len(pending),
            "mean_gross_return_pct": _rounded(mean(gross) if gross else None),
            "median_gross_return_pct": _rounded(median(gross) if gross else None),
            "mean_net_return_pct": _rounded(mean(net) if net else None),
            "median_net_return_pct": _rounded(median(net) if net else None),
            "win_rate_pct": _rounded(
                100 * sum(value > 0 for value in net) / len(net) if net else None),
            "q10_net_return_pct": _rounded(_percentile(net, 0.10)),
            "q90_net_return_pct": _rounded(_percentile(net, 0.90)),
            "first_event_utc": times[0],
            "last_event_utc": times[-1],
            "sample_warning": "small_sample" if len(matured) < 30 else "",
        })
    return rows


def _qc_index_html(generated: str, accepted: int, rejected: int) -> bytes:
    return f"""<!doctype html><html lang="tr"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Signal Bot Kalite Kontrol</title>
<style>body{{font:16px system-ui;max-width:760px;margin:40px auto;padding:0 18px;
background:#0b1220;color:#eaf0fb}}a{{display:inline-block;margin:6px 4px;padding:10px 14px;
background:#1d4ed8;color:white;text-decoration:none;border-radius:8px}}.card{{background:#111a2e;
padding:18px;border:1px solid #22304f;border-radius:12px}}.warn{{color:#fbbf24}}</style>
</head><body><h1>Kalite Kontrol CSV</h1><div class="card">
<p><b>Son güncelleme:</b> {generated}</p>
<p><b>Kabul edilen olay:</b> {accepted} &nbsp; <b>Reddedilen kayıt:</b> {rejected}</p>
<p><a href="signal_events.csv" download>Sinyal olayları</a>
<a href="signal_outcomes.csv" download>Sonuçlar</a>
<a href="strategy_summary.csv" download>Strateji özeti</a>
<a href="rejected_records.csv" download>Reddedilenler</a>
<a href="manifest.json" download>Manifest</a></p>
<p class="warn"><b>Bu veriler sinyaldir, gerçek emir/işlem değildir.</b>
Qty, notional, dolar PnL veya trade-journal kaydı içermez.</p>
</div></body></html>""".encode("utf-8")


def build_package(
    lines: Iterable[str],
    *,
    configured_symbols: Iterable[str],
    core_symbols: Iterable[str],
    extended_symbols: Iterable[str],
    config_version: str,
    confidence_rank: Mapping[str, int],
    min_confidence: str,
    now: datetime | None = None,
    round_trip_cost_bps: float = 12.0,
    candle_loader: CandleLoader | None = None,
    network_usage: dict[str, object] | None = None,
) -> QCBuild:
    """Bellekte tam QC paketini olusturur."""
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    events, rejected = _parse_events(
        lines,
        configured_symbols={str(x).upper() for x in configured_symbols},
        core_symbols={str(x).upper() for x in core_symbols},
        extended_symbols={str(x).upper() for x in extended_symbols},
        config_version=config_version,
        confidence_rank=confidence_rank,
        min_confidence=min_confidence,
    )
    outcomes = [
        _outcome_for(event, now=now, cost_bps=round_trip_cost_bps,
                     candle_loader=candle_loader)
        for event in events
    ]
    outcome_status = {str(row["event_id"]): str(row["outcome_status"])
                      for row in outcomes}
    for event in events:
        event["status"] = outcome_status[str(event["event_id"])]
    summaries = _summaries(events, outcomes)
    generated = _iso(now)

    files: dict[str, bytes] = {
        "qc/signal_events.csv": _csv_bytes(EVENT_FIELDS, events),
        "qc/signal_outcomes.csv": _csv_bytes(OUTCOME_FIELDS, outcomes),
        "qc/strategy_summary.csv": _csv_bytes(SUMMARY_FIELDS, summaries),
        "qc/rejected_records.csv": _csv_bytes(REJECTED_FIELDS, rejected),
        "qc/index.html": _qc_index_html(generated, len(events), len(rejected)),
    }
    manifest = {
        "generated_at_utc": generated,
        "schema_version": SCHEMA_VERSION,
        "config_versions": sorted({str(row["config_version"]) for row in events}
                                  or {config_version}),
        "cost_assumption": {
            "round_trip_cost_bps": round_trip_cost_bps,
            "funding": "not_modeled",
            "slippage": "included_in_round_trip_cost_assumption_only",
        },
        "row_counts": {
            "signal_events": len(events),
            "signal_outcomes": len(outcomes),
            "strategy_summary": len(summaries),
            "rejected_records": len(rejected),
        },
        "rejected_count": len(rejected),
        "network_usage": network_usage or {
            "used": False, "requests": 0, "bytes_received": 0,
            "sources": [],
        },
        "files": {
            path: {"sha256": hashlib.sha256(content).hexdigest(),
                   "bytes": len(content)}
            for path, content in sorted(files.items())
            if path.endswith(".csv")
        },
        "disclaimer": "Signal events only; not real orders or trades.",
    }
    files["qc/manifest.json"] = (
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2)
        + "\n"
    ).encode("utf-8")
    return QCBuild(files=files, accepted_count=len(events),
                   rejected_count=len(rejected))


def write_package(package: QCBuild, output_dir: str | Path) -> list[Path]:
    """Yalniz manuel export icin paketi diske yazar."""
    root = Path(output_dir)
    written: list[Path] = []
    for remote_path, content in sorted(package.files.items()):
        relative = Path(remote_path).relative_to("qc")
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        written.append(target)
    return written


def _cli(argv: Sequence[str] | None = None) -> int:
    """CLI: signals.log -> QC CSV paketi.

    Kullanim:  python qc_export.py [-o CIKTI_DIZINI] [-l SIGNALS_LOG]
    Yapilandirma (evren, esikler, guven kademeleri) signal_bot'tan okunur;
    boylece paket her zaman calisan botun konfigurasyonuyla etiketlenir.
    """
    import argparse

    ap = argparse.ArgumentParser(
        description="signals.log'dan olay-bazli QC CSV paketi uretir "
                    "(trade journal DEGIL: bot emir acmaz).")
    ap.add_argument("-o", "--output", default="qc_out",
                    help="cikti dizini (varsayilan: qc_out)")
    ap.add_argument("-l", "--log", default=None,
                    help="signals.log yolu (varsayilan: bot ayarindaki)")
    ap.add_argument("--cost-bps", type=float, default=12.0,
                    help="gidis-donus maliyet varsayimi, bp (varsayilan 12)")
    args = ap.parse_args(argv)

    sys.path.insert(0, str(Path(__file__).parent))
    import signal_bot as bot          # yapilandirma kaynagi

    log_path = Path(args.log) if args.log else (
        Path(bot.SIGNAL_LOG) if Path(bot.SIGNAL_LOG).is_absolute()
        else Path(bot.__file__).parent / bot.SIGNAL_LOG)
    if not log_path.exists():
        print(f"hata: sinyal kaydi bulunamadi: {log_path}", file=sys.stderr)
        return 1
    lines = log_path.read_text(encoding="utf-8").splitlines()

    core = [s.strip() for s in bot.DEFAULT_SYMBOLS.split(",") if s.strip()]
    built = build_package(
        lines,
        configured_symbols=bot.SYMBOLS,
        core_symbols=core,
        extended_symbols=sorted(bot.EXTENDED_SET),
        config_version=_config_version(bot),
        confidence_rank=bot.CONF_RANK,
        min_confidence=bot.NOTIFY_MIN_CONFIDENCE,
        round_trip_cost_bps=args.cost_bps,
    )
    written = write_package(built, args.output)
    print(f"{len(lines)} kayit okundu -> kabul {built.accepted_count}, "
          f"reddedilen {built.rejected_count}")
    for path in written:
        print(f"  {path}")
    return 0


def _config_version(bot) -> str:
    """Strateji/evren parmak izi (sir icermez)."""
    public = {
        "S1": [bot.RSI_PERIOD, bot.RSI_OVERSOLD, bot.DIVERGENCE_LOOKBACK,
               bot.DIVERGENCE_GAP, bot.S1_COOLDOWN_HOURS],
        "S2": [bot.FUNDING_SQUEEZE_THRESHOLD_PCT, bot.FUNDING_PERSISTENCE,
               bot.S2_COOLDOWN_HOURS],
        "S3": [bot.VOLUME_ZSCORE_THRESHOLD, bot.VOLUME_ZSCORE_WINDOW,
               bot.S3_COOLDOWN_HOURS],
        "S4": [bot.CONFLUENCE_LOOKBACK_HOURS],
        "symbols": sorted(bot.SYMBOLS),
        "min_conf": bot.NOTIFY_MIN_CONFIDENCE,
    }
    packed = json.dumps(public, sort_keys=True, separators=(",", ":"))
    return "cfg-" + hashlib.sha256(packed.encode("utf-8")).hexdigest()[:12]


if __name__ == "__main__":
    raise SystemExit(_cli())
