# S2 Türev Veri Doğrulamaları — Ön Kayıt (S2-DERIV-v2)

Tarih: 2026-09-02
Durum: Aday sonuçlarına bakılmadan dondurulmuştur.

## Amaç

Mevcut S2 olaylarını değiştirmeden iki ek türev-veri hipotezini sınamak:

1. **OI_SHORT_BUILD:** Son 8 saatte toplam open interest artmış ve en yüksek
   marjin bakiyeli yatırımcıların pozisyon long/short oranı `1.0` altında.
   Bu, yeni pozisyon eklenirken büyük pozisyonların short ağırlıklı olduğu bir
   short-birikimi vekilidir.
2. **FUNDING_LS_DIVERGENCE:** İkinci derin-negatif settlement'ta funding önceki
   settlement'a göre daha da negatife gitmiş (`funding_delta < 0`), buna karşın
   global hesap long/short oranı son 8 saatte yükselmiş (`ls_change_8h > 0`).
   Hesap yönü ile funding baskısının ayrıştığı bir uyumsuzluk vekilidir.

Başka eşik veya kombinasyon bu çalışmada aranmayacaktır.

## Sabit veri ve zamanlama

- Evren: canlı S2'nin çalıştığı sabit çekirdek 30 sembol.
- Dönem: 2024-07-01–2026-06-30.
- Train: 2024-07-01–2025-12-31; dokunulmamış test: 2026-01-01–2026-06-30.
- S2: funding `<= -0.03%`, persistence=2, cooldown=24h; aynen korunur.
- Metrics: resmî Binance USD-M daily metrics.
- Global hesap oranı: `count_long_short_ratio`.
- Büyük yatırımcı pozisyon oranı: `sum_toptrader_long_short_ratio`.
- OI: `sum_open_interest`.
- Olay özelliği: olaydan kesinlikle önceki son 5m satır; azami yaş 15 dakika.
- 8h özellik: olayın 8 saat öncesinden kesinlikle önceki son 5m satır; azami
  yaş 15 dakika. Sonraki satır kullanılmaz.
- Giriş: olaydan sonraki 1h USD-M perp mum açılışı.
- Çıkış: girişten 72 saat sonraki kapanış.
- Net getiri: log getiri eksi 12 bp round-trip maliyet.

## Train seçimi ve çoklu-deneme koruması

Her aday kendi gerekli alanları tam olan S2 olaylarında, koşulu sağlamayan
karşı grupla karşılaştırılır. İki aday denendiği için ham gün-kümeli tek taraflı
p-değeri Bonferroni sınırı `0.05 / 2 = 0.025` değerini geçmemelidir.

Bir adayın train kapısı:

1. Gerekli özellik kapsamı >=%90.
2. Filtreli N>=30, bağımsız UTC günü>=25, sembol>=8.
3. Filtreli net ortalama ve medyan >0, isabet >=%52.
4. Filtreli eksi karşı grup ortalama farkı >=+0.50 yüzde puan; medyan farkı >0.
5. Gün-kümeli bootstrap p<=0.025.
6. Top-5 sembol payı <=%70.
7. Filtre, eşleşen olayların en az %10'unu ve en çok %80'ini tutmalı.

Yalnız bir aday geçerse o seçilir. İkisi de geçerse daha küçük p-değerli aday;
eşitlikte daha yüksek ortalama uplift seçilir. Hiçbiri geçmezse test açılmaz.

## Dokunulmamış test kapısı

Testte yalnız train'de seçilmiş aday hesaplanır:

1. Kapsam >=%90; N>=30, gün>=20, sembol>=8.
2. Net ortalama/medyan >0 ve isabet >=%52.
3. Ortalama ve medyan uplift >0; gün-kümeli p<=0.10.
4. Filtreli q10, karşı grubun q10 değerinden 1 yüzde puandan fazla kötü değil.
5. Top-5 sembol payı <=%70.

Tüm kapılar geçmeden `signal_bot.py`, canlı S2, güven etiketi ve Telegram
bildirimi değiştirilmez. `sum_toptrader_long_short_ratio` yalnız en yüksek
marjin bakiyeli yatırımcıların pozisyon oranıdır; piyasanın tam notional
long/short oranı olarak yorumlanmayacaktır.
