"""Offline TP2/TP3 follow-up to archive end; no stop or per-event time limit.

Reuses frozen event identities, not old bracket MFE. No bot import or network.
Unreached targets remain pending, or unavailable when price coverage has gaps.
"""
from __future__ import annotations
import argparse
from collections import defaultdict
import csv
import hashlib
import io
import json
from pathlib import Path
import sys
import zipfile

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from research.market_regime_review import DAY, HOUR, GROUPS, load_hourly

VERSION = "eventual-touch-observed-v1"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_rows(path):
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def evaluate(frame, entry_ms, cutoff_ms, bar_ms, *, entry_price=None):
    """A witnessed touch is success even after a gap; its time is an upper bound.

    No hit plus incomplete history is unavailable. No hit plus full observed
    history is pending (right censored), never a loss. Candles after cutoff and
    before entry are excluded. The first hit bar's close bounds its timestamp.
    """
    times = frame.open_time.to_numpy(dtype=np.int64)
    idx = int(np.searchsorted(times, entry_ms))
    result = {"entry_ms": int(entry_ms), "cutoff_ms": int(cutoff_ms),
              "observed_hours": max(0., (cutoff_ms-entry_ms)/HOUR)}
    if idx == len(times) or times[idx] != entry_ms or not bool(frame.valid.iloc[idx]):
        return {**result, "reason": "missing_or_invalid_entry", "tp2": "unavailable", "tp3": "unavailable"}
    entry = float(frame.open.iloc[idx])
    if entry_price is not None and not np.isclose(entry, entry_price, rtol=1e-9, atol=0):
        raise ValueError("entry_price_provenance_mismatch")
    window = frame[(frame.open_time >= entry_ms) & (frame.open_time + bar_ms <= cutoff_ms)]
    stamps = window.open_time.to_numpy(dtype=np.int64)
    valid = window.valid.to_numpy(dtype=bool)
    complete = (len(stamps) > 0 and stamps[0] == entry_ms
                and np.all(np.diff(stamps) == bar_ms) and valid.all()
                and stamps[-1]+bar_ms == cutoff_ms)
    result.update(entry_price=entry, complete_coverage=bool(complete))
    for target in (2, 3):
        hits = np.flatnonzero(valid & (window.high.to_numpy() >= entry*(1+target/100)))
        result[f"tp{target}"] = "hit" if len(hits) else "pending" if complete else "unavailable"
        result[f"tp{target}_hours_upper"] = (float((stamps[hits[0]]+bar_ms-entry_ms)/HOUR) if len(hits) else None)
    return result


def load_g2_prices(folder, contract):
    """Read checksum-verified Binance USD-M 5m cache, preserving contract units."""
    parts, proofs = [], []
    for path in sorted((folder/"prices"/contract).glob("*.zip")):
        digest = sha(path)
        checksum = path.with_suffix(".zip.CHECKSUM").read_text().split()
        if len(checksum) != 2 or checksum[0].lower() != digest or checksum[1].lstrip("*") != path.name:
            raise ValueError("price_checksum_mismatch")
        with zipfile.ZipFile(path) as archive:
            infos = archive.infolist()
            if len(infos) != 1 or not infos[0].filename.endswith(".csv"):
                raise ValueError("invalid_price_zip")
            with archive.open(infos[0]) as raw:
                for row in csv.reader(io.TextIOWrapper(raw, encoding="utf-8-sig")):
                    if row and row[0] == "open_time":
                        continue
                    t = int(row[0])
                    if len(row) != 12 or t % 300000 or int(row[6]) != t+299999:
                        raise ValueError("invalid_price_timestamp")
                    o, h, l, c = map(float, row[1:5])
                    good = all(np.isfinite([o,h,l,c])) and 0 < l <= min(o,c) <= max(o,c) <= h
                    parts.append((t,o,h,l,c,good))
        proofs.append({"file": path.name, "sha256": digest})
    if not parts:
        raise ValueError("missing_price_archive")
    frame = pd.DataFrame(parts, columns=["open_time","open","high","low","close","valid"]).sort_values("open_time")
    if frame.open_time.duplicated().any():
        raise ValueError("duplicate_price_timestamp")
    return frame, proofs


def summarize(rows):
    frame = pd.DataFrame(rows)
    summaries = []
    for (strategy, universe), subset in frame.groupby(["strategy", "universe"]):
        for group in GROUPS:
            selected = subset if group == "ALL" else subset[(subset.regime == group) | (subset.subtype == group)]
            if selected.empty:
                continue
            item = {"strategy":strategy, "universe":universe, "group":group, "n":len(selected),
                    "days":int((selected.time_ms//DAY).nunique()),
                    "first_signal_ms":int(selected.time_ms.min()), "last_signal_ms":int(selected.time_ms.max()),
                    "cutoff_ms":int(selected.cutoff_ms.max()),
                    "followup_hours_min":float(selected.observed_hours.min()),
                    "followup_hours_median":float(selected.observed_hours.median()),
                    "followup_hours_max":float(selected.observed_hours.max())}
            for target in (2,3):
                key = f"tp{target}"
                hits = selected[selected[key] == "hit"]
                durations = hits[key+"_hours_upper"].dropna()
                n = len(selected)
                item[key] = {"hit":len(hits), "pending":int((selected[key]=="pending").sum()),
                             "unavailable":int((selected[key]=="unavailable").sum()),
                             "observed_hit_pct_all":100*len(hits)/n,
                             "median_hours_to_hit_upper":float(durations.median()) if len(durations) else None,
                             "after_original_horizon":int((hits[key+"_hours_upper"]>hits.horizon).sum())}
            summaries.append(item)
    return summaries


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--events", type=Path, required=True)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--search", type=Path, required=True)
    parser.add_argument("--g2-prices", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    events = read_rows(args.events)
    identities = [(e["strategy"],e["universe"],e["symbol"],e["time_ms"]) for e in events]
    if len(identities) != len(set(identities)):
        raise ValueError("duplicate_event")
    g2_map = {}
    for file in ("search_outcomes.jsonl", "confirm_outcomes.jsonl"):
        for row in read_rows(args.search/file):
            if any(cid == "fade_long_l1_up_d60_e2" for cid, _ in row["members"]):
                key = (row["symbol"], row["signal_hour"]*HOUR)
                if key in g2_map:
                    raise ValueError("duplicate_g2_event")
                g2_map[key] = row
    grouped = defaultdict(list)
    for event in events:
        grouped[(event["strategy"]=="G2",event["symbol"],event.get("market","um"))].append(event)
    results, proofs = [], []
    for (is_g2,symbol,market), selected in grouped.items():
        if is_g2:
            contract = g2_map[symbol,selected[0]["time_ms"]]["contract"]
            frame, files = load_g2_prices(args.g2_prices, contract)
            proofs.extend(files)
            bar_ms = 300000
            available_end = min(int(frame.open_time.max())+bar_ms, int(pd.Timestamp("2026-09-13",tz="UTC").timestamp()*1000))
        else:
            path = args.data/market/(symbol+".parquet")
            frame = load_hourly(path)
            proofs.append({"file":f"{market}/{symbol}.parquet", "sha256":sha(path)})
            bar_ms = HOUR
            available_end = int(frame.open_time.max())+bar_ms
        for event in selected:
            cutoff = available_end
            # User requested all available follow-up, including across the old
            # TRAIN boundary. G1 event selection stays fixed; no fresh OOS claim.
            raw = g2_map[symbol,event["time_ms"]] if is_g2 else {}
            entry = raw.get("entry_ms",event["time_ms"])
            out = evaluate(frame,entry,cutoff,bar_ms,entry_price=raw.get("entry_price"))
            metadata = {k:event[k] for k in ("strategy","universe","symbol","time_ms","regime","subtype","split")}
            results.append({**metadata,"horizon":event.get("horizon",24 if is_g2 else 4),**out})
        print(f"evaluated {symbol} {market}: {len(selected)}",flush=True)
    args.output.mkdir(parents=True,exist_ok=True)
    outcome_path = args.output/"events.jsonl"
    with outcome_path.open("w",encoding="utf-8") as f:
        for row in results:
            f.write(json.dumps(row,ensure_ascii=False,allow_nan=False)+"\n")
    report = {"version":VERSION,"measurement":"no_stop_no_event_time_limit_observed_through_archive_cutoff",
              "source_events_sha256":sha(args.events),"code_sha256":sha(__file__),"events_sha256":sha(outcome_path),
              "n":len(results),"summaries":summarize(results),"source_prices":proofs,
              "unavailable_strategies":{"G1_live":"recent_tablet_records_not_available_locally",
                                        "S5/S6":"historical_dynamic_membership_unavailable", "DL1":"not_directional_strategy"},
              "caveats":["pending_is_not_failure", "finite_observation_not_infinite_future_probability",
                         "same_frozen_cohort_as_previous_report", "G1_train_events_followed_into_2026_not_fresh_OOS",
                         "G2_rebuilt_from_raw_prices_old_MFE_was_exit_truncated"]}
    (args.output/"results.json").write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False)+"\n",encoding="utf-8")


if __name__ == "__main__":
    main()
