"""No network or orders: quote freshness, causal entries, 1m/legacy cohorts."""
from contextlib import ExitStack
from datetime import datetime, timezone, timedelta
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import g1_entry as entry
import signal_bot as bot
import shadow_experiments as shadow
from research.review_g1_entry_shadow import summarize
from test_shadow_experiments import Response, ShadowExperimentTests, klines


class G1EntryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.stack=ExitStack()
        self.addCleanup(self.stack.close)
        self.addCleanup(self.tmp.cleanup)
        for name,value in {'PRICE_TARGET_STATE':bot._empty_price_target_state(),
                           'PRICE_TARGET_STATE_FILE':Path(self.tmp.name)/'targets.json',
                           'PRICE_TARGET_LEVELS_PCT':(2.,3.,5.,10.),
                           'PRICE_TARGET_TRACKING_ENABLED':True}.items():
            self.stack.enter_context(patch.object(bot,name,value))

    def record(self, eid='new'):
        return dict(event_id=eid,strategy='G1',symbol='AAAUSDT',direction='LONG',
            price=100.,horizon_hours=4,performance_market='um_perp',
            config_version=entry.CONFIG_VERSION,price_reference_status='fresh',
            price_target_measurement_version=entry.MEASUREMENT,
            notified_at='2026-10-03T12:00:11+00:00',delivered_at='2026-10-03T12:00:12+00:00',
            delivery_confirmed=True,entry_quote={'exchange_time_ms':1791028811000},push_allowed=True)

    def event(self,eid='new'):
        r=self.record(eid)
        # Set quote relative to fixture rather than hand-maintain an epoch.
        r['entry_quote']['exchange_time_ms']=int(bot._target_dt(r['notified_at']).timestamp()*1000)
        self.assertIsNotNone(bot._register_price_targets(r))
        return bot.PRICE_TARGET_STATE['events'][eid]

    def bars(self,start,n=18):
        return [dict(open_time=start+i*60000,open=100+i*.1,high=103.1 if i==0 else 102.,
                     low=99.,close=100.2+i*.1,close_time=start+(i+1)*60000-1) for i in range(n)]

    def test_quote_uses_ask_not_old_ticker_or_mid(self):
        q=entry.book_reference(dict(symbol='A',bidPrice='99',askPrice='100',time=1000),'A',2000)
        self.assertEqual(q['price'],100)
        self.assertEqual(q['age_seconds'],1)
        self.assertGreater(q['spread_bps'],0)

    def test_invalid_stale_future_and_wrong_symbol_rejected(self):
        base=dict(symbol='A',bidPrice='99',askPrice='100',time=1000)
        for changes,received in [({'symbol':'B'},2000),({'askPrice':'98'},2000),
                                 ({'askPrice':'NaN'},2000),({},32001),({},-5001)]:
            with self.assertRaises(ValueError):
                entry.book_reference({**base,**changes},'A',received)

    def test_new_event_tracks_first_full_minute_and_delivery_elapsed(self):
        e=self.event(); start=e['next_start_ms']
        self.assertEqual(start%60000,0)
        self.assertEqual(e['unobserved_initial_seconds'],48.)
        bars=self.bars(start,1)
        before={**bars[0],'open_time':start-60000,'high':200.,'close_time':start-1}
        hits=bot._apply_price_target_bars(e,[before,*bars],start+60000)
        self.assertEqual(hits,['2','3'])
        self.assertEqual(e['targets']['2']['minutes_to_hit_upper'],1.8)
        self.assertIsNone(e['targets']['5']['hit_at'])
        self.assertEqual(bot._price_target_public(e)['bar_interval_minutes'],1)

    def test_fallback_price_or_stale_delivery_is_not_measured(self):
        r=self.record()
        r['price_reference_status']='unavailable'
        self.assertIsNone(bot._register_price_targets(r))
        r['price_reference_status']='fresh'
        r['entry_quote']['exchange_time_ms']=int(bot._target_dt(r['delivered_at']).timestamp()*1000)-31000
        self.assertIsNone(bot._register_price_targets(r))

    def test_old_g1_backfill_stays_5m_and_cohorts_separate(self):
        old=self.record('old');old.pop('price_target_measurement_version')
        bot._register_price_targets(old)
        e=self.event()
        e['status']='expired'
        old_event=bot.PRICE_TARGET_STATE['events']['old'];old_event['status']='expired'
        old_event['targets']['2']['hit_at']='2026-10-03T12:10:00+00:00'
        summary=bot.price_target_summary()
        self.assertEqual(summary['G1']['2']['hit'],0)
        self.assertEqual(summary['G1 · 5m (eski)']['2']['hit'],1)
        self.assertEqual(entry.tracking_step(old_event),300000)

    def test_missing_minute_does_not_count_as_failure_or_advance(self):
        e=self.event();start=e['next_start_ms']
        bot._apply_price_target_bars(e,self.bars(start+60000,1),start+120000)
        self.assertEqual(e['next_start_ms'],start)
        self.assertEqual(e['status'],'active')

    def test_fetch_market_and_interval_preserve_legacy(self):
        e=self.event()
        with patch.object(bot,'_futures_get',return_value=Response([])) as fetch:
            bot.fetch_price_target_klines(e,e['next_start_ms'],e['next_start_ms']+60000)
            self.assertEqual(fetch.call_args.args[1]['interval'],'1m')
            e['measurement_version']='signal-reference-touch-v1'
            bot.fetch_price_target_klines(e,e['next_start_ms'],e['next_start_ms']+300000)
            self.assertEqual(fetch.call_args.args[1]['interval'],'5m')

    def test_shadow_confirm_uses_only_prior_closed_minutes(self):
        e=self.event();start=e['next_start_ms'];bars=self.bars(start)
        entry.advance_entry_shadow(e,bars[:5])
        self.assertNotIn('confirm_5m',e['entry_shadow']['plans'])
        # Confirmation is determined before this entry bar's fall, not after.
        bars[5].update(open=100.,high=105.,low=90.,close=95.)
        entry.advance_entry_shadow(e,bars[5:6])
        plan=e['entry_shadow']['plans']['confirm_5m']
        self.assertEqual(plan['entry_price'],100.)
        self.assertEqual(plan['status'],'AMBIGUOUS_SL')
        self.assertAlmostEqual(plan['gross_pct'],-2.)

    def test_no_entry_and_timeout_are_explicit(self):
        e=self.event();bars=self.bars(e['next_start_ms'],16)
        for b in bars:
            b.update(open=100.,high=101.,low=99.,close=99.5)
        entry.advance_entry_shadow(e,bars)
        entry.finish_entry_shadow(e)
        self.assertEqual(e['entry_shadow']['plans']['confirm_5m']['status'],'no_entry')
        self.assertEqual(e['entry_shadow']['plans']['wait_15m']['status'],'TIMEOUT')
        e['status']='expired'
        result=summarize([e])
        self.assertFalse(result['readiness_gate'])
        self.assertEqual(result['plans']['confirm_5m']['counts']['no_entry'],1)

    def test_g1_fresh_quote_does_not_modify_frozen_decision(self):
        fixture=ShadowExperimentTests();fixture.setUp()
        now=fixture.now
        def fetch(path,params=None):
            if path.endswith('exchangeInfo'):
                return Response({'symbols':[dict(symbol='AAAUSDT',contractType='PERPETUAL',status='TRADING',quoteAsset='USDT')]})
            if path.endswith('ticker/24hr'):
                return Response([dict(symbol='AAAUSDT',priceChangePercent='6',lastPrice='104.25')])
            if path.endswith('klines'):return Response(klines(now))
            if path.endswith('openInterestHist'):return Response(fixture.oi)
            if path.endswith('globalLongShortAccountRatio'):return Response(fixture.ls)
            if path.endswith('bookTicker'):
                return Response(dict(symbol='AAAUSDT',bidPrice='105',askPrice='105.1',time=int(now.timestamp()*1000)))
            raise AssertionError(path)
        root=Path(self.tmp.name)
        signals=shadow.scan_g1(fetch,root/'s.json',root,now)
        self.assertEqual(len(signals),1)
        self.assertEqual(signals[0]['condition_price'],106.)
        self.assertEqual(signals[0]['price'],105.1)
        self.assertEqual(signals[0]['price_reference_status'],'fresh')
        self.assertEqual(shadow.scan_g1(fetch,root/'s.json',root,now),[])

    def test_optional_quote_is_bounded_and_respects_rate_gate(self):
        with patch.object(bot,'_futures_blocked_until',bot.time.time()+60),patch.object(bot,'_market_get') as get:
            with self.assertRaises(bot.MarketRateLimitError):bot._g1_quote_get('/test')
            get.assert_not_called()
        with patch.object(bot,'_futures_get',return_value=Response({})) as get:
            bot._g1_quote_get('/test',{'symbol':'A'})
            self.assertEqual(get.call_args.kwargs,dict(request_timeout=5,max_retries=1,fail_fast_gate=True))

    def test_quote_failure_keeps_signal_and_cooldown_but_not_new_target(self):
        fixture = ShadowExperimentTests()
        fixture.setUp()
        now = fixture.now

        def fetch(path, params=None):
            if path.endswith('exchangeInfo'):
                return Response({'symbols': [dict(symbol='AAAUSDT',
                    contractType='PERPETUAL', status='TRADING', quoteAsset='USDT')]})
            if path.endswith('ticker/24hr'):
                return Response([dict(symbol='AAAUSDT', priceChangePercent='6', lastPrice='104.25')])
            if path.endswith('klines'):
                return Response(klines(now))
            if path.endswith('openInterestHist'):
                return Response(fixture.oi)
            if path.endswith('globalLongShortAccountRatio'):
                return Response(fixture.ls)
            if path.endswith('bookTicker'):
                raise TimeoutError('optional quote unavailable')
            raise AssertionError(path)

        root = Path(self.tmp.name)
        rows = shadow.scan_g1(fetch, root/'shadow.json', root, now)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['price'], 104.25)
        self.assertEqual(rows[0]['price_reference_status'], 'unavailable')
        record = {**rows[0], 'push_allowed': True, 'delivery_confirmed': True,
                  'notified_at': now.isoformat(), 'delivered_at': now.isoformat()}
        self.assertIsNone(bot._register_price_targets(record))
        self.assertEqual(bot.PRICE_TARGET_STATE['events'], {})
        self.assertIn('AAAUSDT', shadow.load_state(root/'shadow.json')['s7_last_fire'])
        self.assertEqual(shadow.scan_g1(fetch, root/'shadow.json', root, now), [])

    def test_public_shadow_whitelist_omits_private_or_unrelated_fields(self):
        e=dict(entry_shadow={'minutes':[{'secret':'PRIVATE_MARKER'}],
            'plans':{'immediate':{'status':'TP','entry_price':1.,'token':'PRIVATE_MARKER'},
                     'UNKNOWN':{'secret':'PRIVATE_MARKER'}}})
        import json
        public=json.dumps(entry.public_shadow(e))
        self.assertNotIn('PRIVATE_MARKER',public)
        self.assertNotIn('minutes',public)


if __name__=='__main__':unittest.main()
