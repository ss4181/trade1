"""S2 long/short ön-kayıtlı çalışmasının ortak, test edilebilir parçaları."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

try:  # Hem ``python research/x.py`` hem ``python -m unittest`` için.
    from .common import TRAIN_END
    from .strategies import s2_events
except ImportError:  # pragma: no cover - doğrudan script çalıştırma yolu
    from common import TRAIN_END
    from strategies import s2_events

STUDY_ID = "S2-LS-v1"
START = pd.Timestamp("2024-07-01T00:00:00Z")
END_EXCLUSIVE = pd.Timestamp("2026-07-01T00:00:00Z")
THRESHOLD_PCT = -0.03
PERSISTENCE = 2
COOLDOWN_HOURS = 24
HORIZON_HOURS = 72
LONG_SHORT_MAX = 1.0
MAX_METRIC_AGE = pd.Timedelta(minutes=15)
ROUND_TRIP_COST_PCT = 0.12
BOOTSTRAP_ITERATIONS = 5000


def prereg_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_core_symbols(root: Path) -> list[str]:
    manifest = json.loads((root / "manifest_spot89.json").read_text(
        encoding="utf-8"))
    return manifest["symbols"][:30]


def load_funding(path: Path, symbols: list[str]) -> dict[str, pd.DataFrame]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    out = {}
    for symbol in symbols:
        rows = raw.get(symbol, [])
        out[symbol] = pd.DataFrame(
            rows, columns=["calc_time", "last_funding_rate"])
    return out


def build_events(funding: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Canlı/araştırma S2 koşulunu değiştirmeden kanonik olay tablosu."""
    generated = s2_events(
        funding, THRESHOLD_PCT, PERSISTENCE, COOLDOWN_HOURS)
    rows = []
    for symbol in sorted(generated):
        times, directions = generated[symbol]
        for stamp, direction in zip(times, directions):
            stamp = pd.Timestamp(stamp)
            if START <= stamp < END_EXCLUSIVE:
                rows.append({"symbol": symbol, "event_time": stamp,
                             "direction": int(direction)})
    if not rows:
        return pd.DataFrame(columns=["symbol", "event_time", "direction"])
    return pd.DataFrame(rows).sort_values(
        ["event_time", "symbol"]).reset_index(drop=True)


def required_metric_days(events: pd.DataFrame) -> dict[str, list[str]]:
    """00:00 olaylarının önceki 23:55 kaydı için bir önceki günü de ister."""
    wanted = {}
    for symbol, group in events.groupby("symbol"):
        days = set()
        for stamp in group["event_time"]:
            day = pd.Timestamp(stamp).floor("D")
            days.add(day.strftime("%Y-%m-%d"))
            days.add((day - pd.Timedelta(days=1)).strftime("%Y-%m-%d"))
        wanted[symbol] = sorted(days)
    return wanted


def attach_long_short(events: pd.DataFrame,
                      metrics: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Yalnız olaydan önceki ölçümü as-of eşleştirir; gelecek satır kullanmaz."""
    chunks = []
    for symbol, group in events.groupby("symbol", sort=True):
        left = group.sort_values("event_time").copy()
        # Pandas merge_asof aynı zaman birimini ister; funding cache ms,
        # parquet okuyucusu ise ns hassasiyeti döndürebilir.
        left["event_time"] = pd.to_datetime(
            left["event_time"], utc=True).astype("datetime64[ns, UTC]")
        frame = metrics.get(symbol)
        if frame is None or frame.empty:
            left["metric_time"] = pd.NaT
            left["long_short_ratio"] = np.nan
            left["metric_age_minutes"] = np.nan
            chunks.append(left)
            continue
        right = frame[["create_time", "count_long_short_ratio"]].copy()
        right["create_time"] = pd.to_datetime(
            right["create_time"], utc=True).astype("datetime64[ns, UTC]")
        right["count_long_short_ratio"] = pd.to_numeric(
            right["count_long_short_ratio"], errors="coerce")
        right = right.dropna().sort_values("create_time").drop_duplicates(
            "create_time", keep="last")
        joined = pd.merge_asof(
            left, right, left_on="event_time", right_on="create_time",
            direction="backward", allow_exact_matches=False,
            tolerance=MAX_METRIC_AGE)
        joined = joined.rename(columns={
            "create_time": "metric_time",
            "count_long_short_ratio": "long_short_ratio",
        })
        joined["metric_age_minutes"] = (
            joined["event_time"] - joined["metric_time"]
        ).dt.total_seconds() / 60
        chunks.append(joined)
    if not chunks:
        return events.copy()
    return pd.concat(chunks, ignore_index=True).sort_values(
        ["event_time", "symbol"]).reset_index(drop=True)


def attach_derivatives_features(
        events: pd.DataFrame, metrics: dict[str, pd.DataFrame],
        funding: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """OI/pozisyon/hesap/funding özelliklerini yalnız geçmişten eşleştirir."""
    columns = ["sum_open_interest", "count_long_short_ratio",
               "sum_toptrader_long_short_ratio"]
    chunks = []
    for symbol, group in events.groupby("symbol", sort=True):
        left = group.sort_values("event_time").copy()
        left["event_time"] = pd.to_datetime(
            left["event_time"], utc=True).astype("datetime64[ns, UTC]")
        frame = metrics.get(symbol)
        if frame is None or frame.empty or not set(columns).issubset(frame):
            for name in ("open_interest", "global_ls", "top_position_ls",
                         "open_interest_lag8h", "global_ls_lag8h"):
                left[name] = np.nan
        else:
            right = frame[["create_time", *columns]].copy()
            right["create_time"] = pd.to_datetime(
                right["create_time"], utc=True).astype("datetime64[ns, UTC]")
            for column in columns:
                right[column] = pd.to_numeric(
                    right[column], errors="coerce").replace(
                        [np.inf, -np.inf], np.nan)
            right = right.sort_values("create_time").drop_duplicates(
                "create_time", keep="last")
            current = pd.merge_asof(
                left[["event_time"]], right, left_on="event_time",
                right_on="create_time", direction="backward",
                allow_exact_matches=False, tolerance=MAX_METRIC_AGE)
            lag_targets = pd.DataFrame({
                "lag_target": left["event_time"] - pd.Timedelta(hours=8)})
            lagged = pd.merge_asof(
                lag_targets, right, left_on="lag_target",
                right_on="create_time", direction="backward",
                allow_exact_matches=False, tolerance=MAX_METRIC_AGE)
            left["metric_time"] = current["create_time"].to_numpy()
            left["open_interest"] = current["sum_open_interest"].to_numpy()
            left["global_ls"] = current["count_long_short_ratio"].to_numpy()
            left["top_position_ls"] = current[
                "sum_toptrader_long_short_ratio"].to_numpy()
            left["lag8h_metric_time"] = lagged["create_time"].to_numpy()
            left["open_interest_lag8h"] = lagged[
                "sum_open_interest"].to_numpy()
            left["global_ls_lag8h"] = lagged[
                "count_long_short_ratio"].to_numpy()
        left["oi_change_8h"] = (
            left["open_interest"] / left["open_interest_lag8h"] - 1)
        left["global_ls_change_8h"] = (
            left["global_ls"] / left["global_ls_lag8h"] - 1)

        fr = funding.get(symbol)
        if fr is None or fr.empty:
            left["funding_rate"] = np.nan
            left["funding_prev"] = np.nan
        else:
            f = fr[["calc_time", "last_funding_rate"]].copy()
            f["event_time"] = pd.to_datetime(
                f["calc_time"], unit="ms", utc=True).dt.floor("h").astype(
                    "datetime64[ns, UTC]")
            f["funding_rate"] = pd.to_numeric(
                f["last_funding_rate"], errors="coerce")
            f = f.sort_values("event_time").drop_duplicates(
                "event_time", keep="last")
            f["funding_prev"] = f["funding_rate"].shift(1)
            left = left.merge(
                f[["event_time", "funding_rate", "funding_prev"]],
                on="event_time", how="left", validate="many_to_one")
        left["funding_delta"] = left["funding_rate"] - left["funding_prev"]
        chunks.append(left)
    if not chunks:
        return events.copy()
    return pd.concat(chunks, ignore_index=True).sort_values(
        ["event_time", "symbol"]).reset_index(drop=True)


def attach_outcomes(events: pd.DataFrame, root: Path) -> pd.DataFrame:
    """Sonraki saat açılışı -> 72h kapanışı; fiyat uydurmaz."""
    chunks = []
    for symbol, group in events.groupby("symbol", sort=True):
        path = root / "um" / f"{symbol}.parquet"
        part = group.copy()
        if not path.exists():
            part["entry_price"] = np.nan
            part["exit_price"] = np.nan
            chunks.append(part)
            continue
        bars = pd.read_parquet(path, columns=["open_time", "open", "close"])
        bars["bar_time"] = pd.to_datetime(bars["open_time"], unit="ms",
                                           utc=True)
        bars = bars.set_index("bar_time").sort_index()
        entry_times = pd.DatetimeIndex(part["event_time"] + pd.Timedelta(
            hours=1))
        exit_times = pd.DatetimeIndex(part["event_time"] + pd.Timedelta(
            hours=HORIZON_HOURS))
        part["entry_price"] = pd.to_numeric(
            bars["open"].reindex(entry_times), errors="coerce").to_numpy()
        part["exit_price"] = pd.to_numeric(
            bars["close"].reindex(exit_times), errors="coerce").to_numpy()
        chunks.append(part)
    out = pd.concat(chunks, ignore_index=True) if chunks else events.copy()
    valid = ((out.get("entry_price", np.nan) > 0) &
             (out.get("exit_price", np.nan) > 0))
    out["gross_return_pct"] = np.where(
        valid, np.log(out["exit_price"] / out["entry_price"]) * 100, np.nan)
    out["net_return_pct"] = np.where(
        valid, out["gross_return_pct"] - ROUND_TRIP_COST_PCT, np.nan)
    ratio_column = ("long_short_ratio" if "long_short_ratio" in out else
                    "global_ls" if "global_ls" in out else None)
    out["ls_short_majority"] = (
        out[ratio_column] < LONG_SHORT_MAX if ratio_column else False)
    return out


def split_rows(events: pd.DataFrame, split: str) -> pd.DataFrame:
    if split == "train":
        mask = ((events["event_time"] < TRAIN_END) &
                (events["event_time"] + pd.Timedelta(
                    hours=HORIZON_HOURS) < TRAIN_END))
    elif split == "test":
        mask = events["event_time"] >= TRAIN_END
    else:
        raise ValueError(f"bilinmeyen split: {split}")
    return events.loc[mask].copy()


def summarize(rows: pd.DataFrame) -> dict:
    valid = rows.dropna(subset=["net_return_pct"])
    if valid.empty:
        return {"n": 0, "days": 0, "symbols": 0}
    values = valid["net_return_pct"]
    counts = valid["symbol"].value_counts()
    return {
        "n": int(len(valid)),
        "days": int(valid["event_time"].dt.floor("D").nunique()),
        "symbols": int(valid["symbol"].nunique()),
        "mean_net_pct": float(values.mean()),
        "median_net_pct": float(values.median()),
        "win_rate": float((values > 0).mean()),
        "q10_net_pct": float(values.quantile(.10)),
        "q90_net_pct": float(values.quantile(.90)),
        "top5_share": float(counts.head(5).sum() / len(valid)),
        "top_symbols": [
            {"symbol": str(symbol), "n": int(count)}
            for symbol, count in counts.head(5).items()
        ],
    }


def clustered_uplift_pvalue(filtered: pd.DataFrame, rejected: pd.DataFrame,
                            iterations: int = BOOTSTRAP_ITERATIONS,
                            seed: int = 20260902) -> tuple[float, float]:
    """UTC günü kümesiyle LS<1 eksi LS>=1 ortalama farkı ve tek taraflı p."""
    a = filtered.dropna(subset=["net_return_pct"]).copy()
    b = rejected.dropna(subset=["net_return_pct"]).copy()
    if a.empty or b.empty:
        return float("nan"), float("nan")
    a["day"] = a["event_time"].dt.floor("D")
    b["day"] = b["event_time"].dt.floor("D")
    days = np.array(sorted(set(a["day"]) | set(b["day"])))
    if not len(days):
        return float("nan"), float("nan")
    amap = {day: group["net_return_pct"].to_numpy()
            for day, group in a.groupby("day")}
    bmap = {day: group["net_return_pct"].to_numpy()
            for day, group in b.groupby("day")}
    rng = np.random.default_rng(seed)
    sims = []
    for _ in range(iterations):
        draw = rng.choice(days, size=len(days), replace=True)
        av = [amap[day] for day in draw if day in amap]
        bv = [bmap[day] for day in draw if day in bmap]
        if av and bv:
            sims.append(float(np.concatenate(av).mean() -
                              np.concatenate(bv).mean()))
    if not sims:
        return float("nan"), float("nan")
    actual = float(a["net_return_pct"].mean() -
                   b["net_return_pct"].mean())
    non_positive = sum(value <= 0 for value in sims)
    pvalue = (non_positive + 1) / (len(sims) + 1)
    return actual, float(pvalue)


def finite(value) -> bool:
    return isinstance(value, (int, float)) and math.isfinite(value)


def decision(split: str, coverage: float, filtered: dict, rejected: dict,
             uplift: float, pvalue: float) -> tuple[bool, list[str]]:
    reasons = []
    min_n, min_days = (50, 30) if split == "train" else (30, 20)
    checks = [
        (coverage >= .90, f"kapsam %{coverage * 100:.1f} < %90"),
        (filtered.get("n", 0) >= min_n,
         f"filtreli N={filtered.get('n', 0)} < {min_n}"),
        (filtered.get("days", 0) >= min_days,
         f"bağımsız gün={filtered.get('days', 0)} < {min_days}"),
        (filtered.get("symbols", 0) >= 8,
         f"sembol={filtered.get('symbols', 0)} < 8"),
        (filtered.get("mean_net_pct", -math.inf) > 0,
         "filtreli net ortalama pozitif değil"),
        (filtered.get("median_net_pct", -math.inf) > 0,
         "filtreli net medyan pozitif değil"),
        (filtered.get("win_rate", 0) >= .52,
         "filtreli isabet %52 altında"),
        (filtered.get("top5_share", 1) <= .70,
         "top-5 sembol payı %70 üzerinde"),
        (finite(pvalue) and pvalue <= .10,
         "gün-kümeli uplift p-değeri 0.10 üzerinde"),
    ]
    if split == "train":
        checks += [
            (finite(uplift) and uplift >= .25,
             "ortalama uplift +0.25 yüzde puanın altında"),
            (filtered.get("median_net_pct", -math.inf) >
             rejected.get("median_net_pct", math.inf),
             "filtreli medyan LS>=1 medyanından yüksek değil"),
        ]
    else:
        checks += [
            (finite(uplift) and uplift > 0,
             "test ortalama uplift pozitif değil"),
            (filtered.get("median_net_pct", -math.inf) >
             rejected.get("median_net_pct", math.inf),
             "test medyan uplift pozitif değil"),
            (filtered.get("q10_net_pct", -math.inf) >=
             rejected.get("q10_net_pct", math.inf) - 1.0,
             "filtreli q10 karşı gruptan >1 puan kötü"),
        ]
    for passed, reason in checks:
        if not passed:
            reasons.append(reason)
    return not reasons, reasons
