# G1 son dönem kayıpları: neden incelemesi

**Değerlendirme anı: 13 Ekim 2026 19:35:20 TRT / 16:35:20 UTC.**
Bu, sonuçlar görüldükten sonra yapılan açıklayıcı bir incelemedir; ön-kayıtlı
OOS doğrulaması veya gelecekteki başarı oranı değildir. Gerçek dolum ve hesap
kâr/zararı ölçülmemiştir. Canlı strateji, eşik, evren, bildirim, cooldown ve
emir davranışı değiştirilmedi. Testnet denemesi beklemede kalır.

## Kısa sonuç

Tek bir haberin bütün kayıpları açıkladığına dair kanıt yok. Somut olarak
**fiyat/hacim saati ile OI ve long/short saati arasında bir saat uyumsuzluk**
bulundu. Ayrıca günlük yükselenler listesi, son saatte yükselişin sürmesini
garanti etmiyor: yeni on sinyalin beşi kırmızı saatlik mumdan sonra geldi.
Yüksek oynaklık ile sabit %2 stop arasındaki uyumsuzluk da mevcut; ancak bu
oynaklık eski grupta da vardı, yeni bir artış olarak gösterilemez.

En önemlisi, önceki on sinyal de aynı uygulanabilir giriş/çıkış tanımıyla
ortalama pozitif değildi. Yüksek stopsuz hedef dokunma oranı, güçlü ve
uygulanabilir işlem avantajının daha önce doğrulandığını göstermiyor.

## Veri ve karşılaştırma yöntemi

- Kaynak: herkese açık GitHub Pages veri dalının `data.json` anlık görüntüsü;
  Binance USD-M resmi 1dk/1saat mumları, saatlik OI ve global hesap long/short.
  Tabletin özel arşivi veya kişisel hesap verisi bu incelemeye dahil değildir.
- Seçim: değerlendirme anına kadar teslimi doğrulanmış son **10 v3-fresh-ask
  G1** ve bunlardan hemen önceki **10 G1**. Başarıya göre olay seçilmedi.
- Yeni grupta **9 olgun, 1 henüz 4 saatini tamamlamamış** olay; eski grupta
  10 olgun olay var. Yeni grup 11–13 Ekim, eski grup 8–11 Ekim tarihlerini
  kapsar. Aynı gün/anda oluşan olaylar bağımsız deneyler sayılmaz.
- Giriş vekili: Telegram tesliminden sonraki ilk tam 1dk mum açılışı.
  Bu bir gerçek ask dolumu değildir. Teslimin içinde olduğu kısmi dakika ve
  son kısmi dakika dışarıda bırakılır. Azami süre teslim +4 saattir.
- Sabit tanısal plan: fiyat TP %3, SL %2. Aynı 1dk mumda iki bariyer de
  görülürse muhafazakâr stop-önce; stop altı gap daha kötü açılıştan ölçülür.
  Toplam ücret/kayma varsayımı **40 bp = %0,40**; funding **not_modeled**.
  Bu maliyet gerçek hesabın ücreti değildir ve botun canlı TP/SL ayarı değildir.
- Bekleme karşılaştırmaları aynı olaylar üzerinde ilk tam dakikadan 5 veya
  15 dakika sonraki açılışı kullanır; bekleme nedeniyle ufuk uzatılmaz.
- 20 olayın fiyat yollarında ve 160 karşılaştırma-sembolü penceresinde eksik
  mum yok. Eksik veri olsaydı sıfır/kayıp yerine unavailable tutulacaktı.
- İlk indirmede 240 piyasa API GET isteği, 232 benzersiz cache kaydı üretildi.
  Sonraki çevrimdışı tekrar **0 ağ isteğiyle aynı 20 satırı ve özetleri** verdi;
  bütün cache ve snapshot SHA-256 değerleri doğrulandı.

Sanitize edilmiş snapshot SHA-256:
`14fdf015d25a6c7362e34a5243fcb68622093640abbdb85ce48b8f1913b7a949`.
Ham, herkese açık kaynak yanıtının SHA-256 değeri snapshot metadata içinde
ayrıca korunmuştur. Kanıtlar `research/data/g1-diagnostic-2026-10-13/`
altındadır; canlı arşiv veya state üzerine yazılmaz.

## 1. Ölçüm tanımı değişince görünen tablo

| Giriş vekili | Önceki 10 olgun: TP / SL | Ortalama net* | Yeni 9 olgun: TP / SL | Ortalama net* |
|---|---:|---:|---:|---:|
| İlk tam dakika | 4 / 6 | −%0,40 | 1 / 8 | −%1,84 |
| 5 dakika bekleme | 6 / 4 | +%0,60 | 3 / 6 | −%0,73 |
| 15 dakika bekleme | 4 / 6 | −%0,40 | 4 / 5 | −%0,18 |

\* Fiyat getirisi eksi 40 bp; funding hariç, kaldıraçlı ROI veya gerçek hesap
PnL değildir. Yeni gruptaki SUSDT henüz 4 saatini tamamlamadığı için bütün
olgun-örneklem özetlerinden çıkarıldı; fiyat yolu stopa ulaştığını gösterse de
erken sonuçlanmış örnekleri seçerek bekleyen grubu çarpıtmıyoruz.

15 dakika bekleme bu yeni küçük grupta daha az zarar gösteriyor; eski grupta
aynı iyileşme yok. Bu nedenle "15 dakika beklemek artık en iyi giriş" sonucu
çıkarılamaz. Eski gruptaki LUMIA teslimi kapanıştan yaklaşık 31,5 dakika
sonraydı; diğer eski teslimler yaklaşık 10–20 saniye, yeni teslimler 11–17
saniye sonra. Bu da karşılaştırmanın kontrollü bir sürüm deneyi olmadığını
gösterir. Tek bir seriyle yapısal performans kırılması kanıtlanmış değildir.

## 2. Doğrulanan teknik açık: OI/LS bir saat geriden geliyor

`shadow_experiments.py` içindeki `evaluate_g1_snapshot()` fiyat/hacim için
kapanmış saatlik mumu kullanırken metriği mumun `close_time` değerine kadar
seçiyor. Mumun bitiş damgası `H − 1 ms`; saatlik OI/LS örneği ise tam `H`
damgasında. Dolayısıyla bu sınır örneği dışarıda kalıyor.

Saat H'de gelen bildirimde:

- Fiyat/hacim, H'de biten mumdan geliyor.
- "OI son 1 saat" gerçekte H−2 ile H−1 arasındaki değişim oluyor.
- Long/short da H−1 örneği oluyor.

İncelenen **20/20 bildirimin** yuvarlanmış OI ve long/short değerleri eski
cutoff ile birebir eşleşti; iki OI örneği gerçekten bir saat aralıklıydı.
Metrikler koşul mumunun bitişine göre 60 dakika geride. Bu açık yeni ask
sürümüne özgü değil, önceki olaylarda da mevcut.
[Binance resmi dokümantasyonu](https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/market-data)
bu metriklerin timestamp alanını dönem sonu olarak tanımlar.

| Sembol | Bildirimdeki OI değişimi | H sınırındaki tarihsel OI değişimi |
|---|---:|---:|
| SENTUSDT | +%11,281 | −%0,416 |
| BATUSDT | +%2,900 | −%0,985 |
| SUSDT | +%13,738 | −%0,777 |
| QUSDT | +%2,469 | +%1,318 |

SENT örneğinde sinyalin "OI güçlü artıyor" yorumu, fiyatın ölçüldüğü son
saati anlatmıyor. Bu, farklı zamanlardaki bilgilerin birleştirilmesi sorunu.

**Ancak hizalama tek başına başarıyı kurtarmıyor:** aynı ≥%2 OI ve LS<1
kuralları tarihsel H örneğiyle yeniden denetlendiğinde yeni on olaydan yalnız
DODOX, OGN, RSR, GTC ve W kalıyor; beşinin de ilk-dakika TP3/SL2 sonucu SL.
Tek kazanan Q da eleniyor. Eski grupta kalan yedi olayın ikisi TP, beşi SL.

Bu hesap canlıya alınabilir bir backtest değildir: H örneğinin o gün tam
hangi saniyede API'de yayımlandığı bilinmiyor. Tarihsel olarak bugün
erişilebilen değeri, teslim anında erişilebilir varsaymak veri sızıntısı
olabilir. Çözüm yeni, ayrı sürümlü gölge testte **metrik zamanını ve alınma
zamanını** birlikte kaydetmek; mevcut dondurulmuş kohortu geriye dönük
yeniden etiketlememektir.

## 3. Piyasa/haber etkisi: arka plan var, tek neden kanıtı yok

12–13 Ekim için genel satış ve long tasfiyeleri haberleri var.
[The Block'un 12 Ekim akşamı EDT tarihli haberi](https://www.theblock.co/news/markets/2026-10-12-bitcoin-slides-crypto-liquidations-surge-418374)
24 saatte BTC düşüşü ve büyük long tasfiyelerini raporluyor. Haber yayını
13 Ekim 04:57 TRT'ye karşılık geliyor. Analistlerin makro açıklamaları
nedensellik kanıtı değil; SENT gibi bazı kayıplar bu haberden önce oluştu.

Her coin için aynı giriş dakikasından coin bariyerine değdiği dakikanın
sonuna kadar BTC/ETH ve sabit BTC, ETH, SOL, BNB, XRP, ADA, LINK, DOGE sepeti
karşılaştırıldı. Sepet değeri sekiz getirinin medyanıdır; tüm altcoin piyasası
veya sektör eşleştirmesi değildir. Bariyer anı 1dk üst sınırdır, gerçek dolum
anında bir beta ölçümü değildir.

| Coin stopa ulaşırken | BTC değişimi | Sekizli sepet medyanı |
|---|---:|---:|
| SENTUSDT | +%0,007 | +%0,037 |
| WUSDT | +%0,112 | +%0,072 |
| DODOXUSDT | +%0,198 | +%0,204 |
| BATUSDT | −%0,405 | −%0,496 |

Yeni gruptaki sekiz olgun kayıplı olayın **dördünde BTC, dördünde sepet
pozitifti**. Kaybedenlerin stop anındaki sepet medyanı yaklaşık **−%0,014**.
Bu, bütün kayıpları genel piyasa çöküşüne bağlamayı desteklemiyor. BAT gibi
bazı olaylarda piyasa baskısı katkı sağlamış olabilir. Sonraki dört saatlik
genel düşüşü, önceki birkaç dakikada gerçekleşmiş coin kaybının nedeni diye
göstermemek gerekir.

Coin-özel bağlam olarak GTC ve RSR için 12 Ekim Upbit listeleme haberleri
bulundu. [Upbit'in resmi GTC sayfası](https://datalab.upbit.com/assets/GTC/summary)
yeni piyasa desteğini ve 12 Ekim fiyat geçmişini doğruluyor.
[GTC listeleme aktarımı](https://www.kucoin.com/news/flash/gitcoin-gtc-lists-on-upbit-krw-and-usdt-markets-open-october-12)
19:30 KST tahmini başlangıcı veriyor; bu, G1 tesliminden yaklaşık 90 dakika
önce. Kaynak kendi metninde tek resmi sosyal paylaşımına dayandığını ve o
andaki ek teyit eksikliğini belirtiyor. RSR için
[listeleme haberi](https://www.chaincatcher.com/en/article/2295600)
14:05 KST başlangıcı bildiriyor; G1 yaklaşık dokuz saat sonra geliyor.
Bu ikincil aktarım zamanları, arşivlenmiş asıl duyuru kanıtı değildir.

Dolayısıyla **haberle pompalanmış coin / haberin yaşı / ilk hareket sonrası
geri çekilme** araştırmaya değer bir etiket; "listeleme haberi bu iki stopun
kesin nedenidir" iddiası değildir. GTC'nin günlük getirisi bildirimde zaten
%52,2, RSR'ninki %53,462 idi.

Sonic için [resmi airdrop son tarih duyurusu](https://www.soniclabs.com/blog/sonic-airdrop-burn-and-final-claim-deadline)
15 Ekim'i işaret ediyor, fakat duyuru 2 Nisan'dan beri biliniyor. Bunu
13 Ekim'deki hareketin yeni haber nedeni diye sunmak doğru olmaz. Diğer
olaylar için doğrulanmış tek bir ortak taze olumsuz haber saptanmadı; bu,
böyle bir haberin hiç bulunmadığının kanıtı değildir.

## 4. Henüz kurala dönüştürülmemesi gereken aday değişkenler

**Hareketin yaşlanması / son saat ivmesi:** Yeni on olayın beşinde son
saatlik mum kırmızıydı: S, BAT, DODOX, GTC, SENT. Bu beşinin de sabit planı
SL'ye ulaştı; S'nin toplam ufku henüz bekliyor. Eski on olayda iki kırmızı
saatlik mum vardı, ikisi de SL. G1, günlük yükselen olmayı kontrol ediyor;
son saatte halen yukarı gitmeyi zorunlu kılmıyor. Yeşil mumlu yeni olayların
da dördü SL olduğu için yeşil-mum filtresi yeterli veya doğrulanmış değildir.

**Oynaklık / stop mesafesi:** Yeni dokuz olgun olayda son saat high-low
aralığının medyanı %8,01; ATR14 basit ortalama vekilinin medyanı %4,22.
%2 stopun ATR'ye oranı medyan 0,47. Eski grupta aynı değerler %8,07 ve %5,26;
oynaklığın son dönemde arttığına dair bu karşılaştırmada kanıt yok. ATR
burada 14 true range'in basit ortalaması; Wilder ATR veya canlı ayar değildir.
Dar stop, normal geri çekilmede kırılabilir; stopu genişletmek de kuyruk
kaybını büyütebilir. Geçmişte kazandıran stopu seçmek bir çözüm kanıtı olmaz.

**Hesap sayısı ≠ short büyüklüğü:** Kullanılan global long/short,
[Binance dokümantasyonuna göre hesap sayısı oranıdır](https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/market-data).
Short hesap çoğunluğu, short sermayesi çoğunluğu veya zorunlu short squeeze
anlamına gelmez. Yeni grupta short hesap çoğunluğu daha güçlü görünmesine
rağmen sonuç daha kötü. Kapanmış saatin taker-alış hacim payı da medyanda
yaklaşık %50,57; eski grupta %49,94. Belirgin sürekli alım baskısı kanıtı yok.
OI artışı tek başına yeni long/short yönünü ayırmaz.

**Bilinmeyenler:** Gerçek emir defteri derinliği, teslim anı sonrası ilk
saniyeler, spreadin ani genişlemesi, gerçek dolum/kayma, zaman damgalı
likidasyon haritası ve bütün coinlerde doğrulanmış haber/tokenu kilit açılım
arşivi yok. Bunların nedensel etkisi bu veriyle ölçülmedi. Kullanıcının SENT
işlemi gerçek giriş fiyatı/zamanı bilinmeden bu vekil sonuçla eşitlenemez.

## Bundan sonraki doğru adım

1. Önce ayrı bir G1 zaman-hizalama gölge sürümü tasarlanmalı: saat H ve H−1
   OI, H LS, API'de görülme/alınma zamanı, veri yaşı, gecikmiş/yayımlanmamış
   örnek için UNKNOWN. Mevcut sürüm aynı olayda kontrol olarak korunmalı.
2. Son saat ivmesi, yüksekten uzaklık, 5/15dk teyit, taker-akış ve haber
   yaşını araştırma alanı olarak kaydetmeli; son on sinyale bakarak eşik
   taranıp en iyi sonucu canlıya alınmamalı. Aday kurallar yeni veriden önce
   dondurulmalı, kaçırılan hedefler ve giriş yapılmayan olaylar da sayılmalı.
3. Aynı giriş/çıkış tanımıyla net getiri, TP-before-SL, MAE, kuyruk kaybı,
   maliyet/funding kapsaması ve gün bazında bağımsızlık birlikte ölçülmeli.
   ATR-temelli stop adayları mevcut execution-shadow protokolünden ayrı
   sürümle karşılaştırılmalı; burada bulunan sonuçlarla o protokol bozulmamalı.
4. Genel piyasa rejimi ve coin-özel haber etiketleri ayrı tutulmalı. Haber
   bulunamadı = nötr/olumlu haber değildir. İlk gerçek gözlem zamanı kaydedilmeli;
   sonradan öğrenilen haber canlı filtrede biliniyormuş gibi kullanılamaz.

Bu maddeler sonraki değişiklik için öneridir; bu tanı talebi kapsamında
canlı düzeltme veya yeni otomatik deney başlatılmadı. Mevcut veriden
"güvenilir yeni filtre" ya da otomatik işlem uygunluğu sonucu çıkmıyor.

## Teslim ve doğrulama

- `research/diagnose_g1_failures.py`: ayrı, test edilebilir tanı aracı; public
  GET/cache dışında bot importu, secret, Telegram veya emir erişimi yok.
- `tests/test_g1_failure_diagnostic.py`: 12 çevrimdışı test. Zaman dilimi,
  eksik/gelecek/tekrarlı mum, bariyer sırası/gap, pending ayrımı, timestamp
  sınırı ve özel emir endpoint'inin reddi kontrol edildi.
- Çevrimdışı cache tekrarında 20 olay ve özetler birebir aynı; 232 istek/
  yanıt checksum'u doğrulandı. Hiçbir canlı strateji dosyası bu inceleme için
  değiştirilmedi; mevcut kullanıcının/Gemini'nin değişiklikleri korundu.
- Projenin izole çevrimdışı test koşucusunda **50 test grubu geçti, 0 grup
  başarısız**. Yeni 12 tanı testi dahil; canlı dosyalar, özel anahtarlar ve ağ
  bağlantıları bu test koşusunda kullanılmadı. AST kontrolü ve `git diff
  --check` de geçti. Bunlar kod/veri denetimidir, kârlılık doğrulaması değildir.

Tekrar çalıştırma (Windows'ta proje `.venv` Python'u veya tablette `python`):

```bash
python -B -m research.diagnose_g1_failures
```

Bu komut yerel tanı snapshot/cache'i varsa ağ kullanmaz; yoksa açıkça
eksik-cache hatası verir. İlk public veri toplama için ayrı `--fetch` gerekir.
Ürettiği `report.json` yalnız tanı klasörüne yazılır, bot state'ine yazılmaz.
13 Ekim değerlendirme anı varsayılanı bilerek sabittir; yeni bir değerlendirme
ayrı klasör ve açık `--as-of` ile ayrı kohort olarak hazırlanmalıdır.
