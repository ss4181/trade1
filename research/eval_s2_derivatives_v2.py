"""S2-DERIV-v2: OI/pozisyon ve funding-LS uyumsuzluğu ön-kayıtlı testi."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import pandas as pd

try:
    from .s2_long_short_common import (
        STUDY_ID as _OLD_STUDY_ID, attach_derivatives_features,
        attach_outcomes, build_events, clustered_uplift_pvalue,
        load_core_symbols, load_funding, prereg_sha256, split_rows, summarize,
    )
except ImportError:  # pragma: no cover
    from s2_long_short_common import (
        STUDY_ID as _OLD_STUDY_ID, attach_derivatives_features,
        attach_outcomes, build_events, clustered_uplift_pvalue,
        load_core_symbols, load_funding, prereg_sha256, split_rows, summarize,
    )

STUDY_ID = "S2-DERIV-v2"
CANDIDATES = ("OI_SHORT_BUILD", "FUNDING_LS_DIVERGENCE")


def load_metrics(root: Path, symbols: list[str]) -> dict[str, pd.DataFrame]:
    return {
        symbol: (pd.read_parquet(root / "metrics_s2" / f"{symbol}.parquet")
                 if (root / "metrics_s2" / f"{symbol}.parquet").exists()
                 else pd.DataFrame())
        for symbol in symbols
    }


def candidate_masks(rows: pd.DataFrame, name: str) -> tuple[pd.Series, pd.Series]:
    if name == "OI_SHORT_BUILD":
        complete = rows[["oi_change_8h", "top_position_ls"]].notna().all(axis=1)
        selected = complete & (rows["oi_change_8h"] > 0) & (
            rows["top_position_ls"] < 1.0)
    elif name == "FUNDING_LS_DIVERGENCE":
        complete = rows[["funding_delta", "global_ls_change_8h"]].notna().all(
            axis=1)
        selected = complete & (rows["funding_delta"] < 0) & (
            rows["global_ls_change_8h"] > 0)
    else:
        raise ValueError(f"bilinmeyen aday: {name}")
    return complete, selected


def candidate_decision(split: str, coverage: float, retention: float,
                       filtered: dict, rejected: dict, uplift: float,
                       pvalue: float) -> tuple[bool, list[str]]:
    reasons = []
    min_n, min_days = (30, 25) if split == "train" else (30, 20)
    p_limit = .025 if split == "train" else .10
    checks = [
        (coverage >= .90, f"kapsam %{coverage * 100:.1f} < %90"),
        (filtered.get("n", 0) >= min_n,
         f"filtreli N={filtered.get('n', 0)} < {min_n}"),
        (filtered.get("days", 0) >= min_days,
         f"bağımsız gün={filtered.get('days', 0)} < {min_days}"),
        (filtered.get("symbols", 0) >= 8,
         f"sembol={filtered.get('symbols', 0)} < 8"),
        (filtered.get("mean_net_pct", -math.inf) > 0,
         "net ortalama pozitif değil"),
        (filtered.get("median_net_pct", -math.inf) > 0,
         "net medyan pozitif değil"),
        (filtered.get("win_rate", 0) >= .52, "isabet %52 altında"),
        (filtered.get("top5_share", 1) <= .70,
         "top-5 sembol payı %70 üzerinde"),
        (math.isfinite(pvalue) and pvalue <= p_limit,
         f"gün-kümeli p>{p_limit:.3f}"),
        (math.isfinite(uplift) and uplift > 0,
         "ortalama uplift pozitif değil"),
        (filtered.get("median_net_pct", -math.inf) >
         rejected.get("median_net_pct", math.inf),
         "medyan uplift pozitif değil"),
    ]
    if split == "train":
        checks += [
            (uplift >= .50, "ortalama uplift +0.50 puanın altında"),
            (.10 <= retention <= .80,
             "olay tutma oranı %10-%80 dışında"),
        ]
    else:
        checks.append((
            filtered.get("q10_net_pct", -math.inf) >=
            rejected.get("q10_net_pct", math.inf) - 1.0,
            "filtreli q10 karşı gruptan >1 puan kötü"))
    for passed, reason in checks:
        if not passed:
            reasons.append(reason)
    return not reasons, reasons


def evaluate_candidate(rows: pd.DataFrame, name: str, split: str) -> dict:
    complete, selected = candidate_masks(rows, name)
    coverage = float(complete.mean()) if len(rows) else 0.0
    matched = rows.loc[complete].dropna(subset=["net_return_pct"])
    filtered = rows.loc[selected].dropna(subset=["net_return_pct"])
    rejected = rows.loc[complete & ~selected].dropna(
        subset=["net_return_pct"])
    retention = len(filtered) / len(matched) if len(matched) else 0.0
    fs, rs = summarize(filtered), summarize(rejected)
    uplift, pvalue = clustered_uplift_pvalue(filtered, rejected,
                                             seed=20260902)
    passed, reasons = candidate_decision(
        split, coverage, retention, fs, rs, uplift, pvalue)
    return {
        "candidate": name, "coverage": coverage, "retention": retention,
        "filtered": fs, "rejected": rs, "mean_uplift_pct": uplift,
        "clustered_one_sided_pvalue": pvalue, "gate_passed": passed,
        "gate_failures": reasons,
    }


def load_rows(root: Path, split: str) -> pd.DataFrame:
    symbols = load_core_symbols(root)
    funding = load_funding(Path(__file__).parent / "funding_cache" /
                           "funding_history.json", symbols)
    events = build_events(funding)
    events = attach_derivatives_features(
        events, load_metrics(root, symbols), funding)
    return split_rows(attach_outcomes(events, root), split)


def fmt(name: str, result: dict) -> str:
    row = result["filtered"]
    if not row.get("n"):
        return f"{name:<24} N=0"
    return (f"{name:<24} N={row['n']:3d} gün={row['days']:3d} "
            f"sym={row['symbols']:2d} tut={result['retention']:.1%} "
            f"ort={row['mean_net_pct']:+.3f}% med={row['median_net_pct']:+.3f}% "
            f"WR={row['win_rate']:.1%} uplift={result['mean_uplift_pct']:+.3f} "
            f"p={result['clustered_one_sided_pvalue']:.4f} "
            f"top5={row['top5_share']:.1%}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dir", default="research/data")
    parser.add_argument("--phase", choices=("train", "test"), default="train")
    args = parser.parse_args()
    root = Path(args.dir)
    results_dir = Path(__file__).parent / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    prereg = Path(__file__).parent / "PREREG_S2_DERIVATIVES_V2.md"
    train_path = results_dir / "s2_derivatives_v2_train.json"

    selected = None
    if args.phase == "test":
        if not train_path.exists():
            print("TEST KAPALI: önce train seçimi çalıştırılmalı.")
            return 4
        train = json.loads(train_path.read_text(encoding="utf-8"))
        selected = train.get("selected_candidate")
        if (not selected or train.get("prereg_sha256") !=
                prereg_sha256(prereg)):
            print("TEST KAPALI: train adayı seçilmedi veya ön-kayıt değişti.")
            return 4

    rows = load_rows(root, args.phase)
    names = (selected,) if selected else CANDIDATES
    evaluations = {name: evaluate_candidate(rows, name, args.phase)
                   for name in names}
    if args.phase == "train":
        passed = [row for row in evaluations.values() if row["gate_passed"]]
        if passed:
            passed.sort(key=lambda row: (
                row["clustered_one_sided_pvalue"],
                -row["mean_uplift_pct"], row["candidate"]))
            selected = passed[0]["candidate"]
    result = {
        "study_id": STUDY_ID, "phase": args.phase,
        "prereg_sha256": prereg_sha256(prereg),
        "s2_rows": int(len(rows)), "evaluations": evaluations,
        "selected_candidate": selected,
        "live_integration_allowed": bool(
            args.phase == "test" and selected and
            evaluations[selected]["gate_passed"]),
    }
    output = results_dir / f"s2_derivatives_v2_{args.phase}.json"
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2),
                      encoding="utf-8")
    print(f"{STUDY_ID} — {args.phase.upper()} (ön-kayıtlı)")
    for name in names:
        row = evaluations[name]
        print(fmt(name, row))
        if not row["gate_passed"]:
            for reason in row["gate_failures"]:
                print(f"  - {reason}")
    if args.phase == "train" and selected:
        print(f"KARAR: TRAIN GEÇTİ — seçilen aday {selected}; test açılabilir.")
        return 0
    if args.phase == "test" and result["live_integration_allowed"]:
        print(f"KARAR: TEST GEÇTİ — {selected} canlı incelemeye alınabilir.")
        return 0
    print("KARAR: RED — canlı S2 değişmedi.")
    if args.phase == "train":
        print("Dokunulmamış TEST açılmadı.")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
