# Forward OI keşfi — 5 dakikalık hedef/stop ilk-dokunma ön kaydı

**Kayıt tarihi:** 2026-08-31  
**Durum:** Keşif tanısı; OOS değildir, canlı strateji/bildirim değildir.

## Amaç

Saatlik arşiv raporunda yalnız ufuk sonu kapanışı ölçmek, kullanıcının fiyat
+%2 veya +%3 olduğunda çıkma davranışını yanlış sınıflandırabilir. Bu test,
dondurulmuş P0–P5/Q1 olaylarında hedef ile stop seviyesinden hangisinin önce
görüldüğünü resmî Binance USD-M 5 dakikalık kontrat mumlarıyla ölçer.

## Değiştirilmeyecek olay tanımları

Olaylar `explore_forward_oi.py` içindeki P0–P5/Q1 koşulları ve sembol başına
24 saat cooldown ile aynıdır. Sonuca bakarak olay eşiği, sembol veya tarih
çıkarılmaz. Bunlar S1–S6 canlı stratejileri değildir.

## Sabit yürütme varsayımları

- Veri: `data.binance.vision/data/futures/um/daily/klines`, kontrat mumu, `5m`.
- Kaynak ZIP ve resmî `.CHECKSUM` SHA-256 değeri doğrulanır.
- Giriş: olay saatinden sonraki tam UTC saatin 5m mum açılışı. Arşiv worker'ı
  sembolleri sırayla topladığı için daha erken giriş varsayılmaz.
- Hedefler: brüt fiyat hareketi **+%2** ve **+%3**.
- Stop hassasiyeti: **−%1**, **−%1,5**, **−%2**. Birincil rapor −%1,5'tir;
  diğerleri dayanıklılık tanısıdır, en iyisini seçme taraması değildir.
- Ufuklar: 4, 12 ve 24 saat. Birincil karar ufku bu keşif çıktısından seçilmez.
- Aynı 5m mumda hem hedef hem stop varsa sıra bilinemez; birincil sonuçta
  muhafazakâr biçimde **stop önce** sayılır, belirsiz olay sayısı ayrıca yazılır.
- MAE/MFE, çıkış mumunun tamamını içerir; mum içi sıra bilinmediği için bu
  muhafazakâr bir ters/lehte hareket tahminidir. Hedef süresi ilk dokunan 5m
  mumun sonuyla yazılır ve en fazla beş dakikalık bir üst sınırdır.
- Ufuk dolarsa son 5m kapanışından çıkılır.
- Gidiş-dönüş maliyet: 12bp. Funding nakit akışı ve slippage modellenmez.
- Bir 5m bar bile eksikse ilgili olay/ufuk `unavailable` olur; fiyat uydurulmaz.

## Raporlanacak ölçüler

Her kural × hedef × stop × ufuk için N, eksik N, hedef-önce alt/üst sınırı,
stop-önce, timeout, net ortalama/medyan, win rate, q10/q90, medyan MAE,
hedefe medyan süre ve UTC gün-kümeli bootstrap `p(mean<=0)` raporlanır.

## Karar disiplini

Bu mevcut keşif döneminin ikinci görünümüdür ve güvenilirlik/OOS iddiası
üretemez. En az 90 günlük keşif sonunda aday kural önceden dondurulur; sonraki
90 günlük dokunulmamış OOS döneminde tek kez değerlendirilir. Hedef oranı tek
başına başarı değildir: net beklenti, kuyruk, stop sırası, gün ve sembol
yoğunlaşması birlikte olumlu değilse aday reddedilir.
