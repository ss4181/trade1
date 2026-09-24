import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from datetime import datetime, timedelta, timezone

import dashboard_reporting as reporting
import signal_bot as bot


class DashboardTests(unittest.TestCase):
    def test_publication_refreshes_quotes_before_serializing_and_skips_not_due(self):
        order=[]
        class InlineThread:
            def __init__(self, target, **kwargs): self.target=target
            def start(self): self.target()
        with patch.object(bot,'PUBLISH_ENABLED',True), patch.object(bot,'_last_publish',0), \
             patch.object(bot.threading,'Thread',InlineThread), \
             patch.object(bot,'_refresh_display_prices',side_effect=lambda:order.append('prices')), \
             patch.object(bot,'publish_to_github',side_effect=lambda:order.append('publish')):
            self.assertTrue(bot._start_publish_worker())
            self.assertEqual(order,['prices','publish'])
            with patch.object(bot,'_last_publish',bot.time.time()):
                self.assertFalse(bot._start_publish_worker())
            self.assertEqual(order,['prices','publish'])

    def test_regime_denominators_and_missing_metadata(self):
        records = [dict(event_id=str(i), strategy='G1', delivery_confirmed=True,
                        market_regime='BULL', market_regime_subtype='bull_strong') for i in range(4)]
        events = {
            '0': dict(measurement_version='signal-reference-touch-v1',status='expired',targets={'2':{'hit_at':'yes'},'3':{}}),
            '1': dict(measurement_version='signal-reference-touch-v1',status='expired',targets={'2':{},'3':{}}),
            '2': dict(measurement_version='signal-reference-touch-v1',status='active',targets={'2':{'hit_at':'yes'},'3':{}}),
        }
        result = reporting.live_regime_summary(records + [records[0]], events)['rows'][0]
        self.assertEqual(result['n'], 4)
        self.assertEqual(result['tp2'], dict(hit=1,missed=1,pending=1,unavailable=1,resolved=2,hit_rate_pct=50.))
        records[0].pop('market_regime_subtype')
        self.assertEqual(len(reporting.live_regime_summary(records, events)['rows']), 2)
        records[1]['config_version'] = 'different'
        self.assertEqual(len(reporting.live_regime_summary(records, events)['rows']), 3)

    def test_brackets_are_separate_and_ambiguous_is_not_success(self):
        events = {str(i):dict(measurement_version='g2-scheduled-bracket-v1',g2_bracket={'status':s})
                  for i,s in enumerate(['TP','SL','AMBIGUOUS_SL','TIMEOUT','PENDING','UNAVAILABLE_LATE_DELIVERY'])}
        result = reporting.bracket_summary(events)
        self.assertEqual((result['hit_rate_pct'],result['resolved'],result['pending'],result['unavailable']), (25.,4,1,1))
        records = [dict(event_id='0',strategy='G2',delivery_confirmed=True)]
        self.assertEqual(reporting.live_regime_summary(records,events)['rows'][0]['tp3']['unavailable'],1)

    def test_report_selects_latest_valid_and_projects_no_paths(self):
        with tempfile.TemporaryDirectory() as root:
            folder=Path(root)/'research/results';folder.mkdir(parents=True)
            (folder/'regime_eventual_touch_2026-09-22.json').write_text(json.dumps({
                'version':'eventual-touch-observed-v1','summaries':[], 'source_prices':['private/path']}))
            (folder/'regime_eventual_touch_2026-09-23.json').write_text('{}')
            result=reporting.historical_regime_report(root)
            self.assertTrue(result['available'])
            self.assertNotIn('source_prices',result)

    def test_dashboard_market_alias_event_only_and_waiting_outcome(self):
        now=datetime.now(timezone.utc)
        base=dict(symbol='BTCUSDT', strategy='G1', price=100.,direction='LONG',
                  bar_time=(now-timedelta(hours=2)).isoformat(),horizon_hours=4,
                  signal_market='usd_m_perp',performance_market='um_perp',universe='all_active_usdm_perpetuals')
        records=[dict(base,event_id='live'),dict(base,event_id='event',performance_excluded=True),
                 dict(base,event_id='waiting',bar_time=(now-timedelta(hours=5,minutes=30)).isoformat())]
        with patch.object(bot,'_reporting_signal_records',return_value=records), patch.object(bot,'_load_perf_cache',return_value={}), \
             patch.object(bot,'DISPLAY_PRICES',{('um_perp','BTCUSDT'):(110.,now.timestamp())}), \
             patch.object(bot,'PRICE_TARGET_STATE',{'events':{}}), patch.object(bot,'ENABLE_TELEGRAM',False):
            data=bot.build_dashboard_data()
        rows={r['event_id']:r for r in data['signals']}
        self.assertAlmostEqual(rows['live']['gross_pnl_pct'],10.)
        self.assertEqual(rows['live']['universe'],'all_active_usdm_perpetuals')
        self.assertIsNone(rows['event']['pnl_pct'])
        self.assertEqual(rows['waiting']['status'],'HESAPLANIYOR')
        self.assertIsNone(rows['waiting']['pnl_pct'])
        self.assertTrue(rows['live']['exit_by'].endswith('+00:00'))
        self.assertFalse(any(s['pushed'] for s in data['strategies']))


if __name__ == '__main__':
    unittest.main()
