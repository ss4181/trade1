# Trade1 kararlılık takip listesi — 10 Eylül 2026

Bu liste önceki onaylı çalışmanın devamını ve gerçekten tamamlanan adımları
ayırır. Yeni başarı oranı, otomatik al-sat veya strateji eşiği üretmez.

## Bu tur tamamlananlar

1. **Yedek eşitleme:** kaynak tarihini koruyan aynı boyutlu değişikliklerin
   Syncthing tarafından atlanabilmesine karşı değişen hedefin zamanı yenilenir.
   Kaynak değişmez; hash'i aynı dosya tekrar kopyalanmaz. Bozuk hedef kopyası
   onarılırken de bu kural uygulanır. Sembolik bağlantı hedefleri reddedilir.
2. **PC doğrulaması:** hash ve JSON aynı baytlar üzerinden denetlenir. Bozuk
   manifest biçimi, tekrar eden JSON anahtarları, NaN/Infinity, eksik dosyalar,
   kontrol sırasında dosya/manifest değişmesi başarı sayılmaz. CLI hata
   çıktıları içerik veya sır sızdırmadan başarısız kodla döner.
3. **Gerçek dosya kurtarma provası:** PC'deki 9 Eylül snapshot'ı yeni, özel ve
   Git'e alınmayan klasöre kopyalandı. 17 dosya / 408.858.101 bayt doğrulandı.
   Mevcut yedek değişmedi; bot başlatılmadı. Detaylar [PC_BACKUP.md](PC_BACKUP.md).
4. **Telegram kuyruk yarışı:** devam eden gönderim, yeniden deneme zamanı
   geçmiş olsa bile aynı süreçte ikinci thread tarafından tekrarlanmaz.
   Başarılı alıcıya tekrar yok; son başarısız deneme hemen terminal duruma
   geçer. Bozuk/çelişkili kuyruk kayıtları teslim kanıtı kabul edilmez, silinmez.
   Ağda belirsiz zaman aşımı veya gönderim sonrası süreç çökmesi halinde
   Telegram'ın tam-bir-kez teslim garantisi yoktur. Ayrı bot kopyaları için
   tek-instance/token sahipliği kuralı hâlâ gereklidir. Eski kuyruk geçmişi
   silinmedi; keyfi pruning teslim kanıtını/cooldown sonrası tekilleştirmeyi
   kaybettirebileceğinden bu tur otomatik geçmiş temizliği eklenmedi.
5. **Testler:** 21 yeni hata senaryosu; mevcut 19 Python test dosyasının
   tamamı izole ve ağsız çalıştırılır. Pano JavaScript kontrolü ayrıca çalışır.
   GitHub CI yeni test dosyasını da çalıştırır.
6. **Kurulum belgeleri:** gerçek Syncthing Folder ID ve eski tanımı açmama
   uyarısı düzeltildi; güncelleme sırasında hem Python hem uvicorn kopyasının
   durdurulması belirtildi.

## Önceden tamamlanan ve korunanlar

- Olay/alıcı bazlı kalıcı Telegram teslim kuyruğu; teslim kanıtı olmayan eski
  sinyalleri gönderildi saymama.
- Zaman damgalı giriş/çıkış ve eksik mum kontrolü; v3 performans önbelleği.
- Tablet tek bildirim sahibi; bulut sessiz kontrol, watchdog ayrı.
- OI ve likidasyon araştırma takvimlerinin ayrılması; OOS penceresinin eğitim
  satırlarından ayrılması.
- Panoda fiyat kaynağı/yaşı, teslim durumu ve 400 satırlık kapsamın açıklanması.
- Bellekten QC CSV yayını, değişmeyen içerik kontrolü ve güvenli kapalı varsayılan.
- Günlük tablet snapshot'ı, PC SHA-256 kontrolü ve Syncthing 365 günlük sürümleme.

## Gerçek arşivden hazırlık kontrolü (canlı performans/backtest değildir)

Kaynak: geri yüklenen özel snapshot. Son piyasa kaydı 9 Eylül 2026 16:03 UTC.
Değerlendirme 10 Eylül Türkiye saatinde çevrimdışı yapıldı; ağ isteği, yeni
eşik seçimi veya sonuç penceresine tekrar bakarak aday seçimi yapılmadı.

| Ölçü | Sonuç |
|---|---|
| Piyasa satırı / sembol | 108.689 / 135 |
| Tam alanlı satır / süre | 64.792 / 33,9 gün |
| Saat kapsaması | %88,0 |
| OI / funding / long-short doluluğu | %98,9 / %100,0 / %99,9 |
| Likidasyon olayı / olay günü | 316.253 / 10 |
| G1 / DL1 / S2 türev gölge olayları | 37 / 3 / 3 |
| S2 OI-short tam kayıt | 0 |
| Bozuk arşiv satırı | 0 |

**Karar:** `DISCOVERY_COLLECTING`. Süre ve olay-günü kapıları henüz sağlanmıyor.
OI/funding/LS için mevcut protokolün ilk kontrolü **4 Kasım 2026**, birleşik
G1+likidasyon için **29 Kasım 2026**. Tarih gelmesi tek başına yeterlilik
değildir; veri kalitesi ayrıca geçmelidir. Sonraki dondurulmuş OOS tamamlanmadan
bu adaylara güvenilirlik yüzdesi verilmeyecek. S5/S6 dahil mevcut bildirim
ayarları bu çalışma tarafından değiştirilmedi.

## Kullanıcı/cihaz adımı bekleyenler

- **Tablet:** yeni commit'i çekip tek bot sürecini yeniden başlatmak gerekir;
  yerel kod değişikliği çalışan tableti kendiliğinden güncellemez. Talimatlar
  [TABLET.md](TABLET.md). `.env`/arşivlere dokunmayın.
- **QC yayını:** isteğe bağlı `PUBLISH_QC_ENABLED=true` yalnız tabletin `.env`
  dosyasında açılır. Bu tur kullanıcı ayarı veya public yayın açılmadı.
- **S2 top-position:** snapshot'ta yeterli tam kayıt yok. Yapılandırılan
  `BINANCE_MARKET_DATA_API_KEY` yalnız cihazda tutulmalı; sohbete/Git'e
  yazılmamalı. Anahtar/yeni veri erişimi bu tur sağlanmadı.
- **Tam cihaz kurtarma:** dosya provası geçti; yeni cihazda bağımlılık/anahtar
  kurulumu ve gerçek servis başlatması yapılmadı. İki aktif Telegram kopyası
  yaratmamak için mevcut bot durdurulmadan böyle bir prova yapılmamalı.
- **Günlük PC uyarısı:** mevcut Windows görevi yerel sonuç dosyası üretir;
  PC'den Telegram'a yeni bir gönderici veya tablete teslim onayı eklenmedi.
- **Araştırma:** arşivleme ve ön-kayıtlı takvim sürer. Yeni strateji/eşik,
  başarı etiketi ve canlı emir ancak ayrı doğrulama ve açık onayla ele alınır.
