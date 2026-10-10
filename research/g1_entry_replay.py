"""Read previously seen 20-event minute-cache diagnostics; no writes or downloads."""
from collections import Counter
from datetime import timedelta
import hashlib
import json

from g1_entry import MEASUREMENT, MINUTE, ceil_bar, advance_entry_shadow, finish_entry_shadow
from research.g1_entry_comparison import utc, ms, number


def replay(folder):
    raw_snapshot = (folder/'snapshot.json').read_bytes()
    snapshot = json.loads(raw_snapshot)
    cutoff = ms(snapshot['published_at'])
    seen, selected = set(), []
    rows = []
    for row in snapshot['rows']:
        if row.get('strategy') != 'G1' or row.get('delivery_confirmed') is not True:
            continue
        try:
            if ms(row['delivered_at']) > cutoff:
                continue
        except (KeyError, ValueError, TypeError):
            continue
        if row.get('event_id'):
            rows.append(row)
    # Same first-confirmed receipt / latest 20 selection as the old audit.
    for row in sorted(rows, key=lambda r: (utc(r['delivered_at']), r['event_id'])):
        if row['event_id'] not in seen:
            selected.append(row)
            seen.add(row['event_id'])
    selected.sort(key=lambda r: (utc(r['delivered_at']), r['event_id']), reverse=True)
    events, unknown, proofs = [], Counter(), []
    for row in selected[:20]:
        eid, symbol = row['event_id'], row['symbol']
        if (not isinstance(eid, str) or not eid.isalnum() or not isinstance(symbol, str)
                or not symbol.isalnum() or not symbol.endswith('USDT')):
            unknown['invalid_identifier'] += 1
            continue
        delivery = ms(row['delivered_at'])
        start = ceil_bar(delivery, MINUTE)
        end = min(delivery+4*60*MINUTE, cutoff)//MINUTE*MINUTE
        cache = folder/'minute_cache'/f'{eid}.json'
        proof = folder/'minute_cache'/f'{eid}.metadata.json'
        if not cache.exists() or not proof.exists():
            unknown['missing_cache'] += 1
            continue
        raw = cache.read_bytes()
        meta = json.loads(proof.read_bytes())
        params = dict(symbol=symbol, interval='1m', startTime=delivery//MINUTE*MINUTE,
                      endTime=end-1, limit=499)
        digest = hashlib.sha256(raw).hexdigest()
        if meta['sha256'] != digest or meta['params'] != params:
            raise ValueError('cache_mismatch')  # Technical error aborts, not silently excluded.
        data = {}
        for b in json.loads(raw):
            if not isinstance(b, list) or len(b) != 12:
                raise ValueError('invalid_kline')
            t = int(b[0]); o, h, l, c = map(float, b[1:5])
            if (t in data or t % MINUTE or not params['startTime'] <= t < end or
                    int(b[6]) != t+MINUTE-1 or not all(number(v) for v in (o, h, l, c)) or
                    not 0 < l <= min(o, c) <= max(o, c) <= h):
                raise ValueError('invalid_ohlc')
            data[t] = dict(open_time=t, open=o, high=h, low=l, close=c)
        if not data or any(t not in data for t in range(start, end, MINUTE)):
            unknown['incomplete_1m_path'] += 1
            continue
        e = dict(event_id=eid, symbol=symbol, strategy='G1', direction=row.get('direction'),
            market=row.get('performance_market'), universe=row.get('universe'),
            config_version=row.get('config_version'), entry_study_origin='retrospective_proxy',
            started_at=row['delivered_at'], expires_at=(utc(row['delivered_at'])+timedelta(hours=4)).isoformat(),
            status='expired' if delivery+4*60*MINUTE <= cutoff else 'active',
            measurement_version=MEASUREMENT, delivery_evidence='confirmed', tracking_start_ms=start,
            next_start_ms=end)
        advance_entry_shadow(e, [data[t] for t in range(start, end, MINUTE)])
        if e['status'] == 'expired':
            finish_entry_shadow(e)
        events.append(e)
        proofs.append(digest)
    return events, dict(snapshot_sha256=hashlib.sha256(raw_snapshot).hexdigest(),
        cache_sha256=sorted(proofs), as_of_utc=snapshot['published_at'],
        n_selected=min(len(selected), 20), unknown=dict(unknown), retrospective=True,
        forward_oos=False, quote_definition='next_full_1m_open_proxy_NOT_fresh_ask', network_used=False)
