# Rejim değişimi ve sinyal koşulu uyarıları — 23 Eylül 2026

Kullanıcı tercihi: teslim edilmiş sinyali stratejinin mevcut ufku boyunca izle.
Uyarı katmanı performans sonuçlarını, eski başarı tanımını, strateji eşiklerini
ve emirleri değiştirmez. Rejim bozulması sinyalin kesin başarısızlığı değildir.
Bu sürüm risk değişimini bildirir; otomatik iptal veya işlem kapatma yapmaz.

## Ölçüm ve gerekçe

- Günlük BTC/SMA200 ana rejimi korunur.
- Gün içi katman BTCUSDT ve ETHUSDT spot 1h ve 15m kapanışlarını kullanır.
  Her seri için son 240 kapalı mum alınır. EMA20, EMA50, son dört barlık EMA20
  yönü ve 14 barın ortalama gerçek aralığı (ATR14) hesaplanır.
- Boğa: fiyat ve EMA20, EMA50'nin en az `max(0.25 * ATR14, fiyat * 0.001)`
  üzerinde ve EMA20 yükseliyor. Ayı: simetrik olarak altında ve EMA20 düşüyor.
  Diğer durumlar geçiş. Bunlar önceden belirlenmiş gözlem eşikleridir;
  getiriyi en iyi yapan parametreler diye seçilmedi.
- Boğa/ayı etiketi için iki farklı kapanmış mumda aynı yön ve BTC/ETH uyumu
  gerekir. Tek mumluk dönüş veya iki coin arasında ayrışma geçişe düşürür;
  geçiş etiketi bu nedenle boğa/ayıdan önce değişebilir.
- Gün içi veri her 15 dakika yenilenir. Açık mum, eski son mum, eksik aralık,
  yinelenen zaman veya geçersiz fiyat kullanılamaz. Veri hatası ayı/geçiş sayılmaz.
- İlk açılışta piyasa etiketi sessizce başlangıç kabul edilir. Bundan sonraki
  günlük/saatlik/erken etiket değişiklikleri tek piyasa mesajında bildirilir.

Binance'ın [resmî spot mum belgesi](https://github.com/binance/binance-spot-api-docs/blob/master/rest-api.md#klinecandlestick-data)
15m/1h aralıklarını, açılış/kapanış zamanlarını ve UTC parametrelerini tanımlar.
Sinyal fiyat yapısı, sinyalin kendi spot veya USD-M vadeli piyasasında ölçülür.
Hyperliquid dolumu veya açık pozisyon bilgisi kullanılmaz.

## Sinyal takibi

- S1, S1+S4, S2, S3, S5, S6, G1 ve G2: yalnız Telegram teslimi doğrulanmış
  sinyaller. DL1 bir delist olayıdır, bu yön takibine alınmaz.
- Normal sinyalde mevcut bildirim zamanı + `horizon_hours`; G2'de mevcut
  planlanan giriş + 24 saat. Ufuk dolunca takip biter. Hedefe ulaşmak bu seçilen
  ufku kısaltmaz; gerçek işlemin açık olduğu varsayılmaz.
- Günlük, saatlik veya erken yön sinyalin başlangıç etiketine göre yönünün
  aleyhine bozulursa gerekçeli uyarı. Örneğin LONG için boğa → geçiş/ayı;
  SHORT için ayı → geçiş/boğa. Eksik başlangıç etiketi ilk geçerli ölçümle
  tamamlanır, veri yokken geçmiş yön uydurulmaz.
- Fiyat yapısı: LONG için referans saatlik mumun dibinin altında, SHORT için
  tepesinin üstünde **iki ardışık 15dk kapanışı**. Fitil yeterli değildir.
  İki mum da ilk bildirimin ardından başlamalıdır. S2'nin referansı funding
  anından önceki kapalı saattir; diğerlerinde sinyal mumudur.
- Bu fiyat kuralı, stratejilerin orijinal stop kuralı olarak doğrulanmış değildir;
  ek bir risk gözlemidir. Hacim patlamasının veya OI koşulunun sonraki mumda
  kaybolması otomatik başarısızlık sayılmaz.
- Aynı sinyal/gerekçe bir kez uyarılır. Bir kontrolde birden çok gerekçe varsa
  tek mesajda toplanır. İyileşme sonrası aynı gerekçenin tekrarı yeni sinyal
  oluşana kadar yeniden uyarılmaz. Piyasa yönündeki iyileşme genel mesajda görünür.
- Sinyal uyarısı yalnız ilk sinyali almış ve hâlen abone olan kişilere gider.
  Genel rejim değişimi mevcut abonelere gider. Bütün görünen zamanlar TRT'dir.

## Çalışma ve gecikme

Bağımsız worker 15 saniyede bir uyanır, fiyat kontrollerini 5 dakikalık aralıkla
yapar. Her tarama sınırının ilk 30 saniyesinde yeni iş başlatmaz; ana sinyal
tarama yoluna ek ağ isteği eklenmez. Uzayan ağ istekleri ortak bağlantı/borsa
limitlerini yine etkileyebilir; tablet gecikmeleri ayrıca izlenmelidir.

Tur başına en fazla 20 farklı piyasa/sembol fiyat sorgulanır; fazla sinyal varsa
en uzun süredir kontrol edilmeyenlerden devam edilir. Rejim uyarıları bu kotaya
bağlı değildir. `/status` bekleyen fiyat kontrolü ve hata sayısını gösterir.

Erken yön 15dk mum çözünürlüğündedir; boğa/ayı teyidi iki mum ister. EMA yönü
bir dönüşü daha geç yakalayabilir. Bu nedenle anlık veya kesin 30dk tespit
garantisi yok. İlk bildirimden sonraki iki tam fiyat mumu için en az 30–45dk
veri gerekir. Bütçe, veri gecikmesi veya ağ hatası kontrolü daha da geciktirebilir.

Uyarılar `.signal_watch_outbox.json` içinde ayrı tutulur; sinyal teslim
gecikmesi ve son-beş başarı karnesine karışmaz. Hatalı gönderim aynı outbox'ın
en fazla dört deneme / 15dk kuralına tabidir. Ufku geçmiş uyarı gönderilmez.
`.signal_watch_state.json` yeniden başlatmalarda başlangıç/uyarı bilgilerini
korur. Bozuk dosya otomatik silinmez; `/status` hata gösterir. İkisi de özel
`--include-state` yedeğine dahildir; Git'e girmez.

## Tarihsel kontrol

1 Ocak–1 Temmuz 2026 UTC aralığında 4.344 saat, mevcut spot BTC/ETH arşivi:

| Ölçüm | Etiket değişimi | Etikette kalma medyanı |
|---|---:|---:|
| Günlük ana rejim | 4 | 48 saat |
| Yeni saatlik yön | 289 | 10,5 saat |

Bu dönem günlük sınıflama ağırlıkla ayıdır (4.272 saat); yeni saatlik yön
873 saat boğa, 1.171 saat ayı, 2.300 saat geçiş göstermiştir. İki ölçüm
3.133 saatte ayrışmıştır: farklı zaman ölçekleri aynı şeyi ölçmez.
İlk/son gözlenen koşular dönem sınırında kesilir; medyanlar betimseldir.

Bu kontrol daha sık gün içi değişim yakalandığını gösterir; daha yüksek
strateji başarısını veya yanlış uyarı oranını kanıtlamaz. Eşleşen yerel spot
15dk arşivi olmadığından 15dk katman için tarihsel performans iddiası yoktur.
Eşikler optimize edilmedi. Kaynak hash'leri ve sonuçlar
`research/results/intraday_regime_review_2026-09-23.json` içindedir.

## Tablette güncelleme

Doğrulama: 33 izole test grubu geçti. Yeni 13 test; kapalı mum teyidi, eksik
veri, LONG/SHORT simetrisi, ufuk, G2 giriş saati, alıcı yetkisi, tekrar
göndermeme, yeniden başlatma, enqueue sonrası çökme, veri düzelmesi, istek
bütçesi ve gerçek arka plan worker yaşam döngüsünü kapsar.

1. `cd ~/trade1` ardından `git pull --ff-only origin main`. Hata çıkarsa dur.
2. Özellik varsayılan açık; yeni anahtar veya paket gerekmez. Daha önce
   `SIGNAL_WATCH_ENABLED=false` eklediysen onu `true` yap.
3. Botu durdur ve süreç kontrolünün boş olduğunu doğrula:

```bash
touch .stop-signal-bot
pkill -f '[b]oot-signal-bot.sh' 2>/dev/null || true
pkill -f '[u]vicorn server:app|[p]ython signal_bot.py' 2>/dev/null || true
sleep 3
pgrep -af '[b]oot-signal-bot.sh|[u]vicorn server:app|[p]ython signal_bot.py'
```

4. Kontrol boşsa tek bot başlat:

```bash
rm -f .stop-signal-bot
nohup sh ./termux/boot-signal-bot.sh >/dev/null 2>&1 &
```

5. İlk veri kontrolü için birkaç dakika sonra Telegram'da `/piyasa` ve
   `/status` gönder. Günlük/saatlik/15dk satırları, sinyal takibi `çalışıyor`,
   güncel kontrol zamanı ve hata durumu görünmeli. Aktif sinyal 0 olması
   hata değildir. Ufku hâlen devam eden eski bildirimler de takibe alınır.
6. Bundan sonra rejim değişimi ve koşul bozulması uyarıları otomatik gelir.
   Herhangi bir uyarı gerçek emri açmaz veya kapatmaz.
