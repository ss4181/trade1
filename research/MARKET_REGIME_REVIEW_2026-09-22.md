# Telegram piyasa rejimi: araştırma ve uygulama kararı — 22 Eylül 2026

> Güncelleme: [Süre sınırsız TP2/TP3 hesabı](MARKET_REGIME_EVENTUAL_TOUCH_2026-09-22.md) eklendi. Önceki G2 MFE tabanlı stop olmadan dokunma hesabı geçersizdir; MFE ilk çıkışta kesiliyordu. Yeni sonuçlar ham fiyatlardan hesaplandı. “Son 90 gün” ifadesi güncel tablet kayıtlarını değil, 2025 sonunda biten tarihsel G1 arşivini anlatıyordu.


**Karar:** Ayı/geçiş/boğa düğmesi uygulanabilir. Bütün stratejileri boğada açan veya ayıda susturan ortak bir filtreyi veriler desteklemiyor. İlk sürüm bilgi ve sürümlü gözlem kaydı sunmalı. Luna için uygulama planı hazır; canlı kod, Telegram ve tablet bu hazırlıkta değiştirilmedi.

Bu dosyadaki ana tablolar zaman çıkışı ölçüsüdür. TP2/TP3 hedef dokunmasıyla
yeniden hesaplanan sonuçlar ve özellikle G1'in son dönem incelemesi için
[TP2/TP3 dokunma ek raporuna](MARKET_REGIME_TOUCH_REVIEW_2026-09-22.md)
bakılmalıdır; iki ölçü birbirine karıştırılmamalıdır.

## Hesap ve kapsam

- 89 sabit sembol: core30 içinde S1/S1+S4/S2/S3; extended59 içinde yalnız S1/S1+S4. Eski G1 TRAIN vekil testi ve önceden seçilmiş G2 adayı ayrıca değerlendirildi.
- Toplam **2.814** ölçülmüş olay: çekirdek 1.632, extended59 529, G1 vekili 401, G2 252. S1 ve S1+S4 birbirinden ayrı olaylardır; iki kez sayılmadı.
- Çekirdek/extended saatlik arşiv: 01.07.2024–30.06.2026. G2: Temmuz–Eylül 2026 A/B/C mevcut araştırma örnekleri. G1 TEST açılmadı.
- BTC spot günlük verisi 01.10.2023–21.09.2026 aralığında yeniden alındı. 730 ortak tam günün kapanışı saatlik arşivle birebir aynı: azami fark **0**.
- 249 mumda sıfırlanan Wilder RSI, eşik eşitlikleri, ilk eşit dip, S3 cooldown tüketimi ve S4 son 24 saat dahil kuralı korundu. Hızlandırılmış adaptör **15.904** pencerede saf motorla karşılaştırıldı; ayrışma yok. Bu bütün saatlerde canlı Telegram gönderimi olmuş demek değildir.
- İlk tam pencere ve 72 saat state ısınması, veri/ufuk bitimi ve dönem sınırı dışlamaları uygulandı. 89 seride geçersiz özellik penceresi 0; çekirdekte yetersiz funding başlangıcı nedeniyle atlanan tarama 0; 4 olayda tamamlanmış geçerli ufuk/ısınma koşulu sağlanmadı.
- Mevcut core/extended dönemleri ve G2 C daha önce araştırılmıştır: yeni sonuçlar betimleyicidir, yeni OOS değildir. Mevcut sabit evrende hayatta kalma/seçim yanlılığı vardır; geçmiş gerçek üyelik, veri yayın gecikmesi, emir dolumu ve tablet teslimi yeniden oluşturulmadı.

## Sabit günlük rejim tanımı

BTC son kapanışı C, 200 günlük ortalama M200, M200 / M200(20 gün önce) − 1 eğimi. **Boğa:** C > 1,02 × M200 ve eğim pozitif. **Ayı:** C < 0,98 × M200 ve eğim negatif. **Geçiş:** diğer geçerli durumlar. En az 220 kesintisiz kapanmış günlük mum gerekir. Eksik/bayat veri **belirsizdir**, geçiş değildir.

Boğa içinde son 30 günlük basit BTC getirisine göre: **geri çekilme <0; ılımlı 0–%10; güçlü >%10**. Bu sınırlar performansa göre optimize edilmedi. Her olayda yalnız o anda kapanmış günlük veriler kullanıldı. Günün daha sonraki kapanışı geçmiş olaylara verilmedi.

22.09.2026 **03:00 TRT** kapanışına göre örnek sonuç: **BOĞA — güçlü yükseliş**. BTC kapanışı 86.620; M200 70.618,67395; uzaklık +%22,66; M200 20g eğimi +%1,60; 30g getiri +%12,38. Bu günlük BTC eğilimidir; tüm altcoinlerin anlık yönü değildir.

## Ana rejimler: çekirdek ve geniş evren

Her hücre: **olay / ayrı UTC günü · pozitif sonuç oranı · ortalama fiyat getirisi**. Giriş sonraki saat açılışı, çıkış ufuk sonu. Toplam 12 bp (%0,12) maliyet varsayımı çıkarıldı. Spot stratejilerde fiyat senaryosu; **S2 vadeli fiyatla ölçüldü, fonlama hariçtir**. Bu oranlar bildirimdeki TP2 hedef dokunması veya gerçek işlem kârı değildir.

| Strateji / evren / ufuk | Boğa | Geçiş | Ayı |
|---|---|---|---|
| S1 / core30 / 24 saat | 59 / 20 · %69.5 · +1.367% | 29 / 12 · %62.1 · -0.100% | 75 / 30 · %56.0 · +0.776% |
| S1+S4 / core30 / 24 saat | 41 / 11 · %53.7 · +0.966% | 28 / 8 · %67.9 · +4.915% | 68 / 22 · %61.8 · +1.898% |
| S2 / core30 / 72 saat | 103 / 81 · %51.5 · +1.215% | 87 / 64 · %57.5 · +3.442% | 139 / 88 · %50.4 · -0.181% |
| S3 / core30 / 4 saat | 530 / 167 · %55.7 · +0.571% | 186 / 78 · %48.4 · -0.021% | 287 / 97 · %44.6 · +0.103% |
| S1 / extended59 / 24 saat | 130 / 32 · %61.5 · +0.496% | 82 / 19 · %35.4 · -2.659% | 107 / 42 · %57.9 · +2.074% |
| S1+S4 / extended59 / 24 saat | 107 / 22 · %57.0 · +0.745% | 32 / 8 · %75.0 · +8.895% | 71 / 23 · %59.2 · +1.604% |

## Boğa içinde farklı koşullar

Aynı hücre ölçüsü kullanılır. Özellikle olay sayısını ayrı gün sayısıyla birlikte okuyun: aynı gün 20 coin bağımsız 20 piyasa dönemi değildir.

| Strateji / evren | Geri çekilme | Ilımlı yükseliş | Güçlü yükseliş |
|---|---|---|---|
| S1 / core30 | 22 / 10 · %36.4 · -1.630% | 31 / 6 · %87.1 · +3.420% | 6 / 4 · %100.0 · +1.754% |
| S1+S4 / core30 | 29 / 5 · %44.8 · -0.395% | 10 / 5 · %70.0 · +4.807% | 2 / 1 · %100.0 · +1.497% |
| S2 / core30 | 55 / 38 · %49.1 · +1.088% | 27 / 24 · %55.6 · +0.508% | 21 / 19 · %52.4 · +2.456% |
| S3 / core30 | 151 / 44 · %66.9 · +1.931% | 184 / 63 · %47.8 · -0.074% | 195 / 60 · %54.4 · +0.125% |
| S1 / extended59 | 48 / 13 · %33.3 · -1.238% | 67 / 13 · %79.1 · +1.163% | 15 / 6 · %73.3 · +3.070% |
| S1+S4 / extended59 | 76 / 8 · %53.9 · +0.297% | 25 / 9 · %68.0 · +2.650% | 6 / 5 · %50.0 · -1.512% |

**S3 için ileri araştırma adayı:** boğada geri çekilme. 151 olay / 44 gün / 30 sembol; pozitif sonuç %66,9; ortalama +%1,931, medyan +%1,488. Aynı sembol, rejim ve takvim bölümündeki saatlik giriş tabanına göre fark +2,018 yüzde puan. Fakat en yoğun 5 günde 76/151 olay var. 7 günlük bloklarla ortalama getirinin %95 aralığı **[−%0,054, +%3,197]**; sıfırı içeriyor. Taban farkının aralığı [+0,030, +3,283] yüzde puan; taban tahmini sabit kabul edilmiştir ve çoklu karşılaştırma düzeltmesi yapılmamıştır. Bu tek başına uygulanabilir kâr kanıtı değildir.

**S1:** ılımlı boğada core30 %87,1 (31 olay / 6 gün), extended59 %79,1 (67 olay / 13 gün) pozitif. Her iki evrende geri çekilme sonuçları daha kötü. Araştırılmaya değer bir örüntü, fakat birkaç piyasa gününe yoğunlaşmış. Core güçlü boğadaki %100 yalnız 6 olay / 4 gündür; avantaj diye pazarlanamaz.

**S1+S4:** sade S1 ile aynı filtreye sokulmamalı. Güçlü boğada extended59 sadece 6 olayda ortalama −%1,512; küçük örnekleme dayanarak karar verilemez. Geçiş ortalamaları yüksek olsa da yalnız 8 güne yığılmıştır.

**S2:** en yüksek ana-rejim ortalaması geçişte (+%3,442), fakat medyan +%1,082 ve güven aralığı sıfırı içeriyor. Fonlama eksikliği ve 72 saatlik ufuk nedeniyle S3 ile doğrudan kârlılık sıralaması yapılmaz.

## G1: canlıyla eşdeğer olmayan TRAIN vekili

Eski test 89 sözleşmelik sabit sıralama, hacim/OI/long-short geçmişi ve 4 saat çıkış kullanıyor. Bugünkü canlı tüm-piyasa sıralamasının doğrulaması değildir. 12 bp çıkarıldı, fonlama hariç. TEST kısmının sonuçları hesaplanmadı.

| Rejim | Olay / gün | Pozitif fiyat sonucu | Ortalama | Medyan |
|---|---:|---:|---:|---:|
| ALL | 401 / 263 | %45.9 | -0.127% | -0.300% |
| BULL | 194 / 142 | %43.3 | -0.328% | -0.737% |
| TRANSITION | 171 / 99 | %49.7 | +0.054% | -0.008% |
| BEAR | 36 / 22 | %41.7 | +0.093% | -0.065% |
| bull_pullback | 53 / 44 | %37.7 | -0.609% | -0.626% |
| bull_moderate | 80 / 56 | %40.0 | -0.720% | -1.057% |
| bull_strong | 61 / 42 | %52.5 | +0.431% | +0.205% |

G1 güçlü boğada +%0,431 ortalama gösterse de %95 aralığı [−%0,703, +%1,560]; geniş ve sıfırı içeriyor. “G1 artık başarılı” sonucu çıkarılamaz.

## G2: hedef–stop ölçüsü ve rejim

Önceden seçilmiş aday değişmedi: `fade_long_l1_up_d60_e2`. Sinyal kapanışından 60 dakika sonra referans giriş; %3 hedef / %2 stop / 24 saat azami ufuk. Sonuçlar toplam 20 bp maliyet ve muhafazakâr fonlama varsayımını içerir. **Hedefe stoptan önce ulaşma** ile **pozitif fiyat senaryosu** ayrı kolonlardır; pozitif zaman çıkışı başarı hedefiyle aynı şey değildir.

| Dönem / rejim | Olay / gün | Hedef önce | Pozitif sonuç | Ortalama | Hedef / stop / süre sonu |
|---|---:|---:|---:|---:|---|
| ALL / ALL | 252 / 66 | %40.9 | %46.0 | +0.080% | 103 / 127 / 22 |
| A+B / BEAR | 181 / 44 | %41.4 | %47.0 | +0.134% | 75 / 88 / 18 |
| C / ALL | 71 / 22 | %39.4 | %43.7 | -0.057% | 28 / 39 / 4 |
| C / TRANSITION | 47 / 15 | %44.7 | %51.1 | +0.288% | 21 / 22 / 4 |
| C / BULL | 24 / 7 | %29.2 | %29.2 | -0.733% | 7 / 17 / 0 |

G2 boğa örneklerinin tamamı **güçlü boğa**: 24 olay / 7 gün. Boğada hedef başarısı %29,2 (7/24), ortalama −%0,733. Geçişte hedef başarısı %44,7 (21/47), ortalama +%0,288. “Boğa olunca G2 iyileşir” desteklenmiyor.

Önemli karışma: A+B örneklerinin tamamı ayı; C örnekleri geçiş/boğa. Rejim etkisi ile takvim/dönem etkisi ayrılamıyor. G2 boğada-kapat filtresini bu tablodan hemen üretmek yeni örnekleme uyum sağlama riski taşır. Binance/Coinalyze senaryosu, Hyperliquid limit emir dolumu veya gerçek işlem sonucu değildir. Gün sayısı burada **sinyal** günüdür; eski G2 raporundaki giriş-günü sayısından C için bir gün farklı olabilir.

## Doğrulama sınırı ve sonraki araştırma

- 2026 ilk yarısında bu tanım 178 gün AYI, 3 gün GEÇİŞ üretiyor; incelenen çekirdek/extended sinyallerin tamamı ayı günlerine denk geliyor. Dolayısıyla boğa alt-türlerinin yeni dönem doğrulaması bu arşivden çıkarılamaz.
- S5/S6 için tarihsel dinamik evren üyeliği yok: geniş sabit 59 coinin sonuçları bu kanallara taşınmaz. DL1 olay/gözlem alarmıdır; yönlü işlem stratejileriyle aynı başarı listesine sokulmaz.
- Ana ve alt rejimler arasında çok sayıda karşılaştırma var; seçilen iyi hücrelerin p-değeri/garantisi iddia edilmedi. N≥30 ve ayrı olay günü≥28 olmayan hücrelerde güven aralığı yayımlanmadı. Bloklar 7 takvim günü, 2.000 tekrar, sabit seed. Bu eşikler yeterlilik garantisi değildir.
- Bundan sonraki sinyallere sürümlü günlük rejim eklenip her stratejinin kendi mevcut ölçümüyle biriktirilmeli: G2 hedef–stop sırası; diğerleri mevcut hedef dokunması. Bu araştırmadaki zaman-çıkış oranları o kolonlara yazılmamalı.
- Öncelikli sabit hipotezler: S3 / boğada geri çekilme; S1 / ılımlı boğa. S1+S4 ayrı izlenir. Yeni dönem tamamlanmadan eşikler/evren/TP/SL değiştirilmez; başlatılacak ileri testin başlangıcı ve karar koşulları ayrıca kaydedilir.
- Rejim panosunun faydası mevcut bağlamı açıklamak ve karşılaştırılabilir kayıt üretmektir. Tek başına başarı oranını artırması beklenmez.

## Telegram uygulama kararı

**🌐 Piyasa** → `/piyasa`: kısa yanıt, ayı/geçiş/boğa ve boğa alt türü, bir satır gerekçe, günlük veri kapanışının TRT saati. Veri belirsizliği açık. Ayrı arka plan worker ve cache; yeni ağ çağrısı sinyal/komut yolunu bloklamaz. Eski S3 etiketi ile yeni sürüm karıştırılmaz. Yeni rejim bütün stratejilerin kendi sinyal referansında dondurulur; otomatik sinyal filtresi açılmaz.

[Luna uygulama devri](LUNA_MARKET_REGIME_HANDOFF_2026-09-22.md) iş adımlarını, dosya/fonksiyon noktalarını, kabul testlerini ve yayın sonrası tablet adımlarını içerir.

## Yeniden üretim ve testler

Bu hazırlıkta **6 araştırma testi geçti**: motor penceresi eşitliği, günlük veri ısınması ve etiketleri, zaman sınırı/gelecek bilgi/bayatlık, boş/tekrarlı gün, ufuk/getiri hizası ve gün kümeli belirsizlik. Üretim kodu değişmediği için botun tamamı bu turn içinde yeniden test edilmedi.

```powershell
& 'C:\Users\serha\Downloads\trade1\.venv\Scripts\python.exe' research\market_regime_review.py --output research\data\regime-review-2026-09-22 --data 'C:\Users\serha\Downloads\trade1\research\data' --funding 'C:\Users\serha\Downloads\trade1\research\funding_cache\funding_history.json'
& 'C:\Users\serha\Downloads\trade1\.venv\Scripts\python.exe' -m unittest tests.test_market_regime_review -v
```

İlk komut mevcut günlük cache ile çevrimdışı çalışır. Eksikse aynı araçta `--fetch-daily --output ...` ayrı, yalnız herkese açık Binance verisini alan adımdır. Üretim bota/API anahtarlarına dokunmaz. Sabit kaynak serisi yeniden indirilirse hashes kontrol edilmelidir. `--bot` seçeneğiyle başka temiz release kopyası verilebilir; varsayılan incelenen `tmp/tablet-release/signal_bot.py` yoludur.

- [Hesap öncesi protokol ve kapsam eki](MARKET_REGIME_PROTOCOL_2026-09-22.md)
- [Analiz kodu](market_regime_review.py)
- [Tüm hücreler, güven aralıkları ve kaynak SHA-256 kayıtları](results/market_regime_review_2026-09-22.json)
- Ham günlük veri, günlük rejim takvimi ve olay satırları: `research/data/regime-review-2026-09-22/` (yerel araştırma çıktısı).
- Tarihsel G1 metrik kaynağı: `Downloads/trade1/research/data/metrics_gainer/`; G2 kaynakları mevcut `search-2026-09-14/search_outcomes.jsonl` ve `confirm_outcomes.jsonl`.
- İncelenen temiz bot: `6a75b3c`; saf motor kural fingerprint: `4c6e416c9dc87f30050115e7f8976b854d5667f3462733604d8d36cecd691640`.
- Günlük ham veri SHA-256: `cd1d084b38d93ca008c9d96c65a210e61363ab68f2c89f14a28c886dc7e05962`.

API sözleşmeleri: [Binance spot mumlar](https://developers.binance.com/en/docs/catalog/core-trading-spot-trading/api/rest-api/market), [Telegram özel klavye](https://core.telegram.org/bots/api#replykeyboardmarkup).
