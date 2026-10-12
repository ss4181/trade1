# S1/S3/G2 ileri giriş–çıkış takibi — 11 Ekim 2026

Sürüm: `execution-shadow-v1`. Bu metin yeni veri toplanmadan dondurulan
deney sözleşmesidir. Kaynak adaylar: `PREREG_ALL_EXECUTION.md` ve
`ALL_EXECUTION_REVIEW_2026-10-02.md`. Eski araştırma sonuçları bu yeni
ölçümün sonuçlarına eklenmez. Yeni test fiyat yolu karşılaştırmasıdır;
Telegram bildirim politikasını, sinyal üretimini veya gerçek emirleri yönetmez.

## Evren ve sabit deney kolları

| Olay grubu | Karşılaştırma | Aday / kontrol | Azami süre |
|---|---|---|---|
| S1, sabit genişletilmiş 59, spot | İlk referans açılışı, TP3/SL2 | Aynı giriş, TP6/SL3 | 24 saat |
| S3, çekirdek 30, spot | İlk referans açılışı, TP3/SL2 | 15dk teyit, sabit TP3/SL3; aynı teyit, %3'te etkinleşen %3 takip stopu | 4 saat |
| G2, sabit 87, USD-M | Planlanan saat, TP3/SL2 | Önceki TP4/SL3; %6'da yarım çıkış, kalana %3 takip stopu, ilk stop %3 | 24 saat |

S1+S4, çekirdek S1, genişletilmiş S3, S5/S6 ve sonradan eklenen semboller
bu adaylara dahil edilmez. Üyelik, kayıt anındaki evren etiketi ile önceden
sabitlenen sembol listesine birlikte bakılarak kontrol edilir. Motor/config
sürümü, evren, piyasa ve bildirim anındaki rejim ayrı kohort alanlarıdır.
Motor veya sinyal konfigürasyonu farklı olaylar aynı başarı oranına katılmaz.

## Gerçek başlangıç ve giriş

- Başlangıç tarihi tahmin edilmez: tek bot lideri bu özelliği ilk başlattığında
  `.execution_shadow_state.json` içine `activated_ms` yazar. Geçmiş loglar
  taranarak yeni ileri test kaydı üretilmez.
- Yalnız Telegram API'sinin en az bir alıcı için onayladığı, bastırılmamış
  yeni olaylar kaydolur. API onayı, telefonda okuma veya borsada dolum değildir.
  İlk onay zamanı kullanılır; tekrar teslim ve yeniden başlatma olayı çoğaltmaz.
  Başlangıçtan eski, gelecekteki veya kayıt sırasında 5 dakikadan eski
  teslimler alınmaz. Bu kısıt gecikmiş yeniden kurulumu ileri veri diye sunmaz.
- S1/S3 `t0`: onay zamanından **kesin sonraki** tam 5dk mum açılışı.
  Tam sınıra denk gelen onayda da sonraki mum seçilir.
- G2 `t0`: olayın `planned_entry_at` saati. API onayı bu saatten önce
  gelmediyse deney kaydı oluşturulmaz. Binance fiyatı kullanılır; Hyperliquid
  ALO/limit dolumu varsayılmaz.
- Bütün kolların son saati `t0 + azami süre`. Teyit koluna fazladan süre yok.
- Teyit yalnız t0'dan sonraki ilk üç kapanmış 5dk mumdur: üçüncü kapanış ilk
  açılıştan ve ikinci kapanıştan yüksek, üçüncü düşük ikinci düşükten düşük
  değil. Teyit varsa dördüncü açılış giriş; yoksa `NO_ENTRY`. Eksik mum teyit
  reddi sayılmaz. NO_ENTRY fırsat getirisinde sıfırdır, işlem isabetine katılmaz.

## Fiyat yolu, çıkış, veri kapsamı

- Yalnız tam kapanmış, sıralı ve kesintisiz 5dk OHLC. Eksik/çelişen/geçersiz
  gerekli mum `UNKNOWN` olur; imleç o mumda bekler ve sonraki tur tekrar denenir.
  API hatası kayıp veya sıfır fiyat değildir. Önceden sonuçlanmış kolun sonucu
  sonraki veri eksiğiyle değişmez. Pencere kapsamı ayrıca raporlanır.
- Aynı mumda hedef ve stop belirsizse stop önce; stop altı açılışta kötü açılış
  fiyatı, sabit hedef üstü açılışta hedef fiyatı kullanılır.
- Takip stopu `max(eski stop, giriş, kapanmış mumlara kadar tepe × 0.97)`.
  Güncellenen stop **sonraki mumda** uygulanır. Etkinleşme mumunda önce eski
  stop kontrol edilir. Kısmi çıkışta yarısı hedefte kapanır, kalan yarısı taşınır.
- Parçalar yalnız matematiksel ağırlıktır; miktar, sermaye, dolar PnL, kaldıraç,
  gerçek işlem kaydı veya borsa emri üretilmez.
- Maliyet iki sabit senaryo: toplam 20 ve 40 baz puan. Kısmi kapanışlar
  ağırlıklandırılır. G2 funding **not_modeled**: funding dahil net alanlar
  boştur; yalnız funding hariç fiyat getirisi/maliyet senaryosu raporlanır.
  Eski yaklaşık-funding araştırmasının net sonucu bu seriyle birleştirilmez.
- Çıkış mumunun tüm high/low aralığı MAE/MFE'ye dahildir; gerçek mum içi sıra
  bilinmez. Tam pencere hareketi ayrıca tutulur, ulaşılabilir kâr diye sunulmaz.

## Çalışma ve kayıt

`EXECUTION_SHADOW_ENABLED=true` ile bot liderinin ayrı 5dk worker'ı çalışır.
Bir tur en fazla 20 olayın fiyat yolunu günceller; en uzun bekleyen önce gelir.
Ağ çağrıları tarama ve Telegram komut thread'inde yapılmaz. Hatalar worker
durumunda görünür; canlı tarama akışına yayılmaz.

Özel state ve `execution_shadow_bars_YYYY-MM.jsonl` günlük yedek kapsamındadır.
Mum günlüğü olay/plan hash'i ile fiyat kaynağını kaydeder; bu, API verisinin
borsa tarafından imzalandığı anlamına gelmez. Tekrarlar olay+zaman üzerinden
ayırt edilir. State atomik yazılır. Bozuk/sürümü uyumsuz state sıfırlanmaz;
gölge takip hata verir, mevcut veri korunur.

## Rapor ve değerlendirme kapısı

`python research/review_execution_shadow.py --format text` ağı kullanmadan
kayıtları okur. Her kol için toplam/sonuçlanan/bekleyen/UNKNOWN/NO_ENTRY,
giriş oranı, 20/40bp fırsat getirisi, girilenler için medyan ve kötü kuyruk,
aynı olaylarda karşılaştırmaya göre fark, ayrı olay günü, bekleme ve MAE/MFE
gösterilir. Eksikler paydadan sessizce silinmez; sayıları ayrıca görünür.
Rejim grupları ayrı verilir. G2 funding hariç etiketlenir.

En az 90 takvim günü ileri gözlem, kol başına 30 sonuçlanmış giriş ve 14 ayrı
giriş günü oluşmadan aday hakkında karar verilmez. Bunlar üstünlük veya güven
olasılığı garantisi değildir. Sonraki değerlendirmede eşleştirilmiş gün-blok
belirsizliği, yoğunlaşma, eksik kapsam ve birlikte denenmiş kollar göz önüne
alınmalıdır. Yazılım otomatik kazanan seçmez, yeni parametre taramaz, bildirim
güven puanını yükseltmez. Görülen sonuçtan sonra kural değiştirmek yeni sürüm
ve yeni ileri dönem gerektirir.
