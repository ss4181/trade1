# Hyperliquid araştırma protokolü — v1

Bu kurallar ilk replay sonuçları görülmeden belirlendi. Tarama ve replay aynı
`engine.py` dosyasını kullanır. Rapor, motor dosyasının SHA-256 özetini taşır.
Parametre araması yapılmaz; iki ufuk ve OI karşılaştırmasının tamamı raporlanır.

## Evren ve veri

- Hyperliquid'in ana perpetual piyasaları ve USDC kotasyonlu spot piyasaları.
  HIP-3 piyasaları bu sürümde yoktur.
- Varsayılan günlük hacim alt sınırı perpetual 1 milyon, spot 250 bin USD.
  `HL_MARKET_LIMIT=0` varsayılanı eşik üzerindeki tümünü seçer. Pozitif sayı
  her grubu ayrı ayrı en likit N piyasa ile sınırlar.
- Araştırma için önce en likit 10+10 piyasa üzerinde bağlantı/kapsam pilotu yapılır.
  Bu seçim **bugünün evrenidir**. Geçmişte elenen coinleri içermediğinden sonuçlar
  hayatta kalma ve seçim yanlılığı taşır. Başarı kanıtı sayılmaz.
  Pilot sonrasında kurallar değiştirilmeden hacim eşiğini geçen tüm evrene
  genişletilir; pilot raporu da saklanır.
- Yalnız kapanmış mumlar; zaman boşluğu ve yetersiz geçmişte sinyal üretilmez.
  Hyperliquid API'nin son 5.000 mum sınırı aşılmış gibi gösterilmez.
- BTC 200 günlük kesintisiz geçmiş yoksa rejim UNKNOWN olur ve aday çıkmaz.
- Canlı OI/funding bağlamı Hyperliquid katalog yanıtlarıyla SQLite'a arşivlenir.
  Coinalyze geçmişi ayrı kaynaktır: eski manifest, dosya kimliği ve SHA-256
  doğrulanır. Binance OI, Hyperliquid OI diye kullanılmaz. API anahtarı gerekmez.
- OI değeri kendi mum kapanışından bir tam mum sonra erişilebilir varsayılır.
  Gerçek geçmiş yayın zamanı bilinmez. Sembol adı birebir eşleşmezse kullanılmaz.
  Eksik/eski OI sıfırla doldurulmaz. Canlı strateji eski OI'ye bağlı değildir.
  Aynı ticker adı aynı token kimliğini garanti etmez; eşleşmeler kontrat bazında
  doğrulanmadığından OI alt kümesi keşif amaçlıdır, avantaj kanıtı değildir.

## Önceden belirlenen iki hipotez

Her iki hipotezde BTC günlük kapanış > SMA50 > SMA200 koşulu aranır.

| Koşul | HL-S, 24–48 saat | HL-D, spot 14–28 gün |
|---|---|---|
| Mum | 1 saat | 1 gün |
| Kırılım | Önceki 72 saatin en yükseği | Önceki 30 günün en yükseği |
| Hacim | Önceki 72 mum medyanının ≥1,5 katı | Önceki 30 mum medyanının ≥1,8 katı |
| BTC'ye göre getiri farkı | Son 24 saatte ≥1 yüzde puan | Son 7 günde ≥3 yüzde puan |
| Trend | Kapanış > SMA50 > SMA200 | Kapanış > SMA30 |
| Aşırı yükseliş elemesi | SMA50 üzerine ≤%8 | Son 7 günlük getiri ≤%50 |
| Stop mesafesi | 2 × ATR14; girişin %0,5–12'si | 2,5 × ATR14; girişin %2–25'i |
| Hedef | Stop mesafesinin 2 katı | Stop mesafesinin 2 katı |
| Aynı coinde tekrar aralığı | 48 saat | 28 gün |

Hacim yaklaşık USD tutarı `mum hacmi × kapanış` ile hesaplanır; gerçek
işlem bazlı VWAP tutarı değildir. Canlı aday ayrıca spread ≤30 bp ve orta fiyatın
%0,5 çevresinde her iki tarafta ≥10.000 USD görünür emir şartını geçmelidir.
Geçmiş emir defteri olmadığından replay bu son kapıyı doğrulayamaz.

## Limit emir senaryosu

- Giriş referansı sinyal kapanışının %0,2 altıdır; emir gönderilmez.
- Testte sinyalden sonra **bir tam mum beklenir**, sonra emir bir mum boyunca
  bekletilmiş varsayılır. Saatlikte 1 saat, günlükte 1 gün bekleme vardır.
  Bu sonuçlar bildirim gelir gelmez açılan işlemle aynı değildir.
- Fiyatın limite yalnız değmesi yetmez: %0,05 altına geçmesi gerekir.
  Varsayılan emir anında mum açılışı limitin altında/eşit ise marketable ALO
  reddi senaryosu sayılır ve maker dolumu yazılmaz.
  Gerçek ALO kabulü, kuyruk ve kısmi dolum bilinmez. Bu dolum kanıtı değildir.
- Giriş mumunda TP sayılmaz; SL sayılır. Aynı mumda TP ve SL varsa SL önce gelir.
  Stop altında açılan mumda kötü açılış fiyatı kullanılır.
- Standart taban maker/taker ücretleri: perpetual %0,015/%0,045;
  spot %0,040/%0,070. Ayrıca toplam %0,10 kayma kesintisi uygulanır.
  Hesaba/ürüne özel gerçek ücret farklı olabilir.
- Perpetual tarihsel funding bu sürümde net kâra dahil değildir. Rapor alanı
  `net_ex_funding_pct` bunu açıkça belirtir; tam net kâr alanı boş kalır.
- Kaldıraç, likidasyon, pozisyon büyüklüğü, sermaye ve eşzamanlı pozisyonlar
  modellenmez. İşlem senaryosu ortalaması portföy getirisi değildir.

## Değerlendirme

Her strateji için tüm coinlerin ortak takviminde ilk 2/3 ve son 1/3 ayrılır.
Ayrımı geçen gelişim işlemleri değerlendirmeden çıkarılır. Son üçte birde
pozitif sonuç oranı, ortalama/medyan sonuç, kötü/iyi uç, coin sayısı ve
dolmayan/ölçülemeyen kayıtlar birlikte gösterilir. OI değişimi ≥%1 alt kümesi
ayrıca gösterilir; sonuç iyi diye canlı kurala otomatik eklenmez.

Durum daima `NOT_VALIDATED`: gerçek zamanlı izleme, gerçekçi funding ve
dolum doğrulaması olmadan canlı para için üstünlük ilan edilmez. Tarihsel
rapora bakarak kural değiştirilirse yeni hipotez/sürüm sayılır; aynı son üçte
bir artık bağımsız doğrulama değildir.

## Uzun vadeli beklenti

HL-D bir **güçlenen spot coin izleme listesi** üretir. Tüm blokzincirlerde yeni
çıkan coinleri, sosyal ilgiyi, ekip/arz açılımlarını veya manipülasyonu taramaz.
Hyperliquid'de listelenmeyen geleceğin SHIB/DOGE benzeri varlığı bulunamaz.
Fiyat/hacim gücü yüksek getiri garantisi değildir; küçük coinlerde tüm sermaye
kaybı dahil riskler vardır. Daha likit evren çok erken ve sığ coinleri eler.

## Kaynaklar

- [Hyperliquid info/candle API](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint)
- [Perpetual bağlamı ve funding](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint/perpetuals)
- [Spot API](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint/spot)
- [Ücretler](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/fees)
- [İstek sınırları](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/rate-limits-and-user-limits)
