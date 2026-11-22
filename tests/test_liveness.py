"""Canlilik yardimcisi testleri — ag YOK."""

import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
import liveness  # noqa: E402

NOW = datetime(2026, 11, 22, 12, 0, tzinfo=timezone.utc)


class _Resp:
    def __init__(self, code):
        self.status_code = code


class PingTests(unittest.TestCase):
    def test_disabled_or_non_https_url_never_requests(self):
        calls = []
        for url in ("", "   ", "http://hc-ping.com/x", "ftp://x", "https://"):
            self.assertFalse(liveness.ping(url, session_get=lambda *a, **k: calls.append(a)))
        self.assertEqual(calls, [])
        self.assertFalse(liveness.ping_async(""))

    def test_success_and_http_error(self):
        seen = []
        ok = liveness.ping(" https://hc-ping.com/abc ",
                           session_get=lambda u, timeout: seen.append((u, timeout)) or _Resp(200))
        self.assertTrue(ok)
        self.assertEqual(seen, [("https://hc-ping.com/abc", liveness.PING_TIMEOUT_SECONDS)])
        self.assertFalse(liveness.ping("https://hc-ping.com/abc",
                                       session_get=lambda u, timeout: _Resp(500)))

    def test_exception_is_swallowed_and_url_not_logged(self):
        def boom(url, timeout):
            raise RuntimeError(f"failed {url}")
        import io
        from contextlib import redirect_stderr
        err = io.StringIO()
        with redirect_stderr(err):
            self.assertFalse(liveness.ping("https://hc-ping.com/secret-uuid", session_get=boom))
        self.assertNotIn("secret-uuid", err.getvalue())


class StateTests(unittest.TestCase):
    def test_round_trip_and_bad_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "s.json"
            self.assertIsNone(liveness.load_last_scan(path))
            liveness.save_last_scan(NOW, path)
            self.assertEqual(liveness.load_last_scan(path), NOW)
            path.write_text("{bozuk", encoding="utf-8")
            self.assertIsNone(liveness.load_last_scan(path))

    def test_uptime_reads_proc_format(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "uptime"
            path.write_text("4321.55 9999.0\n")
            self.assertEqual(liveness.device_uptime(path), timedelta(seconds=4321.55))
            self.assertIsNone(liveness.device_uptime(Path(tmp) / "yok"))


class RecoveryMessageTests(unittest.TestCase):
    def test_silent_on_first_install_and_short_restart(self):
        self.assertIsNone(liveness.recovery_message(None, NOW, None, 20))
        self.assertIsNone(liveness.recovery_message(NOW - timedelta(minutes=10), NOW, None, 20))

    def test_reboot_during_gap(self):
        msg = liveness.recovery_message(NOW - timedelta(hours=5, minutes=6), NOW,
                                        timedelta(minutes=3), 20)
        self.assertIn("Bot yeniden ayakta", msg)
        self.assertIn("5.1 saat", msg)
        self.assertIn("yeniden başlamış", msg)

    def test_bot_only_stopped(self):
        msg = liveness.recovery_message(NOW - timedelta(minutes=45), NOW,
                                        timedelta(days=3), 20)
        self.assertIn("45 dakika", msg)
        self.assertIn("yalnızca bot durmuştu", msg)

    def test_unknown_uptime_still_reports_gap(self):
        msg = liveness.recovery_message(NOW - timedelta(hours=3), NOW, None, 20)
        self.assertIn("3.0 saat", msg)
        self.assertNotIn("Cihaz", msg)


class BotIntegrationTests(unittest.TestCase):
    """signal_bot._note_liveness: tek seferlik bildirim + her turda ping/kayit."""

    def test_recovery_sent_once_then_only_ping_and_save(self):
        from unittest.mock import patch
        import signal_bot as bot
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "liveness.json"
            liveness.save_last_scan(NOW - timedelta(hours=5), state)
            sent, pings = [], []

            class _SyncThread:
                def __init__(self, target, args=(), **_):
                    self.target, self.args = target, args

                def start(self):
                    self.target(*self.args)

            with patch.object(liveness, "STATE_FILE", state), \
                 patch.object(liveness, "ping_async", lambda url: pings.append(url)), \
                 patch.object(liveness, "device_uptime", lambda: timedelta(minutes=2)), \
                 patch.object(bot, "HEARTBEAT_PING_URL", "https://hc-ping.com/t"), \
                 patch.object(bot, "_liveness_checked", False), \
                 patch.object(bot.threading, "Thread", _SyncThread), \
                 patch.object(bot, "_telegram_send_text", lambda text: sent.append(text)):
                bot._note_liveness(NOW)
                bot._note_liveness(NOW + timedelta(minutes=5))
            self.assertEqual(len(sent), 1)
            self.assertIn("5.0 saat", sent[0])
            self.assertEqual(pings, ["https://hc-ping.com/t"] * 2)
            self.assertEqual(liveness.load_last_scan(state), NOW + timedelta(minutes=5))


if __name__ == "__main__":
    unittest.main()
