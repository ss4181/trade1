# Telegram gecikmesi: kod incelemesi ve çözüm — 16 Eylül 2026

Durum: d1e3c3a tablet ölçümü alındı; aşağıdaki neden doğrulandı. Ortak hızlı
bildirim düzeltmesi yerelde hazırlandı. Henüz tablette etkin değil.

## Gerçek tablet ölçümü

16 Eylül 15:00 UTC kapanışlı son G2, Telegram API'sine 15:02:44.940888 UTC'de
ulaştı. G2 tarama başlangıcına kadar 125,562 saniye, oradan kuyruğa 39,008
saniye ve Telegram kabulüne 0,371 saniye geçti: toplam 164,941 saniye.
Son 20 kaydın Telegram gönderim medyanı 0,368 saniye, en yükseği 0,665 saniye;
bekleyen olay sıfır. Kapanış damgası olan 15 olayın toplam medyanı 162,102 saniye.
Bu örnekte 2–3 dakika botun içinde geçiyor. Kullanıcı diğer stratejilerde de
aynı sorunu doğruladı; kod incelemesi ortak seri taramayı gösteriyor.

## Hazırlanan düzeltme

- Tüm bildirimler açık profilde S1/S2/S3/S5/S6 en fazla 8 işçiyle taranır.
  Hazır sonuçlar ana listede veya gözlem listesinde diğer coinleri beklemez.
  Durum kaydı ve bildirim çıkışı tek tarama sahibinde kalır; cooldown erişimi
  kilitlidir. Açık mum veya farklı strateji eşiği kullanılmaz.
- Düşük bildirim tavanını bilerek koruyan profilde eski global öncelik seçimi
  korunur; bu profilde erken gönderim etkinleşmez. `configure_notifications.py
  --enable-all` profili hızlı yolu varsayılan açar. `SCAN_STREAMING_ENABLED=false`
  veya `SCAN_WORKERS=1` verilmişse hızlı yol kapalıdır.
- S2 araştırma arşivi, sinyaller gönderildikten sonra işlenir; arşivin gerçek
  gözlem zamanı kullanılır.
- G2 ana döngüden bağımsız, tek liderin yönettiği 5 saniyelik kontrol işçisiyle
  çalışır. Kapanış payı varsayılan 10 saniyedir. 87 fiyat sorgusu en fazla 8
  paralel işle toplanır; tam evren şartı korunur. Tespit damgası gerçek karar
  anıdır. Worker liderlik bırakılmadan durdurulur.
- G1/DL1 worker'ı ana tarama öncesinde başlatılır; G1 mesajı DL1'in bitmesini
  beklemez. DL1 mum stratejisi değildir; duyuru kontrol aralığı korunur.
- Telegram'da aynı alıcıya gönderimler ayrı sohbet kilitleriyle aralıklanır
  (özel sohbette en az 1,05 sn, grupta 3,05 sn). Bu, paralel sinyallerin bir
  anda gönderilip 429'a dönüşmesini azaltır. Yoğun saatte tüm mesajların ayrı
  ayrı 30 saniye altında ulaşacağı garanti edilmez.
- Salt okunur teslim teşhisine strateji bazında süreler ve 30 saniye altı
  örnek sayıları eklendi. `/health` teslim bölümünde worker ve tarama ayarları
  görülebilir. CLI `--status` canlı süreç durumunu iddia etmez; dosyayı ölçer.

WebSocket önbelleği ve hata türüne göre kısa Telegram retry takvimi bu ilk
düzeltmeye dahil değil. Tablet ölçümü kalan darboğazı gösterirse ikinci adım
olarak uygulanabilir; mevcut örnekte Telegram retry darboğazı yok.

## Kanıtlanan kod davranışı

İncelenen d1e3c3a sürümünde `signal_bot.py:3357` içindeki `scan_all`, ana sembolleri sırayla tarar.
Bildirimler bütün ana semboller bittikten sonra sıralanıp gönderilir.
Varsayılan 89 sembol için 89 spot mum isteği, çekirdek 30 sembol için 30
funding isteği ve her sembol sonrası 0,25 saniye bekleme vardır.
Bu yalnız ana taramadır; toplam 119 istek ve 22,25 saniye sabit bekleme eder.
Kapanış sonrası zamanlayıcı varsayılan olarak ayrıca 10 saniye bekler.

Mevcut kodun gerçek `scan_all` / `scan_symbol` / mum ve funding ayrıştırma
fonksiyonlarıyla, sahte ağ cevapları ve sanal saat kullanılarak yeniden üretildi.
İlk sembole sentetik bir sinyal eklendi. Ağ, Telegram, gerçek `.env` ve canlı
durum dosyaları kullanılmadı. Gözlem ve araştırma ek işleri deneye dahil değil.

| Her istek için varsayılan süre | İlk sinyal tespiti | Gönderim çağrısı | Tespitten sonra gereksiz bekleme |
|---|---:|---:|---:|
| 0,5 saniye | 11,0 sn | 91,75 sn | 80,75 sn |
| 0,8 saniye | 11,6 sn | 127,45 sn | 115,85 sn |
| 1,2 saniye | 12,4 sn | 175,05 sn | 162,65 sn |

Bunlar tablet performans ölçümü değildir. Seri taramanın bildirilen 2–3
dakikayı tek başına üretebildiğini gösterir. Yerel inceleme betiği (tablet
paketinin parçası değildir) ile yeniden üretim:
`python tmp/latency-audit/reproduce.py`; sonuç `tmp/latency-audit/results.json`.

Ek beklemeler:

- `signal_bot.py:4035–4054`: G2/G1/DL1 worker'ı ancak ana ve gözlem taraması
  ile hedef takibi bittikten sonra başlar. G2 ayrıca 87 futures mum isteğini
  sırayla yapar (`g2_notifications.py:76`). G2'nin planlanan girişteki +1 saat
  kuralı ayrı bir strateji kuralıdır; bildirim gecikmesi değildir.
- `signal_bot.py:1933`: S2 araştırma arşivi aynı sembol taraması içinde
  beklenir. Sinyalin koşulu zaten oluşmuş olsa da ek ağ istekleri onu bekletir.
- `notification_delivery.py:234`: gönderim başarısızlığında tekrarlar 60,
  ardından 120 saniye bekler. İki başarısızlık üçüncü denemeyi yaklaşık
  180. saniyeye taşır. 5 saniyelik retry worker kontrolü bu vadeyi kısaltmaz.
- `signal_bot.py:2481` çevresindeki Telegram gönderici `retry_after` bilgisini
  korumaz; başarısızlığı yalnız doğru/yanlış değerine dönüştürür. Tüm
  kanalların açılması yoğun saatlerde bu yolu daha önemli hale getirir.
- Piyasa isteklerinde 30 saniye timeout ve varsayılan dört deneme bulunur.
  Ağ sorunu tek sembolde dahi bütün sırayı bekletebilir.
- Son 5 kartı için ağ isteği yapılmaz; mevcut yerel kayıtlar kullanılır.
  Büyük outbox dosyalarının JSON yazma maliyeti olası ek etkidir, tablette
  ölçülmeden ana sebep olarak gösterilmemelidir.

## Hedef tasarım ve sonraki seçenekler

1. Sinyal oluşunca kalıcı kuyruğa hemen al; diğer coinlerin bitmesini bekletme.
   Sembol başına cooldown ve olay kimliğiyle tekrar önleme korunmalı. Eski
   global sıralama yalnız sınırlı push bütçesi için gerekliydi; tüm bildirimler
   açık profilde erken bulunan sinyali bu yüzden bekletmek gereksizdir.
2. S1/S3/S5/S6 için kapanmış mumları bellekte tut; Binance WebSocket `x=true`
   kapanış olayında aynı strateji motorunu çalıştır. Başlangıçta geçmiş veriyi
   REST ile tamamla. Kopma, eksik mum, yeniden bağlantı ve 24 saat bağlantı
   yenilemesinde REST uzlaştırması ve aynı olay kimliği kullan.
3. İlk iyileştirme / yedek yol olarak sınırlı paralel REST (örneğin en fazla
   8 işçi) ve bağlantı tekrar kullanımı değerlendir. `ScanState` ve kayıt
   yazımları tek bir sahipte kalmalı; API hata kapıları ortak olmalı.
   Açık mum kullanarak veya bazı coinleri atarak süreyi düşürme.
4. G2'yi kapanışta bağımsız başlat. Sabit 87'lik evrenin kapanışlarını
   önbellekten tamamla, OI'yi uygun zaman damgalarıyla getir. Eksik evrenle
   sıralama yapma. OI sağlayıcı yayımlama süresi ayrıca ölçülmeli; bütün
   stratejiler için 30 saniye garantisi verilemez. G2 `detected_at` alanı
   şu anda tarama başlangıcını tutuyor; gerçek karar anı olarak düzeltilmeli.
5. Funding ve S2 arşivleme işlerini mum sinyallerinden ayır; hedef geçmişini,
   günlük raporu ve yedeği gönderimin önkoşulu yapma. Önceden gözlenen veri
   zamanları arşivde korunmalı; işi erteleyince sonradan gelen veri erken
   gözlenmiş gibi etiketlenmemeli.
6. Telegram gönderimini sohbet başına hız sınırlı ayrı kuyrukta yürüt.
   429 cevabındaki `retry_after` beklemesine uy; ağ/5xx için daha kısa,
   sınırlı tekrar takvimi kullan. Başarısızlık türünü ve deneme süresini
   sır içermeyen teşhise ekle. Çok sayıda eşzamanlı sinyalde mesajları
   birleştirmek gerekebilir; sinyalleri sessizce düşürme.

Binance kapanmış mum bayrağını ve bağlantı kurallarını
[resmî WebSocket belgesinde](https://github.com/binance/binance-spot-api-docs/blob/master/web-socket-streams.md)
tanımlar. Telegram tek sohbette saniyede bir mesajın aşılmamasını,
gruplarda dakikada 20 mesaj sınırını belirtir:
[Bot FAQ](https://core.telegram.org/bots/faq#my-bot-is-hitting-limits-how-do-i-avoid-this).
429 için bekleme süresi [ResponseParameters](https://core.telegram.org/bots/api#responseparameters)
içindedir. Binance [REST limitleri](https://developers.binance.com/en/docs/products/spot/rest-api#limits)
de paralel sorgularda korunmalıdır.

## İlk teşhis için kullanılan tablet komutları

Botu durdurmadan Termux'ta:

```bash
cd ~/trade1
git log -1 --oneline
python notification_delivery.py --status
```

Çıktıyı ve geciken mesajın stratejisini, mum kapanışını, tespit saatini ve
cihazda görülme saatini paylaş. Saatlerin aynı dilimde olduğundan emin ol;
bot UTC, Türkiye UTC+3 kullanır. Anahtar veya `.env` içeriği gerekmez.

`reference_to_detect` yüksekse zamanlama/veri/tarama; `detect_to_queue`
yüksekse taramanın kalanını veya önceki bildirimleri bekleme; `queue_to_ack`
yüksekse gönderim/ağ/retry araştırılır. G2'nin mevcut tespit damgası yüzünden
tarama maliyetinin bir bölümü ikinci alanda görünür. S2 referansı mum
kapanışı değil funding ödeme zamanıdır.

`reference_to_ack` 30 saniyenin altında fakat cihazda görünme geçse Telegram/
Android teslimi ayrıca incelenir. API kabulü cihaz bildirimi değildir;
birden fazla alıcıda bu ölçüm ilk başarılı alıcıya aittir.

## Düzeltme main'e gönderildikten sonra tablette güncelleme

1. Termux'ta `cd ~/trade1`, `python signal_bot.py --backup-now` ve
   `python signal_bot.py --backup-status` çalıştır. Yedek hatasında devam etme.
2. `touch .stop-signal-bot` ile durdurma işareti koy; ardından
   `pkill -f "python signal_bot.py" || true` ve
   `pkill -f "uvicorn server:app" || true` çalıştır.
3. `pgrep -af "boot-signal-bot.sh|uvicorn server:app|python signal_bot.py"`
   boş dönene kadar bekle (wrapper en fazla 5 dakika sürebilir).
4. Aşağıdakileri sırayla çalıştır; herhangi biri hata verirse dur:

```bash
git pull --ff-only origin main
python configure_notifications.py --enable-all
python -m py_compile signal_bot.py g2_notifications.py notification_delivery.py
rm -f .stop-signal-bot
nohup sh ./termux/boot-signal-bot.sh >/dev/null 2>&1 &
```

5. `git log -1 --oneline` ve süreç kontrolünü tekrar çalıştır. Yeni doğal
   sinyal geldikten sonra `python notification_delivery.py --status` çıktısını
   paylaş. `latest_ack_at` kurulumdan sonraki sinyale ait olmalı. Eski kayıtları
   silme; ilk 20 örnekte eski/yeni süreler karışabileceğinden en yeni olay ve
   strateji ayrımına bak. G2 dışındaki ilk yeni mesajın stratejisini de belirt.

Bilgisayarda veya tablette API anahtarı değişikliği gerekmez. Tarama aralığı
5 dakika kalır; hız kazancı isteklerin ve gönderimin düzenlenmesinden gelir.

## Başarı ölçütü

Yerel çalışma alanında 32 izole test grubu geçti. Ek testler erken core/gözlem
gönderimini, eşzamanlılık sınırını, ortak API hatasında yeni iş başlatılmamasını,
aynı motor kararlarını ve cooldown'ı, G2'nin ana tarama sırasında çalışmasını,
liderlikten önce durmasını, seri/paralel G2 karar eşliğini, gerçek tespit
damgasını, S2 arşivi ve DL1 beklemesinin ayrılmasını ve sohbet hız sınırını
doğruladı. Canlı Telegram mesajı gönderilmedi; tablet sonucu değildir.

Sağlıklı bağlantı, hazır geçmiş ve normal mesaj yoğunluğunda kapanıştan
Telegram API kabulüne p95 <30 saniye hedeflenir; her strateji ayrı raporlanır.
Başarısız/eksik sinyaller paydadan gizlenmez. Önce deterministik sinyal eşliği,
yeniden başlatmada tekrar önleme ve kopma telafisi test edilir; ardından
tablette gerçek kapanışlarla ve cihaz alım saatiyle doğrulanır. 10 saniyelik
kapanış payını azaltmak tek başına 2–3 dakikalık sorunu çözmez. Tarama
aralığını 5 dakikadan 1 dakikaya indirmek de seri taramayı hızlandırmaz.
