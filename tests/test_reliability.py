"""Regression tests for approved reliability fixes; no real notifications/network."""
import io
import json
import sys
import tempfile
import unittest
from contextlib import ExitStack, redirect_stdout, redirect_stderr
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import signal_bot as bot
from notification_delivery import DeliveryOutbox
from signal_outcomes import hourly_outcome
from archive_backup import backup_once
from backup_verify import verify_backup, restore_rehearsal
from cloud_standby import decision
from research_monitor import build_research_readiness


class ReliabilityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.now = datetime(2026, 1, 1, tzinfo=timezone.utc)

    def tearDown(self):
        self.tmp.cleanup()

    def test_outcome_uses_timestamp_not_index(self):
        base = int(self.now.timestamp() * 1000)
        bars = [{"open_time": base + i * 3600000, "open": 100+i, "close": 110+i}
                for i in range(1, 6)]
        out = hourly_outcome(bars, base, 4)
        self.assertEqual(out["entry"], 101)
        self.assertEqual(out["exit"], 114)
        self.assertEqual(out["exit_time_ms"], base+5*3600000)
        self.assertAlmostEqual(hourly_outcome(bars, base, 4, "SHORT")["return_pct"], -out["return_pct"])
        with self.assertRaisesRegex(ValueError, "missing_required"):
            hourly_outcome(bars[:1]+bars[2:], base, 4)

    def test_outbox_retries_only_failed_recipient_after_restart(self):
        path = self.root / "outbox.json"
        box = DeliveryOutbox(path)
        box.enqueue({"event_id": "e", "price": 100}, ["a", "b"], self.now)
        calls = []
        def send(cid, _record):
            calls.append(cid)
            return cid == "a"
        box.deliver("e", send, self.now)
        self.assertEqual(box.get_public("e")["delivery_status"], "partial")
        box = DeliveryOutbox(path)
        box.deliver("e", lambda cid, record: calls.append(cid) or True, self.now+timedelta(minutes=2))
        self.assertEqual(calls, ["a", "b", "b"])
        self.assertEqual(box.get_public("e")["delivery_status"], "delivered")
        box.enqueue({"event_id": "e"}, ["a", "b"], self.now)
        self.assertEqual(len(box.items), 1)
        self.assertNotIn("recipients", box.get_public("e"))

    def test_outbox_expired_signal_is_not_sent_late(self):
        box = DeliveryOutbox(self.root / "outbox.json")
        box.enqueue({"event_id": "e"}, ["a"], self.now)
        result = box.deliver("e", lambda *a: self.fail("late send"), self.now+timedelta(minutes=16))
        self.assertEqual(result["delivery_status"], "failed")

    def test_failed_notify_is_not_backfilled_or_shown_as_sent(self):
        sig = {"strategy": "S1", "symbol": "BTCUSDT", "direction": "LONG",
               "strength": "NORMAL", "bar_time": datetime.now(timezone.utc).replace(
                   minute=0, second=0, microsecond=0).isoformat(),
               "price": 100, "horizon_hours": 24, "note": "test condition"}
        with ExitStack() as stack:
            for key, val in {"SIGNAL_LOG": str(self.root/"signals.log"),
                "PRICE_TARGET_STATE": {"events": {}},
                "PRICE_TARGET_STATE_FILE": self.root/"targets.json",
                "DELIVERY_OUTBOX": DeliveryOutbox(self.root/"outbox.json")}.items():
                stack.enter_context(patch.object(bot, key, val))
            stack.enter_context(patch.object(bot, "send_telegram_message", return_value=False))
            stack.enter_context(redirect_stdout(io.StringIO()))
            result = bot.notify(sig)
            self.assertFalse(result["delivery_confirmed"])
            self.assertEqual(bot._backfill_price_targets_from_signal_log(), 0)
            dashboard = bot.build_dashboard_data()
            self.assertEqual(dashboard["signals"][0]["notification_status"], "BASARISIZ")

    def test_once_failure_exits_nonzero(self):
        with ExitStack() as stack:
            for name in ("load_price_target_state", "_backfill_price_targets_from_signal_log",
                         "refresh_universe_if_due", "refresh_perp_map_if_due",
                         "refresh_observe_universe_if_due", "refresh_market_regime_if_due"):
                if hasattr(bot, name):
                    stack.enter_context(patch.object(bot, name))
            scan = stack.enter_context(patch.object(bot, "scan_all", side_effect=RuntimeError("synthetic outage")))
            stack.enter_context(patch.object(bot.ScanState, "load"))
            stack.enter_context(redirect_stdout(io.StringIO()))
            stack.enter_context(redirect_stderr(io.StringIO()))
            with self.assertRaises(SystemExit) as cm:
                bot._run_forever_locked(once=True)
            self.assertEqual(cm.exception.code, 1)
            scan.assert_called_once()

    def test_telegram_http_200_with_false_ok_is_not_delivery(self):
        with patch.object(bot, "ENABLE_TELEGRAM", True), patch.object(bot.requests, "post") as post, redirect_stderr(io.StringIO()):
            post.return_value.json.return_value = {"ok": False}
            self.assertFalse(bot._telegram_send_text("synthetic", chat_id="fake"))
            post.return_value.json.return_value = []
            self.assertFalse(bot._telegram_send_text("synthetic", chat_id="fake"))

    def make_backup(self):
        source = self.root / "source"
        dest = self.root / "backup"
        source.mkdir()
        (source/"market_archive_2026-01.jsonl").write_text('{}\n{"incomplete":', encoding="utf-8")
        (source/".env").write_text("SECRET=DO_NOT_COPY", encoding="utf-8")
        backup_once(source, dest)
        return dest

    def test_backup_hashes_restore_and_no_secrets(self):
        dest = self.make_backup()
        self.assertTrue(verify_backup(dest)["ok"])
        self.assertEqual((dest/"market_archive_2026-01.jsonl").read_text(), '{}\n')
        self.assertFalse((dest/".env").exists())
        self.assertTrue(restore_rehearsal(dest, self.root/"restore")["ok"])
        with self.assertRaises(ValueError):
            restore_rehearsal(dest, self.root/"restore")

    def test_backup_tamper_is_detected(self):
        dest = self.make_backup()
        (dest/"market_archive_2026-01.jsonl").write_text('{"tamper":1}\n')
        self.assertFalse(verify_backup(dest)["ok"])

    def test_backup_rejects_manifest_path_traversal(self):
        dest = self.make_backup()
        path = dest/"backup_manifest.json"
        manifest = json.loads(path.read_text())
        manifest["files"]["../.env"] = {"bytes": 0, "sha256": "x"}
        path.write_text(json.dumps(manifest))
        self.assertIn("unsafe_manifest_path", verify_backup(dest)["errors"])

    def test_cloud_is_silent_fresh_stale_unknown(self):
        self.assertFalse(decision({"status": {"last_scan": self.now.isoformat()}}, self.now)["scan"])
        for result in (decision({}, self.now), decision({"status": {"last_scan": self.now.isoformat()}}, self.now+timedelta(hours=2))):
            self.assertTrue(result["scan"])
            self.assertFalse(result["notifications"])

    def test_training_data_cannot_make_oos_quality_pass(self):
        row = {"schema_version": "market-context-v2", "t": self.now.isoformat(),
               "sym": "BTCUSDT", "oi": 100, "perp_px": 100, "basis": 0,
               "global_ls_ratio": 1, "taker_buy_sell_ratio": 1, "funding_rate_snapshot": 0}
        (self.root/"market_archive_2026-01.jsonl").write_text(json.dumps(row)+'\n')
        report = build_research_readiness(self.root, now=self.now+timedelta(days=200),
                                          oos_start_utc=(self.now+timedelta(days=100)).isoformat())
        self.assertEqual(report["market"]["rows"], 0)
        self.assertFalse(report["quality_ready"])
        self.assertEqual(report["quality_window"]["scope"], "oos_only")


if __name__ == "__main__":
    unittest.main()
