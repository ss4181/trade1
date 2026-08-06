"""Delta-nötr carry araştırması için 89 sembolün USD-M perp 1h verisi.

Kaynak yalnız resmî Binance toplu arşividir:
  data.binance.vision/data/futures/um/monthly/klines

Spot verisini ve funding önbelleğini yeniden indirmez. Spot sembolü ile
1000-kontrat eşleşmesini canlı exchangeInfo'dan kurar; çıktı dosyasını spot
sembol adıyla yazar ve gerçek perp adını manifestte saklar.

Kullanım: python download_um89.py data
"""

from __future__ import annotations

import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd
import requests

from download_data import MONTHS, job

FAPI = "https://fapi.binance.com"


def contract_map(symbols: list[str]) -> dict[str, str]:
    response = requests.get(f"{FAPI}/fapi/v1/exchangeInfo", timeout=45)
    response.raise_for_status()
    active = {
        row["symbol"] for row in response.json().get("symbols", [])
        if row.get("contractType") == "PERPETUAL"
        and row.get("quoteAsset") == "USDT"
    }
    result = {}
    for symbol in symbols:
        if symbol in active:
            result[symbol] = symbol
        elif f"1000{symbol}" in active:
            result[symbol] = f"1000{symbol}"
        elif f"1000000{symbol}" in active:
            result[symbol] = f"1000000{symbol}"
    return result


def main(data_dir: str) -> int:
    root = Path(data_dir)
    source_manifest = json.loads((root / "manifest_spot89.json").read_text(
        encoding="utf-8"))
    symbols = source_manifest["symbols"]
    mapping = contract_map(symbols)
    out = root / "um"
    out.mkdir(parents=True, exist_ok=True)

    missing_contract = sorted(set(symbols) - set(mapping))
    tasks = [(symbol, mapping[symbol], month)
             for symbol in symbols if symbol in mapping for month in MONTHS]
    results: dict[str, dict[str, pd.DataFrame]] = {}
    missing_months: dict[str, list[str]] = {}
    failures: dict[str, str] = {}
    print(f"USD-M 1h: {len(mapping)}/{len(symbols)} kontrat · "
          f"{len(tasks)} aylik dosya", flush=True)

    with ThreadPoolExecutor(max_workers=12) as pool:
        futures = {
            pool.submit(job, "um", perp, month): (symbol, perp, month)
            for symbol, perp, month in tasks
        }
        for done, future in enumerate(as_completed(futures), 1):
            symbol, _perp, month = futures[future]
            try:
                _kind, _name, _month, frame = future.result()
            except Exception as exc:  # ağ hatası manifestte görünür; veri uydurulmaz
                failures[f"{symbol}/{month}"] = (
                    f"{type(exc).__name__}: {exc}")
                continue
            if frame is None:
                missing_months.setdefault(symbol, []).append(month)
            else:
                results.setdefault(symbol, {})[month] = frame
            if done % 250 == 0:
                print(f"progress: {done}/{len(tasks)}", flush=True)

    written = []
    for symbol, monthly in sorted(results.items()):
        if not monthly:
            continue
        frame = pd.concat([monthly[m] for m in sorted(monthly)],
                          ignore_index=True)
        frame = frame.sort_values("open_time").drop_duplicates("open_time")
        frame.to_parquet(out / f"{symbol}.parquet", index=False)
        written.append(symbol)

    manifest = {
        "source": "data.binance.vision futures/um/monthly/klines 1h",
        "months": MONTHS,
        "symbols_requested": symbols,
        "contract_map": mapping,
        "symbols_written": written,
        "missing_contract": missing_contract,
        "missing_months": {k: sorted(v) for k, v in missing_months.items()},
        "failures": failures,
    }
    (root / "manifest_um89.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"bitti: {len(written)} seri · kontratsiz {len(missing_contract)} · "
          f"eksik-ayli {len(missing_months)} · ag-hatasi {len(failures)}",
          flush=True)
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else "data"))
