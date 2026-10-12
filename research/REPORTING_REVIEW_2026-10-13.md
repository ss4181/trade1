# Öncelik 7–8: rapor teslimi ve pano tutarlılığı — 13 Ekim 2026

## Tamamlanma sınırı

Kod ve yerel doğrulama tamamlandı. Kullanıcı onayıyla yalnız rapor/pano
değişiklikleri seçici yayın paketine ayrıldı; GitHub aktarımının kesin commit
ve CI sonucu teslim mesajından kontrol edilmelidir. **Deploy yapılmadı**;
tablet veya Telegram hesabı uzaktan yönetilmedi, gerçek Telegram mesajı
gönderilmedi. Tabletin yeni sürümü çalıştırması, TEST raporunu telefonda
görmeniz ve ilk zamanlanmış verili raporun teslimi hâlâ doğrulanmalıdır.
Çevrimdışı E2E testinde gerçek biçimleyici ve Telegram gönderme kodu kullanıldı;
yalnız HTTP sınırı sentetik API yanıtıyla değiştirildi.

Başlangıçtaki kullanıcı/Gemini değişiklikleri korundu. Bu tur strateji koşulu,
eşik, evren, cooldown, güven kapısı, tarama aralığı veya emir eklenmedi.

## Yapılanlar

| İş | Bulunan açık / uygulama | Doğrulama |
|---|---|---|
| Haftalık rapor | Başarısız teslim haftayı bellekte tamamlanmış sayıyordu. Artık yalnız API kabulünden sonra kalıcı başarı; hata sonrası 1 saatlik tekrar. | Gerçek sentetik JSONL → HTML → API stub → kalıcı ACK; başarısız ACK ve yeniden başlatma testleri |
| Tarama izolasyonu | Büyük arşiv ana döngüde okunuyordu; ayrı haftalık worker ve çakışma kilidi eklendi. | Gerçek thread'de bloke edilen okuyucu, tarama çağrısını bekletmiyor |
| Boş/bozuk veri | Boş arşiv normal sıfırlı rapora dönüşmüyor; aylık boş rapor da reddediliyor. Bozuk scheduler state korunup hata olarak gösteriliyor. | Boş arşiv, bozuk JSON, thread başlatma ve state kilidi testleri |
| Aylık rapor | Kaynak etiketi, TRT üretim zamanı ve son okunan arşiv özeti eklendi; hata sonrası 24 saatlik tekrar korundu. | Aylık gerçek gönderici/API stub ve sayaç değiştirmeyen manuel TEST |
| Süreç ayrımı | Render/GitHub Actions'ta iki otomatik rapor da varsayılan kapalı. Eski çalışan veya açıkça etkinleştirilmiş kopyalar kendiliğinden kapanmaz. | Güvenli varsayılan kodu; kaynak tanıma testi |
| Pano | Kaynak, arşiv varlığı, worker, son API kabulü, aylık/tekrar tarihi, son rapor satır sayısı görünür. | Node DOM testleri ve headless Chrome masaüstü/375px mobil kontrolü |
| G1 ölçümü | Taze best ask, spread ve kotasyon yaşı; saatlik next-bar-open K/Z'den ayrı açıklanır. Yeni 1m ve eski 5m rejim toplamlarında da ayrı kalır. | JS kohort ayrımı ve Python ölçüm-version fallback testleri |
| Windows state yazımı | Tam testte WinError 5 ile atomik dosya değiştirme engellendi. Paylaşım kilitlerine sınırlı tekrar eklendi; kalıcı hatalar gizlenmez. | Yardımcı testleri; outbox/watch/shadow dahil iki tam tur hatasız |

API kabulü, mesajın cihazda görüldüğünü veya okunduğunu kanıtlamaz. Başarılı API
gönderiminden hemen sonra state yazımı kalıcı biçimde başarısız olursa tam
“exactly once” garanti edilemez. Kilitler süreç içidir; iki ayrı bot kopyası
farklı state/arşivle çalışıyorsa kaynak sorunu ayrıca giderilmelidir.

## Değişen dosyalar (yalnız bu turun kapsamı)

- `research_report_delivery.py`, `atomic_state.py`: güvenli state/özet ve
  Windows atomik replace desteği; standart kütüphane, yeni pip bağımlılığı yok.
- `signal_bot.py`, `research_monitor.py`: rapor worker'ları, kaynak/teslim
  durumu, güvenli araştırma hata mesajı, yeni CLI komutları.
- `notification_delivery.py`, `signal_watch.py`, `execution_shadow_store.py`:
  yalnız Windows state replace desteği. İlk iki dosyadaki önceki değişiklikler
  bu turdan ayrıdır ve korunmuştur.
- `dashboard.html`: rapor paneli, ask/ölçüm açıklaması, kohort toplamı ayrımı.
- `README.md`, `TABLET.md`, `.env.example`: davranış ve kullanım bilgileri.
- `.github/workflows/tests.yml`: yeni modüllerin sözdizimi kontrolü.
- `tests/test_atomic_state.py`, `tests/test_research_weekly_delivery.py`,
  `tests/test_forward_oi_periodic_report.py`, `tests/test_dashboard_reporting.py`,
  `tests/test_dashboard.js`, `tests/test_dashboard_browser.js`,
  `tests/dashboard_fixture.js`: sentetik, secretsiz doğrulamalar.

## Test sonuçları

- İlk tam tur: 47 pakette 2 hata (Windows replace erişim hatası ve watch
  teslim beklentisi). Bunlar göz ardı edilmedi. Watch hatasının ilk turdaki
  doğrudan sebebi ayrıca kanıtlanmış değildir; daha sonraki geçiş, her geçmiş
  watch hatasının aynı kökten geldiğini göstermez.
- State düzeltmesinden sonra **iki tam tur: 48 paket / 0 hata**.
- GitHub'a hazırlanmış **seçici paket**, ilgisiz çalışma dosyaları olmadan
  ayrıca test edildi: **40 paket / 0 hata**, bir test kendi koşuluyla atlandı.
  Pano sözdizimi/DOM ve Chrome masaüstü/mobil testleri bu temiz pakette de geçti.
- Haftalık ve aylık rapor paketlerinde ayrı ayrı **10 test**, atomik state'te
  **3 test**. Socket bağlantıları engelli temiz kopyalarda çalıştırıldı.
- `node tests/check_dashboard_js.js` ve `node tests/test_dashboard.js`: geçti.
- `node tests/test_dashboard_browser.js`: başta eksik Playwright browser
  runtime'ı nedeniyle başlayamadı; kurulu Chrome seçilerek üç kez geçti.
  Mobil yatay taşma, filtre koruması, eski/bozuk HTTP yanıtları ve TRT saatleri
  test edildi. Test fixture'ı sentetiktir, canlı veri değildir.
- AST karşılaştırması: `calc_rsi`, `calc_volume_zscore`, `scan_symbol` HEAD ile
  aynı; `strategy_engine.py`, `g1_entry.py`, `shadow_experiments.py` değişmemiş.
  Çalışma ağacındaki önceden var olan G2 değişiklikleri bu iddianın dışındadır.

## PC kopyasında rapor üretimi

13 Ekim yerel incelemesi: **177.219 piyasa satırı / 135 sembol**; temel
alanları tam **131.837** satır. Son piyasa kaydı **11 Ekim 21:00 UTC**;
incelemede **24,8 saat** eski. OI/funding/LS dolulukları sırasıyla
**%98,9 / %100 / %99,4**. Likidasyon **1.659.052 olay / 43 olay günü**.
Hazırlık aşaması `DISCOVERY_COLLECTING`; Telegram HTML uzunluğu 1.367 karakter.

Bu sayılar özel PC yedeğinin okunabildiğini gösterir, tabletin canlı sayacını
veya yedek manifest bütünlüğünü kanıtlamaz. Önceki G1 incelemesinde bildirilen
manifest tazelik/hash açıkları ayrıca tekrar doğrulanmalıdır. Yeni getiri,
strateji güven oranı veya OOS kabul sonucu üretilmedi.

## Kullanıcı adımları / kalan işler

1. Güncellemeden önce teslim mesajındaki seçici GitHub `main` commit'ini ve
   CI sonucunu kontrol edin. Önceden var olan G2/araştırma değişiklikleri bu
   rapor/pano yayın paketine katılmadı; çalışma ağacında korunur.
2. Aktarımdan sonra tablet güncelleme/durdur/yeniden başlat talimatı
   `TABLET.md` içindeki **Haftalık / 30 günlük rapor ve pano teslim kontrolü**
   bölümündedir. `.stop-signal-bot` kaldırma ve `nohup` adımı unutulmamalı.
3. `python signal_bot.py --research-report-status`: beklenen kaynak/tablet,
   `archive_files_present=true`. Hatalıysa ARCHIVE_DIR yerelde düzeltilip bot
   yeniden başlatılır; `.env` paylaşılmaz.
4. `python signal_bot.py --test-research-report weekly`: telefonda TEST,
   doğru kaynak, sıfırdan büyük arşiv ve güncel son kayıt doğrulanır.
5. İsteğe bağlı `--test-research-report monthly`: tüm birikimli arşiv üzerinde
   yeniden 5dk analizi; veri indirmesi ve uzun süre gerekebilir. Takvim değişmez.
6. Aynı tokenı kullanan eski bulut/PC botu kapatılmalı veya iki otomatik raporu
   devre dışı bırakılmalı. Yalnız tablet rapor lideri olarak çalışmalı.
7. Yeni Pages yayını ve ilk zamanlanmış haftalık/aylık rapor ayrı doğrulanmalı.
8. PC yedek bütünlüğü ve G1/S2/likidasyon ileri araştırma kapıları takip edilmeli;
   bu rapor düzeltmesi onları tamamlamış veya stratejileri doğrulamış sayılmaz.
