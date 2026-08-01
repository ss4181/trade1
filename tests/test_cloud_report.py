import json
from datetime import datetime, timezone
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cloud_report import build_payload


class CloudReportTests(unittest.TestCase):
    def test_builds_secret_free_runtime_summary(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            (root / ".bot_state.json").write_text(json.dumps({
                "prev_cond": {"S1|BTCUSDT": True},
                "last_fire": {},
                "recent": [{
                    "strategy": "S1",
                    "symbol": "BTCUSDT",
                    "direction": "LONG",
                    "note": "oversold bullish divergence",
                    "notified_at": "2026-08-01T18:00:00+00:00",
                    "push_allowed": True,
                }],
            }), encoding="utf-8")
            payload = build_payload(root, now=datetime(2026, 8, 1, 19, tzinfo=timezone.utc))
        self.assertEqual(payload["slug"], "trade1-scan")
        self.assertEqual(payload["health"], "healthy")
        self.assertEqual(payload["metrics"][0]["value"], "1")
        self.assertEqual(payload["events"][0]["title"], "S1 · BTCUSDT · LONG")
        self.assertNotIn("token", json.dumps(payload).lower())


if __name__ == "__main__":
    unittest.main()
