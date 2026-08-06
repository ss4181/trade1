# L1 — Pump + short crowding + gerçekleşmiş squeeze vekili ön kaydı

Tarih: 2026-08-06. Kurallar ilk sonuç çalıştırılmadan önce sabitlenmiştir.
Aynı test döneminde sonuç gördükten sonra eşik değiştirilmeyecektir.

## Veri sınırı

- USD-M için resmî `liquidationSnapshot` arşivi yoktur (aynı yol 404; COIN-M
  yolu vardır). Bu nedenle gelecekteki “likidasyon fiyat bölgeleri” üretilmez.
- Resmî USD-M günlük `metrics` arşivindeki 5m OI, genel hesap long/short oranı
  ve taker long/short hacim oranı kullanılır.
- Fiyat yükselirken OI düşüşü ve agresif alış baskısı, **gerçekleşmiş short
  kapanma/likidasyon baskısının vekili**dir; gerçek liquidation emri değildir.
- Fiyat: USD-M perp 1h; funding: settled resmî funding geçmişi. 1000-kontrat
  eşlemesi manifestten alınır.

## Sabit sinyal

Saatlik bar `t` kapandıktan sonra, yalnız o ana kadar bilinen verilerle LONG:

1. Perp kapanışı son 6 saatte en az `%5` yükselmiş (`pump6 >= 0.05`).
2. Genel hesap long/short oranı `<0.80` (hesap sayısında short kalabalığı).
3. Saat sonu open interest bir önceki saate göre `<=-%3`.
4. Saat içindeki 5m taker long/short hacim oranının medyanı `>1.20`.
5. Son settled funding oranı bir önceki settlement'a göre en az `+0.0001`
   (yani `+0.01` yüzde puan) değişmiş ve settlement en fazla 4 saat önce.
6. Koşul False→True geçişinde tetiklenir; sembol cooldown'u 24 saattir.

Giriş: sinyal barından sonraki 1h açılış. Birincil çıkış: girişten 4 saat
sonraki kapanış. 1h/12h/24h yalnız dağılım teşhisidir. Round-trip maliyet 12bp.

## Değerlendirme ve kapılar

- Taban: aynı `%5/6h` pump koşulunun tüm edge-trigger olayları.
- Çekirdek-30 train: `N>=50`, 4h net ortalama/medyan `>0`, net isabet
  `>=%55`, gün-kümeli `p<=0.05`, q10 `>-%5` ve aday ortalaması pump tabanından
  büyük olmalı.
- Genişletilmiş-59 train: `N>=100`, net ortalama/medyan `>0`, isabet `>=%52`
  ve aday ortalaması pump tabanından büyük olmalı.
- Yalnız iki train kapısı geçerse tüm-89 test açılır: `N>=30`, net
  ortalama/medyan `>0`, isabet `>=%52`, gün-kümeli `p<=0.05`, q10 `>-%5`,
  pump tabanından üstünlük ve çekirdek/geniş test ortalamalarının negatif
  olmaması gerekir.

Metrics yalnız pump görülen günler için indirilir; bu sonuç seçimi değildir,
çünkü pump zaten sinyalin birinci ve önceden kayıtlı koşuludur. Pump olmayan
günler aday sinyal üretemez.
