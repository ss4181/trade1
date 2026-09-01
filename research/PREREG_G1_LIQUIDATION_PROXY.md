# G1 + gerçekleşmiş likidasyon yoğunluğu/ fiyat-kümesi proxy testi

**Ön kayıt:** 2026-09-01  
**Durum:** Keşif toplama; canlı G1 koşulu, eşikleri, güven etiketi ve bildirim
kapısı değişmez.

## Veri sınırı

Binance USD-M `!forceOrder@arr` akışı, gelecekte hangi fiyatlarda açık
pozisyonların likide olacağını gösteren bir heatmap değildir. Akış yalnız
**gerçekleşmiş** likidasyon emirlerinden, sembol başına 1000 ms içindeki en
büyük snapshot'ı verir. Bu nedenle aşağıdaki fiyat kümeleri “bekleyen
likidasyon birikimi” diye adlandırılmaz; yalnız geçmiş gerçekleşmiş olayların
fiyat-hafızası proxy'sidir.

CoinGlass liquidation map/heatmap verisi ileride lisanslı ve zaman damgalı
snapshot olarak toplanırsa ayrı veri sürümü ve ayrı ön kayıt gerekir. Sonradan
indirilen güncel harita geçmiş bir G1 olayına eklenemez; bu veri sızıntısı olur.

## Sabit olay ve giriş tanımı

- Olay: canlı gölge arşivindeki mevcut `G1_EVENT`; G1 eşikleri aynen korunur.
- Özellik kesimi: G1 koşul mumunun kapanışı. Bu andan sonraki likidasyon veya
  fiyat verisi özellik olarak kullanılamaz.
- Ölçüm girişi: koşul mumundan sonraki tam 1 saatlik mumun açılışı.
- Birincil çıkış: girişten 4 saat sonraki kapanış.
- Maliyet: 12 bp round-trip.
- Aynı sembolde olaylar canlı G1'in 24 saatlik cooldown'u ile zaten ayrıdır.

## Önceden dondurulmuş proxy'ler

### LQ1 — Short-likidasyon patlaması

Girişten önceki son 1 saatteki `SHORT_LIQUIDATION` USD toplamı, yalnız o anda
mevcut olan önceki 30 günlük ve bağlantısı doğrulanmış saatlik dağılımın
%95 persentiline eşit veya üzerindedir. En az 30 takvim günü ve 576 doğrulanmış
saat yoksa özellik `unavailable` olur; sıfır uydurulmaz.

### LQ2 — Üst fiyat-kümesi proxy'si

Girişten önceki 24 saatin gerçekleşmiş force-order fiyatları, G1 koşul
fiyatına göre 25 bp genişlikte sabit kutulara ayrılır. Koşul fiyatının
`+%0,25` ile `+%3,00` arasındaki SHORT_LIQUIDATION kutuları “üst küme”,
`-%0,25` ile `-%3,00` arasındaki LONG_LIQUIDATION kutuları “alt küme”dir.
Üst küme USD toplamı alt kümenin en az 1,5 katıysa ve 24 saatin en az %80'inde
bağlantı heartbeat'i varsa `LQ2=true` olur. Seçilen üst hedef, aralıktaki en
yüksek USD toplamlı kutunun merkezidir.

### Dondurulmuş karşılaştırmalar

1. `BASE_G1`
2. `G1_LQ1_SHORT_BURST`
3. `G1_LQ2_UP_ZONE`
4. `G1_LQ1_AND_LQ2`

## Raporlanacak ölçüler

- N ve bağımsız olay günü,
- 4 saat net ortalama/medyan, win rate, q10/q90,
- 4 saat MFE/MAE,
- +%2 ve +%3 hedefin -%1,5 stoptan önce görülme oranı,
- LQ2 üst fiyat-kümesine 4 saatte dokunma oranı ve medyan dokunma süresi,
- veri/heartbeat eksiklikleri ve sembol yoğunlaşması.

## Karar kapısı

Bu ilk dönem yalnız keşiftir. En az 90 takvim günü, 30 likidasyon olay günü ve
30 olgun G1 olayı olmadan başarı oranı açıklanmaz. Bir aday keşifte seçilirse
eşikleri dondurulur ve sonraki ayrı 90 günlük OOS dönemde sınanır. OOS'ta en az
30 olay/30 gün, net ortalama ve medyan `>0`, win rate `>=%52`, gün-kümeli
bootstrap `p<=0.05`, q10 `>-%5` ve `BASE_G1`'den pozitif üstünlük gerekir.

Sonuç görülerek 25 bp, %95, 24 saat, %3 veya 1,5x parametreleri değiştirilmez.
Bu test canlı işlem veya otomatik emir üretmez.
