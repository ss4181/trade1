"""No network: streaming order, bounded reads, decision parity and worker lifecycle."""
from contextlib import ExitStack
from datetime import datetime, timezone, timedelta
import threading
import time
import unittest
from unittest.mock import Mock, patch
import signal_bot as bot


class FastNotificationTests(unittest.TestCase):
    def setup_scan(self, stack, core, observed=()):
        for name, value in {'SYMBOLS':core,'OBSERVE_SYMBOLS':list(observed),
                            'OBSERVE_ENABLED':bool(observed),'OBSERVE_PUSH':True,
                            'MAX_PUSH_PER_SCAN':10000,'OBSERVE_MAX_PUSH_PER_SCAN':10000,
                            'SCAN_STREAMING_ENABLED':True,'SCAN_WORKERS':3}.items():
            stack.enter_context(patch.object(bot,name,value))

    def test_ready_core_and_observation_do_not_wait_for_slow_coin(self):
        release=threading.Event()
        timeline=[]
        def scan(symbol,state,observe=False,defer_shadow=False):
            if symbol=='SLOW':
                if not release.wait(3):raise AssertionError('ready alerts blocked behind slow coin')
            timeline.append(('scanned',symbol))
            return [{'strategy':'S5' if observe else 'S1','symbol':symbol,'confidence':'GOZLEM' if observe else 'YUKSEK'}]
        def notify(sig,push=True):
            timeline.append(('sent',sig['symbol']))
            sent={s for kind,s in timeline if kind=='sent'}
            if {'FAST','OBS'}<=sent:release.set()
        state=Mock()
        with ExitStack() as stack:
            self.setup_scan(stack,['SLOW','FAST'],['OBS'])
            stack.enter_context(patch.object(bot,'scan_symbol',side_effect=scan))
            stack.enter_context(patch.object(bot,'notify',side_effect=notify))
            self.assertEqual(bot.scan_all(state),2)
        self.assertLess(timeline.index(('sent','FAST')),timeline.index(('scanned','SLOW')))
        self.assertLess(timeline.index(('sent','OBS')),timeline.index(('scanned','SLOW')))
        state.save.assert_called_once()

    def test_same_engine_signals_cooldowns_and_no_repeated_alerts(self):
        symbols=['BTCUSDT','ETHUSDT','ARBUSDT']
        stamp=int(datetime(2026,9,16,12,tzinfo=timezone.utc).timestamp()*1000)
        candles=[dict(open_time=stamp-(250-i)*3600000,open=100.,high=102.,low=99.,close=101.,volume=10.) for i in range(250)]
        outputs=[];states=[]
        with ExitStack() as stack:
            self.setup_scan(stack,symbols)
            for name,value in {'DISABLED_STRATEGIES':set(),'EXTENDED_SET':set(),
                               'S2_DERIVATIVES_SHADOW_ENABLED':False}.items():
                stack.enter_context(patch.object(bot,name,value))
            stack.enter_context(patch.object(bot,'fetch_klines',return_value=candles))
            stack.enter_context(patch.object(bot,'fetch_funding',return_value=[]))
            stack.enter_context(patch.object(bot,'calc_rsi',return_value=[20.]*250))
            stack.enter_context(patch.object(bot,'calc_volume_zscore',return_value=[0.]*250))
            stack.enter_context(patch.object(bot,'bullish_divergence',return_value=True))
            stack.enter_context(patch.object(bot.time,'sleep'))
            for fast in (False,True):
                state=bot.ScanState();state.save=Mock()
                state.prev_cond.update({('S1',s):False for s in symbols})
                sent=[]
                with patch.object(bot,'SCAN_STREAMING_ENABLED',fast),patch.object(bot,'notify',side_effect=lambda sig,**kw:sent.append(sig.copy())):
                    bot.scan_all(state)
                    self.assertEqual(len(sent),3)
                    bot.scan_all(state)
                    self.assertEqual(len(sent),3)
                outputs.append(sorted((s['strategy'],s['symbol'],s['price'],s['bar_time'],s['confidence']) for s in sent))
                states.append(state)
        self.assertEqual(outputs[0],outputs[1])
        self.assertEqual(states[0].prev_cond,states[1].prev_cond)
        self.assertEqual(set(states[0].last_fire),set(states[1].last_fire))

    def test_parallelism_is_bounded_and_state_saved_after_join(self):
        active=peak=0
        lock=threading.Lock()
        def scan(*args,**kwargs):
            nonlocal active,peak
            with lock:active+=1;peak=max(peak,active)
            time.sleep(.01)
            with lock:active-=1
            return []
        state=Mock()
        state.save.side_effect=lambda:self.assertEqual(active,0)
        with ExitStack() as stack:
            self.setup_scan(stack,[str(i) for i in range(20)])
            stack.enter_context(patch.object(bot,'scan_symbol',side_effect=scan))
            bot.scan_all(state)
        self.assertGreater(peak,1)
        self.assertLessEqual(peak,3)

    def test_research_capture_runs_after_delivery_and_private_job_not_sent(self):
        order=[]
        sig={'strategy':'S2','symbol':'BTCUSDT','confidence':'DUSUK','_s2_shadow_job':('BTCUSDT','BTCUSDT',[])}
        def notify(record,**kwargs):
            self.assertNotIn('_s2_shadow_job',record)
            order.append('notify')
        with ExitStack() as stack:
            self.setup_scan(stack,['BTCUSDT'])
            stack.enter_context(patch.object(bot,'scan_symbol',return_value=[sig]))
            stack.enter_context(patch.object(bot,'notify',side_effect=notify))
            stack.enter_context(patch.object(bot,'_capture_s2_shadow',side_effect=lambda *args:order.append('archive')))
            bot.scan_all(Mock())
        self.assertEqual(order,['notify','archive'])

    def test_shared_service_failure_stops_starting_more_network_work(self):
        state=Mock()
        with ExitStack() as stack:
            self.setup_scan(stack,[str(i) for i in range(40)])
            scan=stack.enter_context(patch.object(bot,'scan_symbol',side_effect=bot.MarketRateLimitError('429')))
            with self.assertRaises(bot.MarketRateLimitError):bot.scan_all(state)
        self.assertLessEqual(scan.call_count,3)
        self.assertEqual(bot.LAST_SCAN_SUCCEEDED_SYMBOLS,0)
        state.save.assert_called_once()

    def test_g2_clock_runs_while_main_scan_is_busy_and_joins_before_unlock(self):
        arrived=threading.Event()
        workers=[]
        def main(**kwargs):
            workers.append(bot._g2_worker)
            self.assertTrue(arrived.wait(3))
        def released(_):self.assertFalse(workers[0].thread.is_alive())
        with ExitStack() as stack:
            for name,value in {'G2_ENABLED':True,'SHADOW_EXPERIMENTS_ENABLED':True,'ENABLE_TELEGRAM':False}.items():
                stack.enter_context(patch.object(bot,name,value))
            stack.enter_context(patch.object(bot,'_poll_g2_notifications',side_effect=lambda *_:arrived.set()))
            stack.enter_context(patch.object(bot,'_run_forever_locked',side_effect=main))
            stack.enter_context(patch.object(bot,'_acquire_instance_file_lock',return_value=object()))
            stack.enter_context(patch.object(bot,'_release_instance_file_lock',side_effect=released))
            bot.run_forever()

    def test_g1_alert_is_sent_before_slow_delist_lookup(self):
        sent=[]
        def delists(*args,**kwargs):
            self.assertEqual(sent,['G1'])
            return []
        with patch.object(bot,'SHADOW_EXPERIMENTS_ENABLED',True),patch.object(bot,'scan_shadow_gainers',return_value=[{'strategy':'G1','symbol':'BTCUSDT'}]),patch.object(bot,'poll_shadow_delists',side_effect=delists),patch.object(bot,'notify',side_effect=lambda sig,**kw:sent.append(sig['strategy'])):
            self.assertEqual(bot.run_shadow_experiments(),1)

    def test_telegram_paces_same_recipient_without_global_sleep(self):
        clock=[100.]
        sent=[]
        with patch.object(bot,'ENABLE_TELEGRAM',True),patch.object(bot,'_telegram_chat_gates',{}),patch.object(bot,'TELEGRAM_MIN_INTERVAL_SECONDS',1.05),patch.object(bot.time,'monotonic',side_effect=lambda:clock[0]),patch.object(bot.time,'sleep',side_effect=lambda n:clock.__setitem__(0,clock[0]+n)),patch.object(bot,'_telegram_send_text_unpaced',side_effect=lambda *a,**kw:sent.append(clock[0]) or True):
            bot._telegram_send_text('test','a')
            bot._telegram_send_text('test','a')
            bot._telegram_send_text('test','b')
        self.assertEqual(sent,[100.,101.05,101.05])


if __name__=='__main__':unittest.main()
