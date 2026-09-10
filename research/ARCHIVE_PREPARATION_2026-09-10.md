# Araştırma verisi hazırlığı — 10 Eylül 2026

**Sonuç: olay testlerinin eksik girdileri tamamlandı; canlı strateji doğrulaması
tamamlanmadı.** Yeni başarı oranı hesaplanmadı, emir/bildirim gönderilmedi.

## Doğrulanan gerçek veri

Kaynak, PC'deki 9 Eylül 19:37 Türkiye saati yedeğinin özel, sabit geri yükleme
kopyasıdır. Son piyasa kaydı 9 Eylül 16:03 UTC'dir; bu sayılar tabletin anlık
durumu değildir. Yedek 17 dosya / 408.858.101 bayt olarak doğrulanmıştır.

**Son cihaz kontrolü:** 10 Eylül sabahı eşitlenen PC klasöründe altı hash
uyuşmazlığı görüldü; araştırmada kullanılan ayrı sabit kopya değildir.
Yeni snapshot alıp PC'de yeniden doğrulamak gerekiyor.
[PC bütünlük notu](../PC_BACKUP.md#10-eylül-sabahı-güncel-ile-bütünlük-kontrolü-farklı-sonuç-verdi)

| Kontrol | Sonuç |
|---|---:|
| Piyasa satırı / geçmişte görülen sembol | 108.689 / 135 |
| Araştırma dönemi satırı | 64.792 |
| Beş temel alanı gerçekten tam satır | 64.077 |
| Araştırma dönemi | 33,9 gün |
| En az bir kayıt bulunan UTC saat dilimi | 716 |
| İlk/son araştırma saati arasında hiç kayıt bulunmayan saat | 99 |
| Likidasyon olayı / olay günü | 316.253 / 10 |
| G1 / S2 türev gölge olayı | 37 / 3 |
| Eksik top-position alanı tamamlanan S2 olayı | 3 / 3 |
| Gerekli 5m mumları eksiksiz olay penceresi | 40 / 40 |
| Bozuk piyasa satırı | 0 |

“Tam alanlı” eski raporda yanlış kullanılıyordu: `research_rows`, ilk temel
alanlı kayıttan sonraki **tüm dönem satırlarını** sayar. Telegram artık dönem
sayısını ve `complete_research_rows` sayısını ayrı gösterir. Temel alanlar OI,
perp fiyatı, genel hesap long/short oranı, taker oranı ve funding snapshot'ıdır;
“tam” ifadesi bütün olası türev alanlarının mevcut olduğu anlamına gelmez.
Araştırma döneminde OI 715, perp fiyatı 691, genel LS 51, taker oranı 51 satırda
eksiktir. Eksikler örtüşür; bu sayılar toplanarak olay sayısı bulunmaz.

Saat denetimi UTC takvimindeki saat kutularını sayar: 815 kutunun 99'u boştur.
Mevcut readiness hesabı iki kesin zaman arasındaki süreyi aşağı yuvarladığı
için 814 payda / %88,0 gösterir. Bu tur ön-kayıtlı kalite kapısının hesabı
değiştirilmedi. Sembol başına 8.811 gözlenmeyen saat ayrıca listelenir; dinamik
evrenin giriş/çıkış takvimi olmadan bunların hepsi bağlantı kesintisi sayılamaz.

## Ne indirildi ve neden?

- 48 günlük USD-M 5m mum ZIP'i ve 4 günlük USD-M metrics ZIP'i: her birinin
  resmî `.CHECKSUM` dosyasıyla SHA-256 doğrulandı.
- 9 Eylül'e ait üç mum dosyası indirme anında henüz yayımlanmamıştı. Yalnız
  bu üç sembol/gün için resmî `fapi/v1/klines` kullanıldı. Ham JSON, alınma
  zamanı ve yerel SHA-256 saklandı. Bu yerel hash, borsanın yayımladığı checksum
  olarak etiketlenmez. Kapanmamış mumlar kullanılmadı.
- Toplam 55 sembol/gün girdisi; tekrar çevrimdışı çalıştırmada 52 ZIP ve 3
  REST kaydı önbellekten doğrulandı. Yeni ağ isteği olmadan 40 pencere de tamdır.

Daily ZIP'ler ertesi gün yayımlanır; resmî depo ayrıca checksum ve sonradan
arşiv düzeltmeleri hakkında bilgi verir. Kaynak ve tarihleri bu yüzden
saklıyoruz. [Binance public-data](https://github.com/binance/binance-public-data)

Top-position API büyük yatırımcıların **pozisyon** oranıdır, genel kullanıcı
**hesap** oranıyla aynı şey değildir. Güncel uç nokta `X-MBX-APIKEY` ister ve
son 30 günle sınırlıdır. Bu çalışmada günlük metrics arşivi kullanıldı;
araştırma indirmesi için anahtar okunmadı.
[Resmî USD-M piyasa verisi belgeleri](https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/market-data)

## S2'de bulunan eksik alan

`sum_toptrader_long_short_ratio`, yalnız olay zamanından **kesinlikle önceki**
ve en fazla 15 dakika eski satırdan alındı. CSV'ler her zaman zaman sırasına
göre gelmediğinden açıkça sıralandı. Bozuk/çelişkili tekrarlar reddedilir.

| Olay zamanı (UTC) | Sembol | Büyük yatırımcı pozisyon L/S |
|---|---|---:|
| 4 Eylül 08:00 | TRXUSDT | 0,863762 |
| 4 Eylül 16:00 | SANDUSDT | 1,194239 |
| 5 Eylül 00:00 | INJUSDT | 2,388893 |

Bu üç sayı **başarı olasılığı değildir**. Funding geçmişi veya alım zamanları
uydurulmadı. SAND olayındaki 9 milisaniyelik zaman farkı aynen korundu;
istatistiğin borsada hangi anda gerçekten erişilebilir olduğunu tarihsel CSV
kanıtlamaz. Hepsi `retrospective_backfill_not_forward` etiketlidir. Canlı
arşivdeki eksik kayıtlar, sıfır “tam S2 gözlemi” sayısı ve ileri-dönem takvimi
geriye dönük değiştirilmedi.

## Hâlâ eksik olanlar

1. **Kesintisiz yeni gözlem:** 99 boş saati veri tablosuyla doldurmak, botun o
   saatte gerçekten çalıştığını veya hangi bildirimi göndereceğini kanıtlamaz.
   Bu saatler özel raporda listelenir; ileri-dönem arşivine eklenmez.
2. **Daha uzun likidasyon geçmişi:** 10 olay günü, mevcut G1 ön-kaydının geçmiş
   ve bağımsız gün şartları için yeterli değildir. Kaçırılmış websocket
   mesajları bu kaynaklardan yeniden oluşturulamaz.
3. **Gerçek heatmap:** gerçekleşmiş `forceOrder` kayıtları, gelecekteki
   likidasyon seviyeleri değildir. Resmî akış sembol başına 1000 ms içindeki
   **en son** olayı iletir; bütün tasfiyeleri kapsamaz.
   [Binance liquidation stream](https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/ws-streams/market)
4. **İleriye dönük top-position kaydı:** tablette salt-okuma/veri erişimi için
   `BINANCE_MARKET_DATA_API_KEY` yapılandırılmalı. Anahtar hiç paylaşılmamalı.
5. **Ayrı doğrulama dönemi:** mevcut OI/LS ilk inceleme tarihi 4 Kasım 2026;
   G1+likidasyon için 29 Kasım 2026. Bunlar otomatik kabul tarihleri değil,
   kalite ve örneklem koşullarına bağlı inceleme kapılarıdır. Sonrasında
   kurallar dondurulmuş 90 günlük ayrı dönem gerekir.

Önemli: [S2-DERIV-v2 tarihsel raporundaki](S2_DERIVATIVES_V2_REPORT.md) iki aday
TRAIN kabul kapısını geçmedi. Yeni alan bulmak bu sonucu tersine çevirmez.
Ayrılmış tarihsel TEST açılmadı; aynı eğitimde yeni eşik arayarak sonuç seçilmedi.

Ön-kayıt açıklama düzeltmesi: `PREREG_G1_LIQUIDATION_PROXY.md` girişindeki
“en büyük” kelimesi “en son” olarak anlaşılmalı. Dondurulmuş ön-kayıt dosyasının
hash'ini değiştirmemek için düzeltme burada kaydedildi; eşikler değişmedi.

## Yeniden üretme — PC'de, canlı botu açmadan

Araç yalnız `market_archive_*.jsonl` ve `shadow_events_*.jsonl` okur; botu veya
`.env` dosyasını import etmez. Kaynak hash'leri çalışma başı/sonu karşılaştırılır.
Ham veri ve rapor `research/data/` altında Git dışında tutulur. Kaynakla çıktı
dizini çakışırsa çalışmaz. Eşitleme süren dizin yerine doğrulanmış sabit bir
geri yükleme kopyası kullanın.

```powershell
.\.venv\Scripts\python.exe -B research/prepare_archive_data.py --dir .restore-rehearsals/2026-09-10 --output research/data/archive_preparation/2026-09-10 --rest-fallback
```

Varsayılan ağ kapalıdır. Yeni snapshot için ayrı çıktı dizini seçin. Eksik
resmî dosyaları indirmeye izin vermek için `--download` eklenir. `--rest-fallback`
yalnız son üç günün yayımlanmamış mum dosyaları için resmî REST'e izin verir;
eski günler ve metrics bu yolla uydurulmaz. Dosyası yoksa raporda eksik kalır.

Çıktı: `preparation_report.json`. Saat listeleri, alan eksikleri, kaynak
URL'leri/hash'leri, tamamlanan S2 alanları ve fiyat penceresi kontrollerini
içerir. **Backtest getiri tablosu veya işlem günlüğü değildir.**

Kullanıcı adımları: [TABLET.md](../TABLET.md#araştırma-verisini-tamamlama-10-eylül-2026).
