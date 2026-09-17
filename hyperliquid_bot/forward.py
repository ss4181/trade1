"""Evaluate recorded live candidates separately from retrospective research."""
from engine import HOUR, DAY, evaluate_limit
from research import summary


def outcomes(store, now):
    results=[]
    cache={}
    for signal in store.events():
        market,coin=signal['market'],signal['coin']
        interval='1d' if market=='spot' else '1h'
        key=(market,coin,interval)
        if key not in cache:
            cache[key]=store.candles(*key)
        for hours in signal['horizons_hours']:
            step=DAY if market=='spot' else HOUR
            end=signal['close_ms']+step+hours*HOUR
            result=evaluate_limit(signal,cache[key],hours)
            if result['status']=='UNAVAILABLE' and now<end:
                result['status']='PENDING'
            results.append(dict(**result,id=signal['id'],strategy=signal['strategy'],
                coin=coin,hours=hours,signal_ms=signal['close_ms'],rule_hash=signal['rule_hash']))
    groups={}
    for strategy,hours in (('HL-S',24),('HL-S',48),('HL-D',336),('HL-D',672)):
        rows=[r for r in results if r['strategy']==strategy and r['hours']==hours]
        groups[f'{strategy}_{hours}h']=summary(rows)
    return dict(schema='hl-forward-scenarios-v1',generated_ms=now,results=groups,trades=results,
        evidence='recorded_live_candidates_hypothetical_fills_not_actual_profit',
        limitations=['Historical funding excluded for perpetuals.',
                     'A candidate leaving the current universe may have missing outcome candles.',
                     'Includes locally recorded candidates, not only acknowledged Telegram messages.'])
