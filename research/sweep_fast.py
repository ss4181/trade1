"""5m scalping adaylari: F1/F2/F3 taramasi (ucret-modelli).

Aileler (onceden kayitli):
  F1 hacim-patlamasi momentum: log-hacim z(288) >= Z, yukari bar -> LONG.
     Birincil ufuk 30dk. Z grid: 3/4/5/6.
  F2 kaskad sicramasi: 30dk getiri <= -k*sigma30m VE hacim z >= 2 -> LONG.
     Birincil ufuk 60dk. k grid: 3/4/5.
  F3 kirilim devami: kapanis > onceki N-bar zirvesi VE hacim z >= zc -> LONG.
     Birincil ufuk 60dk. N in {144,288} x zc in {2,3}.

Maliyet: gidis-donus COST_RT=12bp (taker 2x5bp + spread ~2bp); stres 16bp.
Karar kurali (train): net ort > 0 VE net medyan > 0 VE gun-kumesi p<=0.05,
N>=300. Gecen aile test'e gider (tek atis, p<=0.10).

Kullanim: python sweep_fast.py <data_dir> <split>
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

from common import TRAIN_END, edge_trigger

HORIZONS = [1, 3, 6, 12, 24]          # bar (5dk) cinsinden: 5/15/30/60/120 dk
VOL_WINDOW = 288                       # 24 saatlik 5m bar
COST_RT = 0.0012
COST_STRESS = 0.0016
PRIMARY = {"F1": 6, "F2": 12, "F3": 12}


def build_enriched(data_dir: Path) -> Path:
    src = data_dir / "spot5m"
    dst = data_dir / "enriched5m"
    dst.mkdir(exist_ok=True)
    for f in sorted(src.glob("*.parquet")):
        out = dst / f.name
        if out.exists():
            continue
        df = pd.read_parquet(f)
        df["dt"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
        df = df.set_index("dt").sort_index()
        grid = pd.date_range(df.index[0], df.index[-1], freq="5min", tz="UTC")
        df = df.reindex(grid)
        c, o, v = df["close"], df["open"], df["volume"]
        df["logret"] = np.log(c).diff()
        df["sigma5m"] = df["logret"].rolling(VOL_WINDOW, min_periods=144).std()
        lv = np.log1p(v)
        mu = lv.rolling(VOL_WINDOW, min_periods=144).mean()
        sd = lv.rolling(VOL_WINDOW, min_periods=144).std()
        df["volz"] = (lv - mu) / sd
        df["ret6"] = np.log(c / c.shift(6))
        df["hi288"] = df["high"].rolling(288, min_periods=288).max().shift(1)
        df["hi144"] = df["high"].rolling(144, min_periods=144).max().shift(1)
        entry = o.shift(-1)
        for h in HORIZONS:
            df[f"fwd_{h}"] = np.log(c.shift(-h) / entry)
        keep = (["open", "close", "logret", "sigma5m", "volz", "ret6",
                 "hi288", "hi144"] + [f"fwd_{h}" for h in HORIZONS])
        df[keep].astype("float32").to_parquet(out)
        print(f"  enriched: {f.stem}", flush=True)
    return dst


def family_configs():
    cfgs = []
    for z in (3.0, 4.0, 5.0, 6.0):
        cfgs.append(("F1", f"z={z}", z))
    for k in (3.0, 4.0, 5.0):
        cfgs.append(("F2", f"k={k}", k))
    for n in (144, 288):
        for zc in (2.0, 3.0):
            cfgs.append(("F3", f"N={n},zc={zc}", (n, zc)))
    return cfgs


def events_for(df: pd.DataFrame, fam: str, param) -> pd.DatetimeIndex:
    if fam == "F1":
        cond = df["volz"] >= param
        t = edge_trigger(cond, 1)                      # 1 saat cooldown
        up = (df["close"] > df["open"]).reindex(t).fillna(False).to_numpy(bool)
        return t[up]
    if fam == "F2":
        sigma30 = df["sigma5m"] * np.sqrt(6)
        cond = (df["ret6"] <= -param * sigma30) & (df["volz"] >= 2.0)
        return edge_trigger(cond, 1)
    n, zc = param
    cond = (df["close"] > df[f"hi{n}"]) & (df["volz"] >= zc)
    return edge_trigger(cond, 1)


def main(data_dir: str, split: str):
    data_dir = Path(data_dir)
    dst = build_enriched(data_dir)
    files = sorted(dst.glob("*.parquet"))
    cfgs = family_configs()
    # olay getirilerini topla: cfg -> {h: [dizi], 'days': [gunler]}
    acc = {c[:2]: {h: [] for h in HORIZONS} | {"days": []} for c in cfgs}
    for f in files:
        df = pd.read_parquet(f)
        if split == "train":
            df = df[df.index < TRAIN_END]
        elif split == "test":
            df = df[df.index >= TRAIN_END]
        for fam, name, param in cfgs:
            t = events_for(df, fam, param)
            if len(t) == 0:
                continue
            sel = df.reindex(t)
            key = (fam, name)
            for h in HORIZONS:
                acc[key][h].append(sel[f"fwd_{h}"].to_numpy("float64"))
            acc[key]["days"].append(t.floor("D").to_numpy())
        del df
    rng = np.random.default_rng(7)
    rows = []
    for (fam, name), d in acc.items():
        if not d["days"]:
            continue
        days = np.concatenate(d["days"])
        row = {"family": fam, "config": name}
        for h in HORIZONS:
            x = np.concatenate(d[h])
            ok = ~np.isnan(x)
            x, dd = x[ok], days[ok]
            net = x - COST_RT
            row[f"N_{h}"] = len(x)
            row[f"gross_bp_{h}"] = round(x.mean() * 1e4, 1)
            row[f"net_bp_{h}"] = round(net.mean() * 1e4, 1)
            row[f"netmed_bp_{h}"] = round(np.median(net) * 1e4, 1)
            row[f"netwr_{h}"] = round((net > 0).mean(), 3)
            if h == PRIMARY[fam]:
                cm = pd.Series(net).groupby(dd).mean().to_numpy()
                sims = np.array([rng.choice(cm, len(cm)).mean()
                                 for _ in range(1000)])
                row["p_cluster"] = round(float((sims <= 0).mean()), 3)
                row["stress_bp"] = round((x - COST_STRESS).mean() * 1e4, 1)
        h0 = PRIMARY[fam]
        print(f"{fam} {name:12s} N={row[f'N_{h0}']:6d} "
              f"gross={row[f'gross_bp_{h0}']:+7.1f}bp "
              f"net={row[f'net_bp_{h0}']:+7.1f}bp "
              f"netmed={row[f'netmed_bp_{h0}']:+7.1f}bp "
              f"wr={row[f'netwr_{h0}']:.2f} p_cl={row.get('p_cluster')}",
              flush=True)
        rows.append(row)
    out = Path(__file__).parent / "results" / f"fast_sweep_{split}.csv"
    pd.DataFrame(rows).to_csv(out, index=False)
    print(f"yazildi: {out.name}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
