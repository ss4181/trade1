"""Read-only import of previously downloaded Coinalyze OI, never venue substitution."""
from bisect import bisect_right
import hashlib
import json
import math
from pathlib import Path


def import_manifest(path, output):
    path=Path(path).resolve()
    manifest=json.loads(path.read_text(encoding='utf-8'))
    if manifest.get('schema')!='coinalyze-research-v1':
        raise ValueError('unknown_coinalyze_manifest')
    series={}
    for market in manifest['markets']:
        # Exact base name only. No guessing 1000x/k aliases or wrapped assets.
        if market.get('quote_asset')!='USDT' or market.get('margined')!='STABLE':
            continue
        for interval,step in (('1hour',3600),('daily',86400)):
            key=f"{market['symbol']}|open-interest-history|{interval}"
            entry=manifest['series'].get(key,{})
            if entry.get('status')!='ok':
                continue
            source=(path.parent/entry['file']).resolve()
            if not source.is_relative_to(path.parent):
                raise ValueError('source_outside_manifest_directory')
            raw=source.read_bytes()
            if hashlib.sha256(raw).hexdigest()!=entry['sha256']:
                raise ValueError('oi_source_hash_mismatch')
            data=json.loads(raw)
            if data['market']['symbol']!=market['symbol'] or data['endpoint']!='open-interest-history' or data['interval']!=interval:
                raise ValueError('oi_source_identity_mismatch')
            points=[]
            previous=-1
            for row in data['rows']:
                t=int(row['t']); value=float(row['c'])
                if t<=previous or t%step or not math.isfinite(value) or value<=0:
                    raise ValueError('invalid_oi_point')
                if t+step>manifest['cutoff']:
                    raise ValueError('unclosed_oi_point')
                previous=t
                # Retrospective availability assumption: never use the high/low
                # of a still-open provider candle, plus one full-bar delay.
                points.append([(t+2*step)*1000,value])
            if len(points)!=entry['rows']:
                raise ValueError('oi_row_count_mismatch')
            series_key=f"{market['base_asset']}|{interval}"
            if series_key in series:
                raise ValueError('ambiguous_base_asset')
            series[series_key]=dict(exchange_code=market['exchange'],
                provider_symbol=market['symbol'],native_unit=market['oi_lq_vol_denominated_in'],
                source_sha256=entry['sha256'],step_ms=step*1000,points=points)
    result=dict(source='Coinalyze existing archive',
                usage='external_venue_context_not_Hyperliquid_OI',
                identity_match='exact_ticker_only_not_verified_token_identity',
                availability='bar close plus one bar; historical publication time unknown',
                manifest_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),series=series)
    Path(output).parent.mkdir(parents=True,exist_ok=True)
    Path(output).write_text(json.dumps(result,separators=(',',':')),encoding='utf-8')
    return dict(series=len(series),rows=sum(len(s['points']) for s in series.values()),
                exchange_codes=sorted({s['exchange_code'] for s in series.values()}),
                use=result['usage'])


class OIHistory:
    def __init__(self,path):
        self.series=json.loads(Path(path).read_text(encoding='utf-8'))['series']
        self.times={k:[p[0] for p in v['points']] for k,v in self.series.items()}

    def change(self,asset,when,daily=False):
        base=asset['display'].split('/')[0] if asset['market']=='spot' else asset['coin']
        key=base+('|daily' if daily else '|1hour')
        series=self.series.get(key)
        if not series:
            return None
        times=self.times[key]; step=series['step_ms']; lag=7 if daily else 24
        i=bisect_right(times,when)-1
        if i<lag or when-times[i]>=step or times[i]-times[i-lag]!=lag*step:
            return None
        return series['points'][i][1]/series['points'][i-lag][1]-1
