"""Synthetic scheduling/delivery regression tests; no live bot or network."""
import io
import json
import sys
import tempfile
import threading
import unittest
from contextlib import ExitStack, redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import notification_delivery as delivery
import signal_bot as bot


class NotificationLatencyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "outbox.json"
        self.box = delivery.DeliveryOutbox(self.path)
        self.now = datetime(2026, 9, 11, 12, tzinfo=timezone.utc)

    def tearDown(self):
        self.tmp.cleanup()

    def test_next_scan_keeps_five_minute_grid_and_does_not_skip_pending_slot(self):
        with patch.object(bot, "SCAN_INTERVAL_MINUTES", 5), patch.object(bot, "SCAN_CLOSE_DELAY_SECONDS", 10):
            for now, expected in ((0, 10), (9, 1), (10, 300), (100, 210), (299, 11), (305, 5), (680, 230)):
                self.assertEqual(bot._seconds_until_next_scan(now), expected)
        with patch.object(bot, "SCAN_INTERVAL_MINUTES", 5), patch.object(bot, "SCAN_CLOSE_DELAY_SECONDS", 90):
            self.assertEqual(bot._seconds_until_next_scan(310), 80)

    def test_core_priority_cap_and_overflow_are_delivered_before_slow_observation(self):
        timeline = []
        def scan(symbol, state, observe=False):
            timeline.append(("scan", symbol))
            if observe:
                self.assertIn(("notify", "HIGHUSDT", True), timeline)
                self.assertIn(("overflow", "LOWUSDT"), timeline)
                return [{"strategy": "S5", "symbol": symbol, "confidence": "GOZLEM"}]
            return [{"strategy": "S2" if symbol == "LOWUSDT" else "S1+S4",
                     "symbol": symbol, "confidence": "DUSUK" if symbol == "LOWUSDT" else "YUKSEK"}]
        state = Mock()
        with ExitStack() as stack:
            for name, value in {"SYMBOLS": ["LOWUSDT", "HIGHUSDT"], "OBSERVE_ENABLED": True,
                                "OBSERVE_SYMBOLS": ["OBS1USDT", "OBS2USDT"], "OBSERVE_PUSH": True,
                                "OBSERVE_MAX_PUSH_PER_SCAN": 1, "MAX_PUSH_PER_SCAN": 1,
                                "S2_RESEARCH_PUSH": True, "scan_symbol": scan}.items():
                stack.enter_context(patch.object(bot, name, value))
            stack.enter_context(patch.object(bot.time, "sleep"))
            stack.enter_context(patch.object(bot, "notify", side_effect=lambda sig, push=True:
                                             timeline.append(("notify", sig["symbol"], push))))
            stack.enter_context(patch.object(bot, "_send_overflow_summary", side_effect=lambda sigs:
                                             timeline.append(("overflow", sigs[0]["symbol"]))))
            self.assertEqual(bot.scan_all(state), 2)
        self.assertEqual([x for x in timeline if x[0] == "notify"], [
            ("notify", "HIGHUSDT", True), ("notify", "LOWUSDT", False),
            ("notify", "OBS1USDT", True), ("notify", "OBS2USDT", False)])
        state.save.assert_called_once()

    def test_bar_open_is_not_mistaken_for_close_and_funding_is_not_shifted(self):
        stamp = self.now.isoformat()
        signals = [{"strategy": name, "bar_time": stamp} for name in ("S1", "S1+S4", "S3", "S5", "S6", "S2")]
        bot._stamp_signal_detection(signals, stamp)
        for sig in signals:
            expected = self.now if sig["strategy"] == "S2" else self.now + timedelta(hours=1)
            self.assertEqual(sig["signal_reference_at"], expected.isoformat())
            self.assertIn("detected_at", sig)

    def test_stage_latency_and_read_only_private_report(self):
        self.box.enqueue({"event_id": "private-event", "secret": "PRIVATE_TOKEN",
                          "signal_reference_at": self.now.isoformat(),
                          "detected_at": (self.now + timedelta(seconds=20)).isoformat()},
                         ["PRIVATE_CHAT"], self.now + timedelta(seconds=35))
        with patch.object(delivery, "utcnow", return_value=self.now + timedelta(seconds=37)):
            result = self.box.deliver("private-event", lambda *_: True, self.now + timedelta(seconds=35))
        self.assertEqual(result["delivery_latency_seconds"], {
            "reference_to_detect": 20, "detect_to_queue": 15,
            "queue_to_ack": 2, "reference_to_ack": 37})
        before = self.path.read_bytes()
        report = delivery.DeliveryOutbox(self.path).diagnostics(now=self.now + timedelta(seconds=40))
        self.assertEqual(report["latency_seconds"]["reference_to_ack"]["median"], 37)
        self.assertEqual(before, self.path.read_bytes())
        self.assertNotIn("PRIVATE", json.dumps(report))
        self.assertNotIn("private-event", json.dumps(report))

    def test_unknown_or_reversed_timestamps_do_not_fabricate_zero_latency(self):
        item = {"created_at": self.now.isoformat(), "first_delivered_at": (self.now - timedelta(seconds=1)).isoformat()}
        self.assertTrue(all(value is None for value in delivery.delivery_latency(item).values()))

    def test_retry_due_backoff_and_restart_are_preserved(self):
        self.box.enqueue({"event_id": "e"}, ["a"], self.now)
        self.box.deliver("e", lambda *_: False, self.now)
        restarted = delivery.DeliveryOutbox(self.path)
        self.assertEqual(restarted.pending_ids(due_only=True, now=self.now + timedelta(seconds=59)), [])
        self.assertEqual(restarted.pending_ids(due_only=True, now=self.now + timedelta(seconds=60)), ["e"])
        restarted.deliver("e", lambda *_: False, self.now + timedelta(seconds=60))
        self.assertEqual(restarted.pending_ids(due_only=True, now=self.now + timedelta(seconds=179)), [])
        self.assertEqual(restarted.pending_ids(due_only=True, now=self.now + timedelta(seconds=180)), ["e"])

    def test_expiry_is_rechecked_after_slow_recipient(self):
        self.box.enqueue({"event_id": "e"}, ["a", "b"], self.now)
        sender = Mock(return_value=False)
        with patch.object(delivery, "utcnow", side_effect=[self.now, self.now + timedelta(minutes=16)]):
            self.box.deliver("e", sender)
        sender.assert_called_once()
        self.assertEqual(self.box.items["e"]["recipients"]["b"]["status"], "failed")

    def test_retry_runs_during_scan_and_stops_before_leader_lock_release(self):
        now = delivery.utcnow()
        self.box.enqueue({"event_id": "e"}, ["test-recipient"], now - timedelta(minutes=2))
        self.box.deliver("e", lambda *_: False, now - timedelta(minutes=2))
        arrived = threading.Event()
        workers = []
        def scanning(**kwargs):
            workers.append(bot._delivery_retry_worker)
            self.assertTrue(arrived.wait(3), "retry was blocked by scan")
        def released(_handle):
            self.assertFalse(workers[0].thread.is_alive())
        with ExitStack() as stack:
            for name, value in {"DELIVERY_OUTBOX": self.box, "ENABLE_TELEGRAM": True,
                                "TELEGRAM_SUBSCRIBERS": ["test-recipient"]}.items():
                stack.enter_context(patch.object(bot, name, value))
            stack.enter_context(patch.object(bot, "_acquire_instance_file_lock", return_value=object()))
            stack.enter_context(patch.object(bot, "_release_instance_file_lock", side_effect=released))
            stack.enter_context(patch.object(bot, "_run_forever_locked", side_effect=scanning))
            stack.enter_context(patch.object(bot, "_telegram_signal_text", return_value="synthetic"))
            sender = stack.enter_context(patch.object(bot, "_telegram_send_text", side_effect=lambda *a, **k: arrived.set() or True))
            stack.enter_context(patch.object(bot, "_backfill_price_targets_from_signal_log"))
            bot.run_forever()
            sender.assert_called_once()
        self.assertTrue(self.box.get_public("e")["delivery_confirmed"])

    def test_once_never_starts_background_retry_worker(self):
        with patch.object(bot, "ENABLE_TELEGRAM", True), patch.object(bot, "DeliveryRetryWorker") as worker, \
             patch.object(bot, "_acquire_instance_file_lock", return_value=object()), \
             patch.object(bot, "_release_instance_file_lock"), patch.object(bot, "_run_forever_locked"):
            bot.run_forever(once=True)
        worker.assert_not_called()

    def test_retry_worker_keeps_polling_and_can_be_stopped(self):
        called = threading.Event()
        calls = []
        def callback(stop):
            calls.append(stop)
            if len(calls) >= 2:
                called.set()
        worker = delivery.DeliveryRetryWorker(callback, interval_seconds=0.01)
        worker.start()
        try:
            self.assertTrue(called.wait(3))
        finally:
            worker.stop()
        self.assertFalse(worker.thread.is_alive())


if __name__ == "__main__":
    unittest.main()
