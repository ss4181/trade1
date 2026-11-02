# G2 ve tüm bildirimleri açma — 14 Eylül 2026

## G2 Telegram bildirimini susturma — 2 Kasım 2026

İleri ölçümde G2 TP3/SL2 hedef oranı başabaşın altında kaldığı için Telegram
bildirimi kapatılabilir. **En kolay yol:** bot sahibi Telegram'da `/g2 kapat`
yazar (açmak: `/g2 ac`, durum: `/g2`). Ayar hemen uygulanır, profile yazılır ve
yeniden başlatmada korunur. Terminalden aynı iş için: tüm-bildirimler profili `.env` değerini ezdiğinden
`.env` içine `G2_PUSH=false` yazmak profil varken etkisizdir. Önce bakın:

```bash
python configure_notifications.py
```

`"profile": "all-alerts-2026-09-14"` görünüyorsa `python configure_notifications.py --mute-g2`
çalıştırıp botu yeniden başlatın; yeni profil `all-alerts-g2-muted-2026-11-02` olur.
`existing-env-settings` görünüyorsa `.env` içine `G2_PUSH=false` yazıp yeniden başlatın.
Diğer kanallar değişmez. Geri açmak: `python configure_notifications.py --enable-all`.

G2 taraması ve `g2_events_*.jsonl` / `g2_market_*.jsonl` arşivi sürer. Canlı TP3/SL2
karnesi ise yalnız Telegram teslimi doğrulanan olaylarda başladığı için susturulmuşken
yeni olay eklemez; sonuçlar gerekirse arşivden çevrimdışı ölçülür.

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
# Bildirim zamanı (2026-10-01)

G2 koşulları kapanışta hesaplanır ve kalıcı `.g2_state.json` kuyruğuna alınır.
Telegram hazırlık bildirimi, planlanan girişten 5 dakika önceki ilk worker
kontrolünde gönderilir. Örnek: 00.00 kapanışı → yaklaşık 00.55 bildirim →
01.00 planlanan Binance giriş referansı (TRT). İnternet/worker gecikmesi olabilir.
Giriş saati gelmiş eski bildirimler ve teslim tekrarları gönderilmez.
Yeniden başlatma bekleyen kuyruğu korur. Mevcut sürüme geçmeden önce üretilmiş
olaylar geriye dönük kuyruğa alınmaz.

Bu bir güncel güç doğrulaması değildir: koşullar kapanış anına aittir;
kullanıcı giriş öncesi fiyatı takip eder. Strateji eşikleri, TP3/SL2, 24 saat
ufuk ve ölçüm giriş saati değişmez. Gerçek emir açılmaz.
