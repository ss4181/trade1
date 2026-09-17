"""Frozen research hypotheses, shared by live scans and historical replay."""
from bisect import bisect_right
import hashlib
import json
import statistics
from pathlib import Path

DAY = 86400000
HOUR = 3600000
RULES = {
    'version': 'hl-research-v1', 'btc_sma_fast': 50, 'btc_sma_slow': 200,
    'swing_breakout_hours': 72, 'swing_volume_ratio': 1.5,
    'swing_min_rs_24h': .01, 'swing_max_extension': .08,
    'discovery_breakout_days': 30, 'discovery_volume_ratio': 1.8,
    'discovery_min_rs_7d': .03, 'discovery_max_7d_return': .50,
    'limit_offset_bps': 20, 'penetration_bps': 5,
    'swing_stop_atr': 2, 'discovery_stop_atr': 2.5,
    'reward_risk': 2, 'cooldown_swing_hours': 48, 'cooldown_discovery_days': 28,
}
# Includes implementation and execution assumptions, not only headline parameters.
HASH = hashlib.sha256(Path(__file__).read_bytes().replace(b'\r\n', b'\n')).hexdigest()[:16]


def contiguous(rows, step):
    return all(b['t']-a['t'] == step for a,b in zip(rows, rows[1:]))


def atr(rows, n=14):
    return statistics.mean(max(b['h']-b['l'], abs(b['h']-a['c']),abs(b['l']-a['c']))
                           for a,b in zip(rows[-n-1:-1],rows[-n:]))


class Regime:
    def __init__(self, btc_daily):
        self.ends = [r['end'] for r in btc_daily]
        self.rows = btc_daily
        self.cache = {}

    def at(self, when):
        i = bisect_right(self.ends, when)
        if i < 200 or when-self.rows[i-1]['end'] >= DAY:
            return 'UNKNOWN'
        if i in self.cache:
            return self.cache[i]
        rows = self.rows[max(0,i-200):i]
        if len(rows) != 200 or not contiguous(rows, DAY) or when-rows[-1]['end'] >= DAY:
            return 'UNKNOWN'
        fast = statistics.mean(r['c'] for r in rows[-50:])
        slow = statistics.mean(r['c'] for r in rows)
        self.cache[i] = 'BULL' if rows[-1]['c'] > fast > slow else 'OTHER'
        return self.cache[i]


def candidate(rows, btc_by_end, regime, market, display, coin):
    """All inputs are closed bars. Missing history means no signal, never zero-fill."""
    daily = market == 'spot'
    step, warmup = (DAY,60) if daily else (HOUR,200)
    if len(rows) < warmup:
        return None
    rows = rows[-warmup:]
    if not contiguous(rows, step) or regime.at(rows[-1]['end']) != 'BULL':
        return None
    last = rows[-1]
    lag = 7 if daily else 24
    btc_now, btc_old = btc_by_end.get(last['end']), btc_by_end.get(rows[-1-lag]['end'])
    if btc_now is None or btc_old is None:
        return None
    change = last['c']/rows[-1-lag]['c']-1
    rs = change-(btc_now/btc_old-1)
    n = 30 if daily else 72
    high = max(r['h'] for r in rows[-n-1:-1])
    baseline = statistics.median(r['v']*r['c'] for r in rows[-n-1:-1])
    vr = last['v']*last['c']/baseline if baseline > 0 else 0
    trend = statistics.mean(r['c'] for r in rows[-(30 if daily else 50):])
    if daily:
        valid = (last['c'] > high and vr >= 1.8 and rs >= .03 and change <= .50
                 and last['c'] > trend)
    else:
        slow = statistics.mean(r['c'] for r in rows)
        valid = (last['c'] > high and vr >= 1.5 and rs >= .01 and
                 last['c'] > trend > slow and last['c']/trend-1 <= .08)
    if not valid:
        return None
    entry = last['c']*(1-RULES['limit_offset_bps']/10000)
    distance = (2.5 if daily else 2)*atr(rows)
    risk = distance/entry
    if not (.02 <= risk <= .25 if daily else .005 <= risk <= .12):
        return None
    return dict(strategy='HL-D' if daily else 'HL-S', market=market, coin=coin,
        display=display, close_ms=last['end'], reference=last['c'], limit_reference=entry,
        stop=entry-distance, target=entry+2*distance, risk_pct=risk*100,
        horizons_hours=[336,672] if daily else [24,48], regime='BULL',
        volume_ratio=vr, relative_strength_pct=rs*100, change_pct=change*100,
        rule_hash=HASH, status='RESEARCH', interval='1d' if daily else '1h',
        evidence='unvalidated_hypothesis_not_profit_probability')


def evaluate_limit(signal, future, hours):
    """Conservative limit-fill SCENARIO, never actual execution evidence.

    Wait one complete bar after the signal before placing the hypothetical order.
    One-bar TTL; require 5bp penetration. Entry-bar TP is not credited; SL is.
    Funding is not inferred from current funding. Net perp return remains unknown.
    """
    step = DAY if signal['market']=='spot' else HOUR
    start = signal['close_ms']+step
    by_time = {r['t']:r for r in future}
    first = by_time.get(start)
    result = dict(status='UNAVAILABLE', net_return_pct=None, net_ex_funding_pct=None,
                  gross_return_pct=None, entry_ms=start, exit_ms=None,
                  fill='hypothetical_penetration_not_actual_ALO_fill')
    if first is None:
        return result
    limit = signal['limit_reference']
    # A buy limit already at/above the market at placement may be rejected by ALO.
    # Bar open is only a conservative proxy; we still cannot prove real acceptance.
    if first['o'] <= limit:
        result['status']='ALO_REJECTED_SCENARIO'
        return result
    if first['l'] > limit*(1-RULES['penetration_bps']/10000):
        result['status']='UNFILLED'
        return result
    target, stop = signal['target'], signal['stop']
    for j,t in enumerate(range(start, start+hours*HOUR, step)):
        bar = by_time.get(t)
        if bar is None:
            return result
        if bar['l'] <= stop:
            px, reason = min(stop, bar['o']), 'SL'
        elif j > 0 and bar['h'] >= target:
            px, reason = target, 'TP'
        elif t+step >= start+hours*HOUR:
            px, reason = bar['c'], 'TIME'
        else:
            continue
        gross = (px/limit-1)*100
        # Base tier maker entry / taker exit, +10bp slippage sensitivity.
        maker,taker = (.0004,.0007) if signal['market']=='spot' else (.00015,.00045)
        net = gross-(maker+taker*px/limit)*100-.10
        result.update(status=reason, gross_return_pct=gross, net_ex_funding_pct=net,
                      net_return_pct=net if signal['market']=='spot' else None,
                      exit_ms=bar['end'], ambiguous_entry_bar=(j==0),
                      funding='not_applicable' if signal['market']=='spot' else 'not_modeled')
        return result
    return result
