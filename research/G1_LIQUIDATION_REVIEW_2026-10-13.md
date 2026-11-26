# G1 likidasyon araştırması — 13 Ekim 2026

## Sonuç

**Henüz G1'e likidasyon filtresi eklemeyi destekleyen doğrulanmış sonuç yok.**
Bu tur veri hazırlığı denetlendi ve test aracı sıkılaştırıldı; kârlılık
testi/OOS tamamlanmadı. Canlı G1, evren, eşik, cooldown, bildirim veya emir
davranışı değiştirilmedi. Push/deploy yapılmadı.

Ücretsiz gerçekleşmiş likidasyon proxy'si ile modellenmiş heatmap aynı veri
değildir. Mevcut arşiv ilkini içeriyor. İkinci araştırma için ayrı, karar
anından önce alınmış ve lisansı doğrulanmış snapshot gerekiyor.

## 1. İncelenen özel PC kopyası

Kaynak: `<PC yedek klasörü>`. Denetim başlangıcı
**13 Ekim 2026 00:22:15 TRT / 12 Ekim 21:22:15 UTC**.
Makine çıktısı git dışında:
`research/data/g1-liquidation-review-2026-10-13/audit.json`.
Bu, tabletin anlık durumu veya tüm yedek paketinin doğrulaması değildir.

| Ölçü | Sonuç |
|---|---:|
| Kabul edilen benzersiz G1 olayı | 143 |
| 4 saatlik süresi dolmuş G1 | 141 |
| Henüz süresi dolmamış G1 | 2 |
| Gerçekleşmiş forceOrder kayıtları | 1.659.052 |
| En az bir likidasyon kaydı olan UTC gün | 43 |
| İlk-son likidasyon arasındaki süre | 42,2 gün |
| Bağlantı/status kayıtları | 19.970 |
| Bozuk JSON/olay, tekrarlanan olay, eksik receive zamanı | 0 |
| Getirisi hesaplanan olay / fiyat indirme isteği | 0 / 0 |

Önceki 12 Ekim denetiminde 138 G1 ve 1.618.377 likidasyon kaydı vardı.
Yeni PC kopyasında daha fazla kayıt var; **aktarım olması bütünlüğünün
doğrulandığı anlamına gelmiyor**. 1,66 milyon snapshot, bu hipotez için
1,66 milyon bağımsız işlem/sinyal demek değildir: G1 örneklemi 143'tür.

### Kalan veri engelleri

- Ön kayıt en az **90 günlük kapsam** istiyor; 42,2 gün yeterli değil.
- İlk gerçek likidasyon 31 Ağustos 2026 17:22:29.484 UTC. Takvim açısından
  en erken inceleme **29 Kasım 2026 20:22 TRT**. O tarihe kadar kayıtların
  sürmesi ve kalite kapılarının geçilmesi gerekir; otomatik kabul tarihi değil.
- `backup_manifest.json` denetimde **48,02 saat** eski; 36 saat tazelik
  kontrolünü geçemedi.
- `shadow_events_2026-10.jsonl` ve `liquidation_archive_2026-10.jsonl`
  manifest hash/boyut doğrulamasını geçemedi. Okuma sırasında altı ilgili
  kaynak dosya sabitti. Bu durum veri kaybını veya bozulmayı kanıtlamaz;
  karışık/eski manifestli bir eşitleme de olabilir. Tableti incelemeden
  nedeni kesinleşmez. Kaynak ve manifest **değiştirilmedi**.

Bu sayılar teşhis içindir. Manifest sorunu çözülmeden doğrulanmış analiz
verisi kabul edilmiyor. Özellik kapsamı sayıldı, getiriler açılmadı.

## 2. Tam olarak neyi test ediyoruz?

| Aday | Anlamı | Süresi dolmuş 141 olayda özellik kapsamı |
|---|---|---:|
| BASE_G1 | Arşivdeki mevcut G1 olayı | 141 |
| LQ1 | Önceki saatin short-likidasyon toplamı, geçmiş 30 günlük dağılımın p95'i veya üstünde | 94 ölçülebilir; 73 koşul eşleşmesi |
| LQ2 | Önceki 24 saatin gerçekleşmiş likidasyonlarında fiyat üstündeki küme, alt kümenin en az 1,5 katı | 131 ölçülebilir; 76 koşul eşleşmesi |
| LQ1 + LQ2 | İkisinin birlikte sağlanması | Getiri karşılaştırması kapalı |

**73 veya 76 başarılı işlem sayısı değildir.** Bunlar yalnız koşulun
hesaplanıp doğru bulunduğu kayıtlardır. Eksik gözlem `UNKNOWN` kalır.

Referans giriş: koşul mumundan sonraki saat açılışı. Çıkış: +4 saat kapanış.
Maliyet varsayımı 12 bp; funding **not_modeled**. Ayrıca +%2/+%3 hedefin
-%1,5 stoptan önce görülmesi, MFE/MAE ve üst kümeye dokunma ölçülecek.
Aynı 5dk mumda hedef ve stop varsa muhafazakâr sıra kullanılır. Dokunma
zamanı 5dk mum sonu çözünürlüğündedir, kesin saniye değildir. Bunlar yeni
TP/SL önerisi değil, mevcut ön kaydın sabit ölçümleridir.

Referans açılışından yapılan bu ölçüm Telegram fiyatından fiilen girişin
veya yeni fresh-ask sürümünün başarısını kanıtlamaz. Üst küme girişten önce
zaten aşılmışsa sonradan hedef başarısı diye yazılmaz.

### Fiyat/ölçüm sürümleri ayrı tutuluyor

| G1 sürümü | Toplam | Süresi dolmuş |
|---|---:|---:|
| v1 / eski ölçüm | 13 | 13 |
| v2-price-fix / eski ölçüm | 124 | 124 |
| v3-fresh-ask / signal-reference-touch-1m-v2 | 6 | 4 |

Bu kopyada evren etiketi `all_active_usdm_perpetuals`; test yeni coin veya
sinyal üretmedi. Yeni sürümde **yalnız 4 olgun olay** var. Eski 137 kayıtla
toplanıp yeni girişin güven oranı gibi sunulamaz. Araç sonuçları
config + ölçüm sürümü + evren bazında ayırır; 30'dan küçük kohort tablosunu
kapalı tutar. Kapı sonrasında yeterli ana kohort içindeki küçük filtre
altkümeleri ayrıca `small_sample` uyarısı taşır; kabul kanıtı değildir.

## 3. Bu tur düzeltilen araştırma açıkları

- 90/30/30 veya bütünlük kapısı kapalıysa **getiri hesabı ve fiyat indirmesi
  hiç çalışmıyor**; yalnız sonuçları ekrandan gizlemekle yetinilmiyor.
- Olayın borsa zamanı yanında **yerelde alınma zamanı** da kesimden önce
  olmalı. Geç ulaşan kayıt geçmişte biliniyormuş gibi kullanılmıyor.
- Bir saatte tek heartbeat görülmesi artık tüm saati eksiksiz saydırmıyor;
  LQ1 için 12 adet 5dk kutu gerekir. Kesinti bildirilen kutu dışarıda kalır.
  Heartbeat, borsanın snapshot akışındaki tüm likidasyonları kapsadığını
  yine de kanıtlamaz.
- Eksik bağlantı/alınma zamanı sıfır likidasyon veya `false` filtre sayılmıyor.
  Alt küme sıfırken JSON'a `Infinity` yazılmıyor.
- Okunan gerçek byte'ların hash'i, okuma kararlılığı, dosya kümesi ve varsa
  yedek manifesti doğrulanıyor; hazırlık sonrası değişim de kapıyı kapatıyor.
- Sürümler ve evrenler ayrılıyor; filtre karşılaştırmaları için yalnız aynı
  ölçülebilir özellik kapsamındaki G1 baz grupları ayrıca hazırlanıyor.
- Varsayılan ağ kapalı; `--download` açıkça verilse bile giriş kapıları
  sağlanmadan indirme yok. Yalnız araştırma girdileri okunuyor; bot state/env
  yüklenmiyor ve canlı bot başlatılmıyor.

Araştırma araç sürümü: `g1-liquidation-proxy-v2-causal-audit`.
Bu teknik doğruluk sıkılaştırmaları görünür şekilde kaydedildi; eski araç
çıktıları yeni sürümle doğrudan birleştirilmemeli. **Ön kayıt değiştirilmedi:**

```text
PREREG_G1_LIQUIDATION_PROXY.md SHA-256
acc92c7412098f9f5cf215bd374597aa3a6c2b432d8b4e11148c6526043bc8e3
```

Eski ön kayıttaki "en büyük snapshot" ifadesi bir belge hatasıdır: Binance
sembol başına 1000ms içindeki **en son** olayı yayımlar. Ön kayıt hash'ini
değiştirmemek için düzeltme burada açıklanıyor; Eylül denetiminde de not
edilmişti. Dolayısıyla toplamlar bütün tasfiye piyasasının tam hacmi değildir.
[Binance resmî akış tanımı](https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/ws-streams/market)

## 4. Gerçek heatmap için kalan iş

Model tabanlı harita için öncesinde yakalanmış snapshot yok. Mevcut
forceOrder fiyat kümelerini heatmap diye yeniden adlandırmak bu eksiği
gidermez. CoinGlass Model1 erişimi, zaman semantiği ve lisansı doğrulandıktan
sonra ayrı collector/protokol gerekir; [veri toplama taslağı](G1_HEATMAP_CAPTURE_SPEC.md)
hazırlandı. Ücretli hesap açılmadı veya API anahtarı aranıp kullanılmadı.

## 5. Doğru sonraki adımlar

1. Tablette yeni günlük yedek alıp PC eşitlemesini tamamla. [PC_BACKUP.md](../PC_BACKUP.md)
   doğrulayıcısı `ok: true` olmadan bu snapshot'ın getiri incelemesi açılmasın.
   Manifesti PC'deki bozuk/eksik pakete göre yeniden üretmek çözüm değildir.
2. Mevcut arşivlemeyi sürdür. Kapılar ve kohort sayıları hazır olunca aynı
   sabit protokolü çalıştır; sonuç görerek p95/mesafe/TP/SL değiştirme.
3. Keşifte aday varsa ayrı sonraki **90 günlük OOS** ile sınanır. OOS kabulü
   olmadan G1'i filtreleme, güven yüzdesi artırma veya otomatik emir yok.
4. Heatmap erişimi sağlanırsa yeni bir ileri arşiv başlar; forceOrder'ın
   geçmiş 42 günü yeni haritanın veri geçmişi sayılmaz.

Elle salt okunur kontrol:

```powershell
.\.venv\Scripts\python.exe -B research/eval_g1_liquidation_proxy.py --dir '<PC yedek klasörü>' --no-download
```

Tablete bu yerel kod aktarıldıktan sonra:

```bash
cd ~/trade1
python research/eval_g1_liquidation_proxy.py --dir . --no-download
```

Bu komut botu başlatmaz, bildirim göndermez, arşivi değiştirmez. Araç
şimdilik yerel çalışma ağacındadır; tablette kendiliğinden güncellenmez.

## 6. Doğrulama ve açık test notu

- G1 proxy'nin **14 testi** ve arşiv hazırlığının **17 testi** geçti.
  Yeni kontroller: geç veri sızıntısı, eksik heartbeat, UNKNOWN, JSON
  sonluluğu, gate kapalıyken fiyat/getiriye erişmeme, manifest/secret
  temizliği, kohort ayrımı ve eşitleme sırasında kaynak değişimi.
- Gerçek PC arşiviyle salt okunur denetim çalıştı; 0 fiyat isteği, 0 getiri
  hesabı. Makine raporu git-ignore altında; kaynak arşiv değiştirilmedi.
- **Tam 47 dosyalı çevrimdışı paket iki kez çalıştırıldı; her turda 46 geçti.**
  İlk tur `test_signal_watch.py` içindeki
  `test_baseline_silent_then_global_transition_and_no_repeat` beklenen iki
  sahte teslim yerine sıfır gördü. İkinci tur bu geçti; `test_hardening.py`
  içindeki `test_concurrent_retry_never_sends_to_an_inflight_recipient`
  sahte gönderici başlangıcını 3 saniyede göremedi.
- Tekil tekrarlar geçti. G1 + arşiv + hardening + signal-watch birlikte
  yeniden çalıştırıldığında **65/65 test geçti**. Tam paket için kesintisiz
  yeşil sonuç alınmadı; aralıklı iki hatanın kök nedeni doğrulanmadı.
  Araştırma kapsamı dışındaki canlı bildirim kodu bu hataları bastırmak için
  değiştirilmedi. Bunlar 7. madde bildirim/doğrulama işine açık nottur;
  tablet/Telegram uçtan uca doğrulaması yapıldı diye sunulamaz.
- `git diff --check` başarılı. Dondurulmuş ön kayıt hash'i değişmedi.

Testler sentetik verili ve ağ bağlantısı engellenmiş ayrı geçici kopyada
çalıştırıldı (tam paket). 65 testlik odaklı tekrar yalnız yerel sentetik
dosyalar/sahte göndericiler kullandı. Gerçek Telegram/işlem isteği gönderilmedi.
