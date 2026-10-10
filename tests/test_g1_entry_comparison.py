"""Pure entry/report regressions: causality, missing data, costs and cohort isolation."""
import copy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import g1_entry as entry
from research.g1_entry_comparison import summarize, ms, paired_ci, regime, render_text
from research.g1_entry_replay import replay

NOW = '2026-10-11T12:00:00+00:00'


def fixture(eid='a', day=1, up=False):
    delivery = datetime(2026, 10, day, 12, 0, 12, tzinfo=timezone.utc)
    start = entry.ceil_bar(ms(delivery), entry.MINUTE)
    end = ms(delivery+timedelta(hours=4))//entry.MINUTE*entry.MINUTE
    e = dict(event_id=eid, strategy='G1', symbol='AAAUSDT', direction='LONG', market='um_perp',
        universe='all_active_usdm_perpetuals', config_version=entry.CONFIG_VERSION,
        measurement_version=entry.MEASUREMENT, delivery_evidence='confirmed',
        entry_study_origin='forward_live_delivery', started_at=delivery.isoformat(),
        expires_at=(delivery+timedelta(hours=4)).isoformat(), tracking_start_ms=start,
        next_start_ms=end, status='expired')
    bars = [dict(open_time=t, open=100., high=101., low=99., close=100.5 if up else 99.5)
            for t in range(start, end, entry.MINUTE)]
    return e, bars


def measured(eid='a', day=1, up=False):
    e, bars = fixture(eid, day, up)
    entry.advance_entry_shadow(e, bars)
    entry.finish_entry_shadow(e)
    return e


class EntryComparisonTests(unittest.TestCase):
    def report(self, events, **kwargs):
        return summarize(events, as_of=NOW, **kwargs)

    def test_missing_not_zero_and_pairs_use_same_events(self):
        a, b = measured('a'), measured('b')
        b['entry_shadow']['plans'].pop('immediate')
        r = self.report([a, b])
        self.assertEqual(r['plans']['immediate']['n_observed_opportunities'], 1)
        self.assertEqual(r['plans']['immediate']['counts']['unavailable'], 1)
        self.assertEqual(r['plans']['confirm_5m']['n_observed_opportunities'], 2)
        self.assertEqual(r['plans']['confirm_5m']['paired_vs_immediate']['n'], 1)
        self.assertEqual(r['plans']['confirm_5m']['costs_ex_funding']['40']['per_observed_opportunity']['mean'], 0.)
        self.assertIsNone(r['plans']['confirm_5m']['costs_ex_funding']['40']['per_entered_trade']['mean'])

    def test_pending_early_tp_and_overdue_missing_remain_separate(self):
        e, bars = fixture()
        bars[0].update(high=104., close=103.)
        entry.advance_entry_shadow(e, bars[:1])
        e.update(status='active', next_start_ms=e['tracking_start_ms']+entry.MINUTE)
        r = summarize([e], as_of='2026-10-01T12:05:00+00:00')
        self.assertEqual(r['n_pending'], 1)
        self.assertEqual(r['plans']['immediate']['n_entered'], 0)
        r = self.report([e])
        self.assertEqual(r['n_matured_incomplete'], 1)
        self.assertEqual(r['plans']['immediate']['counts']['unavailable'], 1)

    def test_old_config_wrong_market_universe_proxy_and_future_excluded(self):
        rows = []
        for i, change in enumerate([{'config_version':'legacy'}, {'market':'spot'},
            {'universe':'core30'}, {'entry_study_origin':'retrospective_proxy'},
            {'started_at':'2027-01-01T00:00:00+00:00'}, {'delivery_evidence':'unconfirmed'}]):
            rows.append({**measured(str(i)), **change})
        self.assertEqual(self.report(rows)['n_total'], 0)

    def test_duplicates_identical_dedup_conflict_excluded(self):
        e = measured()
        self.assertEqual(self.report([e, copy.deepcopy(e)])['n_total'], 1)
        other = copy.deepcopy(e)
        other['entry_shadow']['plans']['wait_5m']['gross_pct'] = 999.
        r = self.report([e, other])
        self.assertEqual(r['n_total'], 0)
        self.assertEqual(r['excluded']['conflicting_duplicate_records'], 2)

    def test_costs_and_counterfactual_missed_winner(self):
        e, bars = fixture()
        bars[16].update(high=104., close=103.)
        entry.advance_entry_shadow(e, bars)
        entry.finish_entry_shadow(e)
        r = self.report([e])
        p = r['plans']['confirm_15m']
        self.assertEqual(p['counts']['no_entry'], 1)
        self.assertEqual(p['no_entry_vs_same_time_wait']['missed_net_winner'], 1)
        self.assertAlmostEqual(r['plans']['wait_15m']['costs_ex_funding']['20']['per_entered_trade']['mean'], 2.8)
        self.assertAlmostEqual(r['plans']['wait_15m']['costs_ex_funding']['40']['per_entered_trade']['mean'], 2.6)
        self.assertEqual(r['funding'], 'not_modeled')

    def test_stop_first_ambiguity_and_gap_preserved(self):
        e, bars = fixture(up=True)
        bars[0].update(high=104., low=97.)
        bars[5].update(open=100.,high=104.,low=97.)
        bars[16].update(open=96.,high=97.,low=95.,close=96.)
        entry.advance_entry_shadow(e, bars)
        entry.finish_entry_shadow(e)
        r = self.report([e])
        p = r['plans']['immediate']
        self.assertEqual(p['counts']['AMBIGUOUS_SL'], 1)
        self.assertEqual((p['tp_first_lower_pct'],p['tp_first_upper_pct']), (0., 100.))
        self.assertEqual(r['plans']['wait_15m']['counts']['SL_GAP'], 1)
        self.assertAlmostEqual(r['plans']['wait_15m']['costs_ex_funding']['40']['per_entered_trade']['mean'], -4.4)

    def test_confirmation_does_not_read_entry_close(self):
        e, bars = fixture()
        bars[5].update(close=104., high=105.)  # Cannot retroactively confirm first five.
        entry.advance_entry_shadow(e, bars)
        self.assertEqual(e['entry_shadow']['plans']['confirm_5m']['status'], 'no_entry')

    def test_path_stops_at_exit_and_late_instrumentation_unknown(self):
        e, bars = fixture(up=True)
        bars[1].update(high=104., low=99.)
        bars[2].update(high=200., low=1.)
        entry.advance_entry_shadow(e, bars)
        p = e['entry_shadow']['plans']['immediate']['path']
        self.assertEqual(p['n_bars'], 2)
        self.assertAlmostEqual(p['mfe_full_bar_pct'], 4.)
        self.assertAlmostEqual(p['mae_full_bar_pct'], -1.)
        late, latebars = fixture('late')
        entry.advance_entry_shadow(late, latebars[:5])
        del late['entry_shadow']['plans']['immediate']['path']
        entry.advance_entry_shadow(late, latebars[5:])
        entry.finish_entry_shadow(late)
        p = self.report([late])['plans']['immediate']['path']
        self.assertEqual(p['n_available'], 0)
        self.assertEqual(p['n_unavailable'], 1)

    def test_timeout_all_plans_same_deadline_not_entry_plus_four_hours(self):
        e = measured(up=True)
        for p in e['entry_shadow']['plans'].values():
            self.assertEqual(p['status'], 'TIMEOUT')
            self.assertEqual(p['exit_time_upper_ms'], e['next_start_ms'])
        self.assertEqual(e['entry_shadow']['plans']['wait_15m']['path']['n_bars'], 224)

    def test_regime_timestamp_and_unknown(self):
        e = measured()
        e.update(market_regime='BULL',market_regime_data_close_at='2026-09-30T23:59:59+00:00')
        self.assertEqual(regime(e), 'BULL')
        for time in ('2026-10-02T00:00:00+00:00','2026-09-01T00:00:00+00:00',None):
            e['market_regime_data_close_at'] = time
            self.assertEqual(regime(e), 'UNKNOWN')

    def test_deterministic_secret_free_and_replay_cannot_open_gate(self):
        e = measured(); e['token'] = 'PRIVATE_MARKER'
        a = self.report([e]); b = self.report([e])
        self.assertEqual(a, b)
        self.assertNotIn('PRIVATE_MARKER', json.dumps(a)+render_text(a))
        self.assertFalse(self.report([e], mode='retrospective')['readiness_gate'])

    def test_no_false_ci_and_repeatable_weekly_bootstrap(self):
        self.assertIsNone(paired_ci([(measured(), 1.)])['low'])
        pairs = []
        for i in range(5):
            e = {'started_at':(datetime(2026,1,1,tzinfo=timezone.utc)+timedelta(days=i*7)).isoformat()}
            pairs.append((e, float(i)))
        self.assertEqual(paired_ci(pairs), paired_ci(list(reversed(pairs))))
        self.assertIsNotNone(paired_ci(pairs)['low'])

    def test_gate_requires_complete_days_and_never_validates(self):
        rows = []
        for i in range(31):
            e = measured(str(i))
            delta = timedelta(days=i*4)
            offset = int(delta.total_seconds()*1000)
            for key in ('started_at', 'expires_at'):
                e[key] = (datetime.fromisoformat(e[key])+delta).isoformat()
            for key in ('tracking_start_ms','next_start_ms'):
                e[key] += offset
            for p in e['entry_shadow']['plans'].values():
                for key in ('entry_time_ms','exit_time_upper_ms'):
                    if p.get(key) is not None:
                        p[key] += offset
            for b in e['entry_shadow']['minutes']:
                b['open_time'] += offset
            rows.append(e)
        report = summarize(rows, as_of='2027-03-01T00:00:00+00:00')
        self.assertTrue(report['readiness_gate'])
        self.assertFalse(report['validated'])
        self.assertFalse(summarize(rows, as_of='2027-03-01T00:00:00+00:00', mode='retrospective')['readiness_gate'])
        for e in rows[1:]:
            e['next_start_ms'] = e['tracking_start_ms']
        self.assertFalse(summarize(rows, as_of='2027-03-01T00:00:00+00:00')['readiness_gate'])

    def test_malformed_plan_is_unavailable(self):
        for value in ([], 'bad', None):
            e = measured(); e['entry_shadow'] = value
            self.assertEqual(self.report([e])['plans']['immediate']['counts']['unavailable'], 1)

    def test_replay_missing_cache_is_unknown_and_does_not_write(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            snapshot=dict(published_at=NOW,rows=[dict(event_id='abc',symbol='AAAUSDT',strategy='G1',
                delivered_at='2026-10-01T12:00:12+00:00',delivery_confirmed=True)])
            (root/'snapshot.json').write_text(json.dumps(snapshot),encoding='utf-8')
            before=set(root.rglob('*'))
            events, meta=replay(root)
            self.assertEqual(events, [])
            self.assertEqual(meta['unknown'], {'missing_cache':1})
            self.assertFalse(meta['network_used'])
            self.assertEqual(before,set(root.rglob('*')))

    def test_replay_bad_hash_aborts(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); cache=root/'minute_cache'; cache.mkdir()
            snapshot=dict(published_at=NOW,rows=[dict(event_id='abc',symbol='AAAUSDT',strategy='G1',
                delivered_at='2026-10-01T12:00:12+00:00',delivery_confirmed=True)])
            (root/'snapshot.json').write_text(json.dumps(snapshot),encoding='utf-8')
            (cache/'abc.json').write_text('[]',encoding='utf-8')
            (cache/'abc.metadata.json').write_text(json.dumps({'sha256':'wrong','params':{}}),encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'cache_mismatch'):
                replay(root)


if __name__ == '__main__':
    unittest.main()
