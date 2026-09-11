# Canlı kural eşliği ve fiyat-yolu deney sözleşmesi — 2026-09-11 güncellemesi

Bu dosya yöntem kararlarını ve model devrini kaydeder. Yeni strateji onayı,
yatırım tavsiyesi, otomatik emir veya kârlılık kanıtı değildir. Canlı eşikler,
evren seçimi, S5/S6 ve S2 araştırma bildirimleri, cooldown ve 5dk tarama aynı kaldı.
Kod paketi kullanıcı onayıyla `52f273b` olarak `main`e gönderildi ve CI geçti.
Tablette uygulama/doğrulama [TELEGRAM_LATENCY.md](../TELEGRAM_LATENCY.md)
adımlarına bağlıdır; bu görev canlı tablete bağlanmadı.

## 1. Yüksek muhakeme gerektiren bölümde yapılanlar

- `strategy_engine.py`: canlı RSI, log-hacim, divergence, funding koşulu,
  confluence ve kenar/cooldown mantığı saf ortak fonksiyonlara çıkarıldı.
  `signal_bot.py` aynı fonksiyonları çağırır. Mevcut geçerli girdilerin sayısal
  davranışı değişmedi; veri erişimi ve bildirim politikası taşınmadı.
- `research/replay_live_engine.py`: aynı motorla kapalı saatlik mumlar ve açıkça
  verilen tarama zamanları üzerinden çevrimdışı olay üretimi. Funding settlement
  milisaniyeleri korunur; hh:00:00.009 bilgisi hh:00:00.000'da kullanılamaz.
- `paper_execution.py`: bildirim sonrası ayrı, varsayımsal TP/SL ölçümü.
- `research/evaluate_paper_signals.py`: doğrulanmış bildirim kayıtlarını ve
  piyasa/kontrat etiketli kapalı 5m mumlarını bu ölçüme bağlayan çevrimdışı CLI.
- `research/paper_inputs.py`: özel outbox kopyasından ilk doğrulanmış teslimi
  okur; 5m JSONL için kaynak beyanı, checksum ve seri bazında veri boşluklarını
  kaydeden manifest üretir/doğrular. Ağ veya canlı state yazımı yapmaz.
- `research/evidence_summary.py`: strateji, yön, piyasa, evren, config,
  motor parametre hash'i, kanıt kaynağı ve deney tanımına göre ayrı özetler.
  Gün blokları aynı zamandaki coinleri birlikte tutar; bağımlı olaylar bağımsız
  100 işlem gibi değerlendirilmez. Çıktı doğrulanmış güven olasılığı değildir.
- Yeni çekirdek sinyal kayıtlarına motor sürümü/hash'i, yeni hedef gözlemlerine
  ayrıca ölçüm tanımı ve cohort bilgisi eklenir. Eski kayıtlara bugünkü ayarlar
  yazılmaz; bilinmeyenler UNKNOWN kalır. Eski hedef fiyatları değiştirilmedi.

### Eski araştırmayı neden üzerine yazmadık?

`research/strategies.py` eski raporların tekrar üretimi için legacy olarak kaldı:

1. Eski RSI pandas EWM başlangıcı kullanır; canlı motor SMA başlangıçlı Wilder'dır.
2. Canlı motor her API penceresinde tekrar başlar: 250 limit -> 249 kapalı mum.
3. Canlı S3 eşikte `>=`, yeşil mumda kesin `close > open` kullanır. Legacy yol
   `>` kullanır ve doji'yi yukarı sayabilir.
4. Canlı S4 son 24 saatlik gecikme aralığında herhangi bir ham log-z anomalisine
   bakar (iki uç dahil). Eski değerlendirme bazı yerlerde cooldown uygulanmış
   S3 olaylarına bakar. S1 aile oranı ile sadece S1 oranı da aynı değildir.

Canlı uyumlu yeni replay, eski vektörize raporların başarısını otomatik devralmaz.
RSI'nın yatay seride 100 olması dahil canlı davranış özellikle korunmuştur.

## 2. Üç ayrı ölçüm; birbirinin yerine kullanılmaz

| Ölçüm | Giriş / bitiş | Yorum |
|---|---|---|
| Eski zaman çıkışı | Sinyal barından sonraki saat açılışı / ufuk sonu kapanışı | Tarihsel sinyal karşılaştırması; kullanıcının gerçekleşmiş emri değil |
| `signal-reference-touch-v1` | Bildirimdeki referans fiyat / mevcut hedef takibi | Bir fiyata dokunma gözlemi; stop öncesi kâr veya gerçek fill değil |
| `paper-barriers-v1` | Doğrulanmış teslimden sonra başlayan ilk TAM 5m mum açılışı / ilk TP-SL veya timeout | Ayrı varsayımsal fiyat-yolu deneyi; fill garantisi değil |

Yeni deneyde tam sınıra denk gelen teslimde de bir sonraki 5m açılışı alınır.
Giriş referansı stale saatlik fiyat veya `spot_scaled_proxy` değildir. USD-M için
doğru kontrat ve fiyat piyasası açıkça gerekir; 1000-token çarpanı tahmin edilmez.
Teslim kanıtı olmayan eski kayıtlar `delivery_not_confirmed` olur.

Ufuk girişten itibaren S1/S1+S4/S5/S6 24h, S2 72h, S3/G1 4h'dir.
S1/S3/S5/S6 spot, S2/G1 USD-M kullanır. Bu ufuklar yalnız deney tanımıdır.
Emir, qty, notional, dolar PnL, kaldıraç ROI veya trade-journal üretilmez.

- Aynı mumda TP ve SL: alt sınır stop önce, üst sınır hedef önce; belirsizlik
  işaretlenir. Bunlar mum içi sıralamanın sınırlarıdır, başarı güven aralığı değil.
- Mum stop seviyesinin ötesinde açılırsa açılışın kötü fiyatı kullanılır.
  Hedef ötesi açılışta konservatif olarak hedef fiyatı kullanılır.
- Mum içi çıkış için sahte saniye verilmez: 5m zaman aralığı raporlanır.
- Eksik gerekli mum `unavailable`; henüz kapanmamış gerekli mum `pending`.
  Çıkıştan sonraki eksiklik sonucu bozmaz. Eksik veriler kayıp/kazanç sayılmaz.
  2026-09-11 girdi politikası: çıkıştan sonraki çatışan/hizasız mum da bitmiş
  olayı bozmaz; gerekli aralıktaki çatışma/hizasızlık sonucu engeller. Zamanı
  belirlenemeyen bozuk satır güvenle aralığa yerleştirilemediğinden reddedilir.
  Manifest doğrulaması ise tüm dosyayı denetler ve bozuk/çatışan veriyi reddeder.
- Basit fiyat getirisi: LONG `(exit/entry-1)*100`, SHORT bunun negatifidir.
  Eski log getiriyi yüzde gibi sunma; dönüşüm ham `log(exit/entry)` üzerinden
  `expm1` ile yapılır. Önceden yön işareti verilmiş log değerleri körlemesine çevirme.

## 3. Önceden belirlenen karşılaştırmalar ve kanıt sınırları

Bu sürümün ana deney kolu TP=%2, SL=%1.5, toplam maliyet=12bp'dir. Bunlar
"en iyi" bulunmuş parametreler değil, kullanıcının hedefini sınayan sabit adaydır.
TP=%3 ikincil kol; 24bp maliyet ve fazladan 5dk gecikme olumsuz duyarlılıktır.
Sonuca bakıp en iyi satırı seçerek "doğrulanmış strateji" ilan edilmez.

Maliyet sabit giriş tutarı yüzdesi varsayımıdır; güncel borsa komisyonu veya
gerçek spread/slippage ölçümü değildir. Funding **henüz hesaplanmıyor**:
USD-M için `net_return_pct=null`, `funding_status=not_modeled`; sadece
`net_ex_funding_return_pct` gösterilir. Bunu tam net getiri diye adlandırma.
Gerçek funding modelinde settlement kapsamı, mark price ve değişen ödeme
aralıkları gerekir; oranları sıfır varsayma.
[Binance funding tanımı](https://www.binance.com/en/support/faq/detail/360033525031).

Her raporda N, ayrı olay günü, pending/eksik sayısı, TP-önce-SL alt/üst oranları,
net ortalama/medyan, q10/q90, maliyet ve bilgi kaynağı birlikte sunulur. N<30
küçük örneklem olarak işaretlenir; 30'a ulaşmak güvenilirlik kanıtı değildir.
7 günlük dairesel takvim blok bootstrap aralığı için en az 30 gözlem ve
28 takvim günü gerekir. Bu betimsel aralık çoklu-deneme düzeltmesi/OOS değildir.
Coinler arası korelasyonun tamamını veya bütün rejimleri çözmüş sayılmaz.

Canlıya terfi için sonraki yüksek-muhakeme aşaması:

1. Zamanında bilinen evren ve delist geçmişi, teslim zamanları, 5m fiyat ve
   funding kapsamı denetlensin. Eksik verili olaylar seçilim yanlılığı yaratabilir.
2. TRAIN üzerinde giriş/çıkış ve maliyet yöntemi dondurulsun. Eski görülmüş TEST,
   yeni yöntemin bakılmamış sınaması gibi kullanılmasın.
3. Gelecekte dokunulmamış, dondurulmuş forward/OOS penceresi kullanılsın;
   sınırda en uzun ufuk kadar purge uygulansın. Birlikte denenmiş hipotezler
   sayılıp çoklu karşılaştırma denetimi yapılsın; rejim/coin yoğunlaşması incelensin.
4. Sabit zaman çıkışıyla aynı olaylar üzerinde eşleştirilmiş karşılaştırma ve
   örneklem dışı maliyet duyarlılığı yapılsın. Gerçek portföyde çakışan pozisyonlar,
   sermaye ve tasfiye riski ayrıca modellenmeden olay ortalaması portföy getirisi sayılmasın.

Mevcut OI/likidasyon araştırmasının 90 günlük keşif + dondurulmuş OOS kapıları
değiştirilmedi. Bu yamada yeni alpha/filtre, funding modeli, gerçek emir yürütme
veya başarı oranı yükseldi iddiası yoktur.

## 4. Çalıştırma ve doğrulama

PC/CI sanal ortamı: `requirements-test.txt`. Termux için yeni ağır bağımlılık yok.
Testler canlı .env/state dosyaları olmadan ve ağ kapalı geçici kopyada çalışır:

```sh
python -B tests/run_isolated.py
node tests/test_dashboard.js
node tests/check_dashboard_js.js
python -B research/audit_live_parity.py --output research/data/parity_audit.json
```

Sabit kontrol: 2025-12-01 dahil / 2025-12-08 hariç, BTC/ETH/1INCH. Sonuç:
BTC 1, ETH 2, 1INCH 2 olay; legacy ve yeni replay'de 5/5 eşleşti. Bu küçük
kontrol tüm tarihte fark yok demek değildir. Eşik sınırı/doji/seed farkları
sentetik testlerde ayrıca kapsanır. TEST getirileri hesaplanmadı, parametre seçilmedi.
Parity aracı tüm parquet kolonlarını okuyup hesap öncesi TRAIN dilimini ayırır;
`historical_test_evaluated=false` analiz yapılmadığını belirtir, dosyanın TEST
satırlarına fiziksel erişim olmadığı iddiası değildir.
`tests/fixtures/live_math_v0.py` 17a346d commitindeki canlı kodun test referansıdır;
üretim kodu değildir. Tam `scan_symbol` + durum eşliği de karşılaştırılır.

Doğrulanmış 2026-09-10 PC restore kopyasının sadece kayıt kalitesi de incelendi:
229 JSON sinyal satırı, 0 bozuk JSON; hiçbirinde `delivery_confirmed=true` veya
yeni motor hash'i yok. Yeni adaptörde 156 olay `delivery_not_confirmed`, 67 satır
açık piyasa/yön bilgisi eksikliği, 6 satır desteklenmeyen strateji/sembol nedeniyle
ayrıldı. Bu incelemede fiyat indirilmedi ve kârlılık hesaplanmadı. Bu, geçmişte
bildirim gitmedi demek değil; yeni teslim-zamanı ölçümü için bu yedekte kanıt yok.
İlk gerçek yeni cohort, güncelleme tablete uygulanıp doğrulanmış teslim ve uygun
5m fiyat verisi toplandıktan sonra oluşabilecek.

Yeni manuel fiyat-yolu raporu, PC'de özel ve salt okunur girdi kopyalarıyla:

```sh
python -B research/paper_inputs.py --candles-jsonl /PRIVATE/closed_5m.jsonl \
  --source mixed_binance_klines --captured-at 2026-09-11T00:00:00Z \
  --output /PRIVATE/closed_5m.manifest.json

python -B research/evaluate_paper_signals.py --signals-log /PRIVATE/signals.log \
  --delivery-outbox /PRIVATE/notification_outbox.json \
  --candles-jsonl /PRIVATE/closed_5m.jsonl \
  --candles-manifest /PRIVATE/closed_5m.manifest.json --as-of 2026-09-11T00:00:00Z \
  --target-pct 2 --cost-bps 12 --latency-ms 0 \
  --output research/data/paper_signals.json
```

`--as-of` değerlendirme kesimidir; `--captured-at` dosyanın alınma kesimidir.
Örnek tarihleri gerçek girdi kesimlerine göre seç. Kaynak tek piyasaysa
`binance_spot_klines` / `binance_um_klines`, test verisiyse `synthetic` yaz.
Manifest oluşturulurken son mumun kapanmış olması gerekir. Manifest hash'i veya
seri envanteri uyuşmazsa rapor oluşturulmaz. Checksum kaynak beyanını bağımsız
doğrulamaz; yalnız beyan ve dosya içeriğinin bağını, aradaki boşlukları gösterir.
Mum JSONL satırı örneği (sentetik):

```json
{"market":"spot","symbol":"BTCUSDT","open_time":1735689900000,"open":100,"high":101,"low":99,"close":100.5}
```

Gerçek kaynakta onaylı Binance 5m mumları kullanılmalı; araştırma veri hazırlama
aracı/cache kaynağı ve checksum doğrulaması korunmalı. CLI kendi kendine ağdan
veri çekmez. Çıktı yalnız whitelist alanlar içerir; ham log, token, chat ID ve
env değerleri taşınmaz. Aynı olaydaki çoklu teslimlerden ilk doğrulanmış teslim
seçilir; çelişen kimlik/ayar kayıtları karantinaya alınır. Girdi logu değiştirilmez.
Sağlanan olay ID'si ortak kanonik ID'yle uyuşmuyorsa satır reddedilir; hatalı
ID'den yeni olay türetilmez. Kimlik/config çatışmalarındaki bütün satırlar,
girdi sırasından bağımsız aynı karantina sayacına girer. Bozuk alan tipleri
geçerli satırları düşürmez. Eski kayda bugünkü motor ayarı eklenmez.

Outbox seçeneği, ilk gönderimi başarısız fakat sonradan teslim edilmiş olayları
ve log yazımı başarısız olan doğrulanmış olayları kapsar. Kısmi teslimde ilk
başarılı alıcı zamanı kullanılır; kesimden sonraki teslimler bu kesime alınmaz.
Bu dosyanın bütün geçmişi içerdiği varsayılmaz. Outbox verilmezse raporda
`log_only_retry_coverage_unknown`, manifest verilmezse `unverified` görünür.
Dosya yolları, alıcı kimlikleri, token ve mesaj metinleri rapora aktarılmaz.

## 5. Luna Max'e devredilecek işler — yerel uygulama tamamlandı

2026-09-11'de kullanıcı tüm yerel işleri tamamlama talimatı verdi. Bu bölümdeki
uygulama işleri mevcut görevde tamamlandı; model değiştirildiği iddia edilmiyor.

- Telegram/daily/performans metinlerinin başlık, satır ve sayı düzeni.
- Panoda mevcut ölçümün adı, piyasa, evren, sürüm, N, pending ve UNKNOWN
  uyarılarını görünür yapmak; hedef dokunması ile net TP/SL başarısını ayırmak.
- Hazır JSON raporunun varsa salt-okunur sunumu. Rapor yoksa başarı oranı
  uydurmadan "yeni yöntemle değerlendirilmedi" yazmak. Yeni veri indirme,
  otomatik yeniden eğitim, funding hesabı veya canlıya filtre ekleme bu iş değil.
- README/TABLET kısa kullanıcı talimatları ve biçim düzeni; bu protokolü bağlantılamak.

Pano “Paper raporu seç” ile yalnız üretilmiş yerel JSON'u tarayıcı belleğinde
okur. Otomatik rapor hesaplamaz, dosyayı göndermez, saklamaz veya eski karnelere
katmaz. Rapor seçilmezse/bozuksa açık değerlendirilmedi durumu gösterilir.
Her paper kohortunda motor/config/hash, kanıt kaynağı, TP/SL/ufuk/maliyet/gecikme,
N/ölçülen/gün/pending/eksik ve net veya funding-hariç dağılım ayrı görünür.

Mevcut hedef arşivi ve zaman çıkışı gruplaması korunmuştur; bunlar motor hash'i
ve teslim kanıtını ayırmadığından eski/yeni kayıtlar birlikte olabilir. Bu
sınır Telegram/daily/performans/panoda yazılır. USD-M eski K/Z sayıları funding
hariç; aktif satır geçici referansa göre tahmindir. Motor hash'i artık açılan
satırda da okunabilir, yalnız fare tooltip'ine bağlı değildir.

Son ana dal düzeltmeleri (`b97b0a6`) bu pakete birleştirildi: ölçüm sürümü
bilinmeyen eski olaylar hedef/MFE oranlarına katılmaz, `_meta` içinde ayrıca
sayılır. QC kanonik olayları tekilleştirir ve retry teslimlerini özel outbox'tan
bellekte birleştirir. Önceki paragraftaki toplu gruplama, bu sürüm kapısından
geçen olaylar için geçerlidir.

Strateji eşikleri, canlı 5dk tarama, evren, cooldown, veri erişimi ve bildirim
izinleri değişmedi. Push/deploy yapılmadı. Tam otomatik canlı rapor, funding
modeli, yeni strateji filtresi veya OOS onayı açılmadı.

## 6. Gerçek veri gerektiren açık kapılar

Yerel yazılımın tamamlanması aşağıdaki kanıtların oluştuğu anlamına gelmez:

| Kapı | Gerekli somut girdi / kabul koşulu | Bu sürüm |
|---|---|---|
| Gerçek teslim | Aynı dönemin log/outbox kopyaları; kayıp/retention ve kısmi teslim sayımı | Hazırlama aracı/testi hazır; gerçek dönem değerlendirilmedi |
| 5m kapsamı | Kaynağı ayrıca doğrulanmış spot/USD-M kontrat verisi, checksum, eksik olay sayıları | Manifest aracı hazır; gerçek cohort verisi yüklenmedi |
| Zamanında bilinen evren | Dönem üyeliği, delist/kontrat eşlemesi, yeniden başlatma durumları | Bugünkü evrenle geçmiş üyelik uydurulmaz |
| Funding | Her settlement için doğrulanmış kontrat/oran/mark price, ödeme aralığı ve çıkış-zamanı belirsizliği politikası | `not_modeled`; tam net boş, sıfır funding varsayılmaz |
| Forward/OOS | Veri görülmeden zaman aralığı/deney kolları dondurma; en uzun ufuk (72h) kadar purge; tüm denenmiş hipotezleri kaydetme | Başlatıldı veya tamamlandı iddiası yok |
| Karşılaştırma | Aynı olaylarda sabit zaman çıkışı, maliyet/gecikme duyarlılığı; rejim/coin yoğunlaşması ve çoklu karşılaştırma denetimi | Gerçek sonuç olmadan üstünlük seçilmez |
| Portföy | Çakışan pozisyon, sermaye, marjin/tasfiye kısıtları | Olay ortalaması portföy getirisi diye sunulmaz |

Funding eklemek yeni ölçüm sürümü gerektirir; mevcut `paper-barriers-v1`
matematiği sessizce değiştirilmez. Yeni OOS tarihi, gerçekten dokunulmamış
veri ve gözlem başlangıcı doğrulanmadan geçmişe dönük seçilmez.

Denetim bulgularının kapanışı ve doğrulama sınırları:
[CORE_EXECUTION_COMPLETION_2026-09-11.md](CORE_EXECUTION_COMPLETION_2026-09-11.md).
