"""No network: G1 delivery must not wait for a slow coin/core/delist scan."""
from contextlib import ExitStack
from datetime import timedelta
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

import signal_bot as bot
import shadow_experiments as shadow
from test_shadow_experiments import ShadowExperimentTests, Response, klines


class G1LatencyTests(unittest.TestCase):
    def setUp(self):
        fixture = ShadowExperimentTests()
        fixture.setUp()
        self.now, self.oi, self.ls = fixture.now, fixture.oi, fixture.ls

    def fetcher(self, symbols, before=None):
        def fetch(path, params=None):
            if path.endswith('exchangeInfo'):
                return Response({'symbols': [dict(symbol=s, contractType='PERPETUAL',
                    status='TRADING', quoteAsset='USDT') for s in symbols]})
            if path.endswith('ticker/24hr'):
                return Response([dict(symbol=s, priceChangePercent=str(20-i), lastPrice='104.25')
                                 for i, s in enumerate(symbols)])
            if before:
                before(path, params)
            if path.endswith('klines'):
                return Response(klines(self.now))
            if path.endswith('openInterestHist'):
                return Response(self.oi)
            if path.endswith('globalLongShortAccountRatio'):
                return Response(self.ls)
            raise AssertionError(path)
        return fetch

    def test_fast_coin_is_delivered_and_persisted_before_slow_coin_finishes(self):
        release = threading.Event()
        blocked = threading.Event()
        timeline = []
        def before(path, params):
            if params['symbol'] == 'SLOW' and path.endswith('klines'):
                blocked.set()
                if not release.wait(3):
                    raise AssertionError('ready G1 blocked by slow coin')
                timeline.append('slow_finished')
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            def delivered(sig):
                timeline.append(sig['symbol'])
                if sig['symbol'] == 'FAST':
                    self.assertTrue(blocked.wait(1))
                    self.assertIn('FAST', shadow.load_state(root/'state.json')['s7_last_fire'])
                    self.assertEqual(sig['scan_started_at'], self.now.isoformat())
                    self.assertEqual(sig['detected_at'], (self.now+timedelta(seconds=4)).isoformat())
                    self.assertEqual(sig['notification_delay_minutes'], 30.07)
                    release.set()
            fetch = self.fetcher(['SLOW', 'FAST'], before)
            rows = shadow.scan_g1(fetch, root/'state.json', root, self.now, workers=2,
                                  on_signal=delivered, clock=lambda: self.now+timedelta(seconds=4))
            self.assertEqual(len(rows), 2)
            self.assertLess(timeline.index('FAST'), timeline.index('slow_finished'))
            self.assertEqual(shadow.scan_g1(fetch, root/'state.json', root, self.now), [])

    def test_parallel_and_serial_preserve_decisions_ranks_and_limit(self):
        active = peak = 0
        lock = threading.Lock()
        def before(path, params):
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
            time.sleep(.003)
            with lock:
                active -= 1
        decisions = []
        states = []
        for workers in (1, 3):
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                rows = shadow.scan_g1(self.fetcher([f'C{i}' for i in range(12)], before),
                                      root/'s.json', root, self.now, workers=workers)
                decisions.append(sorted((s['symbol'], s['rank_24h'], s['price'], s['bar_time']) for s in rows))
                states.append(shadow.load_state(root/'s.json'))
        self.assertEqual(decisions[0], decisions[1])
        self.assertEqual(states[0], states[1])
        self.assertEqual(len(decisions[0]), 10)
        self.assertGreater(peak, 1)
        self.assertLessEqual(peak, 3)

    def test_concurrent_strategy_saves_keep_both_cooldowns(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'s.json'
            g1, dl1 = shadow.empty_state(), shadow.empty_state()
            g1['s7_last_fire'] = {'FAST': self.now.isoformat()}
            dl1['seen_articles'] = ['article']
            # Both workers loaded the same old state before either finished.
            shadow._save_strategy_state(path, g1, shadow._G1_STATE_KEYS)
            shadow._save_strategy_state(path, dl1, shadow._DL1_STATE_KEYS)
            state = shadow.load_state(path)
            self.assertEqual(state['s7_last_fire'], g1['s7_last_fire'])
            self.assertEqual(state['seen_articles'], ['article'])

    def test_g1_worker_runs_during_main_and_delist_work_and_joins_before_unlock(self):
        arrived = threading.Event()
        worker = []
        def scanning(**kwargs):
            worker.append(bot._g1_worker)
            with bot._shadow_worker_lock:
                self.assertTrue(arrived.wait(3))
        def released(_):
            self.assertFalse(worker[0].thread.is_alive())
        def scan(*args, **kwargs):
            kwargs['on_signal']({'strategy':'G1', 'symbol':'FAST'})
            return []
        with ExitStack() as stack:
            for key, value in {'SHADOW_EXPERIMENTS_ENABLED':True, 'G2_ENABLED':False,
                               'ENABLE_TELEGRAM':False, 'DISABLED_STRATEGIES':set(),
                               'SHADOW_MAX_PUSH_PER_RUN':20}.items():
                stack.enter_context(patch.object(bot, key, value))
            stack.enter_context(patch.object(bot.time, 'time', return_value=100))
            stack.enter_context(patch.object(bot, 'scan_shadow_gainers', side_effect=scan))
            stack.enter_context(patch.object(bot, 'notify', side_effect=lambda *a, **k:arrived.set()))
            stack.enter_context(patch.object(bot, '_run_forever_locked', side_effect=scanning))
            stack.enter_context(patch.object(bot, '_acquire_instance_file_lock', return_value=object()))
            stack.enter_context(patch.object(bot, '_release_instance_file_lock', side_effect=released))
            bot.run_forever()

    def test_g1_boundary_wait_and_small_cap_keep_order(self):
        with patch.object(bot, 'SHADOW_EXPERIMENTS_ENABLED', True), \
             patch.object(bot, 'DISABLED_STRATEGIES', set()), \
             patch.object(bot, 'SCAN_CLOSE_DELAY_SECONDS', 10), \
             patch.object(bot.time, 'time', return_value=5), \
             patch.object(bot, 'scan_shadow_gainers') as scan:
            bot._poll_g1_notifications()
            scan.assert_not_called()
        with patch.object(bot, 'SHADOW_EXPERIMENTS_ENABLED', True), \
             patch.object(bot, 'DISABLED_STRATEGIES', set()), \
             patch.object(bot, 'SHADOW_PUSH_ENABLED', True), \
             patch.object(bot, 'SHADOW_MAX_PUSH_PER_RUN', 1), \
             patch.object(bot.time, 'time', return_value=100), \
             patch.object(bot, 'scan_shadow_gainers', return_value=[{'symbol':'B'}, {'symbol':'A'}]), \
             patch.object(bot, 'notify') as notify:
            bot._poll_g1_notifications()
            self.assertEqual([(c.args[0]['symbol'], c.kwargs['push']) for c in notify.call_args_list],
                             [('A', True), ('B', False)])


if __name__ == '__main__':
    unittest.main()
