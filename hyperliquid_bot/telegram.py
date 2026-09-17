"""Dedicated Telegram identity; errors never include request URLs or tokens."""
from datetime import datetime,timezone,timedelta
import html
import requests


def tr(ms):
    return datetime.fromtimestamp(ms/1000,timezone(timedelta(hours=3))).strftime('%d.%m.%Y %H:%M TSİ')


def message(event):
    esc=lambda x:html.escape(str(x))
    horizon='24–48 saat' if event['strategy']=='HL-S' else '14–28 gün'
    return '\n'.join([
        f"🔔 <b>{event['strategy']} — {esc(event['display'])} LONG</b> 🔬",
        f"🏦 Hyperliquid {esc(event['market'])} · araştırma adayı",
        f"💰 Kapanış referansı: {event['reference']:.8g}",
        f"📐 Limit araştırma referansı: {event['limit_reference']:.8g}",
        f"🎯 Hedef: {event['target']:.8g} · Stop: {event['stop']:.8g}",
        f"⏱️ İzleme ufku: {horizon} · rejim: BOĞA",
        f"📊 Hacim: {event['volume_ratio']:.2f}× · BTC’ye göre güç: {event['relative_strength_pct']:+.2f}%",
        f"📚 Spread: {event['book']['spread_bps']:.1f} bp",
        f"🕯️ Kapanış: {tr(event['close_ms'])}",
        f"📨 Tespit: {tr(event['detected_ms'])}",
        f"📐 Testte en erken emir: {tr(event['close_ms']+(86400000 if event['market']=='spot' else 3600000))}",
        '💡 Hacimli kırılım, BTC’ye göre güç ve boğa rejimi birlikte görüldü.',
        '<i>Başarı oranı henüz doğrulanmadı. Limit/ALO dolumu ayrıca kontrol edilir; bot emir açmaz.</i>',
    ])


def call(token,method,params):
    try:
        response=requests.post(f'https://api.telegram.org/bot{token}/{method}',
                               json=params,timeout=(10,20))
        if response.status_code!=200:
            return None
        payload=response.json()
        if not isinstance(payload,dict):
            return None
        return payload.get('result') if payload.get('ok') else None
    except (requests.RequestException,ValueError):
        return None


def deliver(store,settings,now):
    if settings.get('HL_TELEGRAM_ENABLED','false').lower()!='true':
        return 0
    token,chat=settings.get('HL_TELEGRAM_BOT_TOKEN'),settings.get('HL_TELEGRAM_CHAT_ID')
    if not token or not chat:
        raise ValueError('dedicated_telegram_credentials_missing')
    count=0
    for eid,event,attempts in store.pending(now):
        # Do not send stale hourly candidates after downtime.
        ttl=2*3600000 if event['strategy']=='HL-S' else 24*3600000
        if now-event['detected_ms']>ttl:
            store.db.execute('UPDATE events SET attempts=4 WHERE id=?',(eid,))
            store.db.commit()
            continue
        ok=call(token,'sendMessage',dict(chat_id=chat,text=message(event),parse_mode='HTML'))
        store.delivery(eid,now,bool(ok))
        count+=bool(ok)
        # One channel, keep burst deliveries below Telegram's per-chat pace.
        import time
        time.sleep(1.1)
    return count
