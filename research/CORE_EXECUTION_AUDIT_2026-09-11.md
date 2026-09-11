# Yerel çekirdek yürütme denetimi — 2026-09-11

> Bu dosya ilk denetimin tarihsel kaydıdır. Kullanıcının sonraki “Luna dahil tüm
> işleri bitirelim” talimatıyla uygulanan düzeltmeler ve kalan doğrulama sınırları
> [kapanış raporunda](CORE_EXECUTION_COMPLETION_2026-09-11.md) kaydedildi.

**Karar:** Geçerli girdiler için incelenen canlı sinyal matematiği korunmuş.
Yeni fiyat-yolu ölçümünün temel hesapları kendi tanımıyla tutarlı. Ancak yeni
raporu otomatik üretip canlı panoda doğrulanmış başarı olarak sunmak için veri
ve sunum kapıları tamamlanmamış. Mevcut testlerin geçmesi bu kapıları kapatmıyor.

Denetim tabanı `17a346d`; kapsam, bu commit üzerindeki 8 değiştirilmiş ve
12 yeni yerel dosya. İnceleme çalışma kopyasında yapıldı. Mevcut 20 dosya
değiştirilmedi; denetim sırasındaki SHA-256 karşılaştırmasında fark yok.
Bu rapor eklendi; sentetik kontroller ve parity çıktısı git tarafından dışlanan
`tmp/` altında tutuldu. Commit, push, deploy, bot başlatma veya gerçek bildirim
yapılmadı. Canlı `.env`, sinyal logu, outbox ve state dosyaları okunmadı/yazılmadı.

## 1. Kullanıcının üç sorusuna yanıt

1. **Matematik korunuyor mu?** İncelenen geçerli girdiler ve çalıştırılan
   kontroller için evet. SMA başlangıçlı Wilder RSI, yatay seride RSI=100,
   log1p hacim ve örneklem varyansı, ilk eşit dip, eşiklerde `<=`/`>=`, kesin
   yeşil mum koşulu, S4'ün iki ucu dahil aralığı, funding yüzde dönüşümü ve
   kenar/cooldown sırası korunuyor. `hourly_outcome` içindeki LONG/SHORT basit
   getiri ifadesi aynı. Tarama sıklığı, evren seçimi ve bildirim izin eşikleri
   değişmemiş. Mesaj metni/metaveri davranışı ise değiştirilmiş; aşağıdaki
   bulgular nedeniyle bütün uygulama davranışına sınırsız eşlik onayı verilmiyor.
2. **Şimdi canlıya ne bağlanmamalı?** Otomatik paper raporu, yeni doğrulanmış
   başarı etiketi, eski/yeni oranları birleştirme, funding'i sıfır sayma,
   filtre/eşik terfisi ve gerçek emir yürütme. Teslim kapsamı, olay kimliği,
   veri manifesti ve sunum ayrımı önce çözülmeli. Bu denetim dağıtım onayı değildir.
3. **Güvenle tamamlanabilecek işler var mı?** Evet: mevcut oranları değiştirmeden
   dokümanları gerçekte sunulan alanlarla eşleştirmek, yeni yöntem raporu yok
   etiketini göstermek, metaveri gösterimini düzeltmek ve sentetik regresyon
   testleri eklemek. Bu turda mevcut kullanıcı dosyalarına müdahale edilmedi;
   somut kabul koşulları aşağıda verildi.

## 2. Doğrulama ve sınırları

| Kontrol | Sonuç | Ne gösterir / ne göstermez |
|---|---|---|
| `tests/run_isolated.py` | 24 paket, 0 başarısız | Geçici kopya, temizlenmiş ortam, socket bağlantıları engelli; canlı servis sınaması değil |
| Yeni motor testleri | 9 test geçti | Eski fonksiyonlarla sayısal ve durum eşliği, funding milisaniyesi, doji ve eşik sınırları |
| Yeni paper/özet/adaptör testleri | 7 + 4 + 4 test geçti | Temel bariyer, maliyet, eksik veri ve kohort davranışı |
| `tests/test_dashboard.js` | Geçti | Sözdizimi, fiyat biçimi ve bazı metin/alanların varlığı; tam DOM/etkileşim testi değil |
| `tests/check_dashboard_js.js` | Geçti | Pano JavaScript sözdizimi |
| Python `compile` kontrolü | 90 dosya geçti | `.pyc` yazmadan sözdizimi denetimi |
| `git diff --check` | Geçti | Mevcut diff'te boşluk hatası yok |
| Sabit TRAIN parity | BTC 1, ETH 2, 1INCH 2; toplam 5/5 eşleşme | S1/S3 olay kimliği/tarihi, üç sabit sembol; getiri veya OOS ölçümü değil |

Testlerde kullanılan hazır yorumlayıcı:
`C:/Users/serha/Downloads/trade1/.venv/Scripts/python.exe`.
Sistemin `C:/Python313/python.exe` ortamında gerekli proje paketleri yoktu;
paket kurulmadı. Hazır sanal ortamın yorumlayıcısı kullanıldı, asıl checkout'ın
botu çalıştırılmadı. Termux üzerinde import/çalıştırma ve GitHub CI çalışması
bu denetimde ayrıca yapılmadı.

Sabit parity tarihleri `2025-12-01` dahil / `2025-12-08` hariç; 72 saat durum
ısınması, saatte bir ideal tarama, sabit üyelik. Funding bu tarihsel kontrolde
yer almıyor. Hash: `4c6e416c9dc87f30050115e7f8976b854d5667f3462733604d8d36cecd691640`.
Veri kaynağı mevcut yerel `research/data/spot` cache'inin salt okunur kullanımı;
yeni veri indirilmedi. Sonuç: `tmp/audit_live_parity_2026-09-11.json`.

**TEST sınırı:** Yeni TEST getirisi/istatistiği hesaplanmadı ve parametre
seçilmedi. Bununla birlikte `research/audit_live_parity.py:49` parquet'in seçilen
kolonlarını bütünüyle okuyup sonra tarih süzgeci uyguluyor. Çıktıdaki
`historical_test_opened=false`, fiziksel dosya erişimi bakımından güçlü bir
garanti değil; analiz yapılmadığı anlamında okunmalı. Gelecekte bu alanın
tanımı açıklaştırılmalı veya TRAIN veri dilimi okuma aşamasında ayrılmalı.

## 3. Bulgular — önem ve dosya bazında

P1: yeni otomatik/canlı kanıt sunumundan önce çözülmesi gereken konu.
P2: yerel raporu bozabilen veya sunumu yanıltabilen kusur.
P3: test/doküman kapsamı ve açıklık eksiği. Bu sınıflar yeni entegrasyon
kararına ilişkindir; canlıda test edilmiş olay/arıza iddiası değildir.

### A. P1 — Canlı özetler yeni kohort ayrımını uygulamıyor

Konumlar: `signal_bot.py:2890`, `signal_bot.py:2987` çevresindeki
`price_path_summary`, `signal_bot.py:4088`, `signal_bot.py:4836`;
`README.md:460`, `dashboard.html:124`, `dashboard.html:128`.

Hedef dokunması ve MFE/MAE özetleri stratejiye göre toplanıyor. Motor hash'i,
ölçüm sürümü, teslim kanıtı ve diğer yeni kohort alanları bu gruplamaya dahil
değil. Zaman çıkışı kohort anahtarı da motor hash'i ve teslim kanıtını içermiyor.
Bu **korunmuş eski davranış**, yeni `evidence_summary.py` davranışıyla karıştırılmamalı.

Sentetik kanıt: bir eski hedef HIT ile bir yeni hedef MISS aynı S3/TP2
özetinde `resolved=2`, `hit_rate_pct=50.0` oluyor. Motor hash'i/teslim kanıtı
eksik kayıt ile bunlar dolu kayıt aynı diğer alanlarda aynı canlı kohort anahtarını
üretiyor. README'nin hash'i olmayan eski kayıtların güncel oranlara eklenmediği
yönündeki genel ifadesi mevcut canlı özetler için doğru değil.

Öneri: mevcut oranları değiştirmeden onları açıkça eski/toplu ölçüm diye
etiketlemek; yeni paper JSON'u ayrı, salt okunur bir görünüm olarak tasarlamak.
Kohort hesaplama politikasını değiştirmek Luna sunum işi sayılmamalı.
Doğrulama: eski/yeni, iki evren, iki hash, teslimi belirsiz kayıtlar içeren
aynı fixture üzerinde yeni raporun ayrı kohortlarını ve eski özetin açık etiketini sınamak.

### B. P1 — Log-only giriş, tekrar denemede doğrulanan teslimleri kaçırıyor

Konumlar: `research/evaluate_paper_signals.py:70`, `:147`;
`signal_bot.py:2341`, `:3094`, `:3203`; `notification_delivery.py:111`.

İlk gönderimde başarısız olan olay loga doğrulanmamış yazılıyor. Sonraki başarılı
tekrar teslim outbox'a işleniyor; `_retry_signal_deliveries` logdaki eski satırı
güncellemiyor. Mevcut hedef takipçisi `confirmed_records()` ile outbox'ı da okuyor;
yeni manuel paper CLI yalnız verilen signals logunu okuyor.

Sentetik kanıt: aynı olayın outbox kaydı `delivery_confirmed=true` iken log-only
paper sonucu `delivery_not_confirmed`. Bu, teslim olmadan işlem uydurma hatası
değil; gerçek teslimlerin eksik temsil edilmesi ve seçilim yanlılığı riski.

Öneri: ilk gerçek forward ölçümünden önce log + doğrulanmış outbox birleşimini,
ilk başarılı teslim zamanını ve eksik kaynak sayısını koruyan **ayrı, özel bir
yerel veri hazırlama adımı** tanımlamak. Ham outbox/abone alanları yayınlanmamalı.
Canlı retry/log davranışını bu sunum işi içinde değiştirmemek.
Doğrulama: ilk başarısız sonra başarılı, kısmi teslim, çoklu alıcı ve log yazımı
başarısız örneklerini denemek; tek olay ve ilk doğrulanmış zaman kalmalı.

### C. P2 — Aynı olaya farklı geçerli ID verilmesi N'yi şişiriyor

Konum: `research/evaluate_paper_signals.py:77`–`:106`.

32 haneli hex `event_id` kanonik kimlikle karşılaştırılmadan kabul ediliyor.
Tekilleştirme yalnız bu sağlanan ID içinde yapıldığı için aynı strateji/sembol/
bar/yön/ufuk kaydı farklı ID'lerle iki ölçüme dönüşüyor.
Sentetik kanıt: aynı satır, `a` × 32 ve `b` × 32 ID'leriyle `n_measured=2`,
`rejected_counts={}`. Bu, bozuk/birleştirilmiş girişe karşı doğrulama açığıdır;
normal canlı üreticinin her olayda yanlış ID ürettiği iddiası değildir.

Öneri: sinyal kimliği sözleşmesini değiştirmeden sağlanan ID ile kanonik
kimliği çapraz doğrulamak veya kanonik kimlikten ikinci tekillik denetimi
yapmak. Uyuşmazlıkları sayarak karantinaya almak. Funding milisaniyelerini
kayıt alanlarında korumak; mevcut saniye tabanlı ortak olay-ID algoritmasını
bu iş sırasında tek taraflı değiştirmemek.
Doğrulama: aynı olay/farklı ID, farklı olay/aynı ID, erken/geç teslim,
çatışan config ve ters satır sırası için aynı deterministik sonuç.

### D. P2 — Geçerli JSON içindeki yanlış tip tüm manuel raporu durdurabiliyor

Konum: `research/evaluate_paper_signals.py:55`, `:82`, `:109`.

`strategy=["S3"]` veya USD-M `performance_symbol=["BTCUSDT"]` satırı
`TypeError: unhashable type: 'list'` üretiyor. Bozuk JSON sayacı bu durumu
yakalamıyor; bunlar sözdizimi geçerli JSON nesneleri.

Öneri: kimlik ve sözlük anahtarlarında kullanılacak alanları kullanımdan önce
tip/biçim bakımından doğrulamak; satırı neden sayacıyla ayırmak. Bütün
hesaplama istisnalarını körlemesine yutmak yerine giriş sınırını sağlamlaştırmak.
Doğrulama: geçerli ve bozuk tipli satırların karışımı; geçerli olaylar kalmalı,
bozuklar sayılmalı, ham alanlar çıktı/hata mesajına taşınmamalı.

### E. P2 — İlgisiz mum bozukluğu tamamlanmış sonucu değiştirebiliyor

Konum: `paper_execution.py:99`–`:108`.

Zaman damgası denetimi tüm mumlarda, çatışma denetimi ise bütün kapalı ufukta
çıkış bulunmadan önce yapılıyor. İlk mumda hedefe çıkılmış olsa da sonraki
mumdaki çatışan iki satır sonucu `conflicting_candle` yapıyor. Ufuk dışındaki
gelecek bir mumun hizasız zaman damgası da `invalid_candle_timestamp` döndürüyor.

Sentetik kanıt: tek hedef mumu `measured`; aynı girdiye çıkış sonrasında
çatışan mumlar eklenince `unavailable`. Bu, TP/SL formülü hatası değil; olayın
ilgili veri aralığı ile bütün dosya doğrulamasının birbirine bağlanması.
Protokol eksik çıkış-sonrası mumları açıkça serbest bırakıyor; bozuk/çatışan
çıkış-sonrası mumlar için politika ayrıca netleştirilmeli.

Öneri: dosya kalitesi uyarıları ile olayın giriş–çıkış için gerekli veri
kalitesini ayırmak; onaylanan politika testlerle dondurulmadan bu çekirdeği
sunum görevi kapsamında değiştirmemek.
Doğrulama: çıkış öncesi eksik/çatışma sonucu engellemeli; çıkış sonrası
eksik/çatışma ve kesim sonrası veri için açıkça seçilmiş politika korunmalı.

### F. P2 — Yeni Telegram sinyali yanlışlıkla eski ölçüm etiketi alıyor

Konumlar: `signal_bot.py:2147`, `:2237`, `:3184`.

`notify`, yeni hedef profilini `record["price_target"]` altında oluşturuyor.
Ölçüm sürümü bu profilin içinde; `_measurement_display` yalnız üst düzey
`measurement_version` okuyor. Dolayısıyla yeni motor hash'i olan yeni sinyalde
dahi “eski kayıt · ölçüm sürümü bilinmiyor” yazıyor.

Sentetik kanıt: iç profil `signal-reference-touch-v1`, Telegram etiketi eski
kayıt, motor `live-compatible-v1`. Pano ise hedef state'ine bakabildiğinden
aynı kusurun bütün pano satırlarında oluştuğu ileri sürülmüyor.

Güvenli sunum işi: açık sürüm → mevcut hedef profili → bilinmiyor sırasıyla
etiket seçmek; eski kayda güncel sürüm yazmamak. Yeni eklenen config/evren/motor
metinlerini diğer Telegram alanları gibi HTML-escape etmek.
Doğrulama: yeni kayıt, eski kayıt, hedef takibi kapalı kayıt ve özel HTML
karakterli config; strateji koşulları ve sayısal sonuçlar aynı kalmalı.

### G. P2 — Eski USD-M net alanları ile doküman anlatımı uyuşmuyor

Konumlar: `signal_bot.py:4832`, `:4891`; `dashboard.html:128`;
`TABLET.md:159` çevresi.

Paper çekirdeği USD-M için doğru biçimde `net_return_pct=null` ve ayrı
`net_ex_funding_return_pct` veriyor. Korunmuş eski pano ise maliyet düşülmüş
sayısal `net_pnl_pct` göstermeye devam ediyor, yanında funding durumu var.
Sentetik eski S2 sonucu: brüt %2 → `net_pnl_pct=1.88`,
`funding_cost_status=not_modeled`. TABLET'teki “net sonuç yerine not_modeled”
ifadesi bu panonun gerçek davranışını anlatmıyor.

Güvenli sunum işi: mevcut USD-M sayısını funding hariç varsayımsal maliyetli
getiri olarak adlandırmak; paper tam net alanıyla karıştırmamak. Aktif pano
satırının girişi de geçici sinyal referansı olabilir (`entry_basis`);
bütün satırları gerçekleşmiş sonraki açılış sonucu diye tanımlamamak.
Doğrulama: aktif/olgun spot, aktif/olgun USD-M ve eksik cache örnekleri.
Bu denetimde eski getiriler veya fonksiyonlar değiştirilmedi.

### H. P3 — Sunum devri tamamlanmış değil; fixture'da karakter bozulması var

`TABLET.md` ölçüm sürümü filtresi var diyor; `dashboard.html:88`–`:100`,
`:129`–`:132` içinde piyasa/evren filtreleri var, ölçüm filtresi yok.
Paper JSON tüketimi ve rapor yokken “yeni yöntemle değerlendirilmedi” durumu
da bağlanmış değil. Motor hash'i yalnız tooltip'te; dokunmatik kullanımda
görünürlüğü ayrıca sınanmalı. `tests/test_dashboard.js:18`–`:21` yalnız ilgili
metinlerin HTML'de bulunmasını denetliyor.

`tests/fixtures/live_math_v0.py:197` içindeki kontrat notunda kaynak commit'in
`—` karakteri yerine `�` var. AST karşılaştırmasında RSI/hacim/divergence/
should_fire eşit; tam `scan_symbol` bu tek literal yüzünden farklı.
Sentetik `PEPEUSDT → 1000PEPEUSDT` taramasında yalnız `note` farklı,
sayısal alanlar ve state aynı. Mevcut tam tarama testi yalnız BTC kullandığı
için bunu yakalamıyor (`tests/test_strategy_engine.py:106`).

Güvenli test işi: fixture literalini kaynak commit'ten doğru UTF-8 ile almak;
eşlenmiş kontrat, ticker hata/proxy yolu, snapshot ve observe taramalarında
gerçek eski-yeni eşlik kontrolleri eklemek. Canlı kodu fixture'ın bozuk
karakterine uydurmamak. Pano filtrelerini gerçek DOM/veri fixture'ıyla
çalıştırmak; rapor yok durumunu da sınamak.

## 4. Dosya bazında sonraki işlem kararı

| Dosya | Öneri | Risk / doğrulama |
|---|---|---|
| `strategy_engine.py` | Matematiği koru | Geçerli girdide refaktör eşliği geçti; yeni alpha/parametre işi açma |
| `signal_bot.py` | Yalnız F/G'deki sunum düzeltmelerini ayrı küçük diff olarak hazırla | A/B'deki canlı kohort ve teslim politikalarını sunum işiyle değiştirme |
| `signal_outcomes.py` | Aynı basit getiri çağrısını koru | Artık `paper_execution.py` zorunlu import; ileride paket tamlığı sınanmalı |
| `paper_execution.py` | Bariyer/maliyet formüllerini koru; E politikasını önce kararlaştır | Erken çıkış, açık mum, gap, SHORT, belirsiz aynı mum testleri geçti |
| `research/replay_live_engine.py` | Çevrimdışı ve açık tarama/üyelik girdileriyle tut | Yeniden başlatma state'i, üyelik değişimi, API gecikmesi ve eksik funding gerçekçi biçimde modellenmiş değil |
| `research/audit_live_parity.py` | Sabit TRAIN kontrolünü koru; TEST alanının anlamını açıklaştır | Üç sembol ve saatlik model canlı 5dk döngüsünün tam kanıtı değil |
| `research/evaluate_paper_signals.py` | B/C/D çözülmeden otomatik entegrasyon yapma | Eksik teslim ve kimlik/tip kontrolü rapor N'sini etkileyebilir |
| `research/evidence_summary.py` | Yeni rapor için ayrı tut | Ana kohortlar ayrılıyor; bootstrap betimsel, OOS veya başarı olasılığı değil |
| `research/strategies.py` | Legacy algoritmayı koru | Yerel diff yalnız doğru ayrımı açıklayan docstring; eski sonuçlar yeniden kalibre edilmiş değil |
| `dashboard.html` | Mevcut metriklere doğru ad; paper yok durumu; sonra ayrı read-only görünüm | Eski özet veya net alanını paper sonucu gibi yeniden kullanma |
| `README.md`, `TABLET.md` | A/G/H ile tutarlı kullanıcı talimatı hazırla | Mevcut davranış ile planlanan davranışı ayır |
| `research/CORE_EXECUTION_PROTOCOL.md` | Devam eden karar kaydı olarak koru | Restore kopyasına ilişkin eski 229 satır iddiası bu denetimde yeniden incelenmedi |
| `tests/test_strategy_engine.py`, `tests/fixtures/live_math_v0.py` | H'deki dar regresyon kapsamı | Mevcut matematiğe müdahale gerektirmez |
| `tests/test_paper_execution.py`, `tests/test_paper_report.py` | B–E için sentetik negatif ve sınır testleri | Beklenen politikayı sabitle; sonucu güzel gösterecek satır seçme |
| `tests/test_evidence_summary.py` | Ayrı kohort ve bağımlı gün testlerini koru | USD-M'de yalnız funding-hariç ortalama var; dağılım sunulacaksa medyan/q10/q90 ihtiyacı ayrıca tanımlanmalı |
| `tests/test_dashboard.js` | Metin varlığına ek davranış testi | Filtre, yenileme, UNKNOWN, rapor yok ve mobil görünüm |
| `.github/workflows/tests.yml` | Yeni modül/test listesini koru | CI doğrudan suite çağırıyor; yerel izole runner'ın ağ engelini birebir uygulamıyor |

## 5. Luna'ya uygun kapsam ve yüksek muhakemede kalacak işler

**Luna'ya uygun:** doküman doğruluğu; ölçüm adı/piyasa/evren/config/hash/N/pending
görünürlüğü; F'deki profil etiketini okuma; G'deki funding-hariç metin; H'deki
fixture ve DOM testi. Hazır, denetlenmiş JSON varsa salt okunur sunum; yoksa
başarı oranı üretmeden “yeni yöntemle değerlendirilmedi”. Sunum işi eski
gruplama veya getiri hesaplarını değiştirmemeli. Küçük N ve UNKNOWN başarısız
işlem olarak sınıflandırılmamalı.

**Yüksek muhakemede kalacak:** doğrulanmış teslim kaynaklarının birleştirilmesi;
kanonik olay kimliği karantinası; 5m veri kaynağı/checksum/kapsam manifesti;
sembol–kontrat eşlemesi ve zamanında bilinen evren/delist geçmişi; E'deki
olay/veri kalitesi politikası; funding settlement/mark-price/ödeme aralığı
modeli; dondurulmuş TRAIN yöntemi ve dokunulmamış forward/OOS penceresi;
en uzun ufuk kadar purge, çoklu karşılaştırma, rejim/coin yoğunlaşması,
eşleştirilmiş zaman çıkışı karşılaştırması ve maliyet duyarlılığı.

Mevcut CLI piyasa/sembol etiketini denetliyor fakat veri kaynağının doğruluğunu
ve checksum manifestini kendi içinde doğrulamıyor. Dolayısıyla keyfi etiketli
JSONL dosyası “doğrulanmış piyasa verisi” sayılmamalı. Log-only raporun kendi
başına tam teslim arşivi olduğu da varsayılmamalı. Çakışan pozisyon/sermaye/
tasfiye modeli olmadan olay ortalaması portföy getirisi değildir.

Gelecekte ayrıca dağıtım istenirse, `strategy_engine.py` ve `paper_execution.py`
gibi yeni zorunlu importların tamamı pakette bulunmalı; temiz kopyada import
kontrolü yapılmalı. Şu an bu dosyalar untracked; yalnız eski takipli dosyaları
taşıyan bir paket başlangıçta hata verir. Bu denetimde stage/commit yapılmadı.

## 6. Tekrar üretim

Çalışma kopyası kökünden PowerShell:

```powershell
& 'C:/Users/serha/Downloads/trade1/.venv/Scripts/python.exe' -B tests/run_isolated.py
node tests/test_dashboard.js
node tests/check_dashboard_js.js
& 'C:/Users/serha/Downloads/trade1/.venv/Scripts/python.exe' -B research/audit_live_parity.py --data-dir C:/Users/serha/Downloads/trade1/research/data --output tmp/audit_live_parity_2026-09-11.json
& 'C:/Users/serha/Downloads/trade1/.venv/Scripts/python.exe' -B tmp/core_audit_probes.py
git diff --check
```

Son probe bu denetimde bırakılmış, git tarafından dışlanan yerel yardımcıdır;
temiz clone'da bulunmaz. Yalnız kaynak dosyalarını geçici dizine kopyalar,
sentetik log/outbox oluşturur, gerçek ağ bağlantılarını engeller. Yeni
strateji veya üretim testi olarak kullanılmaz. Kaynakları değiştirmez;
`tmp/audit_initial_hashes.json` karşılaştırma kaydını yeniler.

Tamamlanan çıktı bu denetim raporudur. Bulguları gizlemek için mevcut testler,
kullanıcı değişiklikleri, ölçüm matematiği veya canlı tarama değiştirilmedi.
