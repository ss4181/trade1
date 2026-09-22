"""Offline, fixed-protocol regime review; never imports the bot or sends messages.

Fetch writes public BTC spot daily bars only when explicitly requested.
The analysis uses the existing canonical engine with a validated numpy adapter.
"""
from __future__ import annotations

import argparse
import ast
from bisect import bisect_right
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd
from numpy.lib.stride_tricks import sliding_window_view

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "research"))
from strategy_engine import CoreRules, closed_window_features, funding_squeeze, should_fire

HOUR = 3_600_000
DAY = 24 * HOUR
SPLIT = int(pd.Timestamp("2026-01-01", tz="UTC").timestamp() * 1000)
VERSION = "btc-daily-regime-v1"
GROUPS = ["ALL", "BULL", "TRANSITION", "BEAR", "bull_pullback", "bull_moderate", "bull_strong"]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2,
                                    allow_nan=False) + "\n", encoding="utf-8")


def fetch_daily(path):
    import requests
    start = int(pd.Timestamp("2023-10-01", tz="UTC").timestamp() * 1000)
    end = int(pd.Timestamp("2026-09-22", tz="UTC").timestamp() * 1000)
    rows, urls = [], []
    while start < end:
        response = requests.get("https://api.binance.com/api/v3/klines", params={
            "symbol": "BTCUSDT", "interval": "1d", "startTime": start,
            "endTime": end - 1, "limit": 1000}, timeout=30)
        response.raise_for_status()
        page = response.json()
        if not page:
            raise ValueError("incomplete_daily_download")
        rows.extend(page)
        urls.append(response.url)
        start = int(page[-1][0]) + DAY
    if rows[0][0] != int(pd.Timestamp("2023-10-01", tz="UTC").timestamp() * 1000) or rows[-1][0] + DAY != end:
        raise ValueError("wrong_daily_coverage")
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    write(path, {"source": "Binance spot BTCUSDT UTC 1d", "urls": urls,
                 "fetched_at": datetime.now(timezone.utc).isoformat(), "rows": rows})


def daily_table(raw):
    rows = raw["rows"]
    stamps = np.array([int(r[0]) for r in rows], dtype=np.int64)
    closes = np.array([float(r[4]) for r in rows])
    if (len(stamps) < 220 or np.any(stamps % DAY) or np.any(np.diff(stamps) != DAY)
            or np.any(~np.isfinite(closes)) or np.any(closes <= 0)
            or any(int(r[6]) != int(r[0]) + DAY - 1 for r in rows)):
        raise ValueError("invalid_daily_grid")
    c = pd.Series(closes)
    m = c.rolling(200, min_periods=200).mean()
    slope = m / m.shift(20) - 1
    momentum = c / c.shift(30) - 1
    frame = pd.DataFrame({"available_ms": stamps + DAY, "close": closes,
                          "sma200": m, "slope20": slope,
                          "distance": c / m - 1, "momentum30": momentum})
    frame["regime"] = "TRANSITION"
    frame.loc[(c > 1.02 * m) & (slope > 0), "regime"] = "BULL"
    frame.loc[(c < .98 * m) & (slope < 0), "regime"] = "BEAR"
    frame.loc[slope.isna(), "regime"] = "UNKNOWN"
    frame["subtype"] = frame["regime"]
    for cond, name in [(momentum < 0, "bull_pullback"),
                       ((momentum >= 0) & (momentum <= .10), "bull_moderate"),
                       (momentum > .10, "bull_strong")]:
        frame.loc[(frame["regime"] == "BULL") & cond, "subtype"] = name
    return frame


def labels(table, times):
    times = np.asarray(times, dtype=np.int64)
    idx = np.searchsorted(table["available_ms"].to_numpy(), times, side="right") - 1
    safe = np.maximum(idx, 0)
    valid = (idx >= 0) & (times - table["available_ms"].to_numpy()[safe] < DAY)
    return (np.where(valid, table["regime"].to_numpy()[safe], "UNKNOWN"),
            np.where(valid, table["subtype"].to_numpy()[safe], "UNKNOWN"))


def load_hourly(path):
    df = pd.read_parquet(path).sort_values("open_time").reset_index(drop=True)
    if df["open_time"].duplicated().any() or (df["open_time"] % HOUR).any():
        raise ValueError("invalid_hourly_timestamps")
    grid = np.arange(int(df.open_time.iloc[0]), int(df.open_time.iloc[-1]) + HOUR, HOUR)
    df = df.set_index("open_time").reindex(grid).rename_axis("open_time").reset_index()
    p = df[["open", "high", "low", "close", "volume"]].to_numpy(dtype=float)
    df["valid"] = (np.isfinite(p).all(axis=1) & (p[:, :4] > 0).all(axis=1)
                   & (p[:, 4] >= 0) & (p[:, 2] <= np.minimum(p[:, 0], p[:, 3]))
                   & (p[:, 1] >= np.maximum(p[:, 0], p[:, 3])))
    return df


def features_fast(df, rules):
    """Reset RSI at each 249-bar window; retain current-inclusive volume math."""
    n = rules.kline_limit - 1
    if len(df) < n:
        return None
    c = sliding_window_view(df.close.to_numpy(dtype=float), n)
    lows = sliding_window_view(df.low.to_numpy(dtype=float), n)
    rsi = np.full(c.shape, np.nan)
    gains = np.zeros(len(c))
    losses = np.zeros(len(c))
    p = rules.rsi_period
    for i in range(1, p + 1):
        d = c[:, i] - c[:, i - 1]
        gains += np.maximum(d, 0)
        losses += np.maximum(-d, 0)
    gains /= p
    losses /= p
    with np.errstate(divide="ignore", invalid="ignore"):
        rsi[:, p] = np.where(losses == 0, 100., 100 - 100 / (1 + gains / losses))
        for i in range(p + 1, n):
            d = c[:, i] - c[:, i - 1]
            gains = (gains * (p - 1) + np.maximum(d, 0)) / p
            losses = (losses * (p - 1) + np.maximum(-d, 0)) / p
            rsi[:, i] = np.where(losses == 0, 100., 100 - 100 / (1 + gains / losses))
    hi = n - 1 - rules.divergence_gap
    lo = hi - rules.divergence_lookback + 1
    pidx = lo + np.argmin(lows[:, lo:hi + 1], axis=1)
    ii = np.arange(len(c))
    s1 = ((rsi[:, -1] <= rules.oversold) & (lows[:, -1] < lows[ii, pidx])
          & (rsi[:, -1] > rsi[ii, pidx]))
    logs = np.log1p(df.volume.astype(float))
    win = logs.rolling(rules.volume_window, min_periods=rules.volume_window)
    z = (logs - win.mean()) / win.std(ddof=1)
    recent = z.rolling(rules.confluence_hours + 1, min_periods=rules.confluence_hours + 1).max()
    return pd.DataFrame({"i": np.arange(n - 1, len(df)), "rsi": rsi[:, -1],
        "volume_logz": z.to_numpy()[n - 1:], "s1": s1,
        "s3_spike": z.to_numpy()[n - 1:] >= rules.volume_threshold,
        "green_bar": df.close.to_numpy()[n - 1:] > df.open.to_numpy()[n - 1:],
        "s4": recent.to_numpy()[n - 1:] >= rules.volume_threshold,
        "valid": sliding_window_view(df.valid.to_numpy(), n).all(axis=1)})


def validate_adapter(df, fast, rules):
    # Every positive S1/volume candidate + deterministic coverage; near-threshold
    # false negatives are also checked against the independent scalar engine.
    chosen = fast.valid & (fast.s1 | fast.s3_spike
        | (np.abs(fast.volume_logz - rules.volume_threshold) < 1e-7)
        | (np.abs(fast.rsi - rules.oversold) < 1e-7))
    ids = set(fast.index[chosen]) | set(np.linspace(0, len(fast)-1, 40, dtype=int))
    bars = df[["open_time", "open", "high", "low", "close", "volume"]].to_dict("records")
    count = 0
    for k in sorted(ids):
        row = fast.loc[k]
        if not row.valid:
            continue
        i = int(row.i)
        expected = closed_window_features(bars[i-rules.kline_limit+2:i+1], rules)
        for name in ("s1", "s3_spike", "s4", "green_bar"):
            if bool(row[name]) != expected[name]:
                raise ValueError(f"adapter_parity_{name}_{i}")
        for name in ("rsi", "volume_logz"):
            if not np.isclose(row[name], expected[name], atol=1e-8, rtol=0, equal_nan=True):
                raise ValueError(f"adapter_parity_{name}_{i}")
        count += 1
    return count


def regimes_for_frame(df, table):
    # Entry at current hour open, after prior hourly bar's close. No entry-delay model.
    df = df.copy()
    df["regime"], df["subtype"] = labels(table, df.open_time.to_numpy())
    return df


def return_grid(df, horizon):
    entry = df.open.astype(float)
    result = (df.close.shift(-(horizon - 1)) / entry - 1) * 100
    valid = df.valid.iloc[::-1].rolling(horizon, min_periods=horizon).sum().iloc[::-1] == horizon
    # Prevent TRAIN exits at/after split and ensure common return horizon.
    valid &= ~((df.open_time < SPLIT) & (df.open_time + horizon * HOUR >= SPLIT))
    return (result - .12).where(valid)


def touch_grid(df, horizon):
    """Return unrestricted long target-touch flags for the hourly window.

    The entry is the opening price of the event bar and the window includes
    that bar through ``horizon - 1``.  This intentionally measures the same
    gross price-touch concept used by the Telegram archive: no stop, fee,
    slippage, fill, or order sequencing is inferred from the hourly OHLC.
    Missing/invalid bars make the touch unavailable instead of a miss.
    """
    if horizon <= 0:
        raise ValueError("invalid_touch_horizon")
    entry = pd.to_numeric(df.open, errors="coerce")
    high = pd.to_numeric(df.high, errors="coerce")
    valid = df.valid.astype(bool)
    future_high = high.iloc[::-1].rolling(
        horizon, min_periods=horizon).max().iloc[::-1]
    complete = valid.iloc[::-1].rolling(
        horizon, min_periods=horizon).sum().iloc[::-1] == horizon
    base = complete & np.isfinite(entry) & (entry > 0) & np.isfinite(future_high)
    out = pd.DataFrame(index=df.index)
    for target in (2, 3):
        touched = (future_high >= entry * (1 + target / 100.0))
        out[f"tp{target}_touch"] = touched.where(base, np.nan)
    return out


def core_events(data_dir, funding_file, bot_path, table):
    module = ast.parse(Path(bot_path).read_text(encoding="utf-8"))
    core = extended = None
    for node in module.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "DEFAULT_SYMBOLS" for t in node.targets):
            core = ast.literal_eval(node.value).split(",")
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "EXTENDED_SYMBOLS_DEFAULT" for t in node.targets):
            extended = ast.literal_eval(node.value).split(",")
    if not core or len(core) != 30 or not extended or len(extended) != 59:
        raise ValueError("expected_core30")
    symbols = core + extended
    funding = json.loads(Path(funding_file).read_text(encoding="utf-8"))
    rules = CoreRules()
    output, audits = [], []
    for symbol in symbols:
        is_extended = symbol in extended
        universe = "extended59" if is_extended else "core30"
        spot = load_hourly(data_dir / "spot" / (symbol + ".parquet"))
        perp = load_hourly(data_dir / "um" / (symbol + ".parquet"))
        fast = features_fast(spot, rules)
        checks = validate_adapter(spot, fast, rules)
        prev, last = {}, {}
        events = []
        fr = [{"time": int(t), "rate": float(r)} for t, r in funding.get(symbol, [])]
        fr.sort(key=lambda r: r["time"])
        ft = [r["time"] for r in fr]
        # State warmup: full window + 72 hours; no first-window performance.
        warmup = int(spot.open_time.iloc[0]) + (rules.kline_limit - 1 + 72) * HOUR
        missing_funding_scans = 0
        for row in fast.itertuples(index=False):
            if not row.valid:
                continue
            now = int(spot.open_time.iloc[row.i]) + HOUR
            def fire(name, cond, cooldown):
                return should_fire(prev, last, name, symbol, bool(cond), cooldown, now / 1000)
            if fire("S1", row.s1, rules.s1_cooldown_hours):
                events.append(("S1+S4" if row.s4 else "S1", now, 24, "spot"))
            if not is_extended and fire("S3", row.s3_spike, rules.s3_cooldown_hours) and row.green_bar:
                events.append(("S3", now, 4, "spot"))
            if is_extended:
                continue
            pos = bisect_right(ft, now)
            known = fr[max(0, pos - rules.funding_persistence):pos]
            if len(known) < rules.funding_persistence:
                missing_funding_scans += 1
            elif fire("S2", funding_squeeze(known, rules.funding_threshold_pct, rules.funding_persistence), rules.s2_cooldown_hours):
                events.append(("S2", now, 72, "um"))
        grids = {}
        for market, frame, horizon in [("spot", spot, 24), ("spot", spot, 4), ("um", perp, 72)]:
            frame = regimes_for_frame(frame, table)
            frame["net_pct"] = return_grid(frame, horizon)
            frame = pd.concat([frame, touch_grid(frame, horizon)], axis=1)
            frame.loc[frame.open_time < warmup, "net_pct"] = np.nan
            frame["split"] = np.where(frame.open_time < SPLIT, "TRAIN", "SEEN_2026H1")
            # Same-symbol, same-regime baseline; subtype baseline kept separate.
            for group in ("regime", "subtype"):
                frame["base_" + group] = frame.groupby(["split", group])["net_pct"].transform("mean")
            grids[(market, horizon)] = frame.set_index("open_time")
        omitted = 0
        for strategy, now, h, market in events:
            grid = grids[(market, h)]
            if now not in grid.index:
                omitted += 1
                continue
            r = grid.loc[now]
            if not np.isfinite(r.net_pct) or r.regime == "UNKNOWN":
                omitted += 1
                continue
            output.append({"strategy": strategy, "universe": universe, "symbol": symbol, "time_ms": now,
                "split": str(r.split), "regime": str(r.regime), "subtype": str(r.subtype),
                "horizon": h, "market": market, "net_pct": float(r.net_pct),
                "gross_pct": float(r.net_pct) + .12, "base_regime": float(r.base_regime),
                "base_subtype": float(r.base_subtype),
                "tp2_touch": bool(r.tp2_touch), "tp3_touch": bool(r.tp3_touch),
                "touch_measurement": "hourly_high_ge_entry_target_no_stop",
                "measurement": "time_exit_12bp_funding_excluded"})
        audits.append({"symbol": symbol, "universe": universe, "parity_windows": checks, "events_before_outcome_filter": len(events),
                       "omitted_outcome_or_warmup": omitted, "missing_funding_scans": missing_funding_scans,
                       "invalid_feature_windows": int((~fast.valid).sum()),
                       "spot_sha256": sha(data_dir / "spot" / (symbol + ".parquet")),
                       "um_sha256": sha(data_dir / "um" / (symbol + ".parquet"))})
        print(f"{universe} {symbol}: parity={checks} events={len(events)}", flush=True)
    return output, {"rules_hash": rules.fingerprint(), "symbols": audits, "funding_sha256": sha(funding_file)}


def g1_proxy(data_dir, table):
    from eval_gainer_short_crowd import prepare, assign_events, collect
    manifest = json.loads((data_dir / "manifest_metrics_gainer.json").read_text())
    if any(r["missing_days"] or r["failures"] for r in manifest["symbols"]):
        raise ValueError("incomplete_g1_metrics")
    symbols = {r["symbol"] for r in manifest["symbols"] if r["written_rows"] > 0}
    panel = {}
    for symbol in sorted(symbols):
        # Slice BEFORE preparing returns: G1's untouched 2026H1 outcomes not evaluated.
        price = pd.read_parquet(data_dir / "um" / (symbol + ".parquet"))
        metric = pd.read_parquet(data_dir / "metrics_gainer" / (symbol + ".parquet"))
        metric_time = pd.to_datetime(metric.create_time, utc=True)
        panel[symbol] = prepare(price[price.open_time < SPLIT], metric[metric_time < pd.Timestamp("2026-01-01", tz="UTC")])
    assign_events(panel)
    selected = collect(panel, symbols, "train", 4, "signal")
    output = []
    touch_frames = {}
    for row in selected.itertuples():
        now = int(row.t.timestamp() * 1000) + HOUR
        regime, subtype = labels(table, [now])
        symbol = str(row.symbol)
        if symbol not in touch_frames:
            touch_frame = load_hourly(data_dir / "um" / (symbol + ".parquet"))
            touch_frame = pd.concat(
                [touch_frame, touch_grid(touch_frame, 4)], axis=1)
            touch_frames[symbol] = touch_frame.set_index("open_time")
        touch_frame = touch_frames[symbol]
        if now not in touch_frame.index:
            continue
        touch = touch_frame.loc[now]
        if (not bool(touch.valid) or pd.isna(touch.tp2_touch)
                or pd.isna(touch.tp3_touch)):
            continue
        output.append({"strategy": "G1_PROXY", "universe": "fixed89_proxy", "symbol": row.symbol, "time_ms": now,
            "split": "TRAIN", "regime": regime[0], "subtype": subtype[0],
            "net_pct": float(row.net_pct), "gross_pct": float(row.net_pct) + .12,
            "horizon": 4, "market": "um",
            "tp2_touch": bool(touch.tp2_touch), "tp3_touch": bool(touch.tp3_touch),
            "touch_measurement": "hourly_high_ge_entry_target_no_stop",
            "measurement": "legacy_fixed89_time_exit_12bp_funding_excluded"})
    print(f"G1 proxy: {len(output)}", flush=True)
    return output


def g2_events(search_dir, table):
    candidate = "fade_long_l1_up_d60_e2"
    output, seen = [], set()
    for file in ("search_outcomes.jsonl", "confirm_outcomes.jsonl"):
        with (search_dir / file).open(encoding="utf-8") as source:
            for line in source:
                row = json.loads(line)
                periods = [split for cid, split in row["members"] if cid == candidate]
                if not periods:
                    continue
                if len(periods) != 1 or row["key"] in seen or not row["available"]:
                    raise ValueError("invalid_selected_g2_scenario")
                seen.add(row["key"])
                now = row["signal_hour"] * HOUR  # closed-hour feature, BEFORE 60m entry delay
                regime, subtype = labels(table, [now])
                output.append({"strategy": "G2", "universe": "fixed87", "symbol": row["symbol"], "time_ms": now,
                    "split": periods[0], "regime": regime[0], "subtype": subtype[0],
                    "entry_time_ms": int(row.get("entry_ms", now + HOUR)),
                    "horizon": 24, "market": "um",
                    "net_pct": row["net20_low"], "gross_pct": row["gross"],
                    # Search MFE ends at the bracket exit. It cannot describe
                    # unrestricted touches after a stop; use raw-price follow-up.
                    "tp2_touch": None,
                    "tp3_touch": None,
                    "touch_measurement": "unavailable_exit_truncated_MFE_use_raw_prices",
                    "outcome": row["outcome"], "measurement": "bracket_20bp_conservative_funding"})
    if Counter(r["split"] for r in output) != {"A": 97, "B": 84, "C": 71}:
        raise ValueError("g2_expected_counts_changed")
    return output


def block_interval(frame, values):
    days = frame.time_ms.to_numpy(dtype=np.int64) // DAY
    if len(frame) < 30 or len(set(days)) < 28:
        return None
    # Moving 7-calendar-day blocks preserve co-occurring cross-symbol events.
    start, end = int(days.min()), int(days.max())
    total = end - start + 1
    sums = np.bincount(days-start, weights=np.asarray(values, dtype=float), minlength=total)
    counts = np.bincount(days-start, minlength=total)
    rng = np.random.default_rng(20260922)
    samples = []
    for _ in range(2000):
        starts = rng.integers(0, total, size=(total+6)//7)
        idx = ((starts[:, None] + np.arange(7)) % total).ravel()[:total]
        n = counts[idx].sum()
        if n:
            samples.append(sums[idx].sum()/n)
    return [float(v) for v in np.quantile(samples, [.025, .975])]


def summaries(events):
    result = []
    allrows = pd.DataFrame(events)
    for (strategy, universe), rows in allrows.groupby(["strategy", "universe"]):
        splits = ["ALL"] + sorted(rows.split.unique().tolist())
        if strategy == "G2":
            splits.append("A+B")
        for split in splits:
            subset = rows if split == "ALL" else rows[rows.split.isin(["A", "B"]) if split == "A+B" else rows.split == split]
            for group in GROUPS:
                frame = subset if group == "ALL" else subset[(subset.regime == group) | (subset.subtype == group)]
                if frame.empty:
                    continue
                values = frame.net_pct.to_numpy()
                record = {"strategy": strategy, "universe": universe, "split": split, "group": group,
                    "n": len(frame), "days": int((frame.time_ms // DAY).nunique()),
                    "symbols": int(frame.symbol.nunique()), "mean_pct": float(values.mean()),
                    "median_pct": float(np.median(values)), "positive_pct": float(np.mean(values>0)*100),
                    "gross_mean_pct": float(frame.gross_pct.mean()),
                    "mean_ci95": block_interval(frame, values)}
                for target in (2, 3):
                    column = f"tp{target}_touch"
                    available = frame[column].dropna() if column in frame else pd.Series(dtype=float)
                    record[f"tp{target}_touch_n"] = int(len(available))
                    record[f"tp{target}_touch_pct"] = (
                        float(available.astype(bool).mean() * 100)
                        if len(available) else None)
                column = "base_subtype" if group.startswith("bull_") else "base_regime"
                if column in frame and frame[column].notna().all():
                    edge = values - frame[column].to_numpy()
                    record.update(baseline_pct=float(frame[column].mean()), edge_pct=float(edge.mean()),
                                  edge_ci95=block_interval(frame, edge))
                if strategy == "G2":
                    record["outcomes"] = dict(Counter(frame.outcome))
                    record["target_pct"] = float((frame.outcome == "TARGET").mean()*100)
                result.append(record)
    return result


def recent_window_summaries(events, strategy="G1_PROXY",
                            windows=(30, 60, 90, 180, 365)):
    """Descriptive trailing-window touch rates, anchored to that strategy's data."""
    frame = pd.DataFrame([row for row in events if row.get("strategy") == strategy])
    if frame.empty:
        return {}
    end = int(frame.time_ms.max())
    result = {}
    for days in windows:
        subset = frame[frame.time_ms >= end - days * DAY]
        if subset.empty:
            continue
        result[str(days)] = {
            "strategy": strategy,
            "window_days": days,
            "anchor_time_ms": end,
            "start_time_ms": int(subset.time_ms.min()),
            "n": int(len(subset)),
            "independent_days": int((subset.time_ms // DAY).nunique()),
            "tp2_touch_n": int(subset.tp2_touch.notna().sum()),
            "tp2_touch_pct": float(subset.tp2_touch.mean() * 100),
            "tp3_touch_n": int(subset.tp3_touch.notna().sum()),
            "tp3_touch_pct": float(subset.tp3_touch.mean() * 100),
            "mean_time_exit_pct": float(subset.net_pct.mean()),
            "positive_time_exit_pct": float((subset.net_pct > 0).mean() * 100),
        }
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fetch-daily", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--data", type=Path)
    parser.add_argument("--funding", type=Path)
    parser.add_argument("--bot", type=Path, default=ROOT / "tmp/tablet-release/signal_bot.py")
    parser.add_argument("--search", type=Path, default=ROOT / "research/data/coinalyze/search-2026-09-14")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    daily_file = args.output / "btc_spot_daily.json"
    if args.fetch_daily:
        fetch_daily(daily_file)
        print(f"daily saved: {sha(daily_file)}")
        return
    table = daily_table(json.loads(daily_file.read_text(encoding="utf-8")))
    # The newly fetched daily series must agree with the archived hourly source.
    btc = load_hourly(args.data / "spot/BTCUSDT.parquet")
    btc["day"] = btc.open_time // DAY
    hourly_daily = btc.groupby("day").agg(close=("close", "last"), n=("close", "count"))
    raw_daily = json.loads(daily_file.read_text(encoding="utf-8"))
    daily_map = {r[0]//DAY: float(r[4]) for r in raw_daily["rows"]}
    diffs = [abs(r.close-daily_map[day]) for day, r in hourly_daily.iterrows() if r.n == 24]
    if not diffs or max(diffs) > .011:
        raise ValueError("daily_hourly_source_mismatch")
    events, audit = core_events(args.data, args.funding, args.bot, table)
    events += g1_proxy(args.data, table)
    events += g2_events(args.search, table)
    report = {"protocol_sha256": sha(Path(__file__).with_name("MARKET_REGIME_PROTOCOL_2026-09-22.md")),
              "code_sha256": sha(__file__), "daily_sha256": sha(daily_file),
              "bot_sha256": sha(args.bot), "engine_sha256": sha(ROOT / "strategy_engine.py"),
              "g2_source_sha256": {f: sha(args.search/f) for f in ("search_outcomes.jsonl", "confirm_outcomes.jsonl")},
              "daily_hourly_check": {"days": len(diffs), "max_price_difference": max(diffs)},
              "version": VERSION, "audit": audit, "summaries": summaries(events),
              "recent_windows": recent_window_summaries(events)}
    with (args.output / "events.jsonl").open("w", encoding="utf-8") as stream:
        for r in events:
            stream.write(json.dumps(r, ensure_ascii=False, allow_nan=False) + "\n")
    table.to_json(args.output / "daily_regimes.json", orient="records", indent=2)
    report["events_sha256"] = sha(args.output / "events.jsonl")
    write(args.output / "results.json", report)
    print(f"completed {len(events)} measured events; parity windows={sum(s['parity_windows'] for s in audit['symbols'])}", flush=True)


if __name__ == "__main__":
    main()
