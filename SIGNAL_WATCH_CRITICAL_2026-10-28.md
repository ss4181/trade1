# Seçici kritik risk bildirimleri — 28 Ekim 2026

## Amaç ve sınır

İstek: küçük yön/güncelleme mesajlarını susturmak; yalnız belirgin ters yön
ve fiyat kırılması birlikte olduğunda uyarmak. Üretim sürümü
`critical-reversal-v1`, `SignalWatch(..., critical_only=True)` ile başlatılır.
Yeni env anahtarı veya bağımlılık gerekmez. `SIGNAL_WATCH_ENABLED=false`
mevcut davranışla bütün takip worker'ını kapatır.

Bu bir **bildirim filtresi**; doğrulanmış kapat/bekle modeli veya optimize TP/SL
değildir. Bot borsadaki gerçek pozisyonu, giriş/dolum fiyatını, kaldıraç,
cross teminatı, tasfiye seviyesini veya gerçekleşmiş stop emrini bilmiyor.
Dolayısıyla “zararda da olsa kesin kapat” gerekliliğini hesaplayamaz ve böyle
bir iddiada bulunmaz. Açık pozisyona otomatik işlem göndermez.

## Bildirim için birlikte gerekli olanlar

1. Hâlen stratejinin mevcut takip ufkunda olan, teslimi doğrulanmış bir sinyal.
2. Mevcut BTC+ETH kapalı mum algoritmasında **hem 1h hem 15m ters yön**:
   LONG için AYI, SHORT için BOĞA. Her iki coinde iki farklı kapanmış mum
   teyidi gerekir. TRANSITION, ayrışma, UNKNOWN veya bayat veri yetmez.
3. Sinyalin **kendi spot veya USD-M perp piyasasında** iki ardışık kapanmış
   15dk mum, referans saatlik low/high seviyesini belirgin biçimde ihlal eder:
   - LONG: iki kapanış da `low - max(0.5 × ATR14, low × 0.002)` altında.
   - SHORT: iki kapanış da `high + max(0.5 × ATR14, high × 0.002)` üstünde.
   - ATR14: iki teyit mumundan önceki 14 gerçek aralığın basit ortalaması.
     Teyit mumu kendi eşiğini büyütmez; hiçbir ileri veri kullanılmaz.
   - 0.5 ATR ve %0.2 tabanı kullanıcı isteğine yönelik muhafazakâr gürültü
     filtresidir. Getiri taramasıyla seçilmedi; başarı/zarar azaltma kanıtı yok.
4. İki fiyat mumu da teslimden sonra başlamış olmalı. G2'de ayrıca planlanan
   girişten sonra başlamalı. Eski G2 state'inin eksik giriş saati, özgün teslim
   kaydından tamamlanmadan uyarı üretilmez. Referans mum geçmişten uydurulmaz.

Tek fitil, tek kırılım mumu, iki kez aynı mumun okunması, sınırdaki küçük
kırılma veya tek zaman dilimi tersliği yeterli değildir. BTC/ETH günlük rejimi
bağlam olarak korunur ama bu yeni mesajın tek başına tetikleyicisi değildir.

## Artık otomatik gönderilmeyenler

- Genel günlük/saatlik/erken etiket değişimleri ve iyileşmeler.
- Tek başına referans mum kırılması.
- Tek başına G1 rank/hacim/OI/LS koşul kaybı. Kontrol/state tutulmaya devam eder.
- Takip ufkunun dolması. Süresi biten olayın takibi yine sonlanır.

Yeni giriş sinyalleri, TP hedef dokunma mesajları, günlük/performans/araştırma
raporları, tarama periyodu, strateji eşikleri, semboller, cooldown ve araştırma
deneyleri değiştirilmez. `/piyasa` ve `/status` isteğe bağlı çalışır.

## Tekrar, kuyruk ve mahremiyet

- Aynı sinyalde kritik gerekçe bir kez; yeniden başlatmada tekrar yok.
- Aynı kontrolün kritik olayları alıcı başına toplu mesaj. Uzun mesaj yalnız
  Telegram sınırı gerektirirse numaralı bölünür; olaylar kaybolmaz.
- Yalnız ilk sinyali teslim almış ve hâlen abone alıcılar. Başkasının sinyali
  veya kişisel pozisyonu gönderilmez.
- Önceki sürümün bekleyen rutin mesajları `suppressed_by_policy` ile susturulur;
  kayıtlar/delivered ACK silinmez, başarısız Telegram teslimi diye sayılmaz.
- Yeni kritik mesajın yalnız başarısız alıcılarına mevcut sınırlı retry/backoff
  uygulanır; TTL en geç sonraki 15dk bağlam sınırında veya takip ufkunda biter.
- State/outbox bozuksa silerek sıfırlanmaz; hata raporlanır. Sır içeren veriler
  mesajlara eklenmez. Testlerde ağ ve canlı Telegram kapalıdır.

## Kullanım ve yayımlama sınırı

Kodun yerelde hazırlanması, tablette çalışan süreci değiştirmez. **Ancak
GitHub main'e bu sürüm aktarıldıktan sonra** normal tek-süreç durdur/pull/
yeniden-başlat akışı uygulanmalı. Var olan `.env` veya özel state dosyalarını
silme/örnekle ezme. Güncellemeden sonra `/status` içinde
`Uyarı filtresi: critical-reversal-v1` görülmeli.

Teyit, fiyat kontrolü ve Telegram teslimi gecikebilir; ani düşüş daha erken
olabilir ve katı filtre bazı tehlikeli hareketleri hiç bildirmeyebilir.
**Mesaj gelmemesi pozisyon güvenli, beklemek doğru veya stop gereksiz demek
değildir.** Bu botun mevcut takip ufku dışındaki açık pozisyonlar izlenmez.

## Doğrulama

27 yeni kritik-politika testi ve mevcut regresyonlarla **56 izole test grubu,
0 hata**. Pano JavaScript kontrolleri de geçti. Kontrollerde canlı ağ,
Telegram ve emir gönderimi kapalıydı. `calc_rsi`, `calc_volume_zscore`,
`scan_symbol`, `_signal_event_id` ve hedef mumlarını getiren fonksiyonun
sözdizimi ağaçları mevcut HEAD ile aynı: giriş/ölçüm mantığı değiştirilmedi.
Bu yazılım doğrulamasıdır; yeni uyarı filtresinin kârlılık veya başarılı çıkış
olasılığı backtest edilmiş değildir. Test başarısı tek başına GitHub yayını
veya tablette çalışan sürecin güncellendiğinin kanıtı değildir.

Yalnız bu değişikliği içeren temiz yayın paketinde ayrıca **45 test grubu,
0 hata**: yerel tarihsel fixture gerektiren mevcut bir test atlandı. Yeni
kritik-politika testlerinin 27'si ve eski takip testlerinin 32'si geçti.
