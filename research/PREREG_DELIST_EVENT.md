# DL1 — Binance tam-token delist olayı ön kaydı

**Kayıt tarihi:** 2026-08-31
**Durum:** Gölge/araştırma olayı; otomatik işlem veya yatırım önerisi değildir.

## İki ayrı hipotez

1. **DL1-PRE:** Binance'in resmî tam-token delist duyurusundan spot işlemlerin
   duracağı ana kadar token fiyatı yükselir.
2. **DL1-POST:** Binance spot delistinden sonra token başka bir borsadaki
   perpetual sözleşmede düşer.

Bu iki sonuç birleştirilmez. İkinci hipotez ancak duyuru anında o borsada
gerçekten işlem gören, short edilebilir sözleşme ve zaman damgalı fiyat/spread/
funding verisi arşivlenmişse ölçülür. Bugünkü ürün listesini geçmişe uygulamak
yasaktır.

## Olay ve kaynak kuralları

- Yalnız Binance'in resmî `Delisting` kataloğundaki, başlığı
  `Binance Will Delist ... on YYYY-MM-DD` biçimindeki **tam-token spot delist**
  duyuruları kabul edilir. Pair/margin/futures/Alpha kaldırmaları dahil edilmez.
- Duyuru zamanı, kesin işlem durdurma zamanı, token ve makale kodu saklanır.
- Canlı tespitte Binance spot fiyatı ile Bybit/OKX perpetual bulunabilirliği,
  mark/last, bid/ask, OI ve funding mevcut olduğu ölçüde snapshot olarak saklanır.
- Eksik veri sıfırla veya tahminle doldurulmaz. Bir borsada kontrat yoksa olay
  `unavailable` kalır.

## Sonuç tanımı

- Tarihsel DL1-PRE ana değerlendirme penceresi sonuçlara bakılmadan önce son
  beş takvim yılı olarak dondurulmuştur (2021-08-31 ve sonrası). Daha eski
  piyasa mikro-yapısı ana karara karıştırılmaz.
- DL1-PRE giriş: duyurudan sonraki ilk 1h bar açılışı; çıkış: Binance spotta
  delist zamanından önceki son 1h kapanış; 12bp maliyet.
- DL1-POST giriş: delistten sonraki ilk işlem gören 5m bar açılışı; çıkışlar
  4h/24h/72h kapanış; short yönlü, gerçekleşen funding ve snapshot spreadi
  ayrı raporlanır. Funding yoksa sıfır yazılmaz.
- Birincil hipotez başına minimum 30 olgun, en az 20 farklı token gerekir.
  Ortalama/medyan net getiri `>0`, win rate `>=%52` ve gün-kümeli bootstrap
  `p<=0.05` olmadan güvenilir strateji ilan edilmez.

İlk kurulum geçmiş makaleleri topluca Telegram'a göndermez. Yalnız halen
gelecekte delist zamanı bulunan olaylar ve kurulumdan sonra yayımlanan yeni
olaylar bir kez bildirilir. Bildirimde PRE ve POST hipotezleri ayrı, doğrulanmamış
ve gölge olarak yazılır.
