"""Offline invariants: python -m unittest discover -s hyperliquid_bot -p test_bot.py."""
import hashlib
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from client import Client, DataError, clean_candles, parse_universe, book_metrics
from engine import HOUR, DAY, Regime, candidate, evaluate_limit
from oi_history import import_manifest, OIHistory
from store import Store
from store import read_delivery_status
from forward import outcomes
import telegram
import bot


def bar(t, step=HOUR, o=100, h=101, l=99, c=100, v=100):
    return dict(t=t,end=t+step,o=o,h=h,l=l,c=c,v=v)


class DataTests(unittest.TestCase):
    def test_open_candle_is_excluded(self):
        raw=[dict(t=t,T=t+HOUR-1,s='BTC',i='1h',o='100',h='101',l='99',c='100',v='5')
             for t in (0,HOUR)]
        self.assertEqual(len(clean_candles(raw,'BTC','1h',HOUR+20_000)),1)
        raw[0]['s']='ETH'
        with self.assertRaises(DataError):
            clean_candles(raw,'BTC','1h',HOUR)

    def test_invalid_price_or_conflicting_duplicate_fails(self):
        r=dict(t=0,T=HOUR,s='BTC',i='1h',o='100',h='101',l='99',c='100',v='5')
        with self.assertRaises(DataError):
            clean_candles([r,dict(r,c='100.5')],'BTC','1h',HOUR)
        with self.assertRaises(DataError):
            clean_candles([dict(r,c='NaN')],'BTC','1h',HOUR)

    def test_spot_context_identity_not_array_offset(self):
        meta=dict(tokens=[dict(index=0,name='USDC'),dict(index=3,name='ABC')],
                  universe=[dict(name='@7',tokens=[3,0])])
        ctx=[dict(coin='@2',markPx='999',dayNtlVlm='1'),
             dict(coin='@7',markPx='2',dayNtlVlm='1000000')]
        assets=parse_universe([{'universe':[]},[]],[meta,ctx])
        self.assertEqual(assets[0]['coin'],'@7')
        self.assertEqual(assets[0]['mark'],2)
        self.assertEqual(assets[0]['display'],'ABC/USDC')

    def test_stale_and_negative_books_fail(self):
        payload=dict(time=HOUR,levels=[[dict(px='100',sz='100')],[dict(px='100.1',sz='100')]])
        self.assertGreater(book_metrics(payload,HOUR)['bid_depth_usd'],0)
        with self.assertRaises(DataError):
            book_metrics(payload,HOUR+60001)
        payload['levels'][0][0]['sz']='-1'
        with self.assertRaises(DataError):
            book_metrics(payload,HOUR)

    def test_api_retries_are_bounded(self):
        from unittest.mock import Mock
        response=Mock(status_code=429,headers={'Retry-After':'5'})
        session=Mock();session.post.return_value=response
        with patch('client.time.sleep'):
            with self.assertRaisesRegex(DataError,'retry_exhausted'):
                Client(session).info({'type':'meta'})
        self.assertEqual(session.post.call_count,3)

    def test_api_json_failure_does_not_expose_body(self):
        from unittest.mock import Mock
        response=Mock(status_code=200)
        response.json.side_effect=ValueError('sensitive body')
        session=Mock();session.post.return_value=response
        with patch('client.time.sleep'):
            with self.assertRaisesRegex(DataError,'hyperliquid_invalid_json'):
                Client(session).info({'type':'meta'})


class EngineTests(unittest.TestCase):
    def test_regime_cannot_see_future_and_requires_contiguous_history(self):
        rows=[bar(i*DAY,DAY,c=100+i) for i in range(201)]
        when=200*DAY
        regime=Regime(rows)
        self.assertEqual(regime.at(when),'BULL')
        rows[-1]['c']=.01
        self.assertEqual(Regime(rows).at(when),'BULL')
        self.assertEqual(regime.at(199*DAY),'UNKNOWN')
        self.assertEqual(Regime(rows[:50]+rows[51:]).at(when),'UNKNOWN')
        self.assertEqual(Regime(rows[:200]).at(201*DAY),'UNKNOWN')

    def test_swing_candidate_closed_data_and_gap_rejection(self):
        class Bull:
            def at(self,when): return 'BULL'
        rows=[bar(i*HOUR,o=100+i*.01,c=100+i*.01,h=100.5+i*.01,l=99.5+i*.01)
              for i in range(200)]
        rows[-1].update(c=104,h=104.2,v=300)
        btc={r['end']:100 for r in rows}
        sig=candidate(rows,btc,Bull(),'perp','ABC','ABC')
        self.assertIsNotNone(sig)
        self.assertLess(sig['limit_reference'],sig['reference'])
        self.assertEqual(sig['horizons_hours'],[24,48])
        self.assertIsNone(candidate(rows[:20]+rows[21:],btc,Bull(),'perp','ABC','ABC'))
        self.assertIsNone(candidate(rows,{},Bull(),'perp','ABC','ABC'))

    def signal(self,market='perp'):
        return dict(market=market,close_ms=HOUR if market=='perp' else DAY,
                    limit_reference=100,stop=98,target=104)

    def test_fill_requires_penetration_and_wait(self):
        sig=self.signal()
        # Touch on the immediately following bar is intentionally not executable.
        rows=[bar(HOUR,l=90),bar(2*HOUR,o=101,l=100)]
        self.assertEqual(evaluate_limit(sig,rows,24)['status'],'UNFILLED')
        self.assertEqual(evaluate_limit(sig,[bar(HOUR,l=90)],24)['status'],'UNAVAILABLE')

    def test_entry_bar_target_never_credited_stop_first_on_ambiguous_bar(self):
        sig=self.signal()
        result=evaluate_limit(sig,[bar(2*HOUR,o=101,h=110,l=97)],24)
        self.assertEqual(result['status'],'SL')
        self.assertAlmostEqual(result['gross_return_pct'],-2)
        self.assertIsNone(result['net_return_pct'])
        result=evaluate_limit(sig,[bar(2*HOUR,o=101,h=110,l=99),bar(3*HOUR,h=105,l=99)],24)
        self.assertEqual(result['exit_ms'],4*HOUR)
        self.assertEqual(result['status'],'TP')

    def test_gap_stop_fees_and_missing_future(self):
        result=evaluate_limit(self.signal(),[bar(2*HOUR,o=101,l=99),bar(3*HOUR,o=90,l=89,h=100)],24)
        self.assertAlmostEqual(result['gross_return_pct'],-10)
        self.assertLess(result['net_ex_funding_pct'],-10)
        self.assertEqual(evaluate_limit(self.signal(),[bar(2*HOUR,o=101,l=99)],24)['status'],'UNAVAILABLE')
        result=evaluate_limit(self.signal('spot'),[bar(2*DAY,DAY,o=101,l=97)],336)
        self.assertIsNotNone(result['net_return_pct'])

    def test_marketable_alo_is_not_counted_as_maker_fill(self):
        result=evaluate_limit(self.signal(),[bar(2*HOUR,o=99,l=97,h=106)],24)
        self.assertEqual(result['status'],'ALO_REJECTED_SCENARIO')
        self.assertIsNone(result['net_ex_funding_pct'])


class StateTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name)
        self.store=Store(self.root/'test.sqlite3')

    def tearDown(self):
        self.store.close();self.tmp.cleanup()

    def event(self):
        return dict(id='one',strategy='HL-S',coin='X',display='X<Y',detected_ms=HOUR,
                    close_ms=HOUR,market='perp',reference=100,limit_reference=99.8,
                    stop=98,target=104,volume_ratio=2,relative_strength_pct=3,
                    book={'spread_bps':2},horizons_hours=[24,48],rule_hash='fixture')

    def test_durable_dedup_and_retry_deadline(self):
        event=self.event()
        self.assertTrue(self.store.add_event(event))
        self.assertFalse(self.store.add_event(event))
        self.store.delivery('one',HOUR,False)
        self.assertEqual(self.store.pending(HOUR),[])
        self.assertEqual(len(self.store.pending(HOUR+60000)),1)
        self.store.close();self.store=Store(self.root/'test.sqlite3')
        self.assertTrue(self.store.recent('HL-S','X',0))
        self.store.delivery('one',HOUR+60000,True)
        self.assertEqual(self.store.pending(2*HOUR),[])
        self.assertEqual(read_delivery_status(self.root/'test.sqlite3')['acknowledged'],1)

    def test_forward_pending_is_separate_from_missing_mature_outcome(self):
        self.store.add_event(self.event())
        early=outcomes(self.store,2*HOUR)
        self.assertEqual(early['trades'][0]['status'],'PENDING')
        mature=outcomes(self.store,100*HOUR)
        self.assertEqual(mature['trades'][0]['status'],'UNAVAILABLE')
        self.assertEqual(mature['results']['HL-S_24h']['n_measured'],0)

    def test_delivery_disabled_by_default_and_expired_dropped(self):
        self.store.add_event(self.event())
        with patch.object(telegram,'call') as call:
            self.assertEqual(telegram.deliver(self.store,{},HOUR),0)
            self.assertEqual(telegram.deliver(self.store,dict(HL_TELEGRAM_ENABLED='true',
                HL_TELEGRAM_BOT_TOKEN='dummy',HL_TELEGRAM_CHAT_ID='dummy'),4*HOUR),0)
            call.assert_not_called()

    def test_message_turkey_time_and_escaped_text(self):
        msg=telegram.message(self.event())
        self.assertIn('04:00 TSİ',msg)
        self.assertIn('X&lt;Y',msg)

    def test_private_channel_setup_uses_only_standalone_env(self):
        responses=[dict(id=5,username='new_bot'),
            [dict(channel_post=dict(chat=dict(id=-100123,type='channel',title='New')))],
            dict(id=-100123,type='channel'),dict(status='administrator',can_post_messages=True)]
        with patch.object(bot,'ROOT',self.root),patch('getpass.getpass',return_value='TEST_TOKEN'),\
             patch('builtins.input',return_value=''),patch.object(telegram,'call',side_effect=responses):
            bot.setup_telegram()
        content=(self.root/'.env').read_text()
        self.assertIn('HL_TELEGRAM_CHAT_ID=-100123',content)
        self.assertIn('HL_TELEGRAM_ENABLED=true',content)
        self.assertFalse((self.root/'.env.tmp').exists())

    def test_setup_requires_channel_post_permission(self):
        responses=[dict(id=5,username='new_bot'),dict(id=-100123,type='channel'),
                   dict(status='member')]
        with patch.object(bot,'ROOT',self.root),patch('getpass.getpass',return_value='TEST_TOKEN'),\
             patch('builtins.input',return_value='@new'),patch.object(telegram,'call',side_effect=responses):
            with self.assertRaises(ValueError):
                bot.setup_telegram()
        self.assertFalse((self.root/'.env').exists())

    def test_scan_archives_and_deduplicates_without_sending(self):
        now=int(time.time()*1000)
        close=now//HOUR*HOUR
        asset=dict(market='perp',coin='X',display='X',volume_usd=2_000_000)
        class FakeClient:
            def universe(self): return [asset],{'test':'public_market_fixture'}
            def candles(self,coin,interval,start,end):
                step=DAY if interval=='1d' else HOUR
                return [bar(end//step*step-step,step)]
            def book(self,coin):
                return dict(time=int(time.time()*1000),levels=[
                    [dict(px='100',sz='1000')],[dict(px='100.1',sz='1000')]])
        signal=self.event();signal.update(close_ms=close,horizons_hours=[24,48])
        with patch.object(bot,'DATA',self.root),patch.object(bot,'candidate',return_value=signal),\
                patch.object(telegram,'call') as send:
            first=bot.scan(FakeClient(),self.store,{})
            second=bot.scan(FakeClient(),self.store,{})
            send.assert_not_called()
        self.assertEqual(first['errors'],[])
        self.assertEqual(second['checked'],1)
        self.assertEqual(len(self.store.pending(now+10000)),1)
        self.assertEqual(self.store.latest()[1]['selected'][0]['coin'],'X')
        self.assertTrue((self.root/'status.json').exists())

    def test_env_does_not_read_original_bot_variables(self):
        (self.root/'.env').write_text('TELEGRAM_BOT_TOKEN=old\nHL_MARKET_LIMIT=12\n')
        with patch.object(bot,'ROOT',self.root),patch.dict('os.environ',{},clear=True):
            self.assertEqual(bot.settings(),{'HL_MARKET_LIMIT':'12'})

    def make_manifest(self):
        market=dict(symbol='ABC_PERP.A',quote_asset='USDT',margined='STABLE',
                    base_asset='ABC',exchange='A',oi_lq_vol_denominated_in='BASE_ASSET')
        rows=[dict(t=i*3600,c=100+i) for i in range(30)]
        data=dict(market=market,endpoint='open-interest-history',interval='1hour',rows=rows)
        raw=json.dumps(data).encode();(self.root/'series.json').write_bytes(raw)
        manifest=dict(schema='coinalyze-research-v1',cutoff=30*3600,markets=[market],
            series={'ABC_PERP.A|open-interest-history|1hour':dict(status='ok',file='series.json',
                sha256=hashlib.sha256(raw).hexdigest(),rows=len(rows))})
        path=self.root/'manifest.json';path.write_text(json.dumps(manifest))
        return path

    def test_oi_import_validates_hash_and_does_not_leak_future(self):
        path=self.make_manifest();out=self.root/'oi.json'
        result=import_manifest(path,out)
        self.assertEqual(result['rows'],30)
        oi=OIHistory(out);asset=dict(market='perp',coin='ABC')
        self.assertIsNone(oi.change(asset,25*HOUR))
        self.assertAlmostEqual(oi.change(asset,26*HOUR),.24)
        self.assertIsNone(oi.change(asset,32*HOUR))
        self.assertIsNone(oi.change(dict(market='perp',coin='kABC'),26*HOUR))
        (self.root/'series.json').write_text('{}')
        with self.assertRaises(ValueError):
            import_manifest(path,out)


if __name__=='__main__':
    unittest.main()
