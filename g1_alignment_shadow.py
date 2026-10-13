"""Forward-only hourly alignment study. No Telegram, credentials or orders.

The live G1 implementation remains the control; this module owns separate
state, observations and five frozen 1m entry proxies for each variant.
"""
from __future__ import annotations

import copy
import ast
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import threading
import time

from atomic_state import replace_state
import g1_entry
from shadow_experiments import (G1_RETURN_24H_MIN, G1_TOP_N, G1_VOLUME_RATIO_MIN,
    G1_OI_CHANGE_1H_MIN, G1_LONG_SHORT_MAX, G1_COOLDOWN_HOURS, G1_HORIZON_HOURS)
from research.diagnose_g1_failures import parse_bars, complete_path

MINUTE = 60_000
HOUR = 60 * MINUTE
VERSION = 'g1-alignment-forward-v1'
_entry_tree = ast.parse(Path(g1_entry.__file__).read_text(encoding='utf-8'))
ENTRY_ENGINE_HASH = hashlib.sha256(''.join(ast.dump(n, include_attributes=False) for n in _entry_tree.body
    if isinstance(n, ast.FunctionDef) and n.name in {'advance_entry_shadow', 'finish_entry_shadow', '_observe_plan_path'}).encode()).hexdigest()
RULES = dict(return24=G1_RETURN_24H_MIN, top_n=G1_TOP_N,
    volume=G1_VOLUME_RATIO_MIN, oi=G1_OI_CHANGE_1H_MIN, ls=G1_LONG_SHORT_MAX,
    cooldown_hours=G1_COOLDOWN_HOURS, horizon_hours=G1_HORIZON_HOURS,
    first_observation_seconds=60, latest_observation_seconds=600,
    tp_pct=3, sl_pct=2, cost_bps=[20, 40], funding='not_modeled',
    entry_engine_hash=ENTRY_ENGINE_HASH, entry_measurement=g1_entry.MEASUREMENT,
    confirmation='closed_window_last_close_gt_first_open', same_bar='stop_first',
    plans=['immediate', 'wait_5m', 'wait_15m', 'confirm_5m', 'confirm_15m'])
RULE_HASH = hashlib.sha256(json.dumps(RULES, sort_keys=True).encode()).hexdigest()


def iso(ms):
    return datetime.fromtimestamp(ms / 1000, timezone.utc).isoformat()


def flags(features, oi_change, ls):
    return dict(return24=features['return24'] >= RULES['return24'],
        rank=features['rank'] <= RULES['top_n'], volume=features['volume_ratio'] >= RULES['volume'],
        oi=oi_change >= RULES['oi'], long_short=ls < RULES['ls'])


def evaluate(klines, oi, ls, boundary, rank, observed_ms, *, max_delay_ms=600_000):
    """Exact timestamps; absent boundary data is UNKNOWN, never old substitute."""
    if not boundary <= observed_ms <= boundary + max_delay_ms:
        raise ValueError('observation_outside_frozen_window')
    rows = [b for b in klines if isinstance(b, list) and b and int(b[0]) < boundary]
    bars = complete_path(parse_bars(rows, HOUR, boundary - 25 * HOUR, boundary),
                         boundary - 25 * HOUR, boundary, HOUR)
    volumes = [b['quote_volume'] for b in bars]
    if not all(math.isfinite(v) and v > 0 for v in volumes):
        raise ValueError('invalid_hourly_volume')
    import statistics
    features = dict(return24=bars[-1]['close'] / bars[0]['close'] - 1,
        rank=rank, volume_ratio=volumes[-1] / statistics.median(volumes[:-1]),
        hour_return=bars[-1]['close'] / bars[-1]['open'] - 1,
        reference_close=bars[-1]['close'], reference_low=bars[-1]['low'])
    def at(raw, timestamp, field):
        matches = [r for r in raw if int(r['timestamp']) == timestamp]
        if not matches:
            return None
        if len(matches) != 1:
            raise ValueError('duplicate_metric_timestamp')
        value = float(matches[0][field])
        if not math.isfinite(value) or value <= 0:
            raise ValueError('invalid_metric_value')
        return value
    result = dict(features=features, boundary_ms=boundary, observed_at_ms=observed_ms,
                  version=VERSION, rule_hash=RULE_HASH, research_only=True)
    for name, end in (('legacy_lag', boundary - HOUR), ('aligned', boundary)):
        before, current = at(oi, end - HOUR, 'sumOpenInterest'), at(oi, end, 'sumOpenInterest')
        ratio = at(ls, end, 'longShortRatio')
        values = dict(oi_times_ms=[end-HOUR, end], ls_time_ms=end, oi_change=None, ls_ratio=ratio)
        if before is None or current is None or ratio is None:
            result[name] = dict(status='UNKNOWN', reason='exact_metric_not_observed', **values)
        else:
            values['oi_change'] = current / before - 1
            conditions = flags(features, values['oi_change'], ratio)
            result[name] = dict(status='ACTIVE' if all(conditions.values()) else 'INACTIVE',
                                conditions=conditions, **values)
    return result


class AlignmentStudy:
    def __init__(self, path, archive_dir, *, fetch, clock=None, context=None):
        self.path, self.archive_dir = Path(path), Path(archive_dir)
        self.fetch = fetch
        self.clock = clock or (lambda: int(time.time()*1000))
        self.context = context or (lambda: {})
        self.lock = threading.Lock()
        self.status = {'version': VERSION, 'research_only': True, 'last_error': None}
        if self.path.exists():
            self.state = json.loads(self.path.read_bytes())
            if (self.state.get('version') != VERSION or self.state.get('rule_hash') != RULE_HASH
                    or not isinstance(self.state.get('events'), dict)
                    or not isinstance(self.state.get('hours'), dict)
                    or not isinstance(self.state.get('activated_ms'), int)):
                raise ValueError('alignment_state_incompatible')
        else:
            self.state = dict(version=VERSION, rule_hash=RULE_HASH, activated_ms=self.clock(),
                              hours={}, events={}, prev={}, last_fire={})
            self.save()

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(self.path.suffix+'.tmp')
        temp.write_text(json.dumps(self.state, sort_keys=True, allow_nan=False), encoding='utf-8')
        replace_state(temp, self.path)

    def journal(self, kind, rows):
        if not rows:
            return
        self.archive_dir.mkdir(parents=True, exist_ok=True)
        month = datetime.fromtimestamp(self.clock()/1000, timezone.utc).strftime('%Y-%m')
        with (self.archive_dir/f'g1_alignment_{kind}_{month}.jsonl').open('a', encoding='utf-8') as f:
            for row in rows:
                f.write(json.dumps(row, sort_keys=True, allow_nan=False)+'\n')

    def get(self, endpoint, params=None):
        if endpoint not in {'/fapi/v1/exchangeInfo', '/fapi/v1/ticker/24hr', '/fapi/v1/klines',
                '/futures/data/openInterestHist', '/futures/data/globalLongShortAccountRatio'}:
            raise ValueError('public_endpoint_not_allowed')
        data = self.fetch(endpoint, params or {})
        return data, self.clock()

    def capture(self, now, stop_event=None):
        boundary = now//HOUR*HOUR
        for stamp, previous in self.state['hours'].items():
            if not previous.get('done') and int(stamp)+600_000 < now:
                for c in previous['candidates']:
                    previous['results'].setdefault(c['symbol'], dict(status='UNKNOWN', reason='observation_timeout'))
                previous['done'] = True
                self.save()
        # Activation mid-hour never backfills a pre-activation signal hour.
        if boundary < self.state['activated_ms'] or now < boundary+60_000:
            return
        key = str(boundary)
        hour = self.state['hours'].get(key)
        if hour and hour.get('done'):
            return
        if now > boundary+600_000:
            if hour is None:
                self.state['hours'][key] = dict(done=True, status='UNKNOWN', reason='missed_window')
            else:
                for candidate in hour['candidates']:
                    if candidate['symbol'] not in hour['results']:
                        hour['results'][candidate['symbol']] = dict(status='UNKNOWN', reason='observation_timeout')
                hour['done'] = True
            self.save()
            return
        if hour is None:
            exchange, exchange_at = self.get('/fapi/v1/exchangeInfo')
            tickers, ranking_at = self.get('/fapi/v1/ticker/24hr')
            if not isinstance(tickers, list) or not tickers or not isinstance(exchange, dict):
                raise ValueError('invalid_ranking_data')
            active = {r['symbol'] for r in exchange['symbols'] if r.get('status') == 'TRADING'
                      and r.get('contractType') == 'PERPETUAL' and r.get('quoteAsset') == 'USDT'}
            ranked = []
            for r in tickers:
                if r.get('symbol') not in active:
                    continue
                change = float(r['priceChangePercent'])
                if not math.isfinite(change):
                    raise ValueError('invalid_ranking_return')
                ranked.append((change, r['symbol']))
            ranked.sort(key=lambda r: (-r[0], r[1]))
            if not ranked or ranking_at > boundary+600_000:
                raise ValueError('ranking_not_available_in_window')
            candidates = [dict(rank=i+1, symbol=s) for i, (_, s) in enumerate(ranked[:RULES['top_n']])]
            hour = dict(candidates=candidates, results={}, ranking_observed_ms=ranking_at,
                        catalog_observed_ms=exchange_at, done=False)
            self.state['hours'][key] = hour
            # Outside top-10 means rank condition cannot hold, for both controls.
            current = {r['symbol'] for r in candidates}
            for name in ('legacy_lag', 'aligned'):
                for sym in list(self.state['prev'].setdefault(name, {})):
                    if sym not in current:
                        self.state['prev'][name][sym] = False
            self.save()  # Freeze ranking before further responses/outcomes.
        for candidate in hour['candidates']:
            if stop_event is not None and stop_event.is_set():
                return
            symbol = candidate['symbol']
            if symbol in hour['results']:
                continue
            times = {}
            try:
                klines, times['klines'] = self.get('/fapi/v1/klines', dict(symbol=symbol, interval='1h',
                    startTime=boundary-25*HOUR, endTime=boundary-1, limit=25))
                params = dict(symbol=symbol, period='1h', startTime=boundary-2*HOUR, endTime=boundary, limit=5)
                oi, times['oi'] = self.get('/futures/data/openInterestHist', params)
                ls, times['ls'] = self.get('/futures/data/globalLongShortAccountRatio', params)
                received = max(times.values())
                decision = evaluate(klines, oi, ls, boundary, candidate['rank'], received)
                decision.update(symbol=symbol, response_received_ms=times,
                                ranking_observed_ms=hour['ranking_observed_ms'])
                context = self.context()
                decision['market_context'] = dict(label=context.get('label', 'UNKNOWN') if context.get('fresh') else 'UNKNOWN',
                    data_close_at=context.get('data_close_at'), reference_at=context.get('reference_at'))
                # Both variants lock at the same observation time; UNKNOWN retries
                # within this fixed window, never substitute or backfill next hour.
                if any(decision[n]['status'] == 'UNKNOWN' for n in ('legacy_lag', 'aligned')):
                    self.journal('observations', [decision])
                    continue
            except Exception as exc:
                self.status['last_error'] = 'candidate_data_unavailable'
                if type(exc).__name__ in {'MarketRateLimitError', 'MarketTransientError'}:
                    break
                continue
            hour['results'][symbol] = decision
            for name in ('legacy_lag', 'aligned'):
                prev = self.state['prev'].setdefault(name, {})
                fires = self.state['last_fire'].setdefault(name, {})
                active = decision[name]['status'] == 'ACTIVE'
                edge = active and not prev.get(symbol, False)
                prev[symbol] = active
                last = fires.get(symbol)
                if not edge or (last is not None and received-last < RULES['cooldown_hours']*HOUR):
                    continue
                eid = hashlib.sha256(f'{VERSION}|{name}|{symbol}|{boundary}'.encode()).hexdigest()[:32]
                start = g1_entry.ceil_bar(received, MINUTE)
                self.state['events'][eid] = dict(event_id=eid, variant=name, strategy='G1',
                    symbol=symbol, market='um_perp', direction='LONG', universe='all_active_usdm_perpetuals',
                    config_version=VERSION, measurement_version=g1_entry.MEASUREMENT,
                    observed_at_ms=received, started_at=iso(received), expires_at=iso(received+4*HOUR),
                    end_ms=(received+4*HOUR)//MINUTE*MINUTE,
                    tracking_start_ms=start, next_start_ms=start, status='active',
                    observation_evidence='response_received_before_entry', actual_fill_known=False,
                    market_regime=decision['market_context']['label'],
                    market_regime_data_close_at=decision['market_context']['data_close_at'],
                    features=decision['features'], data_status='pending')
                fires[symbol] = received
            self.save()
            # The causal decision/entry clock is durable before optional journal
            # IO. A failed journal must never move an enrolled entry on restart.
            self.journal('observations', [decision])
        hour['done'] = len(hour['results']) == len(hour['candidates'])
        self.save()

    def poll_paths(self, now, stop_event=None):
        pending = sorted((e for e in self.state['events'].values() if e['status'] == 'active'),
                         key=lambda e: (e.get('last_poll_ms', 0), e['observed_at_ms'], e['event_id']))
        for event in pending[:20]:
            if stop_event is not None and stop_event.is_set():
                return
            end = min(now//MINUTE*MINUTE, event['end_ms'])
            if event['next_start_ms'] >= end:
                continue
            updated = copy.deepcopy(event)
            shared_service_blocked = False
            try:
                raw, fetched_at = self.get('/fapi/v1/klines', dict(symbol=event['symbol'], interval='1m',
                    startTime=event['next_start_ms'], endTime=end-1, limit=499))
                parsed = parse_bars(raw, MINUTE, event['next_start_ms'], end)
                bars = complete_path(parsed, event['next_start_ms'], end)
                self.journal('bars', [dict(version=VERSION, rule_hash=RULE_HASH,
                    event_id=event['event_id'], symbol=event['symbol'], fetched_at_ms=fetched_at, **b) for b in bars])
                g1_entry.advance_entry_shadow(updated, bars)
                updated['next_start_ms'] = end
                updated['data_status'] = 'observed'
                if end == event['end_ms']:
                    g1_entry.finish_entry_shadow(updated)
                    updated['status'] = 'expired'
            except Exception as exc:
                updated['data_status'] = 'UNKNOWN'
                self.status['last_error'] = 'price_path_unavailable'
                shared_service_blocked = type(exc).__name__ in {'MarketRateLimitError', 'MarketTransientError'}
            updated['last_poll_ms'] = now
            self.state['events'][event['event_id']] = updated
            self.save()
            if shared_service_blocked:
                # A transient shared service failure must not produce a request storm.
                break

    def tick(self, stop_event=None):
        if not self.lock.acquire(blocking=False):
            return
        try:
            if stop_event is not None and stop_event.is_set():
                return
            now = self.clock()
            # Give scan/Telegram the first minute; collection and path work are background.
            if now % HOUR < 60_000:
                return
            self.status['last_error'] = None
            self.capture(now, stop_event)
            self.poll_paths(self.clock(), stop_event)
            self.status.update(last_tick_at=iso(self.clock()), events=len(self.state['events']),
                               activation_at=iso(self.state['activated_ms']))
        except Exception:
            self.status['last_error'] = 'alignment_tick_failed'
            # Discard unsaved mutations, preserving the last atomic checkpoint.
            try:
                self.state = json.loads(self.path.read_bytes())
            except Exception:
                pass
        finally:
            self.lock.release()


def summarize(state, as_of_ms):
    """Report separately; never feed shadow events into live scorecards."""
    if state.get('version') != VERSION or state.get('rule_hash') != RULE_HASH:
        raise ValueError('alignment_state_incompatible')
    from research.g1_entry_comparison import PLANS, plan_summary
    variants = {}
    for name in ('legacy_lag', 'aligned'):
        events = [e for e in state['events'].values() if e['variant'] == name
                  and state['activated_ms'] <= e['observed_at_ms'] <= as_of_ms]
        matured = [e for e in events if e['end_ms'] <= as_of_ms]
        from research.g1_entry_comparison import outcome, utc
        full = [e for e in matured if all(outcome(e, p) is not None for p in PLANS)]
        full_days = len({utc(e['started_at']).date() for e in full})
        times = sorted(e['observed_at_ms'] for e in full)
        span_days = (times[-1]-times[0])/(24*HOUR) if times else 0
        variants[name] = dict(n_total=len(events), n_matured=len(matured), n_pending=len(events)-len(matured),
            n_complete_all_plans=len(full), n_matured_incomplete=len(matured)-len(full),
            complete_event_days=full_days, complete_span_days=span_days,
            sample_gate_only=len(full)>=30 and full_days>=28 and span_days>=90,
            plans={p: plan_summary(matured, p) for p in PLANS})
    return dict(version=VERSION, rule_hash=RULE_HASH, activated_at=iso(state['activated_ms']),
        as_of_utc=iso(as_of_ms), variants=variants, validated=False, live_filter_enabled=False,
        actual_fills=False, funding='not_modeled', decision='NO_LIVE_CHANGE',
        unknown_hours=sum(h.get('status') == 'UNKNOWN' or any(r.get('status') == 'UNKNOWN'
                          for r in h.get('results', {}).values()) for h in state['hours'].values()))
