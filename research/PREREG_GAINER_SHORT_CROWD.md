# G1 — Günün yükseleni + yeni short birikimi ön kaydı

**Kayıt tarihi:** 2026-08-31
**Durum:** Gölge/araştırma sinyali; otomatik işlem veya yatırım önerisi değildir.
Sonuçlar görülmeden önce aşağıdaki kurallar dondurulmuştur.

## Hipotez ve veri

Günün güçlü yükselenlerinden birinde hacim ve open interest birlikte artarken
global hesap long/short oranı 1'in altındaysa yeni short hesaplarının yükselişi
besleyebileceği hipotezi sınanır. Long/short oranı **hesap sayısıdır**, notional
pozisyon büyüklüğü değildir. Bu yüzden OI ve hacim koşulları zorunludur.

- Fiyat/hacim: Binance USD-M perpetual 1h OHLCV.
- OI ve global hesap L/S: resmî USD-M günlük metrics arşivi.
- UTC gün sınırındaki OI değişimi için her aday günün önceki günü yalnız bağlam
  olarak indirilir; o gün tek başına aday olay yaratmaz.
- Tarihsel evren: önceden sabitlenmiş 89 sözleşme.
- Canlı evren: tarama anında Binance'te `TRADING`, `PERPETUAL`, USDT marjinli
  olan tüm USD-M sözleşmeleri. Sıralama resmî 24h ticker snapshot'ındandır.

## Dondurulmuş sinyal

Kapanmış saatlik bar `t` için LONG:

1. 24 saatlik perpetual getiri `>= +%5`.
2. Sembol aynı saatte evrenin getiriye göre ilk 10'unda.
3. Son 1h quote volume, **önceki** 24 tamamlanmış saatin medyanının `>=2.0x`i.
4. OI son 1 saatte `>= +%2`.
5. Global hesap long/short oranı `<1.0`.
6. False→True edge ve sembol başına 24h cooldown.

Giriş sonraki 1h bar açılışıdır. Birincil çıkış girişten 4h sonraki kapanış;
1h/12h/24h yalnız tanısaldır. Round-trip maliyet 12bp. Taban karşılaştırması
yalnız ilk 10 + `%5` getiri koşuludur. Rolling medyanda güncel saat yoktur;
giriş/çıkışta gelecek bar kullanımı yalnız sonuç hesabıdır.

## Karar kapıları

- Train `<2026-01-01`; test `>=2026-01-01`. Sınırdan taşan train getirileri
  purge edilir.
- Çekirdek-30 train `N>=30`; genişletilmiş-59 train `N>=50`.
- Her iki train kümesinde net ortalama ve medyan `>0`, win rate `>=%52` ve
  yükselenler tabanına göre ortalama edge `>0` gerekir. Tüm-89 train için ayrıca
  gün-kümeli bootstrap `p<=0.05`, q10 `>-%5` gerekir.
- Ancak train kapıları geçerse test bir kez açılır. Test `N>=30`, net ortalama
  ve medyan `>0`, win rate `>=%52`, `p<=0.05`, q10 `>-%5`, tabana üstünlük ve
  iki evren parçasında negatif olmayan ortalama gerektirir.
- Kapı geçmese de kullanıcı talebiyle canlı **gölge olay** üretilebilir; bu,
  stratejinin doğrulandığı anlamına gelmez ve performansı ayrı raporlanır.
