# Çekirdek yürütme işleri — yerel uygulama kapanışı

**Sonraki güncelleme:** Kullanıcının mum kapanışından yaklaşık 3 dakika geç
gelen Telegram bildirimi talebiyle kapanış payı 90 → 10 sn yapıldı; ana
gönderimler gözlem taramasından önce alındı; bağımsız retry ve süre ölçümü
eklendi. Ana daldaki `b97b0a6` QC/retry ve legacy ölçüm kapısı da birleştirildi.
Güncel doğrulama: 25 Python paketi (yeni 10 gecikme testi dahil), iki Node
kontrolü. Aşağıdaki önceki turdaki “aynı ayarlar / toplu eski kayıtlar”
ifadeleri bu sonraki operasyon ve legacy kapısı düzeltmesinden öncesini
anlatır. Güncel kapsam ve adım adım tablet işlemleri:
[TELEGRAM_LATENCY.md](../TELEGRAM_LATENCY.md).

Kapsam: 2026-09-11 denetiminden sonra kullanıcının “Luna dahil tüm işleri
bitirelim” talimatı. Luna'ya ayrılan sunum işleri ve A–H bulgularının yerel
yazılım düzeltmeleri uygulandı. Canlı strateji eşikleri, tarama/evren/cooldown,
bildirim izinleri ve basit getiri/TP/SL/maliyet formülleri korunuyor.
Push, deploy, gerçek tarama, bildirim veya emir yapılmadı.

Bu, yeni stratejinin kârlı/forward doğrulanmış olduğu anlamına gelmez. Gerçek
teslim/veri kapsamı ve gelecekteki OOS kanıtı aşağıda açık bırakılmıştır.

## Tamamlanan işler

| Denetim | Değişiklik | Doğrulama |
|---|---|---|
| A — eski/yeni özetlerin karışması | Eski gruplama korunup toplu arşiv olarak etiketlendi; paper raporu ayrı tarayıcı görünümünde | Paper görünümü eski veri dizisini değiştirmiyor; Node davranış testi |
| B — retry teslimleri eksik | `--delivery-outbox` özel kopyayı salt okunur okur; ilk başarılı alıcı zamanıyla loga katılır | İlk başarısız/sonra kısmi başarı, logda olmayan olay, kesimden sonraki teslim; giriş byte'ları aynı |
| C — aynı olayın çift sayılması | Sağlanan ID kanonik ID ile doğrulanır; kimlik/config çatışmaları tüm satırlarla karantinaya alınır | Farklı ID'li aynı olay sayılmıyor; ters sıra aynı sonuç/sayaçları üretiyor |
| D — bozuk tip raporu durduruyor | Strateji, kontrat ve provenance alanları kullanımdan önce doğrulanır | Liste/dict türleri ayrılıyor; geçerli kayıt kalıyor; sır saklama testi |
| E — çıkış sonrası bozuk mum | Yalnız gerekli giriş–çıkış mumları olayı etkiler; dosya bütünü ayrıca manifestte kontrol edilir | Erken TP sonrası çatışma sonucu değiştirmiyor; TP öncesi çatışma engelliyor |
| F — yeni kayıt eski diye gösteriliyor | Ölçüm adı üst alan → hedef profili → bilinmiyor sırasıyla okunur; yeni Telegram metadata HTML-escape edilir | Yeni/eski/üst sürüm ve HTML karakteri örnekleri |
| G — funding ve geçici giriş etiketi | Eski USD-M sayıları funding hariç, aktif satırlar geçici referans diye gösterilir | Pano metin/alan testleri; eski sayısal hesap korunuyor |
| H — sunum/test boşlukları | Ölçüm filtresi, yenilenen seçenekler, açılan satırda motor hash'i, yok/bozuk rapor durumları; oracle UTF-8 kontrat notu düzeltildi | Filtre/reset/yenileme, JSON şeması/escaping/asenkron temizleme; kontrat/proxy/snapshot/observe eşliği |

Ek olarak `research/paper_inputs.py` kapalı 5m mum dosyasını kaynak beyanı,
SHA-256 ve seri bazında başlangıç/son/eksik/tekrar sayılarıyla bağlayan manifest
üretir. Uyuşmayan manifestle rapor yazılmaz. Bu kayıt kaynak beyanını bağımsız
doğrulamaz. Dosya yolları, alıcı ID'leri ve ham mesajlar çıktıya taşınmaz.

Yeni kohortlar motor sürümünü de ayırır; USD-M için funding-hariç ortalama,
medyan, q10/q90 ve betimsel bootstrap alanları hazırdır. Tam net alanı boş kalır.
Teslim kaynağı `confirmed_delivery` diye etiketlenir; sadece teslim edilmiş
olması onu dokunulmamış forward/OOS kanıtı yapmaz.

CI Python paketlerini yereldeki aynı izole runner ile çalıştıracak şekilde
düzenlendi. Windows çıktı kodlaması bir test başarısızlığını saklamayacak
biçimde düzeltildi. README, TABLET ve yöntem protokolü güncellendi.

## Dosya haritası

- `signal_bot.py`, `dashboard.html`: sunum, metadata ve ayrı yerel JSON görünümü.
- `research/evaluate_paper_signals.py`, `research/paper_inputs.py`: kimlik,
  outbox, girdi tipi, checksum/kapsam ve kaynak özeti.
- `paper_execution.py`: ilgili mum aralığında girdi hata politikası;
  bariyer/getiri denklemleri aynı.
- `research/evidence_summary.py`: motor sürümü, deney ayarları ve funding-hariç
  dağılım alanları; farklı kohortları birleştirmez.
- `research/audit_live_parity.py`: TEST analiz edilmediği ile fiziksel dosya
  erişiminin ayrımı; `historical_test_evaluated` / `input_read_scope` alanları.
- `tests/test_strategy_engine.py`, `tests/fixtures/live_math_v0.py`: yeni
  metadata ve eşlenmiş kontrat/proxy/snapshot/observe eşliği.
- `tests/test_paper_execution.py`, `tests/test_paper_report.py`,
  `tests/test_evidence_summary.py`, `tests/test_dashboard.js`: regresyonlar.
- `tests/run_isolated.py`, `.github/workflows/tests.yml`: test izolasyonu/çıktı.
- `README.md`, `TABLET.md`, `research/CORE_EXECUTION_PROTOCOL.md`: doğru
  ölçüm adları, manuel kullanım ve açık kanıt kapıları.

`strategy_engine.py` ve `signal_outcomes.py` bu düzeltme turunda değiştirilmedi;
önceki kullanıcının ortak matematik refaktörü korunuyor. Legacy strateji
algoritması da değiştirilmedi. Yeni zorunlu modüller henüz untracked olduğu
için gelecekte yapılacak bir paketleme bütün dosyaları içermeli.

## Doğrulama

- İzole Python runner: 24 paket, 0 başarısız; motor paketinde 11, paper
  çekirdeğinde 8, rapor/girdi paketinde 8 ve kanıt özetinde 4 test.
- 91 Python dosyası sözdizimi kontrolünden, diff boşluk kontrolünden geçti.
  `signal_bot.py` üst düzey mevcut ayar atamaları `17a346d` ile AST düzeyinde
  aynı. Ortak motor, saatlik getiri ve legacy strateji dosyalarının denetim
  başlangıcındaki SHA-256 değerleri korundu.
- Sabit TRAIN parity tekrarlandı: BTC 1, ETH 2, 1INCH 2; toplam 5/5 eşleşme,
  yeni/legacy fazladan olay yok. `tmp/parity_after_completion.json` yalnız
  olay eşliğini kaydeder; getiri ve TEST değerlendirmesi yapılmadı.
- Node: pano sözdizimi ve gerçek JavaScript fonksiyonları/handler'ları üzerinde
  filtre, yenileme, funding, HTML kaçışları ve asenkron dosya seçimi testleri.
  Node testi küçük bir DOM sözleşmesi kullanır; görsel tarayıcı testi değildir.
- Gerçek tarayıcıda yalnız sentetik verili yerel pano açılışı doğrulandı:
  ayrı rapor-yok durumu, ölçüm filtresi ve funding-hariç metinler DOM'da görüldü.
- Tarayıcıda sentetik JSON dosyasını seçme adımı **otomatik onay incelemesinin
  kullanım sınırı hatası nedeniyle reddedildi**. Bu adım ve mobil görsel kontrol
  tamamlandı sayılmıyor; başka tarayıcı/alt seviye yolla kısıtlama aşılmadı.
- Gerçek `.env`, sinyal logu, outbox ve bot state'i kullanılmadı. Outbox ve
  log testleri geçici dizinde sentetik dosyalarla çalıştı.

## Uygulama dışındaki açık işler

| İş | Neden açık / gereken kanıt |
|---|---|
| İlk gerçek yeni cohort | Aynı döneme ait doğrulanmış log/outbox ve doğru kontratın kapalı 5m verisi gerekli; bu turda gerçek veri verilmedi |
| Tarihsel üyelik/delist/state | Zamanında bilinen üyelik ve yeniden başlatma kayıtları gerekli; bugünkü liste geçmişe atanamaz |
| Funding nakit akışı | Settlement, mark price, ödeme aralığı ve belirsiz çıkış zamanının kapsamı olmadan tam net model kurulmadı; mevcut matematiğe eklenmedi |
| Forward/OOS ve purge | Görülmemiş dönem önce dondurulmalı; gelecekteki sonuçlar bugün üretilemez. En uzun ufuk 72h sınır arındırması protokolde |
| Eşleştirilmiş zaman çıkışı / maliyet / rejim / çoklu test | Gerçek ve yöntemce dondurulmuş olay kümesi olmadan üstünlük iddiası hesaplanmadı |
| Portföy/sermaye/tasfiye | Bu proje akışı olay ölçüyor; emir/sermaye modeli eklenmedi |
| Tarayıcı dosya seçimi ve mobil QA | Otomatik onay hizmetindeki kullanım sınırı kalkınca yapılmalı; çevrimdışı handler testleri geçti |
| Tablet/CI/push/deploy | Bu turda yapılmadı; dağıtım için ayrı kullanıcı talimatı gerekli |

Bu satırlar tamamlanmış araştırma gibi işaretlenmedi. Yerel yazılım/test/sunum
işlerinin tamamlanması ile canlıya terfi ve yeni bilimsel kanıt farklı sonuçlardır.
Çalıştırma komutları ve girdi sözleşmesi
[CORE_EXECUTION_PROTOCOL.md](CORE_EXECUTION_PROTOCOL.md) bölüm 4–6'dadır.
