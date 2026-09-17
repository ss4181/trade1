"""Hyperliquid-only, unsigned market data. No exchange/order API methods."""
from __future__ import annotations
import math
import time
import requests

INFO_URL = 'https://api.hyperliquid.xyz/info'
INTERVALS = {'1h': 3600000, '1d': 86400000}


class DataError(RuntimeError):
    pass


def number(value):
    value = float(value)
    if not math.isfinite(value):
        raise DataError('nonfinite_value')
    return value


class Client:
    def __init__(self, session=None):
        self.session = session or requests.Session()
        self.next_call = 0.0

    def info(self, body, weight=20):
        # 600 weight/min budget leaves headroom beneath the shared 1200/IP limit.
        # Conservative pre-reservation includes the requested result count.
        for attempt in range(3):
            time.sleep(max(0, self.next_call - time.monotonic()))
            self.next_call = time.monotonic() + weight / 10
            try:
                response = self.session.post(INFO_URL, json=body, timeout=(10, 30))
            except requests.RequestException:
                if attempt == 2:
                    raise DataError('hyperliquid_network_unavailable') from None
                self.next_call = max(self.next_call, time.monotonic() + 2 ** attempt)
                continue
            if response.status_code in (429, 500, 502, 503, 504):
                try:
                    delay = max(5, number(response.headers.get('Retry-After', 10)))
                except (ValueError,TypeError,DataError):
                    delay = 10
                if delay > 60:
                    raise DataError('hyperliquid_retry_after_over_60s')
                self.next_call = max(self.next_call, time.monotonic() + delay)
                continue
            if response.status_code != 200:
                raise DataError(f'hyperliquid_http_{response.status_code}')
            try:
                return response.json()
            except ValueError:
                raise DataError('hyperliquid_invalid_json') from None
        raise DataError('hyperliquid_retry_exhausted')

    def universe(self):
        perps = self.info({'type': 'metaAndAssetCtxs'})
        spot = self.info({'type': 'spotMetaAndAssetCtxs'})
        return parse_universe(perps, spot), {'perp': perps, 'spot': spot}

    def candles(self, coin, interval, start_ms, end_ms):
        step = INTERVALS[interval]
        count = min(5000, max(1, (end_ms-start_ms)//step+1))
        rows = self.info({'type': 'candleSnapshot', 'req': {
            'coin': coin, 'interval': interval, 'startTime': start_ms,
            'endTime': end_ms}}, weight=20+math.ceil(count/60))
        return clean_candles(rows, coin, interval, end_ms)

    def book(self, coin):
        return self.info({'type': 'l2Book', 'coin': coin}, weight=2)


def parse_universe(perps, spots):
    result = []
    for market, payload in (('perp', perps), ('spot', spots)):
        if not isinstance(payload, list) or len(payload) != 2:
            raise DataError('invalid_catalog')
        meta, contexts = payload
        universe = meta['universe']
        if market == 'perp' and len(universe) != len(contexts):
            raise DataError('catalog_context_mismatch')
        tokens = {r['index']: r for r in meta.get('tokens', [])}
        # Spot context arrays include markets absent from the tradable catalog.
        # Native coin identity is authoritative; array offsets are not.
        if market == 'spot':
            by_coin = {r['coin']: r for r in contexts}
            if len(by_coin) != len(contexts):
                raise DataError('duplicate_spot_context')
            pairs = [(item, by_coin.get(item['name'])) for item in universe]
        else:
            pairs = zip(universe, contexts)
        for item, ctx in pairs:
            if ctx is None:
                raise DataError('missing_spot_context')
            if item.get('isDelisted'):
                continue
            coin = item['name']
            if market == 'spot':
                base, quote = (tokens[i] for i in item['tokens'])
                if quote['name'] != 'USDC':
                    continue
                display = f"{base['name']}/USDC"
                token_id = base.get('tokenId')
            else:
                display, token_id = coin, None
            try:
                volume = number(ctx.get('dayNtlVlm', 0))
                mark = number(ctx['markPx'])
                if mark <= 0 or volume < 0:
                    continue
            except (ValueError, TypeError, KeyError, DataError):
                continue
            result.append(dict(market=market, coin=coin, display=display,
                               token_id=token_id, volume_usd=volume,
                               context=ctx, mark=mark))
    return result


def clean_candles(rows, coin, interval, now_ms):
    if not isinstance(rows, list):
        raise DataError('invalid_candle_response')
    step, result = INTERVALS[interval], {}
    for raw in rows:
        if raw.get('s') != coin or raw.get('i') != interval:
            raise DataError('candle_market_mismatch')
        t = int(raw['t'])
        if t % step or int(raw['T']) not in (t+step-1, t+step):
            raise DataError('candle_time_mismatch')
        if t+step > now_ms:
            continue
        o, h, l, c, v = [number(raw[k]) for k in ('o','h','l','c','v')]
        if min(o,h,l,c) <= 0 or v < 0 or not l <= min(o,c) <= max(o,c) <= h:
            raise DataError('invalid_ohlcv')
        bar = dict(t=t, end=t+step, o=o, h=h, l=l, c=c, v=v)
        if t in result and result[t] != bar:
            raise DataError('conflicting_candle')
        result[t] = bar
    return [result[t] for t in sorted(result)]


def book_metrics(payload, now_ms):
    bids, asks = payload['levels']
    if not bids or not asks or not 0 <= now_ms-int(payload['time']) <= 60000:
        raise DataError('empty_or_stale_book')
    bid, ask = number(bids[0]['px']), number(asks[0]['px'])
    if not 0 < bid < ask:
        raise DataError('crossed_book')
    mid = (bid+ask)/2
    def depth(rows):
        total = 0.0
        for row in rows:
            px, size = number(row['px']), number(row['sz'])
            if px <= 0 or size < 0:
                raise DataError('invalid_book_level')
            if abs(px/mid-1) <= .005:
                total += px*size
        return total
    return dict(bid=bid, ask=ask, spread_bps=(ask/bid-1)*10000,
                bid_depth_usd=depth(bids), ask_depth_usd=depth(asks))
