"""Read-only retrospective G1 diagnostics, not threshold selection or forward OOS.

Only public Pages/market GETs. No signal_bot import, secrets, notifications or
orders. Evidence is saved separately under ignored research/data, never over
the tablet archive. All entries are proxies, never asserted actual fills.
"""
from __future__ import annotations
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import statistics as st
import threading

import requests

MINUTE = 60_000
HOUR = 60 * MINUTE
ANCHOR = '2026-10-13T16:35:20+00:00'
NEW_CONFIG = 'G1-prereg-2026-10-03-v3-fresh-ask'
BENCHMARKS = ('BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'BNBUSDT',
              'XRPUSDT', 'ADAUSDT', 'LINKUSDT', 'DOGEUSDT')
PAGE = 'https://raw.githubusercontent.com/ss4181/trade1/trade1-data/data.json'
ENDPOINTS = {'/fapi/v1/klines', '/futures/data/openInterestHist',
             '/futures/data/globalLongShortAccountRatio'}


def utc(value):
    result = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    if result.tzinfo is None:
        raise ValueError('timezone_required')
    return result.astimezone(timezone.utc)


def ms(value):
    return int(utc(value).timestamp() * 1000)


def distribution(values):
    values = [x for x in values if isinstance(x, (int, float)) and math.isfinite(x)]
    return {'n': len(values), 'mean': st.mean(values) if values else None,
            'median': st.median(values) if values else None,
            'min': min(values) if values else None, 'max': max(values) if values else None}


def parse_bars(rows, width, start, end):
    if not isinstance(rows, list):
        raise ValueError('bars_not_list')
    parsed = {}
    for b in rows:
        if not isinstance(b, list) or len(b) != 12:
            raise ValueError('invalid_bar_shape')
        t = int(b[0]); o, h, l, c = map(float, b[1:5])
        if (t % width or int(b[6]) != t + width - 1 or t in parsed
                or not start <= t < end
                or not all(math.isfinite(x) for x in (o, h, l, c))
                or not 0 < l <= min(o, c) <= max(o, c) <= h):
            raise ValueError('invalid_bar')
        parsed[t] = {'open_time': t, 'open': o, 'high': h, 'low': l,
                     'close': c, 'quote_volume': float(b[7]),
                     'taker_buy_quote_volume': float(b[10])}
    return parsed


def complete_path(data, start, end, width=MINUTE):
    times = list(range(start, end, width))
    if not times or any(t not in data for t in times):
        raise ValueError('incomplete_price_path')
    return [data[t] for t in times]


def bracket(path, entry, tp=3., sl=2., matured=True):
    target, stop = entry * (1 + tp / 100), entry * (1 - sl / 100)
    status = 'TIMEOUT' if matured else 'pending'
    fill = path[-1]['close'] if matured else None
    exit_time = path[-1]['open_time'] + MINUTE if matured else None
    for b in path:
        o, h, l = (b[k] for k in ('open', 'high', 'low'))
        if o <= stop: status, fill = 'SL_GAP', o
        elif o >= target: status, fill = 'TP', target
        elif l <= stop: status, fill = ('AMBIGUOUS_SL' if h >= target else 'SL'), stop
        elif h >= target: status, fill = 'TP', target
        else: continue
        exit_time = b['open_time'] + MINUTE
        break
    gross = (fill / entry - 1) * 100 if fill is not None else None
    return {'status': status, 'exit_upper_ms': exit_time, 'gross_pct': gross,
            'net40_ex_funding_pct': gross - .4 if gross is not None else None}


def aligned_metrics(oi, ls, close_ms):
    def latest(rows, cutoff, field, count):
        if not isinstance(rows, list): raise ValueError('metrics_not_list')
        usable = sorted((r for r in rows if 0 < int(r['timestamp']) <= cutoff),
                        key=lambda r: int(r['timestamp']))[-count:]
        if len(usable) != count: return None
        values = [float(r[field]) for r in usable]
        if not all(math.isfinite(v) and v > 0 for v in values): return None
        return usable, values
    result = {'historical_publication_time_known': False}
    for name, cutoff in (('current_code_cutoff', close_ms - 1),
                         ('completed_hour_boundary', close_ms)):
        os = latest(oi, cutoff, 'sumOpenInterest', 2)
        ls_ = latest(ls, cutoff, 'longShortRatio', 1)
        result[name] = {
            'oi_change_pct': (os[1][1] / os[1][0] - 1) * 100 if os else None,
            'oi_times_ms': [int(r['timestamp']) for r in os[0]] if os else None,
            'oi_latest_age_minutes': (close_ms - int(os[0][-1]['timestamp'])) / MINUTE if os else None,
            'ls_ratio': ls_[1][0] if ls_ else None,
            'ls_time_ms': int(ls_[0][0]['timestamp']) if ls_ else None,
            'ls_age_minutes': (close_ms - int(ls_[0][0]['timestamp'])) / MINUTE if ls_ else None}
    return result


class PublicData:
    def __init__(self, folder, fetch):
        self.folder, self.fetch = folder, fetch
        self.lock = threading.Lock(); self.proofs = {}; self.network_calls = 0

    def get(self, path, params):
        if path not in ENDPOINTS: raise ValueError('endpoint_not_allowed')
        request = {'path': path, 'params': params}
        key = hashlib.sha256(json.dumps(request, sort_keys=True).encode()).hexdigest()
        cache = self.folder / 'cache' / (key + '.json')
        if cache.exists():
            stored = json.loads(cache.read_bytes())
            raw = json.dumps(stored['response'], separators=(',', ':')).encode()
            if stored['request'] != request or hashlib.sha256(raw).hexdigest() != stored['sha256']:
                raise ValueError('cache_checksum_mismatch')
        else:
            if not self.fetch: raise ValueError('cache_missing')
            with self.lock: self.network_calls += 1
            res = requests.get('https://fapi.binance.com' + path, params=params, timeout=(5, 20))
            if res.status_code != 200: raise ValueError('public_http_' + str(res.status_code))
            data = res.json(); raw = json.dumps(data, separators=(',', ':')).encode()
            stored = {'request': request, 'response': data, 'sha256': hashlib.sha256(raw).hexdigest(),
                      'downloaded_at_utc': datetime.now(timezone.utc).isoformat()}
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps(stored, separators=(',', ':')), encoding='utf-8')
        with self.lock: self.proofs[key] = stored['sha256']
        return stored['response']

    def bars(self, symbol, width, start, end):
        rows = self.get('/fapi/v1/klines', {'symbol': symbol, 'interval': '1m' if width == MINUTE else '1h',
                                         'startTime': start, 'endTime': end - 1, 'limit': 499})
        return parse_bars(rows, width, start, end)


def feature_number(row, label):
    value = next((x[1] for x in row.get('detail', []) if x[0] == label), None)
    if value is None: return None
    try: return float(str(value).strip('+#%x '))
    except ValueError: return None


def diagnose(row, provider, cutoff):
    result = {k: row.get(k) for k in ('event_id', 'symbol', 'delivered_at', 'config_version')}
    delivery = ms(row['delivered_at']); hour_end = ms(row['t']) + HOUR
    start = (delivery + MINUTE - 1) // MINUTE * MINUTE
    end = min(delivery + 4 * HOUR, cutoff) // MINUTE * MINUTE
    mature = delivery + 4 * HOUR <= cutoff
    result.update(matured=mature, diagnostic_kind='retrospective_not_oos', actual_fill_known=False)
    try:
        data = provider.bars(row['symbol'], MINUTE, start, end)
        path = complete_path(data, start, end)
        entry = path[0]['open']
        result.update(entry_proxy=entry, immediate=bracket(path, entry, matured=mature),
                      price_bars=len(path), return_to_horizon_or_cutoff_pct=(path[-1]['close'] / entry - 1) * 100,
                      mae_pct=min(0., (min(b['low'] for b in path) / entry - 1) * 100),
                      mfe_pct=max(0., (max(b['high'] for b in path) / entry - 1) * 100))
        for wait in (5, 15):
            result[f'wait_{wait}m'] = bracket(path[wait:], path[wait]['open'], matured=mature) if len(path) > wait else {'status': 'pending'}
        hdata = provider.bars(row['symbol'], HOUR, hour_end - 25 * HOUR, hour_end)
        hours = complete_path(hdata, hour_end - 25 * HOUR, hour_end, HOUR)
        last = hours[-1]; ran = last['high'] - last['low']; close = last['close']
        tr = [max(b['high'] - b['low'], abs(b['high'] - a['close']), abs(b['low'] - a['close'])) for a, b in zip(hours, hours[1:])]
        result['features'] = {
            'return24_pct': feature_number(row, 'Kapanmış mum 24s getirisi'),
            'volume_ratio': feature_number(row, '1s hacim / önceki 24s medyan'),
            'reported_oi_change_pct': feature_number(row, 'Open interest 1s'),
            'reported_ls_ratio': feature_number(row, 'Global hesap long/short'),
            'hour_return_pct': (close / last['open'] - 1) * 100,
            'hour_range_pct': ran / close * 100,
            'atr14_sma_pct': st.mean(tr[-14:]) / close * 100,
            'fixed_sl2_over_atr14': .02 * close / st.mean(tr[-14:]) if st.mean(tr[-14:]) else None,
            'close_location_pct': (close - last['low']) / ran * 100 if ran else None,
            'hour_taker_buy_share_pct': last['taker_buy_quote_volume'] / last['quote_volume'] * 100 if last['quote_volume'] else None,
            'delivery_delay_seconds': (delivery - hour_end) / 1000}
    except (ValueError, KeyError, TypeError, requests.RequestException) as exc:
        result['price_or_features_unavailable'] = str(exc) if isinstance(exc, ValueError) else type(exc).__name__
    benchmarks = {}
    for symbol in BENCHMARKS:
        try:
            data = provider.bars(symbol, MINUTE, delivery // MINUTE * MINUTE - HOUR, end)
            path = complete_path(data, start, end); entry = path[0]['open']
            stop = (result.get('immediate') or {}).get('exit_upper_ms')
            at_stop = data.get(stop - MINUTE) if stop is not None else None
            prefix_end = delivery // MINUTE * MINUTE
            prefix = complete_path(data, prefix_end - HOUR, prefix_end)
            benchmarks[symbol] = {'return_pct': (path[-1]['close'] / entry - 1) * 100,
                                  'mae_pct': min(0., (min(b['low'] for b in path) / entry - 1) * 100),
                                  'return_at_coin_exit_upper_pct': (at_stop['close'] / entry - 1) * 100 if at_stop else None,
                                  'pre60_return_pct': (prefix[-1]['close'] / prefix[0]['open'] - 1) * 100}
        except (ValueError, KeyError, TypeError, requests.RequestException) as exc:
            benchmarks[symbol] = {'unavailable': str(exc) if isinstance(exc, ValueError) else type(exc).__name__}
    result['benchmarks'] = benchmarks
    returns = [v['return_at_coin_exit_upper_pct'] for v in benchmarks.values() if v.get('return_at_coin_exit_upper_pct') is not None]
    result['basket_at_coin_exit_median_pct'] = st.median(returns) if len(returns) == len(BENCHMARKS) else None
    result['basket_full_horizon_median_pct'] = st.median([v['return_pct'] for v in benchmarks.values()]) if all('return_pct' in v for v in benchmarks.values()) else None
    try:
        params = {'symbol': row['symbol'], 'period': '1h', 'startTime': hour_end - 3 * HOUR, 'endTime': hour_end, 'limit': 10}
        oi = provider.get('/futures/data/openInterestHist', params)
        ls = provider.get('/futures/data/globalLongShortAccountRatio', params)
        result['metric_alignment'] = aligned_metrics(oi, ls, hour_end)
    except (ValueError, KeyError, TypeError, requests.RequestException) as exc:
        result['metric_alignment'] = {'unavailable': str(exc) if isinstance(exc, ValueError) else type(exc).__name__}
    return result


def summary(rows):
    matured = [r for r in rows if r.get('matured')]
    out = {'n_selected': len(rows), 'n_matured': len(matured), 'n_pending': len(rows) - len(matured),
           'n_days': len({utc(r['delivered_at']).date() for r in rows}), 'small_sample': True}
    for key in ('immediate', 'wait_5m', 'wait_15m'):
        plans = [r.get(key) or {'status': 'unavailable'} for r in matured]
        out[key] = {'counts': dict(Counter(p['status'] for p in plans)),
                    'net40_ex_funding_pct': distribution([p.get('net40_ex_funding_pct') for p in plans])}
    for key in ('hour_return_pct', 'hour_range_pct', 'atr14_sma_pct', 'fixed_sl2_over_atr14',
                'reported_ls_ratio', 'return24_pct', 'volume_ratio', 'hour_taker_buy_share_pct'):
        out[key] = distribution([(r.get('features') or {}).get(key) for r in matured])
    out['basket_at_exit'] = distribution([r.get('basket_at_coin_exit_median_pct') for r in matured])
    out['basket_full_horizon'] = distribution([r.get('basket_full_horizon_median_pct') for r in matured])
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fetch', action='store_true')
    parser.add_argument('--dir', type=Path, default=Path(__file__).parent / 'data/g1-diagnostic-2026-10-13')
    parser.add_argument('--as-of', default=ANCHOR)
    args = parser.parse_args(); cutoff = ms(args.as_of)
    path = args.dir / 'snapshot.json'
    if path.exists(): snapshot = json.loads(path.read_bytes())
    elif args.fetch:
        res = requests.get(PAGE, headers={'Cache-Control': 'no-cache'}, params={'diagnostic': '20261013'}, timeout=(5, 25))
        if res.status_code != 200: raise ValueError('public_pages_http_' + str(res.status_code))
        p = res.json()
        fields = ('event_id', 'strategy', 'symbol', 't', 'direction', 'delivered_at', 'delivery_confirmed',
                  'config_version', 'universe', 'horizon_h', 'signal_price', 'signal_price_source', 'detail')
        snapshot = {'published_at': p['now'], 'public_source_sha256': hashlib.sha256(res.content).hexdigest(),
                    'rows': [{k:r.get(k) for k in fields} for r in p['signals'] if r.get('strategy') == 'G1']}
        args.dir.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(snapshot, sort_keys=True, indent=2), encoding='utf-8')
    else: raise ValueError('snapshot_missing')
    if ms(snapshot['published_at']) < cutoff: raise ValueError('snapshot_before_anchor')
    seen = set(); all_rows = []
    for r in sorted(snapshot['rows'], key=lambda r:r.get('delivered_at') or ''):
        if (r.get('delivery_confirmed') is not True or not r.get('delivered_at') or not r.get('event_id')
                or r['event_id'] in seen or ms(r['delivered_at']) > cutoff): continue
        if not r['event_id'].isalnum() or not r['symbol'].isalnum() or not r['symbol'].endswith('USDT'):
            raise ValueError('invalid_event')
        if r['direction'] != 'LONG' or r['horizon_h'] != 4 or r['universe'] != 'all_active_usdm_perpetuals':
            raise ValueError('unexpected_cohort')
        seen.add(r['event_id']); all_rows.append(r)
    recent = sorted([r for r in all_rows if r['config_version'] == NEW_CONFIG], key=lambda r:r['delivered_at'], reverse=True)[:10]
    first = min(r['delivered_at'] for r in recent)
    previous = sorted([r for r in all_rows if r['delivered_at'] < first], key=lambda r:r['delivered_at'], reverse=True)[:10]
    provider = PublicData(args.dir, args.fetch)
    results = []
    with ThreadPoolExecutor(max_workers=3) as pool:
        for i, row in enumerate(pool.map(lambda r:diagnose(r, provider, cutoff), recent + previous), 1):
            results.append(row)
            print('DIAGNOSTIC', i, '/', len(recent + previous), row['symbol'], flush=True)
    report = {'as_of_utc': args.as_of, 'source': PAGE, 'selection': 'last_10_v3_and_immediately_preceding_10_delivered_events',
              'hypothesis_selection_after_seen_results': True, 'forward_oos': False, 'live_changes': False,
              'net_cost_bps': 40, 'funding': 'not_modeled', 'benchmarks': list(BENCHMARKS),
              'snapshot_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
              'recent': summary(results[:len(recent)]), 'previous': summary(results[len(recent):]), 'rows': results,
              'network_calls': provider.network_calls, 'cache_proofs': dict(sorted(provider.proofs.items()))}
    (args.dir / 'report.json').write_text(json.dumps(report, sort_keys=True, indent=2), encoding='utf-8')
    print(json.dumps({k:report[k] for k in ('as_of_utc', 'recent', 'previous', 'network_calls')}, ensure_ascii=True))


if __name__ == '__main__':
    main()
