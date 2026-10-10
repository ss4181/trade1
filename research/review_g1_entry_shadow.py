"""Summarize frozen forward G1 entries. No orders or live confidence score."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import statistics
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from g1_entry import MEASUREMENT


def summarize(events):
    cohort = [e for e in events if isinstance(e,dict) and e.get('strategy')=='G1'
              and e.get('measurement_version')==MEASUREMENT
              and e.get('delivery_evidence')=='confirmed']
    completed = [e for e in cohort if e.get('status')=='expired']
    times = sorted(datetime.fromisoformat(e['started_at']).astimezone(timezone.utc) for e in cohort)
    days = len({e['started_at'][:10] for e in completed})
    span = (times[-1]-times[0]).total_seconds()/86400 if times else 0.
    plans = {}
    for key in ('immediate','wait_5m','wait_15m','confirm_5m','confirm_15m'):
        counts = Counter()
        returns = []
        for e in completed:
            plan = e.get('entry_shadow',{}).get('plans',{}).get(key)
            if not plan:
                counts['unavailable'] += 1
            elif plan['status']=='no_entry':
                counts['no_entry'] += 1
                returns.append(0.)  # Research opportunity not traded: zero, not a winning trade.
            elif plan['status'] in ('TP','SL','SL_GAP','AMBIGUOUS_SL','TIMEOUT') and 'gross_pct' in plan:
                counts[plan['status']] += 1
                returns.append(plan['gross_pct']-.4)
            else:
                counts['unavailable'] += 1
        n = sum(counts[k] for k in ('TP','SL','SL_GAP','AMBIGUOUS_SL','TIMEOUT'))
        plans[key] = dict(counts=dict(counts),n_entered=n,n_opportunities=len(completed),
            tp_first_lower_pct=100*counts['TP']/n if n else None,
            tp_first_upper_pct=100*(counts['TP']+counts['AMBIGUOUS_SL'])/n if n else None,
            mean_net40_per_observed_opportunity_ex_funding_pct=statistics.mean(returns) if returns else None,
            sample_warning='small_sample' if n<30 or days<28 or span<90 else 'forward_sample_not_yet_validated')
    return dict(schema_version='g1-entry-shadow-report-v1',n_total=len(cohort),n_matured=len(completed),
        n_pending=sum(e.get('status')=='active' for e in cohort),event_days=days,span_days=round(span,1),
        readiness_gate=span>=90 and len(completed)>=30 and days>=28,
        funding='not_modeled',live_filter_enabled=False,plans=plans)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state',type=Path,default=Path(__file__).resolve().parents[1]/'.price_target_state.json')
    args=parser.parse_args()
    if not args.state.exists():
        print('G1 ileri giriş ölçümü henüz yok; yeni sürümde taze kotasyonlu teslimler bekleniyor.')
        return 0
    data=json.loads(args.state.read_text(encoding='utf-8'))
    print(json.dumps(summarize(data.get('events',{}).values()),ensure_ascii=False,indent=2))
    return 0


if __name__=='__main__':
    raise SystemExit(main())
