import copy
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

import intraday_regime as regime
from notification_delivery import DeliveryOutbox
from signal_watch import SignalWatch, register, structure_reason, changed_against

HOUR = regime.HOUR
NOW = 500000 * HOUR + 75_000


def candles(ms, now=NOW, count=240, down=False):
    end = now//ms*ms
    values = [300-i*.5 if down else 100+i*.5 for i in range(count)]
    return [[end-(count-i)*ms, v, v+.2, v-.2, v, 1, end-(count-i-1)*ms-1]
            for i, v in enumerate(values)]


def signal(now=NOW):
    return {"event_id": "abc", "strategy": "S3", "symbol": "TESTUSDT", "direction": "LONG",
            "delivered_at": regime.iso(now-HOUR), "notified_at": regime.iso(now-HOUR),
            "bar_time": regime.iso(now//HOUR*HOUR-2*HOUR), "horizon_hours": 4,
            "performance_market": "spot", "delivery_confirmed": True, "market_regime": "BULL",
            "intraday_regime": {"hourly": "BULL", "early": "BULL"}}


class IntradayTests(unittest.TestCase):
    def test_closed_only_consensus_and_two_distinct_bars(self):
        raw = {(s, i): candles(ms) for s in ("BTCUSDT", "ETHUSDT")
               for i, ms in (("1h", HOUR), ("15m", regime.MINUTE*15))}
        first = regime.snapshot(raw, NOW)
        self.assertEqual((first["hourly"], first["early"]), ("BULL", "BULL"))
        raw["BTCUSDT", "15m"].append([NOW//900000*900000, 1, 1, 1, 1, 1, NOW+900000])
        self.assertEqual(regime.snapshot(raw, NOW)["early"], "BULL")
        raw["ETHUSDT", "15m"] = candles(900000, down=True)
        self.assertEqual(regime.snapshot(raw, NOW)["early"], "TRANSITION")
        flipped = candles(900000)
        flipped[-1][1:5] = [1, 1, 1, 1]
        self.assertEqual(regime.trend(regime.closed_bars(flipped, 900000, NOW))["label"], "BEAR")
        raw["BTCUSDT", "15m"] = flipped
        # A single large reversal still lacks two-bar confirmation.
        self.assertEqual(regime.snapshot(raw, NOW)["early"], "TRANSITION")

    def test_stale_gap_duplicate_and_nonfinite_rejected(self):
        for kind in ("stale", "gap", "duplicate", "nan"):
            raw = candles(900000)
            if kind == "stale": raw.pop()
            if kind == "gap": raw.pop(-3)
            if kind == "duplicate": raw.append(raw[-1])
            if kind == "nan": raw[-1][4] = float("nan")
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                regime.closed_bars(raw, 900000, NOW)

    def test_horizon_delivery_and_g2_planned_clock(self):
        record = signal()
        original = copy.deepcopy(record)
        event = register(record, NOW, {}, {})
        self.assertEqual(event["end_ms"], NOW+3*HOUR)
        self.assertIsNone(register(record, NOW+3*HOUR, {}, {}))
        record["delivery_confirmed"] = False
        self.assertIsNone(register(record, NOW, {}, {}))
        record = dict(original, strategy="G2", horizon_hours=24, planned_entry_at=regime.iso(NOW+HOUR))
        self.assertEqual(register(record, NOW, {}, {})["end_ms"], NOW+25*HOUR)
        self.assertEqual(original, signal())

    def test_structure_needs_two_post_delivery_closes_not_wicks(self):
        event = register(signal(), NOW, {}, {})
        t = event["reference_ms"]
        ref = [[t, 100, 101, 99, 100, 1, t+HOUR-1]]
        recent = candles(900000, count=4)
        for row in recent:
            row[1:5] = [98, 100, 95, 98]
        self.assertIsNotNone(structure_reason(event, ref, recent, NOW))
        recent[-1][4] = 100
        self.assertIsNone(structure_reason(event, ref, recent, NOW))
        event["delivered_ms"] = NOW-900000
        recent[-1][4] = 98
        self.assertIsNone(structure_reason(event, ref, recent, NOW))
        event["delivered_ms"] = NOW-HOUR
        event["direction"] = "SHORT"
        for row in recent: row[1:5] = [102, 105, 100, 102]
        self.assertIsNotNone(structure_reason(event, ref, recent, NOW))

    def test_regime_risk_is_directional_not_unknown(self):
        self.assertTrue(changed_against("BULL", "TRANSITION", "LONG"))
        self.assertFalse(changed_against("BULL", "TRANSITION", "SHORT"))
        self.assertTrue(changed_against("BEAR", "BULL", "SHORT"))
        self.assertFalse(changed_against("UNKNOWN", "BEAR", "LONG"))
        self.assertFalse(changed_against("BULL", "UNKNOWN", "LONG"))


class WatchTests(unittest.TestCase):
    def make(self, root, delivered, sent, down=False):
        def fetch(market, symbol, interval, params):
            if symbol == "TESTUSDT":
                t = signal()["bar_time"]
                from signal_watch import millis
                if interval == "1h":
                    a = millis(t)
                    return [[a, 100, 101, 99, 100, 1, a+HOUR-1]]
                rows = candles(900000, now=self.now, count=4)
                for row in rows: row[1:5] = [98, 100, 95, 98]
                return rows
            return candles(HOUR if interval == "1h" else 900000, now=self.now, down=down)
        return SignalWatch(root/"watch.json", fetch=fetch, records=lambda: delivered,
                           recipients=lambda eid: ["owner"], subscribers=lambda: ["owner", "other"],
                           sender=lambda text, cid: sent.append((text, cid)) or True)

    def setUp(self):
        self.now = NOW

    def test_warning_only_to_signal_recipient_once_across_restart(self):
        with tempfile.TemporaryDirectory() as d:
            path, sent, records = Path(d), [], [signal()]
            before = copy.deepcopy(records)
            watch = self.make(path, records, sent, down=True)
            watch.tick({"fresh": True, "label": "BULL"}, now_ms=self.now)
            self.assertEqual(len(sent), 1)
            self.assertEqual(sent[0][1], "owner")
            self.assertIn("İki kapanmış", sent[0][0])
            self.assertIn("Saatlik yön", sent[0][0])
            self.now += 300000
            watch = self.make(path, records, sent, down=True)
            watch.tick({"fresh": True, "label": "BULL"}, now_ms=self.now)
            self.assertEqual(len(sent), 1)
            self.assertEqual(records, before)

    def test_baseline_silent_then_global_transition_and_no_repeat(self):
        with tempfile.TemporaryDirectory() as d:
            path, sent = Path(d), []
            watch = self.make(path, [], sent)
            watch.tick({"fresh": True, "label": "BULL"}, now_ms=self.now)
            self.assertEqual(sent, [])
            self.now += 900000
            watch = self.make(path, [], sent, down=True)
            watch.tick({"fresh": True, "label": "BULL"}, now_ms=self.now)
            self.assertEqual(len(sent), 2)
            self.assertTrue(all("Piyasa yönü değişti" in t for t, c in sent))
            self.now += 300000
            watch.tick({"fresh": True, "label": "BULL"}, now_ms=self.now)
            self.assertEqual(len(sent), 2)

    def test_unknown_data_and_expired_signal_never_warn(self):
        with tempfile.TemporaryDirectory() as d:
            sent = []
            watch = self.make(Path(d), [signal(NOW-5*HOUR)], sent)
            watch.fetch = lambda *args: (_ for _ in ()).throw(ValueError("stale"))
            watch.tick({"fresh": False, "label": "BEAR"}, now_ms=NOW)
            self.assertEqual(sent, [])
            self.assertFalse(watch.fast["fresh"])
            self.assertEqual(watch.status["active_signals"], 0)

    def test_crash_after_enqueue_recovers_without_repeat(self):
        with tempfile.TemporaryDirectory() as d:
            path, sent, records = Path(d), [], [signal()]
            watch = self.make(path, records, sent, down=True)
            watch.load()
            watch.save()
            with patch.object(watch, "save", side_effect=OSError()):
                watch.tick({"fresh": True, "label": "BULL"}, now_ms=NOW)
            self.assertEqual(sent, [])
            watch = self.make(path, records, sent, down=True)
            watch.tick({"fresh": True, "label": "BULL"}, now_ms=NOW)
            self.assertEqual(len(sent), 1)
            self.assertEqual(len(watch.outbox.all_records()), 1)

    def test_corrupt_state_not_overwritten_and_scan_boundary_reserved(self):
        with tempfile.TemporaryDirectory() as d:
            path, sent = Path(d), []
            state = path/"watch.json"
            state.write_text("bad-json")
            watch = self.make(path, [signal()], sent)
            watch.tick({}, now_ms=NOW)
            self.assertEqual(state.read_text(), "bad-json")
            self.assertTrue(watch.status["last_error"])
            state.unlink()
            watch = self.make(path, [signal()], sent)
            with patch.object(watch, "fetch") as fetch:
                watch.tick({}, now_ms=NOW//HOUR*HOUR+5000)
            fetch.assert_not_called()

    def test_confirmed_recipient_routing_excludes_failed_and_unrelated(self):
        with tempfile.TemporaryDirectory() as d:
            box = DeliveryOutbox(Path(d)/"signal.json")
            box.enqueue({"event_id": "one"}, ["owner", "failed"])
            box.deliver("one", lambda cid, row: cid == "owner")
            self.assertEqual(box.confirmed_recipients("one"), ["owner"])
            self.assertEqual(box.confirmed_recipients("unknown"), [])

    def test_bad_reference_can_recover_and_price_budget_is_bounded(self):
        with tempfile.TemporaryDirectory() as d:
            sent = []
            watch = self.make(Path(d), [signal()], sent)
            original = watch.fetch
            def lagging(market, symbol, interval, params):
                return [] if symbol == "TESTUSDT" and interval == "1h" else original(market, symbol, interval, params)
            watch.fetch = lagging
            watch.tick({"fresh": True, "label": "BULL"}, now_ms=NOW)
            self.assertEqual(watch.status["price_errors"], 1)
            self.assertFalse(watch.state["events"]["abc"].get("reference_raw"))
            self.now += 300000
            watch.fetch = original
            watch.tick({"fresh": True, "label": "BULL"}, now_ms=self.now)
            self.assertEqual(len(sent), 1)
        with tempfile.TemporaryDirectory() as d:
            records = [dict(signal(), event_id=str(i), symbol=f"COIN{i}") for i in range(25)]
            watch = self.make(Path(d), records, [])
            watch.tick({"fresh": True, "label": "BULL"}, now_ms=NOW)
            self.assertEqual(watch.status["price_backlog"], 5)

    def test_real_background_worker_starts_once_and_stops(self):
        import signal_bot as bot
        from unittest.mock import Mock
        event = threading.Event()
        engine = Mock()
        engine.tick.side_effect = lambda *a, **kw: event.set()
        engine.status = {"active_signals": 0}
        engine.fast = {"fresh": False}
        with patch.object(bot, "SIGNAL_WATCH_ENABLED", True), patch.object(bot, "_signal_watch", None), \
                patch.object(bot, "_signal_watch_worker", None), \
                patch.object(bot.signal_watch_engine, "SignalWatch", return_value=engine):
            try:
                bot.start_signal_watch()
                first = bot._signal_watch_worker
                self.assertTrue(event.wait(2))
                bot.start_signal_watch()
                self.assertIs(first, bot._signal_watch_worker)
                self.assertTrue(bot.signal_watch_snapshot()["worker_alive"])
            finally:
                bot._signal_watch_worker.stop()
            self.assertFalse(bot.signal_watch_snapshot()["worker_alive"])


if __name__ == "__main__":
    unittest.main()
