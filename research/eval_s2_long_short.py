"""Ön-kayıtlı S2-LS-v1 train/test değerlendirmesi."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

try:
    from .s2_long_short_common import (
        LONG_SHORT_MAX, STUDY_ID, attach_long_short, attach_outcomes,
        build_events, clustered_uplift_pvalue, decision, load_core_symbols,
        load_funding, prereg_sha256, split_rows, summarize,
    )
except ImportError:  # pragma: no cover - doğrudan script çalıştırma yolu
    from s2_long_short_common import (
        LONG_SHORT_MAX, STUDY_ID, attach_long_short, attach_outcomes,
        build_events, clustered_uplift_pvalue, decision, load_core_symbols,
        load_funding, prereg_sha256, split_rows, summarize,
    )


def load_metrics(root: Path, symbols: list[str]) -> dict[str, pd.DataFrame]:
    out = {}
    for symbol in symbols:
        path = root / "metrics_s2" / f"{symbol}.parquet"
        out[symbol] = pd.read_parquet(path) if path.exists() else pd.DataFrame()
    return out


def fmt(label: str, row: dict) -> str:
    if not row.get("n"):
        return f"{label:<18} N=0"
    return (f"{label:<18} N={row['n']:3d} gün={row['days']:3d} "
            f"sym={row['symbols']:2d} ort={row['mean_net_pct']:+.3f}% "
            f"med={row['median_net_pct']:+.3f}% WR={row['win_rate']:.1%} "
            f"q10={row['q10_net_pct']:+.2f}% q90={row['q90_net_pct']:+.2f}% "
            f"top5={row['top5_share']:.1%}")


def evaluate(root: Path, split: str) -> dict:
    symbols = load_core_symbols(root)
    funding = load_funding(Path(__file__).parent / "funding_cache" /
                           "funding_history.json", symbols)
    events = build_events(funding)
    events = attach_long_short(events, load_metrics(root, symbols))
    events = attach_outcomes(events, root)
    rows = split_rows(events, split)
    coverage = float(rows["long_short_ratio"].notna().mean()) if len(rows) else 0
    priced = rows.dropna(subset=["net_return_pct"])
    matched = priced.dropna(subset=["long_short_ratio"])
    filtered = matched[matched["long_short_ratio"] < LONG_SHORT_MAX]
    rejected = matched[matched["long_short_ratio"] >= LONG_SHORT_MAX]
    summaries = {
        "all_s2": summarize(priced),
        "matched_s2": summarize(matched),
        "ls_below_1": summarize(filtered),
        "ls_at_least_1": summarize(rejected),
    }
    uplift, pvalue = clustered_uplift_pvalue(filtered, rejected)
    passed, reasons = decision(split, coverage, summaries["ls_below_1"],
                               summaries["ls_at_least_1"], uplift, pvalue)
    prereg = Path(__file__).parent / "PREREG_S2_LONG_SHORT_FILTER.md"
    return {
        "study_id": STUDY_ID, "phase": split,
        "prereg_sha256": prereg_sha256(prereg),
        "event_rows_before_price_filter": int(len(rows)),
        "metric_coverage": coverage, "summaries": summaries,
        "mean_uplift_pct_vs_ls_at_least_1": uplift,
        "clustered_one_sided_pvalue": pvalue,
        "gate_passed": passed, "gate_failures": reasons,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dir", default="research/data")
    parser.add_argument("--phase", choices=("train", "test"), default="train")
    args = parser.parse_args()
    root = Path(args.dir)
    result_dir = Path(__file__).parent / "results"
    result_dir.mkdir(parents=True, exist_ok=True)
    train_path = result_dir / "s2_long_short_train.json"
    prereg = Path(__file__).parent / "PREREG_S2_LONG_SHORT_FILTER.md"
    if args.phase == "test":
        if not train_path.exists():
            print("TEST KAPALI: önce train kapısı çalıştırılmalı.")
            return 4
        train = json.loads(train_path.read_text(encoding="utf-8"))
        if (not train.get("gate_passed") or
                train.get("prereg_sha256") != prereg_sha256(prereg)):
            print("TEST KAPALI: train geçmedi veya ön-kayıt sonradan değişti.")
            return 4
    result = evaluate(root, args.phase)
    path = result_dir / f"s2_long_short_{args.phase}.json"
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2),
                    encoding="utf-8")
    print(f"{STUDY_ID} — {args.phase.upper()} (ön-kayıtlı)")
    print(f"metrics kapsamı: %{result['metric_coverage'] * 100:.1f}")
    for key, label in (("all_s2", "Tüm S2"),
                       ("matched_s2", "Eşleşen S2"),
                       ("ls_below_1", "LS < 1"),
                       ("ls_at_least_1", "LS >= 1")):
        print(fmt(label, result["summaries"][key]))
    print("LS<1 eksi LS>=1 ortalama farkı: "
          f"{result['mean_uplift_pct_vs_ls_at_least_1']:+.3f} yüzde puan · "
          f"gün-kümeli p={result['clustered_one_sided_pvalue']:.4f}")
    if result["gate_passed"]:
        print("KARAR: KAPI GEÇTİ" +
              (" — dokunulmamış test açılabilir."
               if args.phase == "train" else
               " — canlı entegrasyon kod incelemesine geçebilir."))
        return 0
    print("KARAR: RED — canlı S2 değişmedi.")
    for reason in result["gate_failures"]:
        print(f"  - {reason}")
    if args.phase == "train":
        print("Dokunulmamış TEST açılmadı.")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
