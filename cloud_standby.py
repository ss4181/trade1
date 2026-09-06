"""Read tablet heartbeat; cloud is a SILENT diagnostic standby, not another sender."""
import json
import os
from datetime import datetime, timezone
from urllib.request import urlopen


def decision(payload, now=None, max_age_minutes=60):
    now = now or datetime.now(timezone.utc)
    try:
        status = payload["status"]
        stamp = datetime.fromisoformat(status["last_scan"].replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            raise ValueError("naive_heartbeat")
        age = (now - stamp).total_seconds() / 60
        if 0 <= age <= max_age_minutes:
            return {"scan": False, "reason": "tablet_fresh", "notifications": False}
        return {"scan": True, "reason": "tablet_stale_or_future", "notifications": False}
    except (KeyError, TypeError, ValueError):
        return {"scan": True, "reason": "tablet_status_unknown", "notifications": False}


def main():
    repo = os.environ["GITHUB_REPOSITORY"]
    url = f"https://raw.githubusercontent.com/{repo}/trade1-data/data.json"
    try:
        with urlopen(url, timeout=20) as response:
            payload = json.loads(response.read(10_000_001))
    except Exception:
        payload = {}
    result = decision(payload)
    if os.environ.get("FORCE_SCAN") == "true":
        result.update(scan=True, reason="manual_silent_diagnostic")
    print(json.dumps(result))
    with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as stream:
        stream.write(f"scan={str(result['scan']).lower()}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
