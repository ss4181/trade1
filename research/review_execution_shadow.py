"""Read-only report of frozen S1/S3/G2 forward price-path candidates."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import statistics
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import execution_shadow as engine

DAY = 86_400_000
TERMINAL = {"NO_ENTRY", "TP", "STOP", "STOP_GAP", "TRAIL_STOP",
            "TRAIL_STOP_GAP", "AMBIGUOUS_STOP", "TIMEOUT"}
COHORT = ("strategy", "universe", "market", "config_version",
          "engine_version", "engine_config_hash", "regime")


def distribution(values):
    values = sorted(v for v in values if type(v) in (int, float) and math.isfinite(v))
    if not values:
        return {"n": 0, "mean": None, "median": None, "q10": None, "worst": None}
    p = (len(values)-1)*.1
    low, high = math.floor(p), math.ceil(p)
    return {"n": len(values), "mean": statistics.mean(values),
            "median": statistics.median(values),
            "q10": values[low]+(values[high]-values[low])*(p-low), "worst": values[0]}


def summarize(data, now_ms=None):
    now_ms = int(time.time()*1000) if now_ms is None else now_ms
    if (not isinstance(data, dict) or data.get("study_version") != engine.VERSION
            or data.get("plan_hash") != engine.PLAN_HASH
            or not isinstance(data.get("events"), dict)
            or type(data.get("activated_ms")) is not int):
        raise ValueError("invalid_study_state")
    activated = data["activated_ms"]
    groups = defaultdict(list)
    excluded = Counter()
    for event_id, raw in data["events"].items():
        event = engine.public_event(raw)
        if (event.get("study_version") != engine.VERSION or event.get("plan_hash") != engine.PLAN_HASH
                or event.get("event_id") != event_id
                or not event.get("plans") or any(k not in event for k in COHORT)
                or not activated <= event.get("delivered_ms", -1) <= now_ms
                or event.get("activated_ms") != activated):
            excluded["incompatible_event"] += 1
            continue
        groups[tuple(event[k] for k in COHORT)].append(event)
    rows = []
    for key, events in sorted(groups.items(), key=lambda pair: tuple(str(v) for v in pair[0])):
        for plan_id in sorted({p for e in events for p in e["plans"]}):
            pairs = [(e, e["plans"][plan_id]) for e in events if plan_id in e["plans"]]
            measured = [(e, p) for e, p in pairs if p.get("status") in TERMINAL]
            entered = [(e, p) for e, p in measured if p.get("entered")]
            no_entry = [(e, p) for e, p in measured if p.get("status") == "NO_ENTRY"]
            unknown = sum(p.get("status") not in TERMINAL and (
                p.get("data_status") == "UNKNOWN" or e.get("data_status") == "UNKNOWN") for e, p in pairs)
            matched = [(e, p, e["plans"]["baseline"]) for e, p in measured
                       if e["plans"].get("baseline", {}).get("status") in TERMINAL]
            days = len({e["delivered_ms"]//DAY for e, p in entered})
            observation_days = max(0, (now_ms-min(e["delivered_ms"] for e in events))/DAY)
            row = dict(zip(COHORT, key))
            row.update(plan_id=plan_id, n_total=len(pairs), n_outcomes=len(measured),
                       n_entries=sum(bool(p.get("entered")) for e, p in pairs),
                       n_matured_entries=len(entered), n_no_entry=len(no_entry),
                       n_unknown=unknown, n_pending=len(pairs)-len(measured)-unknown,
                       n_event_days=len({e["delivered_ms"]//DAY for e, p in pairs}),
                       n_entry_days=days, observation_days=observation_days,
                       n_path_complete=sum(bool(e.get("full_window_complete")) for e, p in pairs),
                       n_path_unknown=sum(e.get("data_status") == "UNKNOWN" for e, p in pairs),
                       entry_rate_of_decided_pct=(100*sum(p.get("entered", False) for e, p in pairs)/
                           sum(p.get("entered", False) or p.get("status") == "NO_ENTRY" for e, p in pairs)
                           if any(p.get("entered") or p.get("status") == "NO_ENTRY" for e, p in pairs) else None),
                       statuses=dict(sorted(Counter(p["status"] for e, p in pairs).items())),
                       funding_status="not_modeled" if key[2] == "um_perp" else "not_applicable",
                       minimum_observation_gate_met=observation_days >= 90 and len(entered) >= 30 and days >= 14,
                       auto_promote=False,
                       sample_warning="small_sample" if len(entered) < 30 or days < 14 else "forward_review_required")
            row["gross_per_opportunity_pct"] = distribution(p.get("gross_pct") for e, p in measured)
            for bps in (20, 40):
                field = f"net_ex_funding{bps}_pct"
                row[f"net_ex_funding{bps}_per_opportunity_pct"] = distribution(p.get(field) for e, p in measured)
                row[f"net_ex_funding{bps}_per_entry_pct"] = distribution(p.get(field) for e, p in entered)
                row[f"paired_delta{bps}_vs_baseline_pp"] = distribution(
                    p[field]-base[field] for e, p, base in matched
                    if p.get(field) is not None and base.get(field) is not None)
                # USD-M full net is intentionally unavailable while funding is unmodeled.
                row[f"net{bps}_per_opportunity_pct"] = (
                    distribution(p.get(f"net{bps}_pct") for e, p in measured) if key[2] == "spot" else None)
            row["wait_minutes"] = distribution((p["entry_ms"]-e["anchor_ms"])/60000 for e, p in pairs if p.get("entered"))
            row["until_exit_mae_pct"] = distribution(p.get("until_exit_mae_pct") for e, p in entered)
            row["until_exit_mfe_pct"] = distribution(p.get("until_exit_mfe_pct") for e, p in entered)
            for field in ("full_window_mae_pct", "full_window_mfe_pct"):
                row[field] = distribution(p.get(field) for e, p in pairs if p.get("full_window_complete") and p.get("entered"))
            row["no_entry_complete_paths"] = sum(e.get("full_window_complete", False) for e, p in no_entry)
            row["no_entry_missed_3pct_touch"] = sum(e.get("full_window_complete", False) and
                e.get("full_window_mfe_pct", 0) >= 3 for e, p in no_entry)
            row["no_entry_baseline_tp"] = sum(p["status"] == "NO_ENTRY" and base["status"] == "TP" for e, p, base in matched)
            rows.append(row)
    return {"study_version": engine.VERSION, "plan_hash": engine.PLAN_HASH,
            "research_only": True, "network_used": False, "activated_ms": activated,
            "generated_at_utc": datetime.fromtimestamp(now_ms/1000, timezone.utc).isoformat(),
            "accepted_events": sum(len(es) for es in groups.values()), "excluded": dict(excluded),
            "cohorts": rows,
            "interpretation": "Sabit ileri gözlem; fiyat referansı gerçek dolum değildir. "
                "G2 getirisi funding hariçtir. Eksik veri kayıp/sıfır sayılmaz. "
                "Başarı olasılığı veya otomatik aday onayı üretmez."}


def render_text(report):
    lines = ["S1 / S3 / G2 — SABİT İLERİ GİRİŞ–ÇIKIŞ GÖLGESİ",
             f"Sürüm: {report['study_version']} · olay: {report['accepted_events']}",
             report["interpretation"]]
    if report.get("input_status") == "state_missing_not_activated":
        lines.append("State bulunamadı: bu klasörde gölge takibin başladığı doğrulanmadı.")
    elif report.get("activated_ms") is not None:
        lines.append("Toplama başlangıcı (UTC): " + datetime.fromtimestamp(
            report["activated_ms"]/1000, timezone.utc).isoformat())
    if not report["cohorts"]:
        lines.append("Henüz uygun yeni teslim kaydı yok. Eski sinyaller ileri teste eklenmez.")
    def fmt(value):
        return "—" if value is None else f"{value:+.3f}"
    for row in report["cohorts"]:
        lines += ["", f"{row['strategy']} / {row['universe']} / {row['market']} / {row['regime']}",
                  f"Config: {row['config_version']} · motor: {row['engine_version']} / {row['engine_config_hash']}",
                  f"Kol: {row['plan_id']} · toplam {row['n_total']} · sonuç {row['n_outcomes']} "
                  f"· girişsiz {row['n_no_entry']} · bekleyen {row['n_pending']} · UNKNOWN {row['n_unknown']}",
                  f"Giriş günü {row['n_entry_days']} · olgun giriş {row['n_matured_entries']} "
                  f"· ileri süre {row['observation_days']:.1f} gün · kapsamı tamam {row['n_path_complete']}",
                  f"Fırsat başına maliyet sonrası{' (FUNDING HARİÇ)' if row['market'] == 'um_perp' else ''}: "
                  f"20bp %{fmt(row['net_ex_funding20_per_opportunity_pct']['mean'])} · "
                  f"40bp %{fmt(row['net_ex_funding40_per_opportunity_pct']['mean'])}",
                  f"40bp girilenler: medyan %{fmt(row['net_ex_funding40_per_entry_pct']['median'])} "
                  f"· kötü %10 %{fmt(row['net_ex_funding40_per_entry_pct']['q10'])} · "
                  f"aynı olaylarda baseline farkı {fmt(row['paired_delta40_vs_baseline_pp']['mean'])} puan "
                  f"(N={row['paired_delta40_vs_baseline_pp']['n']})",
                  f"Giriş bekleme ort. {fmt(row['wait_minutes']['mean'])}dk · "
                  f"çıkışa kadar medyan MAE %{fmt(row['until_exit_mae_pct']['median'])} / "
                  f"MFE %{fmt(row['until_exit_mfe_pct']['median'])}",
                  f"Tam pencere medyan MAE %{fmt(row['full_window_mae_pct']['median'])} / "
                  f"MFE %{fmt(row['full_window_mfe_pct']['median'])} · "
                  f"girişsizken kaçan %3 dokunma {row['no_entry_missed_3pct_touch']}/{row['no_entry_complete_paths']}",
                  "Karar: " + ("Asgari gözlem doldu; bağımsız değerlendirme gerekli." if row['minimum_observation_gate_met']
                                else "Veri birikiyor; 90 gün / 30 olgun giriş / 14 giriş günü kapısı dolmadı.")]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", type=Path, default=Path(__file__).resolve().parents[1]/".execution_shadow_state.json")
    parser.add_argument("--format", choices=("text", "json"), default="text")
    args = parser.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    try:
        if not args.state.exists():
            data = {"study_version": engine.VERSION, "plan_hash": engine.PLAN_HASH,
                    "activated_ms": int(time.time()*1000), "events": {}}
            report = summarize(data)
            report.update(input_status="state_missing_not_activated", activated_ms=None)
        else:
            raw = args.state.read_bytes()
            report = summarize(json.loads(raw))
            report["input_sha256"] = hashlib.sha256(raw).hexdigest()
            report["input_status"] = "loaded"
        protocol = Path(__file__).with_name("EXECUTION_SHADOW_PROTOCOL.md")
        report["protocol_sha256"] = hashlib.sha256(protocol.read_bytes()).hexdigest() if protocol.exists() else None
        print(render_text(report) if args.format == "text" else json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False))
        return 0
    except (OSError, ValueError, TypeError, KeyError, OverflowError):
        print("Gölge rapor okunamadı; state biçimini ve protokol sürümünü kontrol edin.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
