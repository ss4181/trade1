# Tarama ve bildirim hızlandırması — 22 Eylül 2026

Son tablet ölçümü: kapanıştan Telegram API kabulüne medyan 15,166 sn,
en fazla 20,089 sn (13 bildirim). Tarama başlangıcına kadar medyan 10,007 sn;
tarama–tespit medyan 3,728 sn. Bunlar cihaz ekranına geliş zamanı değildir.

## Değişiklik

- Kapanış payı varsayılan 10 → 5 saniye. `.env` içinde açıkça yazılan eski
  değer varsa o korunur; aşağıdaki güncellemede 5 yapılır.
- Spot ve USD-M GET istekleri ayrı bağlantı havuzları kullanır. Aynı session
  aynı anda iki worker'a verilmez. Havuz başına en fazla 16 boş session saklanır;
  fazlası ve ağ hatası verenler kapanır. Cevap cache'i yok, güncel veri yeniden alınır.
- Paralellik 8 worker; mevcut 429/Retry-After ve 5xx geri çekilmesi korunur.
  Telegram gönderme sıklığı değiştirilmedi.
- Spot taraması son saatin kapanmış mumunu bekler; geç yayımlanırsa saniyede
  bir, en fazla 5 ek saniye dener. Hâlâ yoksa strateji state'i eski mumla
  değiştirilmez ve sembol hatası raporlanır. Sonraki normal taramada tekrar denenir.
- G1 son kapanmış saati doğrular. Bazı adaylar eksikse saat tamamlanmış sayılmaz;
  sonraki worker turu tekrar dener. Önceden gönderilen sinyaller cooldown ile korunur.
- `/health` ve pano verisindeki `notification_delivery.market_http` alanı
  toplam istek, session oluşturma ve yeniden kullanım sayılarını gösterir.

## Ölçüm

Bu bilgisayardan Binance herkese açık BTCUSDT 1h/250 mum isteği, 4 çift deneme,
sıra dönüşümlü ve havuz için 1 ısınma isteği: yeni bağlantıda medyan 0,60415 sn,
yeniden kullanımda 0,26670 sn. Yaklaşık %56 daha kısa istek süresi;
bu sonuç bütün taramanın %56 hızlanacağı anlamına gelmez. Tablette doğrulanmalıdır.
Tekrar ölçüm aracı: `python research/benchmark_market_http.py --samples 4`.
Bu araç botu açmaz, Telegram mesajı göndermez, anahtar veya canlı state kullanmaz.

Beklenti: benzer ağ koşullarında kapanıştan bildirime süre birkaç saniye daha
kısalır. 5 saniyelik bekleme azaltımı doğrudan; bağlantı kazancı ağ koşullarına
bağlıdır. Bütün bildirimlere tek bir süre garantisi verilmez.

## Tablet adımları

Doğrulama: `tests/run_isolated.py` ile 32 test grubu geçti, hata yok.
Testler canlı dosyalara ve ağa dokunmadı; yukarıdaki API ölçümü ayrı çalıştırıldı.

1. `cd ~/trade1` ve `git pull --ff-only origin main`. Git hata verirse devam etmeyin.
2. Aşağıdaki kod yalnız iki performans ayarını günceller, başka `.env` satırını
   veya bildirim tercihini değiştirmez; anahtarları yazdırmaz:

```bash
python - <<'PY'
from pathlib import Path
import re
p = Path('.env')
text = p.read_text(encoding='utf-8') if p.exists() else ''
keys = {'SCAN_CLOSE_DELAY_SECONDS': '5', 'MARKET_HTTP_REUSE_ENABLED': 'true'}
lines = [line for line in text.splitlines()
         if not any(re.match(r'^\s*(?:export\s+)?' + key + r'\s*=', line) for key in keys)]
lines.extend(key + '=' + value for key, value in keys.items())
tmp = p.with_suffix('.scan-speed.tmp')
tmp.write_text('\n'.join(lines) + '\n', encoding='utf-8')
tmp.replace(p)
print('Kapanış payı: 5 sn; bağlantı yeniden kullanımı: açık.')
PY
```

3. Mevcut wrapper ve botu durdurun:

```bash
touch .stop-signal-bot
pkill -f '[b]oot-signal-bot.sh' 2>/dev/null || true
pkill -f '[u]vicorn server:app|[p]ython signal_bot.py' 2>/dev/null || true
sleep 3
pgrep -af '[b]oot-signal-bot.sh|[u]vicorn server:app|[p]ython signal_bot.py'
```

4. Üstteki kontrol boşsa tek wrapper başlatın:

```bash
mkdir -p tmp
date -u +%Y-%m-%dT%H:%M:%SZ > tmp/notification-check-since.txt
rm -f .stop-signal-bot
nohup sh ./termux/boot-signal-bot.sh >/dev/null 2>&1 &
```

5. Telegram `/status` ile kapanış payının 5 sn olduğunu kontrol edin. Birkaç
   yeni bildirimden sonra aşağıdaki çıktıyı paylaşın:

```bash
python notification_delivery.py --status --since "$(cat tmp/notification-check-since.txt)"
```

Geri alma: `.env` içinde `SCAN_CLOSE_DELAY_SECONDS=10` ve
`MARKET_HTTP_REUSE_ENABLED=false`, sonra aynı tek-instance yeniden başlatma.
