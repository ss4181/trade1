# G2 ve tüm bildirimleri açma — 14 Eylül 2026

16 Eylül gecikme incelemesi ve ortak hızlı bildirim güncellemesi:
[ölçüm, değişiklikler ve tablet adımları](TELEGRAM_LATENCY_AUDIT_2026-09-16.md).

G2, `fade_long_l1_up_d60_e2` adayının ileriye dönük araştırma bildirimidir.
Sabit 87 Binance sözleşmesi içinde son 24 saatte en çok düşen ilk 10,
en az %5 düşüş ve son 1 saatte en az %1 OI artışı aranır. Yalnız kapanmış
saatler kullanılır; giriş referansı koşul kapanışından 1 saat sonradır.
TP %3, SL %2, azami takip 24 saat; aynı sembolde 24 saat bekleme vardır.
Eksik evrenle yeniden sıralama yapılmaz; veri hatasında ilgili kontrol yeniden denenir.

Canlı OI, Binance 5 dakikalık nokta verisidir; araştırmadaki Coinalyze saatlik
OHLC serisinin birebir tekrarı değildir. Bu nedenle ayrı sürümle kaydedilir.
G2 mesajındaki fiyat Binance sözleşme birimidir; örneğin 1000PEPE fiyatını
Hyperliquid PEPE/kPEPE emrine doğrudan kopyalamayın. Bot emir göndermez.
Hyperliquid sembolü, limit dolumu, ücret ve funding bu başarı ölçümüne dahil değildir.

Her strateji mesajı, o stratejinin gerçekten teslim edilmiş son 5 sinyalini
gösterir. Mevcut mesaj bu beşliye dahil değildir. Az geçmiş varsa mevcut sayı
yazılır. Başarılı / başarısız / bekliyor / ölçülemedi ayrı gösterilir.
Sonuçlananların oranı ayrıca verilir; bekleyenler başarı gibi sayılmaz.
Eski ölçüm sürümü veya eksik sonuçlar yerine daha eski kazananlar seçilmez.
Araştırma sonuçları canlı bildirim geçmişine eklenmez.

- G2: planlanan saatteki Binance 5dk açılışından TP %3, SL %2'den önce.
  Aynı mumda iki sınır görülürse başarısız; 24 saatte hedef yoksa başarısız.
  Eksik mumlar bekler; planlanan girişten sonra teslim edilen mesaj ölçülemedi sayılır.
- Diğerleri: mevcut `USER_SUCCESS_TARGET_PCT` hedefine dokunma (varsayılan %2),
  mevcut takip ufku boyunca. Bu ölçüm stop sırası veya net kâr değildir.

## Tablette adımlar

Bu adımları paket main'e gönderildikten sonra, tabletin Termux uygulamasında yapın.
Bilgisayarda ayrıca anahtar girişi veya kurulum gerekmiyor. Yeni bağımlılık yok.

1. Projeye girin ve mevcut kaydı yedekleyin:

```bash
cd ~/trade1
git status --short
python signal_bot.py --backup-now
python signal_bot.py --backup-status
```

Yedek hatası varsa durun ve hata çıktısını paylaşın. Yerel kod değişiklikleri
varsa silmeyin; güncelleme çakışırsa çıktısını paylaşın.

2. Botu durdurun:

```bash
touch .stop-signal-bot
pkill -f "python signal_bot.py" || true
pkill -f "uvicorn server:app" || true
pgrep -af "boot-signal-bot.sh|uvicorn server:app|python signal_bot.py"
```

Liste boşalana kadar yeniden başlatmayın. Eski wrapper en fazla 5 dakika
içinde kapanabilir; son kontrol komutunu tekrar çalıştırın.

3. Paketi alın ve tüm strateji bildirimlerini açın:

```bash
git pull --ff-only origin main
test -f G2_NOTIFICATIONS.md && echo "G2 paketi mevcut"
python configure_notifications.py --enable-all
python -m py_compile signal_bot.py g2_notifications.py notification_scorecard.py configure_notifications.py
```

Komut `.env` dosyasını okumaz veya değiştirmez. Ayrı yerel tercih dosyası
gözlem, G1/DL1/G2, S2 araştırma, hedef ve özet bildirimlerini açar;
strateji kapatma listesini boşaltır ve düşük güven sessizliğini kaldırır.
Sinyal koşulları ve tekrar bildirim bekleme süreleri korunur.
Telegram token/alıcı ayarları mevcut haliyle kullanılır.

4. Botu bir kez başlatın:

```bash
rm -f .stop-signal-bot
nohup sh ./termux/boot-signal-bot.sh >/dev/null 2>&1 &
```

5. Kontrol edin:

```bash
pgrep -af "boot-signal-bot.sh|uvicorn server:app|python signal_bot.py"
python configure_notifications.py
python notification_delivery.py --status
git log -1 --oneline
```

Bir wrapper ve bir ana bot beklenir. Tercih çıktısında `all-alerts-2026-09-14`,
`G2_ENABLED: true`, `G2_PUSH: true` ve boş `DISABLED_STRATEGIES` görünmelidir
(değerler JSON metni olarak yazılır). Son üç komutun çıktısını paylaşabilirsiniz;
anahtarınızı veya `.env` içeriğini paylaşmayın.
Telegram sohbetini uygulamadan ayrıca sessize aldıysanız sohbetin bildirimlerini açın.

G2 yalnız koşul oluştuğunda gelir. İlk mesajda geçmiş olmaması normaldir.
Geçmiş mesajların Telegram içeriği geriye dönük değişmez; yeni mesajlar güncel
sonuçları içerir. İlk doğal mesajdaki Son 5 satırını kontrol edin.

## Doğrulama

İzole testler gerçek `.env`, canlı durum dosyaları ve ağ bağlantısı olmadan
çalıştırılır: `python tests/run_isolated.py`. G2 kapanış sınırları, eksik evren,
OI zamanları, yeniden başlatma, TP/SL sırası, belirsiz mum, geç teslim,
24 saat zaman aşımı, son beş seçimi, Telegram metni ve yedek kapsamı testlidir.
Tablet çalışması ve gerçek Hyperliquid limit dolumu yerel test sonucu değildir.
