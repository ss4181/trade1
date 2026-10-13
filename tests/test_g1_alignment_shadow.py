import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import g1_alignment_shadow as study

H = study.HOUR
M = study.MINUTE
B = 400000 * H


def hours():
    return [[B-25*H+i*H, 100+i, 102+i, 99+i, 100+i, 1,
             B-24*H+i*H-1, 300 if i == 24 else 100, 1, 1, 50, 0] for i in range(25)]


def metrics(aligned=113):
    oi = [dict(timestamp=B-2*H, sumOpenInterest='100'),
          dict(timestamp=B-H, sumOpenInterest='110'), dict(timestamp=B, sumOpenInterest=str(aligned))]
    ls = [dict(timestamp=B-H, longShortRatio='.8'), dict(timestamp=B, longShortRatio='.9')]
    return oi, ls


class AlignmentTests(unittest.TestCase):
    def setUp(self):
        self.now = B-10_000
        self.calls = []
        self.aligned = 113

    def fetch(self, endpoint, params):
        self.calls.append((endpoint, params))
        if endpoint.endswith('exchangeInfo'):
            return dict(symbols=[dict(symbol='TESTUSDT', status='TRADING', contractType='PERPETUAL', quoteAsset='USDT')])
        if endpoint.endswith('24hr'):
            return [dict(symbol='TESTUSDT', priceChangePercent='24')]
        if endpoint.endswith('openInterestHist'):
            return metrics(self.aligned)[0]
        if endpoint.endswith('globalLongShortAccountRatio'):
            return metrics(self.aligned)[1]
        if params.get('interval') == '1h':
            return hours()
        return [[t, 100, 101, 99, 100, 1, t+M-1, 100, 1, 1, 50, 0]
                for t in range(params['startTime'], params['endTime']+1, M)]

    def make(self, directory):
        return study.AlignmentStudy(Path(directory)/'study.json', Path(directory),
                                    fetch=self.fetch, clock=lambda:self.now)

    def test_old_and_boundary_metrics_are_distinct(self):
        oi, ls = metrics(99)
        r = study.evaluate(hours(), oi, ls, B, 1, B+75_000)
        self.assertEqual(r['legacy_lag']['status'], 'ACTIVE')
        self.assertEqual(r['aligned']['status'], 'INACTIVE')
        self.assertAlmostEqual(r['legacy_lag']['oi_change'], .1)
        self.assertAlmostEqual(r['aligned']['oi_change'], -.1)
        self.assertEqual(r['aligned']['oi_times_ms'], [B-H, B])

    def test_no_boundary_substitute_or_future_metric(self):
        oi, ls = metrics()
        r = study.evaluate(hours(), oi[:-1]+[dict(timestamp=B+H,sumOpenInterest='999')], ls, B, 1, B+75_000)
        self.assertEqual(r['aligned']['status'], 'UNKNOWN')
        self.assertEqual(r['legacy_lag']['status'], 'ACTIVE')

    def test_duplicate_gap_nan_and_late_rejected(self):
        oi, ls = metrics()
        for kind in ('duplicate', 'gap', 'nan', 'late'):
            bars, o = hours(), copy.deepcopy(oi)
            if kind == 'duplicate': o.append(o[-1])
            if kind == 'gap': bars.pop(2)
            if kind == 'nan': bars[-1][7] = float('nan')
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                study.evaluate(bars, o, ls, B, 1, B+601_000 if kind == 'late' else B+75_000)

    def test_activation_mid_hour_no_backfill_no_network(self):
        with tempfile.TemporaryDirectory() as d:
            self.now = B+75_000
            s = self.make(d)
            s.tick()
            self.assertFalse(self.calls)
            self.assertFalse(s.state['events'])

    def test_first_minute_reserved(self):
        with tempfile.TemporaryDirectory() as d:
            s = self.make(d)
            self.now = B+5_000
            s.tick()
            self.assertFalse(self.calls)

    def test_restart_dedup_and_separate_variants(self):
        with tempfile.TemporaryDirectory() as d:
            s = self.make(d)
            self.now = B+75_000
            s.tick()
            self.assertEqual(len(s.state['events']), 2)
            self.assertEqual({e['variant'] for e in s.state['events'].values()}, {'legacy_lag', 'aligned'})
            clocks = {e['observed_at_ms'] for e in s.state['events'].values()}
            self.assertEqual(clocks, {self.now})
            s = self.make(d)
            s.tick()
            self.assertEqual(len(s.state['events']), 2)
            self.assertEqual(sum('/24hr' in p for p, _ in self.calls), 1)

    def test_forward_five_plans_pending_and_matured(self):
        with tempfile.TemporaryDirectory() as d:
            s = self.make(d)
            self.now = B+75_000
            s.tick()
            r = study.summarize(s.state, self.now)
            self.assertEqual(r['variants']['aligned']['n_pending'], 1)
            self.now = B+21*M
            s.tick()
            for e in s.state['events'].values():
                self.assertEqual(len(e['entry_shadow']['plans']), 5)
                self.assertEqual(e['entry_shadow']['plans']['confirm_5m']['status'], 'no_entry')
            self.now = B+4*H+3*M
            s.tick()
            r = study.summarize(s.state, self.now)
            self.assertEqual(r['variants']['aligned']['n_matured'], 1)
            self.assertEqual(r['variants']['aligned']['plans']['immediate']['counts'], {'TIMEOUT':1})
            self.assertFalse(r['validated'])

    def test_absent_aligned_retry_timeout_is_unknown_not_event(self):
        with tempfile.TemporaryDirectory() as d:
            s = self.make(d)
            orig = self.fetch
            def incomplete(p, q):
                value = orig(p, q)
                return value[:-1] if p.endswith('openInterestHist') else value
            s.fetch = incomplete
            self.now = B+75_000
            s.tick()
            self.assertFalse(s.state['events'])
            self.now = B+H+75_000
            s.tick()
            self.assertEqual(s.state['hours'][str(B)]['results']['TESTUSDT']['status'], 'UNKNOWN')
            self.assertEqual(study.summarize(s.state, self.now)['unknown_hours'], 1)

    def test_missing_minute_never_negative_outcome(self):
        with tempfile.TemporaryDirectory() as d:
            s = self.make(d)
            self.now = B+75_000
            s.tick()
            orig = self.fetch
            def missing(p, q):
                value = orig(p, q)
                return value[:-1] if q.get('interval') == '1m' else value
            s.fetch = missing
            self.now = B+20*M
            s.tick()
            for e in s.state['events'].values():
                self.assertEqual(e['data_status'], 'UNKNOWN')
                self.assertNotIn('entry_shadow', e)

    def test_journal_failure_cannot_move_frozen_entry_on_restart(self):
        with tempfile.TemporaryDirectory() as d:
            s = self.make(d)
            self.now = B+75_000
            with patch.object(s, 'journal', side_effect=OSError('DO_NOT_LOG_SECRET')):
                s.tick()
            self.assertEqual(len(s.state['events']), 2)
            self.now += 60_000
            s = self.make(d)
            s.tick()
            self.assertEqual({e['observed_at_ms'] for e in s.state['events'].values()}, {B+75_000})

    def test_unchanged_live_state_and_no_credentials_or_private_endpoint(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            old = root/'.experiment_state.json'
            old.write_text('user state')
            s = self.make(d)
            with self.assertRaises(ValueError): s.get('/fapi/v1/order')
            self.now = B+75_000
            s.tick()
            self.assertEqual(old.read_text(), 'user state')
            self.assertTrue(all(p.startswith(('/fapi/v1/', '/futures/data/')) for p, _ in self.calls))

    def test_corrupt_or_different_protocol_state_preserved(self):
        with tempfile.TemporaryDirectory() as d:
            s = self.make(d)
            text = s.path.read_text()
            data = json.loads(text)
            data['rule_hash'] = 'changed'
            s.path.write_text(json.dumps(data))
            with self.assertRaises(ValueError): self.make(d)
            self.assertEqual(json.loads(s.path.read_bytes())['rule_hash'], 'changed')

    def test_cancelled_worker_performs_no_fetch(self):
        import threading
        with tempfile.TemporaryDirectory() as d:
            s = self.make(d)
            self.now = B+75_000
            stop = threading.Event()
            stop.set()
            s.tick(stop)
            self.assertFalse(self.calls)

    def test_rate_limit_stops_candidate_round(self):
        class MarketRateLimitError(Exception): pass
        with tempfile.TemporaryDirectory() as d:
            s = self.make(d)
            self.now = B+75_000
            self.state_input = {'candidates':[{'rank':1,'symbol':'AUSDT'}, {'rank':2,'symbol':'BUSDT'}],
                'results':{}, 'ranking_observed_ms':self.now, 'done':False}
            s.state['hours'][str(B)] = self.state_input
            calls=[]
            def blocked(p, q):
                calls.append(p)
                raise MarketRateLimitError('NEVER_LOG_KEY')
            s.fetch=blocked
            s.tick()
            self.assertEqual(len(calls), 1)
            self.assertEqual(s.status['last_error'], 'candidate_data_unavailable')

    def test_bot_worker_lifecycle_isolated_from_live_scan(self):
        import signal_bot as bot
        from unittest.mock import Mock
        fake = Mock()
        fake.status = {'research_only':True}
        with patch.object(bot, 'SHADOW_EXPERIMENTS_ENABLED', True), \
                patch.object(bot, 'G1_ALIGNMENT_SHADOW_ENABLED', True), \
                patch.object(bot, 'EXECUTION_SHADOW_ENABLED', False), \
                patch.object(bot, 'ENABLE_TELEGRAM', False), patch.object(bot, 'G2_ENABLED', False), \
                patch.object(bot, '_run_forever_locked'), patch.object(bot, 'DeliveryRetryWorker') as worker, \
                patch.object(bot.g1_alignment_shadow, 'AlignmentStudy', return_value=fake), \
                patch.object(bot, '_acquire_instance_file_lock', return_value=Mock()), \
                patch.object(bot, '_release_instance_file_lock'):
            bot.run_forever()
            self.assertTrue(worker.return_value.start.called)
            self.assertTrue(worker.return_value.stop.called)
            self.assertIsNone(bot._g1_alignment_worker)
            self.assertIsNone(bot._g1_alignment_study)

    def test_once_mode_never_creates_alignment_state(self):
        import signal_bot as bot
        from unittest.mock import Mock
        with patch.object(bot, 'SHADOW_EXPERIMENTS_ENABLED', True), \
                patch.object(bot, 'G1_ALIGNMENT_SHADOW_ENABLED', True), \
                patch.object(bot, '_run_forever_locked'), \
                patch.object(bot.g1_alignment_shadow, 'AlignmentStudy') as constructor, \
                patch.object(bot, '_acquire_instance_file_lock', return_value=Mock()), \
                patch.object(bot, '_release_instance_file_lock'):
            bot.run_forever(once=True)
            constructor.assert_not_called()


if __name__ == '__main__': unittest.main()
