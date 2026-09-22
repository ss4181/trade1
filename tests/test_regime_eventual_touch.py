import unittest
import pandas as pd
from research.regime_eventual_touch import evaluate, summarize, HOUR


class EventualTouchTests(unittest.TestCase):
    def frame(self):
        return pd.DataFrame({"open_time":[i*HOUR for i in range(8)], "open":100.,
                             "high":[101.,101.,102.,101.,101.,103.,101.,101.], "valid":True})

    def test_late_hits_are_success_and_cutoff_is_respected(self):
        frame=self.frame()
        result=evaluate(frame,0,8*HOUR,HOUR)
        self.assertEqual((result["tp2"],result["tp3"]),("hit","hit"))
        self.assertEqual(result["tp3_hours_upper"],6.)
        early=evaluate(frame,0,5*HOUR,HOUR)
        self.assertEqual(early["tp3"],"pending")
        self.assertEqual(evaluate(frame,6*HOUR,8*HOUR,HOUR)["tp2"],"pending")

    def test_gaps_preserve_witnessed_hit_but_prevent_miss_claim(self):
        frame=self.frame().drop(index=1)
        result=evaluate(frame,0,8*HOUR,HOUR)
        self.assertEqual(result["tp3"],"hit")
        self.assertFalse(result["complete_coverage"])
        result=evaluate(frame,0,5*HOUR,HOUR)
        self.assertEqual(result["tp3"],"unavailable")

    def test_invalid_entry_and_contract_price_mismatch(self):
        frame=self.frame()
        self.assertEqual(evaluate(frame,HOUR//2,8*HOUR,HOUR)["tp2"],"unavailable")
        with self.assertRaises(ValueError):
            evaluate(frame,0,8*HOUR,HOUR,entry_price=.1)

    def test_pending_stays_in_denominator(self):
        rows=[]
        for i in (0,6):
            out=evaluate(self.frame(),i*HOUR,8*HOUR,HOUR)
            rows.append(dict(strategy="S3",universe="core30",regime="BULL",subtype="bull_strong",
                             time_ms=i*HOUR,horizon=4,**out))
        result=summarize(rows)[0]
        self.assertEqual(result["tp3"]["hit"],1)
        self.assertEqual(result["tp3"]["pending"],1)
        self.assertEqual(result["tp3"]["observed_hit_pct_all"],50.)
        self.assertEqual(result["tp3"]["after_original_horizon"],1)


if __name__=="__main__": unittest.main()
