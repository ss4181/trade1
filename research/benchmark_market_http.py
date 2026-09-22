"""Explicit public-data benchmark. No bot import, credentials, state or messages."""
import argparse
import json
from pathlib import Path
import statistics
import sys
import time
import requests

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from market_http import MarketHttp


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--samples',type=int,default=4)
    args=parser.parse_args()
    if not 2 <= args.samples <= 8:parser.error('samples must be 2..8')
    client=MarketHttp()
    observations={name:[] for name in ('fresh','pooled')}
    url='https://api.binance.com/api/v3/klines'
    def one(get):
        start=time.perf_counter()
        response=get(url,params={'symbol':'BTCUSDT','interval':'1h','limit':250},timeout=15)
        response.raise_for_status()
        if len(response.json()) != 250:raise ValueError('unexpected_candle_count')
        return round(time.perf_counter()-start,4)
    try:
        one(client.get)  # warm once; compare established connection throughput
        for index in range(args.samples):
            order=('fresh','pooled') if index%2==0 else ('pooled','fresh')
            for name in order:
                observations[name].append(one(requests.get if name=='fresh' else client.get))
        print(json.dumps({'measurement':'public_BTC_klines_this_computer_not_tablet',
                          'seconds':observations,'median_seconds':{k:statistics.median(v) for k,v in observations.items()},
                          'pool':client.snapshot()},indent=2))
    finally:client.close()


if __name__=='__main__':main()
