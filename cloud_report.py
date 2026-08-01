"""Post a small, secret-free Trade1 runtime summary to Serhan Lab."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def _read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    return value if isinstance(value, dict) else {}


def _as_utc(value: object) -> datetime | None:
    try:
        text = str(value).replace("Z", "+00:00")
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def build_payload(
    root: Path,
    *,
    failed: bool = False,
    now: datetime | None = None,
) -> dict[str, object]:
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    state = _read_json(root / ".bot_state.json")
    recent = [item for item in state.get("recent", []) if isinstance(item, dict)]
    cutoff = now - timedelta(hours=24)
    recent_24h = sum(
        1 for item in recent
        if (stamp := _as_utc(item.get("notified_at") or item.get("bar_time")))
        and stamp >= cutoff
    )
    events = []
    for item in recent[:5]:
        strategy = str(item.get("strategy") or "Sinyal")
        symbol = str(item.get("symbol") or "?")
        direction = str(item.get("direction") or "?")
        events.append({
            "title": f"{strategy} · {symbol} · {direction}",
            "detail": str(item.get("note") or "Kenar-tetiklemeli sinyal"),
            "time": str(item.get("notified_at") or item.get("bar_time") or now.isoformat()),
            "tone": "signal" if item.get("push_allowed", True) else "muted",
        })
    run_url = ""
    if os.environ.get("GITHUB_SERVER_URL") and os.environ.get("GITHUB_REPOSITORY") and os.environ.get("GITHUB_RUN_ID"):
        run_url = (
            f"{os.environ['GITHUB_SERVER_URL']}/{os.environ['GITHUB_REPOSITORY']}"
            f"/actions/runs/{os.environ['GITHUB_RUN_ID']}"
        )
    telegram_ready = bool(os.environ.get("TELEGRAM_BOT_TOKEN", "").strip() and os.environ.get("TELEGRAM_CHAT_ID", "").strip())
    return {
        "slug": "trade1-scan",
        "status": "Bulut taraması başarısız" if failed else "Bulut taraması tamamlandı",
        "health": "attention" if failed else "healthy",
        "detail": (
            "Son GitHub Actions taraması hata verdi; ayrıntı için koşu kaydını açın."
            if failed else
            "S1/S2/S3/S4 taraması bulutta tamamlandı; kenar-tetikleme ve cooldown durumu sonraki koşuya taşındı."
        ),
        "observedAtUtc": now.isoformat().replace("+00:00", "Z"),
        "component": "89 coin kripto tarayıcı",
        "mode": "Uyarı · emir üretmez",
        "schedule": "Yaklaşık 5 dakikada bir",
        "runUrl": run_url,
        "facts": ["1 saatlik mum", "S1/S2/S3/S4", "Durum korumalı"],
        "metrics": [
            {"label": "İzlenen koşul", "value": str(len(state.get("prev_cond", {})))},
            {"label": "Son 24 saat", "value": f"{recent_24h} sinyal"},
            {"label": "Telegram", "value": "Bağlı" if telegram_ready else "Gizli anahtar bekliyor"},
        ],
        "events": events,
    }


def post_payload(payload: dict[str, object]) -> bool:
    endpoint = os.environ.get("PROJECT_HUB_INGEST_URL", "").strip()
    token = os.environ.get("PROJECT_HUB_INGEST_TOKEN", "").strip()
    if not endpoint or not token:
        print("Serhan Lab bağlantısı tanımlı değil; rapor atlandı.")
        return False
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "User-Agent": "trade1-cloud/1.0",
    }
    bypass = os.environ.get("OAI_SITES_BYPASS_TOKEN", "").strip()
    if bypass:
        headers["OAI-Sites-Authorization"] = f"Bearer {bypass}"
    request = Request(
        endpoint,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urlopen(request, timeout=20) as response:
            if response.status not in (200, 201, 202, 204):
                raise RuntimeError(f"Serhan Lab HTTP {response.status}")
    except (HTTPError, URLError, TimeoutError, OSError) as error:
        raise RuntimeError("Serhan Lab durum raporu gönderilemedi") from error
    print("Serhan Lab proje durumu güncellendi.")
    return True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--failed", action="store_true")
    args = parser.parse_args()
    post_payload(build_payload(Path(__file__).parent, failed=args.failed))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
