#!/usr/bin/env python3
"""Independent Hyperliquid research bot. Run this file from any directory."""
from __future__ import annotations
import argparse
from contextlib import contextmanager
from datetime import datetime,timezone
import getpass
import json
import os
from pathlib import Path
import sys
import time

from client import Client,DataError,INTERVALS,book_metrics,number
from store import Store,read_delivery_status
from engine import HASH,HOUR,DAY,Regime,candidate
from research import replay,markdown
from forward import outcomes
from oi_history import import_manifest,OIHistory
import telegram

ROOT=Path(__file__).resolve().parent
DATA=ROOT/'data'


def settings():
    values={}
    if (ROOT/'.env').exists():
        for line in (ROOT/'.env').read_text(encoding='utf-8-sig').splitlines():
            if '=' in line and not line.lstrip().startswith('#'):
                key,_,value=line.partition('=')
                if key.strip().startswith('HL_'):
                    values[key.strip()]=value.strip()
    values.update({k:v for k,v in os.environ.items() if k.startswith('HL_')})
    for key in ('HL_PERP_MIN_VOLUME','HL_SPOT_MIN_VOLUME','HL_MAX_SPREAD_BPS','HL_MIN_DEPTH_USD'):
        if key in values and number(values[key])<=0:
            raise DataError('invalid_positive_setting_'+key)
    if 'HL_MARKET_LIMIT' in values and int(values['HL_MARKET_LIMIT'])<0:
        raise DataError('invalid_nonnegative_market_limit')
    return values


def write_json(path,body):
    path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix('.tmp')
    temp.write_text(json.dumps(body,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    temp.replace(path)


@contextmanager
def leader():
    DATA.mkdir(parents=True,exist_ok=True)
    stream=(DATA/'bot.lock').open('a+b')
    stream.seek(0)
    if stream.read(1)==b'':
        stream.write(b'0');stream.flush()
    stream.seek(0)
    try:
        if os.name=='nt':
            import msvcrt
            msvcrt.locking(stream.fileno(),msvcrt.LK_NBLCK,1)
        else:
            import fcntl
            fcntl.flock(stream,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except OSError:
        stream.close()
        raise RuntimeError('hyperliquid_bot_already_running') from None
    try:
        yield
    finally:
        stream.close()


def universe(client,store,config,limit=None):
    assets,raw=client.universe()
    limit=int(config.get('HL_MARKET_LIMIT',0)) if limit is None else limit
    if limit<0:
        raise ValueError('market_limit_must_be_nonnegative')
    selected=[]
    for market in ('perp','spot'):
        threshold=float(config.get('HL_PERP_MIN_VOLUME' if market=='perp' else 'HL_SPOT_MIN_VOLUME',
                                   1000000 if market=='perp' else 250000))
        group=sorted([a for a in assets if a['market']==market and a['volume_usd']>=threshold],
                     key=lambda a:(-a['volume_usd'],a['coin']))
        selected.extend(group[:limit] if limit else group)
    stamp=int(time.time()*1000)
    store.snapshot(stamp,dict(assets=assets,selected=selected,raw=raw))
    return selected


def sync_candles(client,store,market,coin,interval,bars=5000,incremental=False):
    end=int(time.time()*1000)
    step=INTERVALS[interval]
    start=end-bars*step
    old=store.candles(market,coin,interval)
    if incremental and old:
        start=max(start,old[-1]['t']-step)
    rows=client.candles(coin,interval,start,end)
    store.put_candles(market,coin,interval,rows)
    return len(rows)


def bootstrap(client,store,config,limit,bars):
    assets=universe(client,store,config,limit)
    jobs={('perp','BTC','1h'),('perp','BTC','1d')}
    jobs.update((a['market'],a['coin'],'1d' if a['market']=='spot' else '1h') for a in assets)
    errors=[]
    for i,(market,coin,interval) in enumerate(sorted(jobs),1):
        try:
            count=sync_candles(client,store,market,coin,interval,bars)
            print(f'{i}/{len(jobs)} {market} {coin} {interval}: {count} closed bars',flush=True)
        except (DataError,ValueError,KeyError) as exc:
            errors.append(dict(market=market,coin=coin,interval=interval,error=type(exc).__name__))
            print(f'{i}/{len(jobs)} {coin}: unavailable',flush=True)
    write_json(DATA/'coverage.json',dict(errors=errors,selected=len(assets),jobs=len(jobs),
               source='Hyperliquid',retrieved_at=datetime.now(timezone.utc).isoformat()))
    return errors


def scan(client,store,config,send=False):
    assets=universe(client,store,config)
    sync_candles(client,store,'perp','BTC','1d',incremental=True)
    sync_candles(client,store,'perp','BTC','1h',incremental=True)
    daily=store.candles('perp','BTC','1d')
    hourly=store.candles('perp','BTC','1h')
    regime=Regime(daily)
    status=dict(started_ms=int(time.time()*1000),source='Hyperliquid',
                rule_hash=HASH,mode='RESEARCH',checked=0,errors=[],candidates=[],
                regime=regime.at(int(time.time()*1000)))
    for asset in assets:
        market,coin=asset['market'],asset['coin']
        interval='1d' if market=='spot' else '1h'
        try:
            if not (market=='perp' and coin=='BTC'):
                sync_candles(client,store,market,coin,interval,incremental=True)
            rows=store.candles(market,coin,interval)
            now=int(time.time()*1000)
            if not rows or not 0<=now-rows[-1]['end']<INTERVALS[interval]:
                raise DataError('latest_closed_candle_unavailable')
            benchmark={r['end']:r['c'] for r in (daily if market=='spot' else hourly)}
            signal=candidate(rows,benchmark,regime,market,asset['display'],coin)
            status['checked']+=1
            if signal:
                book=book_metrics(client.book(coin),int(time.time()*1000))
                min_depth=float(config.get('HL_MIN_DEPTH_USD',10000))
                if (book['spread_bps']>float(config.get('HL_MAX_SPREAD_BPS',30)) or
                        min(book['bid_depth_usd'],book['ask_depth_usd'])<min_depth):
                    status['errors'].append(dict(coin=coin,reason='candidate_failed_live_liquidity_gate'))
                    continue
                detected=int(time.time()*1000)
                signal.update(book=book,detected_ms=detected,
                    id=f"{HASH}|{market}|{coin}|{signal['close_ms']}")
                status['candidates'].append(signal)
                cooldown=28*DAY if market=='spot' else 48*HOUR
                if not store.recent(signal['strategy'],coin,detected-cooldown):
                    store.add_event(signal)
                if send:
                    telegram.deliver(store,config,detected)
        except (DataError,ValueError,KeyError,TypeError) as exc:
            status['errors'].append(dict(coin=coin,error=type(exc).__name__))
    status['finished_ms']=int(time.time()*1000)
    write_json(DATA/'forward.json',outcomes(store,status['finished_ms']))
    write_json(DATA/'status.json',status)
    if send:
        telegram.deliver(store,config,int(time.time()*1000))
    return status


def setup_telegram():
    print('Yalnız yeni Hyperliquid Telegram botunun tokenını kullan. Cüzdan anahtarı gerekmez.')
    token=getpass.getpass('Yeni BotFather tokenı (gizli): ').strip()
    chat=input('Yeni kanal: @kullaniciadi / -100... ID; özel kanalı bulmak için boş bırak: ').strip()
    if not token or '\n' in token+chat or '\r' in token+chat:
        raise ValueError('invalid_telegram_settings')
    identity=telegram.call(token,'getMe',{})
    if not identity:
        print('Bot doğrulanamadı. Yeni BotFather tokenını ve bağlantıyı kontrol et.')
        raise ValueError('bot_not_verified')
    if not chat:
        updates=telegram.call(token,'getUpdates',{'timeout':0}) or []
        channels={}
        for update in updates:
            post=update.get('channel_post',{})
            candidate_chat=post.get('chat',{})
            if candidate_chat.get('type')=='channel':
                channels[str(candidate_chat['id'])]=candidate_chat
        if len(channels)==1:
            chat=next(iter(channels))
            print('Bulunan kanal: '+channels[chat].get('title',chat))
        else:
            for cid,item in channels.items():
                print(cid+' : '+item.get('title',''))
            if not channels:
                print('Yeni botu kanalda yönetici yap, kanala yeni bir mesaj yaz ve tekrar dene.')
                raise ValueError('no_new_channel_post')
            chat=input('Yukarıdaki yeni kanalın ID değeri: ').strip()
            if chat not in channels:
                raise ValueError('channel_not_selected')
    channel=telegram.call(token,'getChat',{'chat_id':chat})
    if not channel or channel.get('type')!='channel':
        raise ValueError('new_bot_or_channel_could_not_be_verified')
    member=telegram.call(token,'getChatMember',{'chat_id':chat,'user_id':identity['id']})
    if not member or not (member.get('status')=='creator' or
            (member.get('status')=='administrator' and member.get('can_post_messages'))):
        print('Yeni bota kanalda yönetici ve mesaj gönderme yetkisi ver.')
        raise ValueError('channel_post_permission_missing')
    path=ROOT/'.env'
    config={}
    if path.exists():
        for line in path.read_text(encoding='utf-8').splitlines():
            if '=' in line and line.startswith('HL_'):
                k,v=line.split('=',1);config[k]=v
    config.update(HL_TELEGRAM_BOT_TOKEN=token,HL_TELEGRAM_CHAT_ID=str(channel['id']),
                  HL_TELEGRAM_ENABLED='true')
    temporary=ROOT/'.env.tmp'
    temporary.write_text('\n'.join(f'{k}={v}' for k,v in config.items())+'\n',encoding='utf-8')
    if os.name!='nt':
        temporary.chmod(0o600)
    temporary.replace(path)
    print(f"Ayrı bot doğrulandı: @{identity['username']}. Ayarlar yalnız bu klasöre kaydedildi.")


def main():
    p=argparse.ArgumentParser(description=__doc__)
    sub=p.add_subparsers(dest='command',required=True)
    sub.add_parser('doctor');sub.add_parser('status');sub.add_parser('setup-telegram')
    sub.add_parser('test-telegram')
    b=sub.add_parser('bootstrap');b.add_argument('--limit',type=int);b.add_argument('--bars',type=int,default=5000)
    s=sub.add_parser('scan');s.add_argument('--send',action='store_true')
    sub.add_parser('run')
    oi=sub.add_parser('import-oi');oi.add_argument('manifest',type=Path)
    sub.add_parser('research');sub.add_parser('paper')
    args=p.parse_args();config=settings()
    if args.command=='setup-telegram':
        setup_telegram();return 0
    if args.command=='test-telegram':
        sent=telegram.call(config.get('HL_TELEGRAM_BOT_TOKEN',''),'sendMessage',{
            'chat_id':config.get('HL_TELEGRAM_CHAT_ID',''),'text':'Hyperliquid araştırma botu bağlantı testi. Emir açılmadı.'})
        print('Test mesajı gönderildi.' if sent else 'Telegram testi başarısız.');return 0 if sent else 1
    if args.command=='status':
        path=DATA/'status.json'
        status=json.loads(path.read_text(encoding='utf-8')) if path.exists() else {'scan':'not_started'}
        status['delivery']=read_delivery_status(DATA/'hyperliquid.sqlite3')
        print(json.dumps(status,ensure_ascii=False,indent=2))
        return 0
    with leader():
        store=Store(DATA/'hyperliquid.sqlite3');client=Client()
        try:
            if args.command=='doctor':
                assets,_=client.universe()
                print(json.dumps(dict(source='Hyperliquid',perps=sum(a['market']=='perp' for a in assets),
                    usdc_spot=sum(a['market']=='spot' for a in assets),
                    telegram_enabled=config.get('HL_TELEGRAM_ENABLED','false'),rule_hash=HASH),indent=2))
            elif args.command=='bootstrap':
                if not 200<=args.bars<=5000:
                    p.error('--bars must be 200..5000')
                return int(bool(bootstrap(client,store,config,args.limit,args.bars)))
            elif args.command=='import-oi':
                print(json.dumps(import_manifest(args.manifest,DATA/'external_oi.json'),indent=2))
            elif args.command=='research':
                _,snapshot=store.latest()
                if not snapshot:
                    raise ValueError('run_bootstrap_first')
                oi_path=DATA/'external_oi.json'
                report=replay(store,snapshot['selected'],OIHistory(oi_path) if oi_path.exists() else None)
                write_json(DATA/'research.json',report)
                (DATA/'research.md').write_text(markdown(report),encoding='utf-8')
                print(json.dumps(report['results'],indent=2))
            elif args.command=='paper':
                report=outcomes(store,int(time.time()*1000))
                write_json(DATA/'forward.json',report)
                print(json.dumps(report['results'],indent=2))
            elif args.command=='scan':
                status=scan(client,store,config,args.send)
                print(json.dumps(status,ensure_ascii=False,indent=2))
                return int(bool(status['errors']))
            elif args.command=='run':
                next_scan=0
                while True:
                    now=time.time()
                    try:
                        if now>=next_scan:
                            result=scan(client,store,config,send=True)
                            print(f"scan checked={result['checked']} candidates={len(result['candidates'])} errors={len(result['errors'])}",flush=True)
                            # Scan at the next hour +20 seconds; retries stay independent.
                            next_scan=(time.time()//3600+1)*3600+20
                        telegram.deliver(store,config,int(time.time()*1000))
                    except (DataError,ValueError,KeyError,TypeError) as exc:
                        print(f'cycle_error={type(exc).__name__}',flush=True)
                        next_scan=time.time()+60
                    time.sleep(5)
        finally:
            store.close()
    return 0


if __name__=='__main__':
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print('Durduruldu.')
    except Exception as exc:
        # No URLs, tokens or env values in error output.
        print(f'İşlem başarısız: {type(exc).__name__}: '+
              (str(exc) if isinstance(exc,DataError) else 'ayarları/veriyi kontrol et'),file=sys.stderr)
        raise SystemExit(1)
