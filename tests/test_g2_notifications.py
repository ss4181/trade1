import json
from pathlib import Path
import tempfile
import unittest
import threading
from datetime import datetime,timezone
from unittest.mock import patch

import g2_notifications as g2
import notification_scorecard as scores
import configure_notifications as settings
import signal_bot as bot


class Response:
    def __init__(self,data):self.data=data
    def raise_for_status(self):pass
    def json(self):return self.data


class G2Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name)
        self.now=datetime(2026,9,14,12,1,tzinfo=timezone.utc)
        self.h=int(self.now.timestamp()*1000)//g2.HOUR*g2.HOUR

    def tearDown(self):self.tmp.cleanup()

    def candles(self,change=-.06):
        return [[t,100,110,90,100 if i<24 else 100*(1+change),10,t+g2.HOUR-1,1000]
                for i,t in enumerate(range(self.h-25*g2.HOUR,self.h,g2.HOUR))]

    def fetch(self,path,params):
        if path.endswith('klines'):return Response(self.candles())
        return Response([{'timestamp':self.h-g2.HOUR-300000,'sumOpenInterest':100},
                         {'timestamp':self.h-300000,'sumOpenInterest':102}])

    def test_scan_closed_cross_section_cooldown_restart_and_one_hour_plan(self):
        signals=g2.scan_g2(self.fetch,self.root/'state.json',self.root,self.now,contracts=('BTCUSDT','ETHUSDT'))
        self.assertEqual(len(signals),2)
        self.assertEqual(signals[0]['planned_entry_at'],g2.iso(self.h+g2.HOUR))
        self.assertEqual(signals[0]['config_version'],g2.VERSION)
        self.assertTrue(signals[0]['experimental'])
        self.assertEqual(g2.scan_g2(self.fetch,self.root/'state.json',self.root,self.now,contracts=('BTCUSDT','ETHUSDT')),[])

    def test_missing_cross_section_never_re_ranks_remaining_symbols(self):
        def fetch(path,p):
            if p['symbol']=='ETHUSDT':raise RuntimeError('missing')
            return self.fetch(path,p)
        with self.assertRaises(RuntimeError):g2.scan_g2(fetch,self.root/'s.json',self.root,self.now,contracts=('BTCUSDT','ETHUSDT'))
        state=json.loads((self.root/'s.json').read_text())
        self.assertEqual(state['last_fire'],{})
        self.assertNotIn('completed_hour',state)

    def test_future_and_stale_oi_not_used(self):
        rows=[{'timestamp':self.h,'sumOpenInterest':10000}]
        with self.assertRaises(ValueError):g2.oi_change(rows,self.h)
        candles=self.candles()
        candles.pop(10)
        with self.assertRaises(ValueError):g2.closed_return(candles,self.h)
        self.assertEqual(len(g2.CONTRACTS),87)

    def test_prices_parallel_and_detection_is_after_inputs_not_scan_start(self):
        entered=threading.Barrier(2)
        def fetch(path,params):
            if path.endswith('klines'):entered.wait(timeout=3)
            return self.fetch(path,params)
        detected=datetime(2026,9,14,12,1,8,tzinfo=timezone.utc)
        signals=g2.scan_g2(fetch,self.root/'parallel.json',self.root,self.now,
                           contracts=('BTCUSDT','ETHUSDT'),workers=2,clock=lambda:detected)
        self.assertEqual(len(signals),2)
        self.assertEqual(signals[0]['scan_started_at'],self.now.isoformat())
        self.assertEqual(signals[0]['detected_at'],detected.isoformat())

    def test_parallel_and_serial_g2_produce_identical_decisions(self):
        outputs=[]
        for workers in (1,8):
            outputs.append(g2.scan_g2(self.fetch,self.root/f'{workers}.json',self.root,self.now,
                                      contracts=('BTCUSDT','ETHUSDT'),workers=workers,clock=lambda:self.now))
        self.assertEqual(outputs[0],outputs[1])

    def event(self):
        e=dict(status='active',entry_ref=90,config_version=g2.VERSION,strategy='G2',direction='LONG')
        g2.initialize_tracking(e,{'planned_entry_at':g2.iso(self.h)},self.h-1000)
        return e

    def bar(self,t,h=101,l=99):return dict(open_time=t,open=100,high=h,low=l,close=100,close_time=t+299999)

    def test_entry_is_scheduled_open_and_ambiguous_stop_stays_failed(self):
        e=self.event()
        self.assertEqual(g2.advance_tracking(e,[self.bar(self.h,104,97)],self.h+g2.BAR),[])
        self.assertEqual(e['entry_ref'],100)
        self.assertEqual(e['g2_bracket']['status'],'AMBIGUOUS_SL')
        g2.advance_tracking(e,[self.bar(self.h+g2.BAR,110)],self.h+2*g2.BAR)
        self.assertEqual(e['g2_bracket']['status'],'AMBIGUOUS_SL')

    def test_gap_pending_target_and_late_delivery(self):
        e=self.event()
        g2.advance_tracking(e,[self.bar(self.h+g2.BAR,104)],self.h+2*g2.BAR)
        self.assertFalse(e['g2_bracket']['entry_set'])
        self.assertEqual(g2.advance_tracking(e,[self.bar(self.h,104)],self.h+g2.BAR),['3'])
        self.assertEqual(e['g2_bracket']['status'],'TP')
        late=self.event()
        g2.initialize_tracking(late,{'planned_entry_at':g2.iso(self.h)},self.h+1)
        self.assertEqual(late['g2_bracket']['status'],'UNAVAILABLE_LATE_DELIVERY')

    def test_timeout_and_public_tracker_migration(self):
        e=self.event()
        bars=[self.bar(t) for t in range(self.h,self.h+24*g2.HOUR,g2.BAR)]
        g2.advance_tracking(e,bars,self.h+24*g2.HOUR)
        self.assertEqual(e['g2_bracket']['status'],'TIMEOUT')
        with patch.object(bot,'PRICE_TARGET_STATE',{'schema_version':2,'events':{'x':e}}),patch.object(bot,'_save_price_target_state'):
            self.assertEqual(bot._ensure_price_target_state_schema(),0)
        self.assertEqual(bot._price_target_public(e)['success_status'],'FAILED')
        with patch.object(bot,'PRICE_TARGET_STATE',{'events':{'x':e}}):
            summary=bot.price_target_summary()
            self.assertEqual(summary['_meta']['g2_separate_bracket_events'],1)
            self.assertEqual(summary['_meta']['legacy_unverified_events'],0)
            self.assertNotIn('G2',summary)

    def test_delivery_tracking_retains_g2_schedule_and_telegram_details(self):
        sig=g2.scan_g2(self.fetch,self.root/'s.json',self.root,self.now,contracts=('BTCUSDT',))[0]
        sig.update(push_allowed=True,delivery_confirmed=True,notified_at=self.now.isoformat(),delivered_at=self.now.isoformat())
        with patch.object(bot,'PRICE_TARGET_STATE',{'events':{}}),patch.object(bot,'_save_price_target_state'):
            profile=bot._register_price_targets(sig)
            self.assertEqual(profile['measurement_version'],g2.MEASUREMENT)
            self.assertIsNone(profile['entry_ref'])
            sig['price_target']=profile
            sig['last_five_scorecard']=scores.summarize(sig,[],{})
            text=bot._telegram_signal_text(sig)
            self.assertIn('Son 5 G2',text)
            self.assertIn('TP %3',text)
            self.assertIn('planlanan Binance',text)
            self.assertLess(len(text),4096)


class ScorecardTests(unittest.TestCase):
    def test_last_five_not_last_five_resolved_and_no_failed_delivery(self):
        sig=dict(strategy='S3',config_version='v1',direction='LONG',event_id='new',notified_at='2026-09-14T12:00:00+00:00')
        delivered=[];events={}
        for i in range(7):
            eid=str(i)
            delivered.append(dict(strategy='S3',event_id=eid,delivered_at=f'2026-09-14T0{i}:00:00+00:00',delivery_confirmed=True))
            events[eid]=dict(config_version='v1',direction='LONG',measurement_version='signal-reference-touch-v1',status='expired',targets={'2':{'hit_at':'yes'}})
        events['6']['status']='active';events['6']['targets']['2']['hit_at']=None
        events['5']['config_version']='old'
        events['4']['targets']['2']['hit_at']=None
        delivered.append(dict(strategy='S3',event_id='failed',delivered_at='2026-09-14T11:00:00+00:00',delivery_confirmed=False))
        r=scores.summarize(sig,delivered,events)
        self.assertEqual((r['n'],r['success'],r['failed'],r['pending'],r['unknown']),(5,2,1,1,1))
        self.assertEqual([r['event_id'] for r in r['events']],['6','5','4','3','2'])

    def test_g2_succeeded_only_before_stop_and_no_backtest_injection(self):
        sig=dict(strategy='G2',config_version=g2.VERSION,direction='LONG')
        delivered=[dict(strategy='G2',event_id='x',delivered_at='2026-09-14T00:00:00+00:00',delivery_confirmed=True)]
        events={'x':dict(config_version=g2.VERSION,direction='LONG',measurement_version=g2.MEASUREMENT,g2_bracket={'status':'AMBIGUOUS_SL'})}
        r=scores.summarize(sig,delivered,events)
        self.assertEqual(r['success'],0)
        self.assertEqual(r['failed'],1)
        self.assertIn('TP%3 / SL%2',scores.format_html(r))

    def test_preferences_only_allow_known_notification_settings(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'settings.json'
            settings.enable(path)
            self.assertEqual(settings.load(path)['G2_PUSH'],'true')
            self.assertEqual(settings.load(path)['DISABLED_STRATEGIES'],'')
            self.assertNotIn('TELEGRAM_BOT_TOKEN',settings.load(path))
            path.write_text('{"overrides":{"TELEGRAM_BOT_TOKEN":"bad"}}')
            with self.assertRaises(ValueError):settings.load(path)

    def test_g2_state_and_preferences_are_backed_up(self):
        import archive_backup
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            names={'.g2_state.json','.notification_preferences.json','g2_events_2026-09.jsonl','g2_market_2026-09.jsonl'}
            for name in names:(root/name).write_text('{}\n')
            self.assertEqual({p.name for p in archive_backup.collect_files(root,True)},names)


if __name__=='__main__':unittest.main()
