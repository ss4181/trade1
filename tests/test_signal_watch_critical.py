"""Production default: only confirmed, signal-specific critical risk warnings."""
import copy
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import intraday_regime as regime
from signal_watch import (BAR, CRITICAL_POLICY, CRITICAL_REASON, SignalWatch,
                          MESSAGE_LIMIT, critical_reversal_reason, register)


HOUR = regime.HOUR
NOW = 500000 * HOUR + 75_000


def signal(eid="event", direction="LONG", **extra):
    return dict(event_id=eid, strategy="G1", symbol="TESTUSDT", direction=direction,
                delivered_at=regime.iso(NOW-HOUR), notified_at=regime.iso(NOW-HOUR),
                bar_time=regime.iso(NOW//HOUR*HOUR-2*HOUR), horizon_hours=4,
                performance_market="um_perp", delivery_confirmed=True, **extra)


def context(now=NOW, hourly="BEAR", early="BEAR", fresh=True):
    return dict(hourly=hourly, early=early, fresh=fresh,
                reference_at=regime.iso(now//BAR*BAR),
                hourly_reference_at=regime.iso(now//HOUR*HOUR), last_error=None)


def prices(now=NOW, direction="LONG", *, close=None, count=32):
    # Stable pre-confirmation ATR=2; signal ref low=99 / high=101.
    end = now//BAR*BAR
    rows = [[end-(count-i)*BAR, 100, 101, 99, 100, 1,
             end-(count-i-1)*BAR-1] for i in range(count)]
    price = close if close is not None else (96 if direction == "LONG" else 104)
    for row in rows[-2:]:
        row[1:5] = [price, price+1, price-1, price]
    return rows


def reference(event):
    t = event["reference_ms"]
    return [[t, 100, 101, 99, 100, 1, t+HOUR-1]]


class CriticalReasonTests(unittest.TestCase):
    def test_long_and_short_require_opposite_consensus_and_buffer(self):
        for direction, opposite in (("LONG", "BEAR"), ("SHORT", "BULL")):
            with self.subTest(direction=direction):
                event = register(signal(direction=direction), NOW, {}, {})
                reason = critical_reversal_reason(event, reference(event), prices(direction=direction), NOW,
                                                  context(hourly=opposite, early=opposite))
                self.assertIn("0.5 ATR14", reason)
                self.assertIn("İki kapanmış", reason)
                self.assertIn("gerçek işlem K/Z hesabı değildir", reason)

    def test_transition_mismatch_unknown_or_favorable_context_is_silent(self):
        event = register(signal(), NOW, {}, {})
        for hourly, early in (("BEAR", "TRANSITION"), ("TRANSITION", "BEAR"),
                              ("BULL", "BEAR"), ("BEAR", "BULL"),
                              ("UNKNOWN", "BEAR"), ("BULL", "BULL")):
            self.assertIsNone(critical_reversal_reason(event, reference(event), prices(), NOW,
                                                      context(hourly=hourly, early=early)))

    def test_marginal_structure_crossing_or_exact_buffer_is_silent(self):
        event = register(signal(), NOW, {}, {})
        for close in (98.99, 98.5, 98, 100):
            self.assertIsNone(critical_reversal_reason(event, reference(event), prices(close=close), NOW, context()))

    def test_wicks_or_one_closed_break_are_silent(self):
        event = register(signal(), NOW, {}, {})
        raw = prices(close=100)
        raw[-2][3] = raw[-1][3] = 90
        self.assertIsNone(critical_reversal_reason(event, reference(event), raw, NOW, context()))
        raw = prices()
        raw[-2][1:5] = [100, 101, 99, 100]
        self.assertIsNone(critical_reversal_reason(event, reference(event), raw, NOW, context()))

    def test_repeated_poll_and_partial_delivery_bar_do_not_count_as_confirmation(self):
        rec = signal()
        rec.update(delivered_at=regime.iso(NOW-BAR), notified_at=regime.iso(NOW-BAR))
        event = register(rec, NOW, {}, {})
        for _ in range(3):
            self.assertIsNone(critical_reversal_reason(event, reference(event), prices(), NOW, context()))

    def test_g2_planned_entry_cannot_trigger_early(self):
        rec = signal()
        rec.update(strategy="G2", planned_entry_at=regime.iso(NOW+HOUR), horizon_hours=24)
        event = register(rec, NOW, {}, {})
        self.assertIsNone(critical_reversal_reason(event, reference(event), prices(), NOW, context()))
        later = NOW + 2*HOUR
        self.assertIsNotNone(critical_reversal_reason(event, reference(event), prices(later), later, context(later)))
        event.pop("monitor_from_ms")
        self.assertIsNone(critical_reversal_reason(event, reference(event), prices(later), later, context(later)))

    def test_stale_or_future_context_is_not_invalidation(self):
        event = register(signal(), NOW, {}, {})
        for fast in (context(fresh=False), context(NOW-BAR), context(NOW+HOUR),
                     {**context(), "reference_at": "bad"},
                     {**context(), "hourly_reference_at": regime.iso(NOW//HOUR*HOUR-HOUR)}):
            self.assertIsNone(critical_reversal_reason(event, reference(event), prices(), NOW, fast))

    def test_bad_gap_duplicate_stale_or_missing_candles_fail_closed(self):
        event = register(signal(), NOW, {}, {})
        for mode in ("gap", "duplicate", "stale", "short", "nan"):
            raw = prices()
            if mode == "gap": raw.pop(-4)
            if mode == "duplicate": raw.append(raw[-1])
            if mode == "stale": raw.pop()
            if mode == "short": raw = raw[-16:]
            if mode == "nan": raw[-1][4] = float("nan")
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                critical_reversal_reason(event, reference(event), raw, NOW, context())

    def test_expired_signal_never_becomes_close_instruction(self):
        event = register(signal(), NOW, {}, {})
        later = event["end_ms"]
        self.assertIsNone(critical_reversal_reason(event, reference(event), prices(later), later, context(later)))

    def test_wrong_reference_is_rejected(self):
        event = register(signal(), NOW, {}, {})
        raw = reference(event)
        raw[0][0] -= HOUR
        raw[0][6] -= HOUR
        with self.assertRaises(ValueError):
            critical_reversal_reason(event, raw, prices(), NOW, context())


class CriticalWatchTests(unittest.TestCase):
    def setUp(self):
        self.now = NOW

    def make(self, root, records, sent, *, broken=True, fast=None, recipients=None):
        def fetch(market, symbol, interval, params):
            if symbol in {"BTCUSDT", "ETHUSDT"}:
                return []  # Context snapshot is mocked; no real market requests.
            if interval == "1h":
                t = params["startTime"]
                return [[t, 100, 101, 99, 100, 1, t+HOUR-1]]
            self.assertEqual(params["limit"], 32)
            return prices(self.now, close=96 if broken else 100)
        return SignalWatch(root/"watch.json", fetch=fetch, records=lambda: records,
                           recipients=recipients or (lambda eid: ["owner"]),
                           subscribers=lambda: ["owner", "other"],
                           sender=lambda text, cid: sent.append((text,cid)) or True,
                           condition_check=lambda e,n: {"status": "CONDITIONS_LOST", "bar_end_ms": n//HOUR*HOUR,
                                                        "failed_conditions": ["volume below threshold"]})

    def tick(self, watch, *, hourly="BEAR", early="BEAR", fresh=True, daily="BEAR"):
        with patch("signal_watch.regime.snapshot", return_value=context(self.now, hourly, early, fresh)):
            watch.tick({"fresh": True, "label": daily}, now_ms=self.now)

    def test_default_is_critical_only_no_g1_loss_or_horizon_notice(self):
        with tempfile.TemporaryDirectory() as tmp:
            sent = []
            watch = self.make(Path(tmp), [signal()], sent, broken=False)
            self.assertTrue(watch.critical_only)
            self.tick(watch)
            self.assertEqual(sent, [])
            self.assertEqual(watch.state["events"]["event"]["condition_status"], "CONDITIONS_LOST")
            self.now += 3*HOUR
            self.tick(watch)
            self.assertEqual(sent, [])
            self.assertFalse(watch.state["events"])

    def test_global_regime_flips_without_active_signal_are_silent(self):
        with tempfile.TemporaryDirectory() as tmp:
            sent = []
            watch = self.make(Path(tmp), [], sent)
            self.tick(watch, hourly="BULL", early="BULL", daily="BULL")
            self.now += BAR
            self.tick(watch)
            self.now += BAR
            self.tick(watch, hourly="TRANSITION", early="TRANSITION")
            self.assertEqual(sent, [])

    def test_critical_only_to_original_recipient_once_across_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, sent, records = Path(tmp), [], [signal()]
            before = copy.deepcopy(records)
            watch = self.make(root, records, sent)
            self.tick(watch)
            self.assertEqual(len(sent), 1)
            text, cid = sent[0]
            self.assertEqual(cid, "owner")
            self.assertIn("Kritik risk", text)
            self.assertIn("kesin kapat emri", text)
            self.assertNotIn("Sinyal takip süresi bitti", text)
            self.assertEqual(watch.status["alert_policy"], CRITICAL_POLICY)
            self.now += BAR
            watch = self.make(root, records, sent)
            self.tick(watch)
            self.assertEqual(len(sent), 1)
            self.assertEqual(records, before)

    def test_structure_alone_or_market_alone_is_silent(self):
        with tempfile.TemporaryDirectory() as tmp:
            sent = []
            watch = self.make(Path(tmp), [signal()], sent)
            self.tick(watch, hourly="BULL", early="BULL")
            self.assertFalse(sent)
        with tempfile.TemporaryDirectory() as tmp:
            sent = []
            watch = self.make(Path(tmp), [signal()], sent, broken=False)
            self.tick(watch)
            self.assertFalse(sent)

    def test_shared_warning_is_aggregated_and_recipient_private(self):
        with tempfile.TemporaryDirectory() as tmp:
            sent = []
            records = [dict(signal("one"), symbol="ALPHAUSDT"),
                       dict(signal("two"), symbol="BETAUSDT"),
                       dict(signal("three"), strategy="S3", symbol="ALPHAUSDT")]
            watch = self.make(Path(tmp), records, sent, recipients=lambda eid: ["other"] if eid=="two" else ["owner"])
            self.tick(watch)
            self.assertEqual(len(sent), 2)
            for text, cid in sent:
                self.assertIn("ALPHA" if cid == "owner" else "BETA", text)
                self.assertNotIn("BETA" if cid == "owner" else "ALPHA", text)

    def test_queued_old_updates_are_suppressed_not_replayed_on_upgrade(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, sent = Path(tmp), []
            old = self.make(root, [], sent)
            old.enqueue("old", "ROUTINE_UPDATE", ["owner", "other"], NOW, NOW+HOUR)
            eid = old.outbox.pending_ids()[0]
            old.outbox.deliver(eid, lambda cid,row: cid == "owner",
                               now=datetime.fromtimestamp(NOW/1000,timezone.utc))
            watch = self.make(root, [], sent)
            watch.flush(NOW+60_000)
            self.assertFalse(sent)
            recipient = watch.outbox._load()[eid]["recipients"]
            self.assertEqual(recipient["owner"]["status"], "delivered")
            self.assertEqual(recipient["other"]["suppressed_by_policy"], CRITICAL_POLICY)
            self.assertEqual(watch.status["failed_alert_deliveries"], 0)

    def test_old_digest_is_silent_but_does_not_block_a_new_critical_warning(self):
        with tempfile.TemporaryDirectory() as tmp:
            sent = []
            watch = self.make(Path(tmp), [signal()], sent)
            event = register(signal(), NOW, {}, {})
            item = watch._watch_item(event, {"structure": "OLD_CONTEXT"}, NOW)
            watch.outbox.enqueue_groups({"owner": [item]}, NOW)
            self.tick(watch)
            self.assertEqual(len(sent), 1)
            self.assertNotIn("OLD_CONTEXT", sent[0][0])
            self.assertIn(CRITICAL_REASON, watch.state["events"]["event"]["warned"])

    def test_critical_delivery_retries_only_failed_recipient(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, sent, records = Path(tmp), [], [signal()]
            watch = self.make(root, records, sent, recipients=lambda eid: ["owner", "other"])
            watch.sender = lambda text,cid: sent.append((text,cid)) or cid == "owner"
            self.tick(watch)
            self.now += 5*regime.MINUTE
            watch = self.make(root, records, sent, recipients=lambda eid: ["owner", "other"])
            self.tick(watch)
            self.assertEqual([cid for _,cid in sent].count("owner"), 1)
            self.assertEqual([cid for _,cid in sent].count("other"), 2)

    def test_pending_critical_expires_at_next_context_boundary(self):
        with tempfile.TemporaryDirectory() as tmp:
            sent = []
            watch = self.make(Path(tmp), [signal()], sent)
            watch.sender = lambda text,cid: False
            self.tick(watch)
            self.assertTrue(watch.outbox.pending_ids())
            self.now = (NOW//BAR+1)*BAR+75_000
            watch.sender = lambda text,cid: sent.append((text,cid)) or True
            watch.flush(self.now)
            self.assertFalse(sent)

    def test_enqueue_then_state_save_failure_deduplicates_after_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, sent, records = Path(tmp), [], [signal()]
            watch = self.make(root, records, sent)
            watch.load(); watch.save()
            with patch.object(watch, "save", side_effect=OSError("PRIVATE")):
                self.tick(watch)
            self.assertFalse(sent)
            self.now += 5*regime.MINUTE
            watch = self.make(root, records, sent)
            self.tick(watch)
            self.assertEqual(len(sent), 1)
            self.assertNotIn("PRIVATE", sent[0][0])

    def test_policy_migration_save_failure_preserves_old_queue(self):
        with tempfile.TemporaryDirectory() as tmp:
            watch = self.make(Path(tmp), [], [])
            watch.enqueue("old", "old context", ["owner"], NOW, NOW+HOUR)
            before = copy.deepcopy(watch.outbox._load())
            with patch.object(watch.outbox, "_save", side_effect=OSError()):
                with self.assertRaises(OSError): watch.outbox.suppress_context()
            self.assertEqual(watch.outbox._load(), before)

    def test_stale_unknown_context_never_sends_or_claims_close(self):
        with tempfile.TemporaryDirectory() as tmp:
            sent = []
            watch = self.make(Path(tmp), [signal()], sent)
            self.tick(watch, fresh=False)
            self.assertFalse(sent)
            self.assertNotIn(CRITICAL_REASON, watch.state["events"]["event"]["warned"])

    def test_old_structure_warning_does_not_suppress_new_critical_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            sent = []
            watch = self.make(Path(tmp), [signal()], sent)
            watch.load()
            old = register(signal(), NOW, {}, {})
            old.pop("monitor_from_ms")
            old["warned"] = ["structure", "hourly", "early", "conditions_lost"]
            watch.state["events"]["event"] = old
            watch.save()
            self.tick(watch)
            self.assertEqual(len(sent), 1)
            self.assertIn("monitor_from_ms", watch.state["events"]["event"])

    def test_unversioned_or_mixed_digest_cannot_upgrade_itself_to_critical(self):
        with tempfile.TemporaryDirectory() as tmp:
            sent = []
            watch = self.make(Path(tmp), [], sent)
            event = register(signal(), NOW, {}, {})
            fake = watch._watch_item(event, {CRITICAL_REASON: "UNVERSIONED"}, NOW)
            watch.outbox.enqueue_groups({"owner": [fake]}, NOW)
            watch.flush(NOW)
            self.assertFalse(sent)

    def test_critical_pages_keep_version_size_and_all_member_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            sent = []
            watch = self.make(Path(tmp), [], sent)
            members = []
            for i in range(70):
                event = register(dict(signal(str(i)), symbol=f"COIN{i:03}USDT"), NOW, {}, {})
                item = watch._watch_item(event, {CRITICAL_REASON: "Kritik fiyat < sınır & yön teyidi"}, NOW)
                item.update(alert_policy=CRITICAL_POLICY)
                members.append(item)
            watch.outbox.enqueue_groups({"owner": members}, NOW)
            watch.flush(NOW)
            self.assertGreater(len(sent), 1)
            for text, _ in sent:
                self.assertIn("Kritik risk", text)
                self.assertLessEqual(len(text.encode("utf-16-le"))//2, MESSAGE_LIMIT)
                self.assertIn("&lt;", text)
            for i in range(70):
                self.assertEqual(sum(f"COIN{i:03}USDT" in text for text, _ in sent), 1)

    def test_reference_error_is_retryable_instead_of_cached_forever(self):
        with tempfile.TemporaryDirectory() as tmp:
            sent = []
            watch = self.make(Path(tmp), [signal()], sent)
            fetch = watch.fetch
            watch.fetch = lambda m,s,i,p: [] if i == "1h" and s == "TESTUSDT" else fetch(m,s,i,p)
            self.tick(watch)
            self.assertFalse(sent)
            self.assertEqual(watch.status["price_errors"], 1)
            self.assertNotIn("reference_raw", watch.state["events"]["event"])
            self.now += 5*regime.MINUTE
            watch.fetch = fetch
            self.tick(watch)
            self.assertEqual(len(sent), 1)

    def test_live_delivery_checks_actual_clock_not_the_slow_fetch_start(self):
        with tempfile.TemporaryDirectory() as tmp:
            sent = []
            watch = self.make(Path(tmp), [signal()], sent)
            watch.sender = lambda text,cid: False
            self.tick(watch)
            watch.sender = lambda text,cid: sent.append((text,cid)) or True
            later = datetime.fromtimestamp(((NOW//BAR+1)*BAR+1)/1000,timezone.utc)
            with patch("signal_watch.datetime", wraps=datetime) as live_datetime:
                live_datetime.now.return_value = later
                watch.flush(NOW+60_000, live_clock=True)
            self.assertFalse(sent)


if __name__ == "__main__":
    unittest.main()
