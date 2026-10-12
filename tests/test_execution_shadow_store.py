"""Forward collection boundaries, persistence and isolated bot integration."""
import copy
from datetime import datetime, timezone
import io
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from contextlib import redirect_stdout
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import execution_shadow as engine
from execution_shadow_store import ShadowStore
import archive_backup
import signal_bot as bot


T = 1_800_000_000_000


def record(strategy="S1"):
    return {"event_id": "a"*32, "strategy": strategy, "symbol": "LDOUSDT",
            "direction": "LONG", "universe": "extended59", "performance_market": "spot",
            "config_version": "test-config", "engine_version": "test-engine",
            "engine_config_hash": "b"*64, "market_regime": "BULL",
            "horizon_hours": 24, "delivery_confirmed": True, "push_allowed": True,
            "suppressed": False,
            "delivered_at": datetime.fromtimestamp((T+1000)/1000, timezone.utc).isoformat(),
            "bar_time": datetime.fromtimestamp(T/1000, timezone.utc).isoformat(),
            "price": 100, "strength": "NORMAL", "note": "synthetic"}


def bar(t, o=100, h=101, l=99, c=100):
    return dict(open_time=t, open=o, high=h, low=l, close=c, close_time=t+engine.STEP-1)


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.path = self.root/".execution_shadow_state.json"
        self.store = ShadowStore(self.path, self.root, T)

    def tearDown(self):
        self.tmp.cleanup()

    def enroll(self):
        self.assertTrue(self.store.enroll(record(), "a"*32, T+1000))
        return copy.deepcopy(self.store.data["events"]["a"*32])

    def test_duplicate_restart_and_activation_persist(self):
        self.enroll()
        store = ShadowStore(self.path, self.root, T+100_000)
        self.assertEqual(store.data["activated_ms"], T)
        self.assertFalse(store.enroll(record(), "a"*32, T+1000))
        self.assertEqual(len(store.data["events"]), 1)

    def test_corrupt_or_different_protocol_not_reset(self):
        for raw in ('{broken', json.dumps({"study_version": "old", "events": {}})):
            self.path.write_text(raw, encoding="utf-8")
            with self.assertRaises(ValueError):
                ShadowStore(self.path, self.root, T)
            self.assertEqual(self.path.read_text(encoding="utf-8"), raw)

    def test_disk_failure_does_not_claim_enrollment(self):
        with patch.object(self.store, "_save", side_effect=OSError("test")):
            with self.assertRaises(OSError):
                self.store.enroll(record(), "a"*32, T+1000)
        self.assertEqual(self.store.data["events"], {})
        self.enroll()

    def test_corrupt_event_cursor_preserved_and_rejected(self):
        self.enroll()
        raw = json.loads(self.path.read_text())
        raw["events"]["a"*32]["next_start_ms"] += 60_000
        text = json.dumps(raw)
        self.path.write_text(text)
        with self.assertRaises(ValueError):
            ShadowStore(self.path, self.root, T)
        self.assertEqual(self.path.read_text(), text)

    def test_fetch_error_preserves_cursor_and_no_secrets(self):
        event = self.enroll()
        start = event["anchor_ms"]
        secret = "TOKEN_PRIVATE_SENTINEL"
        self.store.poll(Mock(side_effect=ValueError(secret)), start+engine.STEP)
        current = self.store.data["events"]["a"*32]
        self.assertEqual(current["next_start_ms"], start)
        self.assertEqual(current["data_status"], "UNKNOWN")
        self.assertNotIn(secret, self.path.read_text())
        self.store.poll(lambda *args: [bar(start)], start+engine.STEP)
        self.assertEqual(self.store.data["events"]["a"*32]["next_start_ms"], start+engine.STEP)

    def test_fetch_does_not_hold_store_lock(self):
        event = self.enroll()
        entered = threading.Event()
        def fetch(*args):
            thread = threading.Thread(target=lambda: (self.store.status(), entered.set()))
            thread.start()
            thread.join(timeout=1)
            self.assertTrue(entered.is_set())
            return [bar(event["anchor_ms"])]
        self.store.poll(fetch, event["anchor_ms"]+engine.STEP)

    def test_journal_and_backup_include_new_files_without_input_secrets(self):
        r = record()
        r["token"] = "SECRET_SENTINEL"
        r["recipients"] = ["PRIVATE_CHAT"]
        self.store.enroll(r, r["event_id"], T+1000)
        start = self.store.data["events"][r["event_id"]]["anchor_ms"]
        self.store.poll(lambda *args: [{**bar(start), "token": "SECRET_SENTINEL"}], start+engine.STEP)
        files = archive_backup.collect_files(self.root, include_state=True)
        self.assertIn(self.path, files)
        self.assertTrue(any(p.name.startswith("execution_shadow_bars_") for p in files))
        for p in files:
            self.assertNotIn("SECRET_SENTINEL", p.read_text())
            self.assertNotIn("PRIVATE_CHAT", p.read_text())

    def test_event_budget_and_stop(self):
        for i in range(3):
            self.store.enroll(record(), f"{i:032x}", T+1000)
        fetch = Mock(return_value=[])
        self.store.poll(fetch, T+2*engine.STEP, max_events=2)
        self.assertEqual(fetch.call_count, 2)
        stop = threading.Event(); stop.set()
        fetch.reset_mock()
        self.store.poll(fetch, T+3*engine.STEP, stop_event=stop)
        fetch.assert_not_called()

    def test_bot_hook_has_no_market_or_delivery_calls_and_failure_isolated(self):
        with patch.object(bot, "EXECUTION_SHADOW_ENABLED", True), \
             patch.object(bot, "_execution_shadow_store", self.store), \
             patch.object(bot, "EXECUTION_SHADOW_LAST_ERROR", None), \
             patch.object(bot, "fetch_price_target_klines") as fetch, \
             patch.object(bot, "send_telegram_message") as send, \
             patch.object(self.store, "enroll", side_effect=OSError("secret")):
            bot._register_execution_shadow(record())
            self.assertEqual(bot.EXECUTION_SHADOW_LAST_ERROR, "execution_shadow_enrollment_failed")
            fetch.assert_not_called(); send.assert_not_called()

    def test_bot_frozen_symbol_membership(self):
        store = Mock()
        with patch.object(bot, "EXECUTION_SHADOW_ENABLED", True), patch.object(bot, "_execution_shadow_store", store):
            for strategy, symbol in (("S1", "BTCUSDT"), ("S3", "LDOUSDT"), ("S5", "LDOUSDT")):
                bot._register_execution_shadow({**record(), "strategy": strategy, "symbol": symbol})
            store.enroll.assert_not_called()
            bot._register_execution_shadow(record())
            store.enroll.assert_called_once()

    def test_bot_poll_explicit_market_5m_adapter(self):
        event = self.enroll()
        for market in ("spot", "um_perp"):
            with patch.object(bot, "_execution_shadow_store", self.store), \
                 patch.object(self.store, "poll", side_effect=lambda fetch, **k: fetch({**event, "market": market}, 1, 2)), \
                 patch.object(bot, "fetch_price_target_klines", return_value=[]) as fetch:
                bot._poll_execution_shadow()
                fetch.assert_called_once_with({"symbol": "LDOUSDT", "market": market,
                                               "performance_symbol": "LDOUSDT"}, 1, 2)

    def test_successful_poll_does_not_hide_failed_enrollment(self):
        with patch.object(bot, "_execution_shadow_store", self.store), \
             patch.object(bot, "EXECUTION_SHADOW_LAST_ERROR", "execution_shadow_enrollment_failed"), \
             patch.object(self.store, "poll"):
            bot._poll_execution_shadow()
            self.assertEqual(bot.EXECUTION_SHADOW_LAST_ERROR, "execution_shadow_enrollment_failed")

    def test_leader_initializes_shadow_before_delivery_workers(self):
        from contextlib import ExitStack
        order = []
        class Worker:
            def __init__(self, callback, interval_seconds=5):
                self.callback = callback
                self.thread = Mock()
            def start(self):
                order.append(self.callback.__name__)
                self_outer.assertIsNotNone(bot._execution_shadow_store)
            def stop(self):
                pass
        self_outer = self
        with ExitStack() as stack:
            for name, value in {"EXECUTION_SHADOW_ENABLED": True,
                                "EXECUTION_SHADOW_STATE_FILE": self.path,
                                "ARCHIVE_DIR": self.root, "ENABLE_TELEGRAM": True,
                                "SHADOW_EXPERIMENTS_ENABLED": True, "G2_ENABLED": True,
                                "_signal_watch_worker": None, "DeliveryRetryWorker": Worker}.items():
                stack.enter_context(patch.object(bot, name, value))
            for name in ("_acquire_instance_file_lock", "_release_instance_file_lock", "_run_forever_locked",
                         "stop_market_regime_worker"):
                stack.enter_context(patch.object(bot, name))
            stack.enter_context(patch.object(bot, "_spot_http", Mock()))
            stack.enter_context(patch.object(bot, "_futures_http", Mock()))
            bot.run_forever()
        self.assertEqual(order[0], "_poll_execution_shadow")
        self.assertIsNone(bot._execution_shadow_store)
        self.assertIsNone(bot._execution_shadow_worker)

    def test_notify_and_retry_reach_hook_only_after_success(self):
        r = record()
        with patch.object(bot, "_delivery_record", return_value=r), \
             patch.object(bot, "_register_price_targets", return_value=None), \
             patch.object(bot, "_register_execution_shadow") as register, \
             patch.object(bot, "send_telegram_message", return_value=True), \
             patch.object(bot, "SIGNAL_LOG", str(self.root/"signals.log")), \
             redirect_stdout(io.StringIO()):
            bot.notify(r)
            register.assert_called_once()
            self.assertTrue(register.call_args.args[0]["delivery_confirmed"])
        box = Mock()
        box.pending_ids.return_value = [r["event_id"]]
        box.deliver.return_value = {"delivery_confirmed": True}
        box.confirmed_records.return_value = [r]
        with patch.object(bot, "ENABLE_TELEGRAM", True), patch.object(bot, "DELIVERY_OUTBOX", box), \
             patch.object(bot, "_register_execution_shadow") as register, \
             patch.object(bot, "_backfill_price_targets_from_signal_log"):
            bot._retry_signal_deliveries()
            register.assert_called_once_with(r)


if __name__ == "__main__":
    unittest.main()
