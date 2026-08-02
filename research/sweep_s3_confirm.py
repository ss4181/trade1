"""S3 icin DESTEKLEYICI METRIK arastirmasi (onceden kayitli tasarim).

Soru: S3 (log-hacim z>=3.0 + yesil bar, 4h) sinyaline eklenecek ikinci bir
kosul, guvenilirligi artirir mi?

Aday destekleyiciler (hepsi mevcut ham kolonlardan; sizinti yok — hepsi
sinyal barinin KENDI verisi, gelecege bakmiyor):
  A) taker_buy_ratio = taker_buy_volume / volume
     Hacim patlamasi ALICI mi yoksa SATICI mi kaynakli? Momentum devami
     hipotezinin dogal teyidi.
  B) close_position = (close-low)/(high-low)  — bar govdesinin kapanis gucu
  C) trade_size_z: ortalama islem buyuklugu z-skoru (buyuk emirler mi,
     cok sayida kucuk emir mi)
  D) coin_specific: ayni saatte evrenin <=X%'i patladi mi (coin'e ozgu olay
     mi yoksa piyasa geneli mi)

PROTOKOL (sonuca gore degistirilmeyecek):
  - Tasarim/secim YALNIZ cekirdek-30 TRAIN (2024-07..2025-12) uzerinde.
  - Secim kurali: birincil ufuk 4h; net-edge (edge_voln) maks; kisitlar
    N>=150 ve p<=0.05 ve medyan(brut) > 12bp (ucret esigi).
  - Kazanan TEK atisla iki bagimsiz kumede dogrulanir:
      (1) cekirdek-30 TEST (2026H1)  — S3 icin daha once bakildi, zayif kanit
      (2) GENIS-59 tum donem         — S3 arastirmasinda HIC kullanilmadi,
          bu yuzden asil bagimsiz sinav budur.
  - Iki dogrulamadan en az biri anlamli degilse: EKLEME.
Kullanim: python sweep_s3_confirm.py <data_dir>
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))
import signal_bot as bot  # noqa: E402
from common import TRAIN_END, edge_trigger  # noqa: E402

CORE = {s.strip() for s in bot.DEFAULT_SYMBOLS.split(",") if s.strip()}
EXT = set(bot.EXTENDED_SET)
H = 4                       # birincil ufuk (S3 kanonik)
MIN_N, MAX_P, MIN_MED_BP = 150, 0.05, 12.0


def load(data_dir: Path, sym: str) -> pd.DataFrame:
    df = pd.read_parquet(data_dir / "spot" / f"{sym}.parquet")
    df["dt"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    d = df.set_index("dt").sort_index()
    grid = pd.date_range(d.index[0], d.index[-1], freq="h", tz="UTC")
    d = d.reindex(grid)
    c, o, h, l, v = (d["close"], d["open"], d["high"], d["low"], d["volume"])
    d["logret"] = np.log(c).diff()
    d["sigma"] = d["logret"].rolling(168, min_periods=100).std()
    lv = np.log1p(v)
    d["volz"] = (lv - lv.rolling(168, min_periods=84).mean()) / \
        lv.rolling(168, min_periods=84).std()
    # --- aday destekleyiciler ---
    d["taker_ratio"] = (d["taker_buy_volume"] / v).clip(0, 1)
    rng = (h - l).replace(0, np.nan)
    d["close_pos"] = ((c - l) / rng).clip(0, 1)
    avg_sz = v / d["count"].replace(0, np.nan)
    lsz = np.log1p(avg_sz)
    d["size_z"] = (lsz - lsz.rolling(168, min_periods=84).mean()) / \
        lsz.rolling(168, min_periods=84).std()
    entry = o.shift(-1)
    d["fwd"] = np.log(c.shift(-H) / entry)
    d["fwdn"] = d["fwd"] / (d["sigma"] * np.sqrt(H))
    return d


def base_events(d: pd.DataFrame) -> pd.DatetimeIndex:
    """Kanonik S3: hacim patlamasi (kenar+cooldown) sonra yesil-bar filtresi."""
    spike = pd.Series((d["volz"] >= bot.VOLUME_ZSCORE_THRESHOLD).to_numpy(),
                      index=d.index)
    t = edge_trigger(spike, bot.S3_COOLDOWN_HOURS)
    up = (d["close"] > d["open"]).reindex(t).fillna(False).to_numpy(bool)
    return t[up]


def evaluate(panel, evs, split, rng, n_iter=1000):
    ex, pools, counts, gross = [], [], [], []
    for sym, t in evs.items():
        d = panel[sym]
        if split == "train":
            m, sub = t < TRAIN_END, d[d.index < TRAIN_END]
        elif split == "test":
            m, sub = t >= TRAIN_END, d[d.index >= TRAIN_END]
        else:
            m, sub = np.ones(len(t), bool), d
        t = t[m]
        if len(t) == 0:
            continue
        sel = d.reindex(t)
        x = sel["fwdn"].dropna().to_numpy()
        g = sel["fwd"].dropna().to_numpy()
        pool = sub["fwdn"].dropna().to_numpy()
        if len(x) == 0 or len(pool) == 0:
            continue
        ex.append(x - pool.mean())
        pools.append(pool - pool.mean())
        counts.append(len(x))
        gross.append(g)
    if not ex:
        return None
    e = np.concatenate(ex)
    sims = np.empty(n_iter)
    for i in range(n_iter):
        tot = n = 0
        for p, c in zip(pools, counts):
            tot += rng.choice(p, c).sum()
            n += c
        sims[i] = tot / n
    g = np.concatenate(gross)
    return {"N": len(e), "edge": e.mean(),
            "p": float((np.count_nonzero(sims >= e.mean()) + 1) / (n_iter + 1)),
            "med_bp": float(np.median(g) * 1e4),
            "wr": float((g > 0).mean())}


def apply_filter(panel, base, kind, thr, spike_counts=None):
    out = {}
    for sym, t in base.items():
        if len(t) == 0:
            out[sym] = t
            continue
        d = panel[sym]
        sel = d.reindex(t)
        if kind == "none":
            keep = np.ones(len(t), bool)
        elif kind == "taker":
            keep = (sel["taker_ratio"] >= thr).fillna(False).to_numpy()
        elif kind == "closepos":
            keep = (sel["close_pos"] >= thr).fillna(False).to_numpy()
        elif kind == "sizez":
            keep = (sel["size_z"] >= thr).fillna(False).to_numpy()
        elif kind == "specific":
            cnt = np.array([spike_counts.get(ts, 99) for ts in t])
            keep = cnt <= thr
        else:
            raise ValueError(kind)
        out[sym] = t[keep]
    return out


def main(data_dir):
    data_dir = Path(data_dir)
    syms = sorted(p.stem for p in (data_dir / "spot").glob("*.parquet"))
    core = [s for s in syms if s in CORE]
    ext = [s for s in syms if s in EXT]
    print(f"panel: {len(core)} cekirdek + {len(ext)} genis = {len(syms)}\n",
          flush=True)
    panel = {s: load(data_dir, s) for s in syms}
    base = {s: base_events(panel[s]) for s in syms}
    # ayni saatte kac sembol patladi (piyasa-geneli tespiti)
    spike_counts = {}
    for s, t in base.items():
        for ts in t:
            spike_counts[ts] = spike_counts.get(ts, 0) + 1
    rng = np.random.default_rng(31)

    core_base = {s: base[s] for s in core}
    print("=== TRAIN (cekirdek-30) — aday taramasi ===")
    print(f"{'filtre':22s} {'N':>5s} {'edge':>7s} {'p':>6s} {'medyan':>8s} {'wr':>5s}")
    cands = [("none", None)]
    cands += [("taker", x) for x in (0.50, 0.55, 0.60, 0.65)]
    cands += [("closepos", x) for x in (0.5, 0.6, 0.7)]
    cands += [("sizez", x) for x in (0.5, 1.0, 1.5)]
    cands += [("specific", x) for x in (1, 2, 3)]
    best = None
    for kind, thr in cands:
        evs = apply_filter(panel, core_base, kind, thr, spike_counts)
        r = evaluate(panel, evs, "train", rng)
        if not r:
            continue
        label = f"{kind}" + ("" if thr is None else f" >= {thr}")
        star = ""
        if kind != "none" and r["N"] >= MIN_N and r["p"] <= MAX_P and \
                r["med_bp"] > MIN_MED_BP:
            star = "  <- kurali gecti"
            if best is None or r["edge"] > best[0]:
                best = (r["edge"], kind, thr)
        print(f"{label:22s} {r['N']:5d} {r['edge']:+7.3f} {r['p']:6.3f} "
              f"{r['med_bp']:+7.1f}bp {r['wr']:5.2f}{star}")

    if best is None:
        print("\nSONUC: hicbir aday TRAIN kurallarini gecemedi -> "
              "destekleyici metrik EKLENMEZ (test/genis kume yakilmadi).")
        return
    _, kind, thr = best
    print(f"\n=== KAZANAN: {kind} >= {thr} — bagimsiz dogrulama ===")
    evs_core = apply_filter(panel, core_base, kind, thr, spike_counts)
    r = evaluate(panel, evs_core, "test", rng)
    print(f"1) cekirdek-30 TEST (2026H1): N={r['N']} edge={r['edge']:+.3f} "
          f"p={r['p']:.3f} med={r['med_bp']:+.1f}bp wr={r['wr']:.2f}")
    ext_base = {s: base[s] for s in ext}
    evs_ext = apply_filter(panel, ext_base, kind, thr, spike_counts)
    r2 = evaluate(panel, evs_ext, "all", rng)
    print(f"2) GENIS-59 (tum donem, bagimsiz sembol kumesi): N={r2['N']} "
          f"edge={r2['edge']:+.3f} p={r2['p']:.3f} med={r2['med_bp']:+.1f}bp "
          f"wr={r2['wr']:.2f}")
    # ayni kumede filtresiz referans (karsilastirma icin)
    r3 = evaluate(panel, ext_base, "all", rng)
    print(f"   (genis-59 FILTRESIZ referans: N={r3['N']} edge={r3['edge']:+.3f} "
          f"p={r3['p']:.3f} med={r3['med_bp']:+.1f}bp wr={r3['wr']:.2f})")
    ok1 = r["p"] <= 0.10 and r["edge"] > 0
    ok2 = r2["p"] <= 0.05 and r2["edge"] > 0 and r2["edge"] > r3["edge"]
    print(f"\nKARAR: cekirdek-test {'GECTI' if ok1 else 'gecemedi'} | "
          f"genis-59 {'GECTI' if ok2 else 'gecemedi'} -> "
          f"{'EKLE' if (ok1 and ok2) else 'EKLEME'}")


if __name__ == "__main__":
    main(sys.argv[1])
