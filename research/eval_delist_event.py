"""DL1-PRE: resmî tam-token delist duyurusundan delist anına spot getiri.

DL1-POST burada test edilmez: geçmişte başka borsada short edilebilir kontratın
varlığını bugünkü ürün listesinden geriye yürütmek veri sızıntısı olur.
"""

from __future__ import annotations

import io
import json
import re
import sys
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import pandas as pd
import requests

LIST_URL = "https://www.binance.com/bapi/composite/v1/public/cms/article/list/query"
DETAIL_URL = "https://www.binance.com/bapi/composite/v1/public/cms/article/detail/query"
KLINE_BASE = "https://data.binance.vision/data/spot/monthly/klines"
TITLE_RE = re.compile(
    r"^Binance Will Delist (?P<tokens>.+?) on (?P<date>\d{4}-\d{2}-\d{2})$")
DEADLINE_RE = re.compile(r"(20\d{2}-\d{2}-\d{2})\s+(\d{2}:\d{2})\s*\(UTC\)")
CUTOFF = pd.Timestamp("2021-08-31", tz="UTC")
ROUND_TRIP_COST_PCT = 0.12


def _get_json(url: str, params: dict) -> dict:
    response = requests.get(url, params=params, timeout=45)
    response.raise_for_status()
    payload = response.json()
    if payload.get("code") != "000000" or not payload.get("success"):
        raise RuntimeError(f"Binance CMS hata kodu: {payload.get('code')}")
    return payload


def _texts(node) -> list[str]:
    if isinstance(node, dict):
        own = [str(node["text"])] if "text" in node else []
        return own + [text for value in node.values() for text in _texts(value)]
    if isinstance(node, list):
        return [text for value in node for text in _texts(value)]
    return []


def title_tokens(title: str) -> list[str]:
    match = TITLE_RE.fullmatch(title.strip())
    if not match:
        return []
    raw = re.sub(r"\s+(?:and|&)\s+", ",", match.group("tokens"),
                 flags=re.IGNORECASE)
    return [token.strip().upper() for token in raw.split(",")
            if re.fullmatch(r"[A-Z0-9]{2,15}", token.strip().upper())]


def announcements() -> list[dict]:
    page_size = 20
    first = _get_json(LIST_URL, {"type": 1, "catalogId": 161,
                                 "pageNo": 1, "pageSize": page_size})
    catalog = first["data"]["catalogs"][0]
    articles = list(catalog.get("articles", []))
    pages = (int(catalog["total"]) + page_size - 1) // page_size
    for page in range(2, pages + 1):
        payload = _get_json(LIST_URL, {"type": 1, "catalogId": 161,
                                       "pageNo": page,
                                       "pageSize": page_size})
        articles.extend(payload["data"]["catalogs"][0].get("articles", []))
    selected = []
    for article in articles:
        released = pd.to_datetime(article["releaseDate"], unit="ms", utc=True)
        tokens = title_tokens(article.get("title", ""))
        if released >= CUTOFF and tokens:
            selected.append({**article, "released_at": released,
                             "tokens": tokens})
    return selected


def enrich_article(article: dict) -> dict:
    payload = _get_json(DETAIL_URL, {"articleCode": article["code"]})
    data = payload["data"]
    try:
        body = json.loads(data.get("body") or "{}")
    except json.JSONDecodeError:
        body = {}
    text = " ".join(_texts(body)).replace("&nbsp;", " ")
    phrase = "delist and cease trading on all spot trading pairs"
    tail = text[text.lower().find(phrase):] if phrase in text.lower() else text
    deadline = DEADLINE_RE.search(tail)
    return {
        "code": article["code"], "title": article["title"],
        "released_at": article["released_at"].isoformat(),
        "tokens": article["tokens"],
        "delist_at": (pd.Timestamp(f"{deadline.group(1)} {deadline.group(2)}",
                                   tz="UTC").isoformat() if deadline else None),
    }


def load_events(cache_path: Path) -> list[dict]:
    if cache_path.exists():
        return json.loads(cache_path.read_text(encoding="utf-8"))
    base = announcements()
    events = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(enrich_article, article): article["code"]
                   for article in base}
        for future in as_completed(futures):
            events.append(future.result())
    events.sort(key=lambda row: (row["released_at"], row["code"]))
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(events, ensure_ascii=False, indent=2),
                          encoding="utf-8")
    return events


def _months(start: pd.Timestamp, end: pd.Timestamp) -> list[str]:
    return pd.period_range(start.tz_localize(None).to_period("M"),
                           end.tz_localize(None).to_period("M"),
                           freq="M").strftime("%Y-%m").tolist()


def fetch_month(symbol: str, month: str) -> pd.DataFrame:
    url = f"{KLINE_BASE}/{symbol}/1h/{symbol}-1h-{month}.zip"
    response = requests.get(url, timeout=60)
    if response.status_code == 404:
        return pd.DataFrame()
    response.raise_for_status()
    archive = zipfile.ZipFile(io.BytesIO(response.content))
    if archive.testzip() is not None:
        raise zipfile.BadZipFile(f"CRC hatası: {symbol} {month}")
    with archive.open(archive.namelist()[0]) as stream:
        frame = pd.read_csv(stream, header=None)
    if frame.shape[1] < 7:
        raise ValueError(f"kline kolonları eksik: {symbol} {month}")
    frame = frame.iloc[:, :7]
    frame.columns = ["open_time", "open", "high", "low", "close", "volume",
                     "close_time"]
    divisor = 1_000_000 if float(frame["open_time"].iloc[0]) > 1e14 else 1_000
    frame["open_dt"] = pd.to_datetime(frame["open_time"] / divisor,
                                       unit="s", utc=True)
    frame["close_dt"] = pd.to_datetime(frame["close_time"] / divisor,
                                        unit="s", utc=True)
    for col in ("open", "high", "low", "close"):
        frame[col] = pd.to_numeric(frame[col], errors="coerce")
    return frame


def evaluate_token(event: dict, token: str) -> dict:
    released = pd.Timestamp(event["released_at"])
    deadline = pd.Timestamp(event["delist_at"]) if event["delist_at"] else None
    base = {"article_code": event["code"], "token": token,
            "symbol": f"{token}USDT", "released_at": event["released_at"],
            "delist_at": event["delist_at"]}
    if deadline is None:
        return {**base, "status": "unavailable", "reason": "deadline_parse"}
    if deadline > pd.Timestamp.now(tz="UTC"):
        return {**base, "status": "pending", "reason": "not_delisted"}
    frames = [fetch_month(base["symbol"], month)
              for month in _months(released, deadline)]
    frames = [frame for frame in frames if not frame.empty]
    if not frames:
        return {**base, "status": "unavailable", "reason": "no_usdt_archive"}
    frame = pd.concat(frames, ignore_index=True).sort_values("open_dt")
    entries = frame.loc[frame["open_dt"] >= released]
    exits = frame.loc[frame["close_dt"] < deadline]
    if entries.empty or exits.empty:
        return {**base, "status": "unavailable", "reason": "no_valid_bars"}
    entry_row, exit_row = entries.iloc[0], exits.iloc[-1]
    if entry_row["open_dt"] > exit_row["open_dt"]:
        return {**base, "status": "unavailable", "reason": "bad_window"}
    window = frame.loc[(frame["open_dt"] >= entry_row["open_dt"]) &
                       (frame["open_dt"] <= exit_row["open_dt"])]
    entry, exit_price = float(entry_row["open"]), float(exit_row["close"])
    gross = (exit_price / entry - 1) * 100
    return {**base, "status": "matured", "reason": None,
            "entry_time": entry_row["open_dt"].isoformat(),
            "entry_price": entry, "exit_time": exit_row["close_dt"].isoformat(),
            "exit_price": exit_price, "gross_pct": gross,
            "net_pct": gross - ROUND_TRIP_COST_PCT,
            "mfe_pct": (float(window["high"].max()) / entry - 1) * 100,
            "mae_pct": (float(window["low"].min()) / entry - 1) * 100}


def sign_flip_pvalue(frame: pd.DataFrame, iterations: int = 8000,
                     seed: int = 831) -> float:
    values = frame["net_pct"].to_numpy(float)
    days = pd.to_datetime(frame["released_at"], utc=True).dt.floor("D")
    groups = [np.flatnonzero(days.to_numpy() == day)
              for day in days.drop_duplicates().to_numpy()]
    actual = float(values.mean())
    rng = np.random.default_rng(seed)
    exceed = 0
    for _ in range(iterations):
        simulated = values.copy()
        for idx, sign in zip(groups, rng.choice((-1.0, 1.0), len(groups))):
            simulated[idx] *= sign
        exceed += simulated.mean() >= actual
    return (exceed + 1) / (iterations + 1)


def main(data_dir: str) -> int:
    root = Path(data_dir)
    events = load_events(root / "delist" / "announcements_5y.json")
    rows = []
    jobs = [(event, token) for event in events for token in event["tokens"]]
    print(f"DL1-PRE: {len(events)} tam-token makale · {len(jobs)} token", flush=True)
    with ThreadPoolExecutor(max_workers=12) as pool:
        futures = {pool.submit(evaluate_token, event, token): (event, token)
                   for event, token in jobs}
        for done, future in enumerate(as_completed(futures), 1):
            rows.append(future.result())
            if done % 20 == 0:
                print(f"fiyat {done}/{len(jobs)}", flush=True)
    frame = pd.DataFrame(rows).sort_values(["released_at", "token"])
    matured = frame.loc[frame["status"] == "matured"].copy()
    pending = int((frame["status"] == "pending").sum())
    unavailable = frame.loc[frame["status"] == "unavailable", "reason"].value_counts()
    print(f"olgun N={len(matured)} token={matured['token'].nunique()} "
          f"pending={pending} unavailable={int(unavailable.sum())}")
    if not unavailable.empty:
        print("unavailable: " + ", ".join(f"{k}={v}" for k, v in unavailable.items()))
    if matured.empty:
        print("KARAR: YETERSİZ — ölçülebilir olgun olay yok.")
        return 2
    values = matured["net_pct"]
    pvalue = sign_flip_pvalue(matured)
    print(f"net ort={values.mean():+.3f}% med={values.median():+.3f}% "
          f"WR={(values > 0).mean():.1%} q10={values.quantile(.1):+.2f}% "
          f"q90={values.quantile(.9):+.2f}% p(day)={pvalue:.4f} "
          f"MFE-med={matured['mfe_pct'].median():+.2f}% "
          f"MAE-med={matured['mae_pct'].median():+.2f}%")
    passed = (len(matured) >= 30 and matured["token"].nunique() >= 20 and
              values.mean() > 0 and values.median() > 0 and
              (values > 0).mean() >= .52 and pvalue <= .05)
    print("KARAR: " + ("KABUL — DL1-PRE ön-kayıt kapısı geçti."
                       if passed else "RED — DL1-PRE ön-kayıt kapısı geçilmedi."))
    print("DL1-POST: TEST EDİLMEDİ — geçmiş point-in-time harici kontrat "
          "bulunabilirliği yok; prospektif arşiv gerekir.")
    return 0 if passed else 3


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else "data"))
