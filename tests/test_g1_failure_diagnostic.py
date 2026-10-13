"""Offline checks for descriptive G1 diagnostics; never import the running bot."""
import unittest
from research.diagnose_g1_failures import (
    HOUR, MINUTE, PublicData, aligned_metrics, bracket, complete_path,
    parse_bars, summary, utc,
)


class DiagnosticTests(unittest.TestCase):
    def bar(self, t=0, o=100., h=101., l=99., c=100.):
        return {'open_time': t, 'open': o, 'high': h, 'low': l, 'close': c}

    def test_timezone_required(self):
        with self.assertRaises(ValueError): utc('2026-10-13T10:00:00')

    def test_missing_path_is_not_zero_or_loss(self):
        with self.assertRaises(ValueError): complete_path({0:self.bar()}, 0, 2*MINUTE)

    def test_no_future_candle(self):
        row=[MINUTE,'100','101','99','100','1',2*MINUTE-1,'100',1,'1','50','0']
        with self.assertRaises(ValueError): parse_bars([row], MINUTE, 0, MINUTE)

    def test_duplicate_candle_rejected(self):
        row=[0,'100','101','99','100','1',MINUTE-1,'100',1,'1','50','0']
        with self.assertRaises(ValueError): parse_bars([row,row], MINUTE, 0, MINUTE)

    def test_intrabar_stop_first(self):
        result=bracket([self.bar(h=104,l=97)],100)
        self.assertEqual(result['status'],'AMBIGUOUS_SL')
        self.assertAlmostEqual(result['net40_ex_funding_pct'],-2.4)

    def test_gap_stop_uses_worse_open(self):
        result=bracket([self.bar(o=95,h=101,l=94,c=100)],100)
        self.assertEqual(result['status'],'SL_GAP')
        self.assertAlmostEqual(result['gross_pct'],-5.)

    def test_known_open_target_precedes_low(self):
        result=bracket([self.bar(o=104,h=105,l=97)],100)
        self.assertEqual(result['status'],'TP')

    def test_pending_is_not_timeout(self):
        result=bracket([self.bar()],100,matured=False)
        self.assertEqual(result['status'],'pending')
        self.assertIsNone(result['gross_pct'])

    def test_boundary_minus_one_excludes_hour_snapshot(self):
        end=3*HOUR
        oi=[{'timestamp':HOUR,'sumOpenInterest':'100'},
            {'timestamp':2*HOUR,'sumOpenInterest':'110'},
            {'timestamp':3*HOUR,'sumOpenInterest':'99'}]
        ls=[{'timestamp':2*HOUR,'longShortRatio':'.9'},
            {'timestamp':3*HOUR,'longShortRatio':'1.1'}]
        result=aligned_metrics(oi,ls,end)
        old=result['current_code_cutoff']; new=result['completed_hour_boundary']
        self.assertAlmostEqual(old['oi_change_pct'],10.)
        self.assertEqual(old['oi_latest_age_minutes'],60)
        self.assertAlmostEqual(new['oi_change_pct'],-10.)
        self.assertEqual(new['ls_ratio'],1.1)
        self.assertFalse(result['historical_publication_time_known'])

    def test_missing_metrics_unavailable(self):
        result=aligned_metrics([],[],3*HOUR)
        self.assertIsNone(result['current_code_cutoff']['oi_change_pct'])
        self.assertIsNone(result['completed_hour_boundary']['ls_ratio'])

    def test_summary_excludes_pending_even_if_plan_closed(self):
        rows=[{'delivered_at':'2026-10-13T10:00:00+00:00','matured':True,
               'immediate':{'status':'TP','net40_ex_funding_pct':2.6}},
              {'delivered_at':'2026-10-13T11:00:00+00:00','matured':False,
               'immediate':{'status':'SL','net40_ex_funding_pct':-2.4}}]
        result=summary(rows)
        self.assertEqual(result['n_pending'],1)
        self.assertEqual(result['immediate']['counts'],{'TP':1})
        self.assertAlmostEqual(result['immediate']['net40_ex_funding_pct']['mean'],2.6)

    def test_private_write_endpoint_refused(self):
        provider=PublicData(None,False)
        with self.assertRaises(ValueError): provider.get('/fapi/v1/order',{})


if __name__ == '__main__': unittest.main()
