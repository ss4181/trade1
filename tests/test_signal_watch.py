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
from signal_watch import SignalWatch, WatchOutbox, register, structure_reason, changed_against, MESSAGE_LIMIT

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
                           sender=lambda text, cid: sent.append((text, cid)) or True,
                           critical_only=False)  # Explicit legacy replay, not production defaults.

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
                self.assertTrue(bot.signal_watch_engine.SignalWatch.call_args.kwargs["critical_only"])
                self.assertTrue(event.wait(2))
                bot.start_signal_watch()
                self.assertIs(first, bot._signal_watch_worker)
                self.assertTrue(bot.signal_watch_snapshot()["worker_alive"])
            finally:
                bot._signal_watch_worker.stop()
            self.assertFalse(bot.signal_watch_snapshot()["worker_alive"])

    def test_categories_and_expiry_are_not_execution_instructions(self):
        with tempfile.TemporaryDirectory() as d:
            sent = []
            watch = self.make(Path(d), [signal()], sent)
            watch.tick({"fresh": True, "label": "BULL"}, now_ms=NOW)
            self.assertIn("Referans mum yapısı ihlal edildi", sent[0][0])
            self.assertIn("doğrulanmış çıkış modeli değil", sent[0][0])
            self.now = NOW+3*HOUR
            watch.tick({"fresh": True, "label": "BULL"}, now_ms=self.now)
            self.assertEqual(len(sent), 2)
            self.assertIn("Sinyal takip süresi bitti", sent[1][0])
            self.assertIn("Pozisyonun kapandığı anlamına gelmez", sent[1][0])
            self.now += 300000
            watch.tick({"fresh": True, "label": "BULL"}, now_ms=self.now)
            self.assertEqual(len(sent), 2)

    def test_closed_hour_g1_condition_loss_once_across_restart(self):
        with tempfile.TemporaryDirectory() as d:
            root, sent = Path(d), []
            records = [dict(signal(), strategy="G1")]
            def callback(event, now):
                return {"status":"CONDITIONS_LOST", "bar_end_ms":now//HOUR*HOUR,
                        "failed_conditions":["Hacim 1.2x < 2x"]}
            watch = self.make(root, records, sent)
            watch.condition_check = callback
            watch.tick({"fresh": True, "label": "BULL"}, now_ms=NOW)
            self.assertEqual(len(sent), 1)
            self.assertIn("G1 kurulum koşulları artık sağlanmıyor", sent[0][0])
            self.assertIn("Hacim 1.2x", sent[0][0])
            self.assertEqual(sent[0][1], "owner")
            self.now += 300000
            watch = self.make(root, records, sent)
            watch.condition_check = callback
            watch.tick({"fresh": True, "label": "BULL"}, now_ms=self.now)
            self.assertEqual(len(sent), 1)

    def test_unknown_condition_is_not_cancellation(self):
        with tempfile.TemporaryDirectory() as d:
            sent = []
            watch = self.make(Path(d), [dict(signal(), strategy="G1")], sent)
            watch.condition_check = lambda e, n: {"status":"UNKNOWN"}
            watch.tick({"fresh": True, "label": "BULL"}, now_ms=NOW)
            self.assertNotIn("conditions_lost", watch.state['events']['abc']['warned'])
            self.assertEqual(watch.status['condition_errors'], 1)
            self.assertTrue(all("G1 kurulum koşulları" not in t for t, _ in sent))

    def test_fresh_or_pre_signal_hour_never_rechecks_older_conditions(self):
        with tempfile.TemporaryDirectory() as d:
            rec = dict(signal(), strategy="G1", bar_time=regime.iso(NOW//HOUR*HOUR-HOUR),
                       delivered_at=regime.iso(NOW-1000), notified_at=regime.iso(NOW-1000))
            watch = self.make(Path(d), [rec], [])
            with patch.object(watch, 'condition_check') as callback:
                watch.tick({"fresh": True, "label":"BULL"}, now_ms=NOW)
            callback.assert_not_called()

    def test_many_signals_one_message_and_no_repeat_after_restart(self):
        with tempfile.TemporaryDirectory() as d:
            root, sent = Path(d), []
            records=[dict(signal(), event_id=f"event{i}",strategy=s) for i,s in enumerate(("S1","S2","S3","G1","G2"))]
            records[-1]['planned_entry_at']=records[-1]['notified_at']
            watch=self.make(root,records,sent,down=True)
            watch.tick({'fresh':True,'label':'BULL'},now_ms=NOW)
            self.assertEqual(len(sent),1)
            text=sent[0][0]
            self.assertIn('toplu güncelleme',text)
            for s in ('S1','S2','S3','G1','G2'):self.assertIn(s+' — TESTUSDT',text)
            self.assertEqual(text.count('Saatlik yön:'),1)
            self.now+=300000
            watch=self.make(root,records,sent,down=True)
            watch.tick({'fresh':True,'label':'BULL'},now_ms=self.now)
            self.assertEqual(len(sent),1)

    def test_digest_recipient_privacy_and_unsubscribe(self):
        with tempfile.TemporaryDirectory() as d:
            sent=[]
            records=[dict(signal(),event_id='one',symbol='ALPHAUSDT'),
                     dict(signal(),event_id='two',symbol='BETAUSDT')]
            watch=self.make(Path(d),records,sent,down=True)
            watch.recipients=lambda eid:['owner','gone'] if eid=='one' else ['other']
            watch.tick({'fresh':True,'label':'BULL'},now_ms=NOW)
            self.assertEqual({cid for _,cid in sent},{'owner','other'})
            for text,cid in sent:
                self.assertIn('ALPHA' if cid=='owner' else 'BETA',text)
                self.assertNotIn('BETA' if cid=='owner' else 'ALPHA',text)
            watch.subscribers=lambda:[]
            self.now+=300000
            watch.tick({'fresh':True,'label':'BEAR'},now_ms=self.now)
            self.assertEqual(len(sent),2)

    def test_global_regime_and_related_signals_share_single_message(self):
        with tempfile.TemporaryDirectory() as d:
            root,sent=Path(d),[]
            watch=self.make(root,[signal()],sent)
            watch.tick({'fresh':True,'label':'BULL'},now_ms=NOW)
            sent.clear()
            self.now+=900000
            watch=self.make(root,[signal()],sent,down=True)
            watch.tick({'fresh':True,'label':'BULL'},now_ms=self.now)
            self.assertEqual(len(sent),2)  # one per subscriber, not one per reason
            self.assertTrue(all('Piyasa yönü değişti' in text for text,_ in sent))
            self.assertIn('TESTUSDT',next(text for text,cid in sent if cid=='owner'))
            self.assertNotIn('TESTUSDT',next(text for text,cid in sent if cid=='other'))

    def test_failed_recipient_retried_without_replaying_delivered(self):
        with tempfile.TemporaryDirectory() as d:
            root,sent=Path(d),[]
            watch=self.make(root,[signal()],sent,down=True)
            watch.recipients=lambda eid:['owner','other']
            def fail_other(text,cid):
                sent.append((text,cid))
                return cid=='owner'
            watch.sender=fail_other
            watch.tick({'fresh':True,'label':'BULL'},now_ms=NOW)
            self.assertEqual(len(sent),2)
            self.now+=300000
            watch=self.make(root,[signal()],sent,down=True)
            watch.recipients=lambda eid:['owner','other']
            watch.tick({'fresh':True,'label':'BULL'},now_ms=self.now)
            self.assertEqual([cid for _,cid in sent].count('owner'),1)
            self.assertEqual([cid for _,cid in sent].count('other'),2)

    def test_atomic_enqueue_for_all_recipients_and_crash_recovery(self):
        with tempfile.TemporaryDirectory() as d:
            root,sent=Path(d),[]
            watch=self.make(root,[signal()],sent,down=True)
            watch.recipients=lambda eid:['owner','other']
            watch.load();watch.save()
            with patch.object(watch.outbox,'_save',side_effect=OSError('PRIVATE_ERROR')):
                watch.tick({'fresh':True,'label':'BULL'},now_ms=NOW)
            self.assertEqual(watch.outbox.all_records(),[])
            self.assertFalse(sent)
            self.now+=300000
            watch=self.make(root,[signal()],sent,down=True)
            watch.recipients=lambda eid:['owner','other']
            with patch.object(watch,'save',side_effect=OSError()):
                watch.tick({'fresh':True,'label':'BULL'},now_ms=self.now)
            self.assertFalse(sent)
            self.now+=300000
            watch=self.make(root,[signal()],sent,down=True)
            watch.recipients=lambda eid:['owner','other']
            watch.tick({'fresh':True,'label':'BULL'},now_ms=self.now)
            self.assertEqual(sorted(cid for _,cid in sent),['other','owner'])

    def test_legacy_pending_alerts_coalesced_not_delivered_replayed(self):
        with tempfile.TemporaryDirectory() as d:
            root,sent=Path(d),[]
            watch=self.make(root,[],sent)
            watch.enqueue('one','<b>ALPHA weakening</b>',['owner'],NOW,NOW+HOUR,signal_id='one',reasons=['structure'])
            watch.enqueue('two','BETA weakening',['owner'],NOW,NOW+HOUR,signal_id='two',reasons=['structure'])
            watch.flush(NOW)
            self.assertEqual(len(sent),1)
            self.assertIn('ALPHA',sent[0][0]);self.assertIn('BETA',sent[0][0])
            self.assertNotIn('&lt;b&gt;',sent[0][0])
            self.assertEqual(watch.status['failed_alert_deliveries'],0)
            watch=self.make(root,[],sent)
            watch.flush(NOW+300000)
            self.assertEqual(len(sent),1)

    def test_expired_member_not_resent_with_long_lived_retry(self):
        with tempfile.TemporaryDirectory() as d:
            sent=[]
            watch=self.make(Path(d),[],sent)
            def member(name,end):
                return dict(kind='signal',signal_id=name,strategy='G1',symbol=name,direction='LONG',
                    delivered_ms=NOW-HOUR,end_ms=end,expires_ms=end,observed_ms=NOW,details={'structure':'Mum kırıldı'})
            watch.outbox.enqueue_groups({'owner':[member('EXPIRED',NOW+60000),member('ACTIVE',NOW+HOUR)]},NOW)
            watch.sender=lambda text,cid:False
            watch.flush(NOW)
            watch.sender=lambda text,cid:sent.append((text,cid)) or True
            watch.flush(NOW+120000)
            self.assertEqual(len(sent),1)
            self.assertNotIn('EXPIRED',sent[0][0])
            self.assertIn('ACTIVE',sent[0][0])

    def test_large_digest_split_all_signals_preserved_and_html_safe(self):
        from html.parser import HTMLParser
        class Balanced(HTMLParser):
            def __init__(self):super().__init__();self.tags=[]
            def handle_starttag(self,tag,attrs):self.tags.append(tag)
            def handle_endtag(self,tag):
                if not self.tags or self.tags.pop()!=tag:raise AssertionError('unbalanced')
        with tempfile.TemporaryDirectory() as d:
            sent=[]
            box=WatchOutbox(Path(d)/'outbox.json')
            members=[dict(kind='signal',signal_id=str(i),strategy='G1',symbol=f'COIN{i:03}USDT',direction='LONG',
                delivered_ms=NOW-HOUR,end_ms=NOW+HOUR,expires_ms=NOW+HOUR,observed_ms=NOW,
                details={'conditions_lost':'Hacim < 2x & OI < %2'}) for i in range(70)]
            box.enqueue_groups({'owner':members},NOW)
            records=box.all_records()
            self.assertGreater(len(records),1)
            all_ids=[]
            for record in records:
                text=record['text']
                self.assertLessEqual(len(text.encode('utf-16-le'))//2,MESSAGE_LIMIT)
                self.assertIn('&lt;',text)
                parser=Balanced();parser.feed(text);self.assertFalse(parser.tags)
                all_ids += [m['signal_id'] for m in record['watch_items']]
            self.assertEqual(sorted(all_ids),sorted(str(i) for i in range(70)))

    def test_coalesce_save_failure_preserves_original_pending_queue(self):
        with tempfile.TemporaryDirectory() as d:
            watch=self.make(Path(d),[],[])
            for name in ('one','two'):
                watch.enqueue(name,name,['owner'],NOW,NOW+HOUR)
            before=copy.deepcopy(watch.outbox._load())
            with patch.object(watch.outbox,'_save',side_effect=OSError()):
                with self.assertRaises(OSError):watch.outbox.coalesce_due(NOW,{'owner'})
            self.assertEqual(watch.outbox._load(),before)

    def test_pending_ttl_not_extended_by_coalescing(self):
        with tempfile.TemporaryDirectory() as d:
            sent=[]
            watch=self.make(Path(d),[],sent)
            watch.enqueue('old','EXPIRED_OLD_ALERT',['owner'],NOW-16*regime.MINUTE,NOW+HOUR)
            watch.enqueue('fresh','fresh',['owner'],NOW,NOW+HOUR)
            watch.flush(NOW)
            self.assertEqual(len(sent),1)
            self.assertNotIn('EXPIRED_OLD_ALERT',sent[0][0])
            self.assertIn('fresh',sent[0][0])

    def test_large_pages_are_actually_delivered_not_self_superseded(self):
        with tempfile.TemporaryDirectory() as d:
            sent=[]
            watch=self.make(Path(d),[],sent)
            members=[dict(kind='signal',signal_id=str(i),strategy='G1',symbol=f'COIN{i:03}USDT',direction='LONG',
                delivered_ms=NOW-HOUR,end_ms=NOW+HOUR,expires_ms=NOW+HOUR,observed_ms=NOW,
                details={'structure':'Mum desteği kırıldı'}) for i in range(70)]
            watch.outbox.enqueue_groups({'owner':members},NOW)
            watch.flush(NOW)
            self.assertGreater(len(sent),1)
            for i in range(70):
                self.assertEqual(sum(f'COIN{i:03}USDT' in text for text,_ in sent),1)
            n=len(sent)
            watch=self.make(Path(d),[],sent)
            watch.flush(NOW+300000)
            self.assertEqual(len(sent),n)

    def test_regime_digest_enqueue_before_state_save_does_not_repeat_transition(self):
        with tempfile.TemporaryDirectory() as d:
            root,sent=Path(d),[]
            watch=self.make(root,[],sent)
            watch.tick({'fresh':True,'label':'BULL'},now_ms=NOW)
            self.now+=900000
            watch=self.make(root,[],sent,down=True)
            with patch.object(watch,'save',side_effect=OSError()):
                watch.tick({'fresh':True,'label':'BULL'},now_ms=self.now)
            self.assertFalse(sent)
            self.now+=300000
            watch=self.make(root,[],sent,down=True)
            watch.tick({'fresh':True,'label':'BULL'},now_ms=self.now)
            self.assertEqual(sorted(cid for _,cid in sent),['other','owner'])
            self.assertEqual(len(watch.outbox.all_records()),2)

    def test_legacy_backoff_does_not_reset_or_replay_to_delivered_user(self):
        with tempfile.TemporaryDirectory() as d:
            root,sent=Path(d),[]
            watch=self.make(root,[],sent)
            for name in ('one','two'):
                watch.enqueue(name,name,['owner','other'],NOW,NOW+HOUR)
                watch.outbox.deliver(watch.outbox.pending_ids(now=datetime.fromtimestamp(NOW/1000,timezone.utc))[-1],
                    lambda cid,row:cid=='owner',now=datetime.fromtimestamp(NOW/1000,timezone.utc))
            watch.flush(NOW+30000)
            self.assertFalse(sent)
            watch.flush(NOW+60000)
            self.assertEqual(len(sent),1)
            self.assertEqual(sent[0][1],'other')
            digest=[r for r in watch.outbox._load().values() if r['record'].get('watch_format')=='digest-v1'][0]
            self.assertEqual(digest['recipients']['other']['attempts'],2)

    def test_legacy_reason_evidence_survives_coalescing_and_restart(self):
        with tempfile.TemporaryDirectory() as d:
            root,sent=Path(d),[]
            watch=self.make(root,[signal()],sent)
            watch.enqueue('old','Old structure warning',['owner'],NOW,NOW+HOUR,signal_id='abc',reasons=['structure'])
            watch.flush(NOW)
            self.assertEqual(len(sent),1)
            watch=self.make(root,[signal()],sent)
            watch.tick({'fresh':True,'label':'BULL'},now_ms=NOW)
            self.assertEqual(len(sent),1)
            self.assertIn('structure',watch.state['events']['abc']['warned'])

    def test_coalesced_retry_retains_each_members_original_ttl(self):
        with tempfile.TemporaryDirectory() as d:
            sent=[]
            watch=self.make(Path(d),[],sent)
            watch.enqueue('old','OLDER_ALERT',['owner'],NOW-14*regime.MINUTE,NOW+HOUR)
            watch.enqueue('fresh','NEWER_ALERT',['owner'],NOW,NOW+HOUR)
            watch.sender=lambda text,cid:False
            watch.flush(NOW)
            watch.sender=lambda text,cid:sent.append((text,cid)) or True
            watch.flush(NOW+2*regime.MINUTE)
            self.assertEqual(len(sent),1)
            self.assertNotIn('OLDER_ALERT',sent[0][0])
            self.assertIn('NEWER_ALERT',sent[0][0])


if __name__ == "__main__":
    unittest.main()
