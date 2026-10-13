# Stratejiler, kanıtlar ve aktarım sınırı

13 Ekim 2026. Kod varsayılanları özetlenmiştir; tablet `.env` değerleri okunmadı.
Hiçbir eski güven etiketi, HL'de işlem başarı olasılığı değildir.

| Kimlik | Mevcut mekanik | Araştırma durumu / HL kararı |
|---|---|---|
| S1 | 1h Wilder RSI14 ≤22,5; fiyat daha düşük dip, RSI daha yüksek dip; lookback60/gap5; LONG; 24h | Tarihsel Binance aday avantajı, fakat canlı rejim/kohort farkları var; HL-S1 ayrı deney |
| S1+S4 | S1 + önceki 24h içinde log-volume z≥3 | S4 tek başına emir stratejisi değil; HL-S1-CONFLUENCE ayrı kohort |
| S2 | USD-M funding ≤−%0,03; 2 ardışık ödeme/örnek; 72h | Düşük güven; LS/OI türev filtreleri kabul edilmedi. HL funding saatliği/ölçek farkı nedeniyle birebir port yok |
| S3 | 1h log1p(volume) z≥3; window168; close>open; 4h | İkinci holdout bakışı ve zayıf net avantaj; HL shadow-only |
| S5 / S6 | Dinamik, doğrulanmamış evrende sırasıyla S1+S4 / S1 | Kimi'nin VWAP/rejim S5/S6'sı değiller! `observe=true` ayrı kova; HL'de yeni isimler ver |
| G1 | Günlük ilk10 yükselen; kapalı24h ≥%5; 1h hacim/önceki24h medyan≥2; OI≥%2; global hesap LS<1; 4h; 24h cooldown | Train kapısı geçmedi; yüksek hedef dokunması net kâr değildir. HL'de LS kaynağı doğrulanamazsa UNKNOWN veya yeni ön-kayıtlı vekil, eski adı/başarısı taşınmaz |
| G2 | Sabit87 kontratta ilk10 düşen; 24h≤−%5; OI≥%1; LONG; kapanış+1h giriş, 24h ufuk; TP3/SL2 | Binance vekili; HL ALO dolumu doğrulanmış değil. HL-G2 yeni forward test |
| DL1 | Resmî tam-token delist duyurusu/öncesi ve sonrası | PRE tarihsel tutma reddedildi; POST dış borsa PIT/fill verisi eksik. Canlı port yok |
| P0…P5 / Q1 | Yükselen→hacim→OI→short çoğunluğu→funding katmanları; Q1 OI-düşüş squeeze vekili | Keşif kontrol/hipotezleri; ayrı bildirim veya güvenilir emir stratejisi sayılmaz |
| Donchian4h, carry, VWAP, EMA/RSI HTF, BB/KC, OB/FVG | Önceki öneriler veya ön-kayıtlı adaylar | Var olan uygulama/olumlu sonuç varsayılmasın; iki bacaklı carry küçük pilot kapsamı dışında |
| AMD/POC | Dar aralık, sweep, geri kapanış ve daha sonra kilitli POC geçişi | 15m/uzun geçmiş sonrası net avantaj yok; canlıya alınmadı |

Çekirdek S1/S2/S3 cooldown: 12/24/12h. Ana varsayılan 30 çekirdek +59
genişletilmiş coin; geniş59'da S1 ailesi, S2/S3 çekirdek30. Tarama 5dk olsa da
temel mum 1h; bu bir 5dk scalping edge'i değildir. HL evreninin kesişimi, fiyat
çarpanı ve sembolün ekonomik varlığı ayrıca doğrulanacak; USDT son ekini
silmek veya `1000PEPE`yi `PEPE` diye eşitlemek yeterli değil.

## Son kararları önce oku

1. `research/G1_FAILURE_DIAGNOSIS_2026-10-13.md`: son20 olayda OI/LS'nin
   fiyat saatinden bir saat geride olduğu doğrulandı. Eski10 ilk tam1m TP3/SL2
   4TP/6SL; yeni9 olgun 1TP/8SL; %0,40 maliyetle ortalamalar −%0,40/−%1,84.
   Bu küçük, sonuç-sonrası tanı; yeni OOS veya kapat/bekle modeli değil.
2. `research/G1_ALIGNMENT_FORWARD_PROTOCOL.md`: legacy/aligned, ortak gerçek
   alınma zamanı ve beş sabit giriş planı; 90gün/30tamolay/28olaygünü yalnız
   örnek hazırlığı. Sonuçlar henüz yok; canlı G1 değişmedi.
3. `research/HISTORICAL_GAINERS_AND_G1_RESULTS_2026-10-10.md`: 895 kontrat,
   15.887.385 1h mum, yaklaşık6yıl9ay. P0/P1 net40 bütün dönemlerde negatif.
   Exact-time G1 kapsamı %81,14; G1 net40 üç dönemde de negatif, yakın dönem
   CI sıfırı içeriyor. Son rapor önceki "metrics eksik" notlarını aşar fakat
   gerçek zaman yayın/erişilebilirlik ve HL aktarımı kanıtı değildir.
4. `research/S2_REVIEW_2026-10-12.md`: LS/OI/funding üç aday ret; top-position
   alanı 0/12; ön-kayıt hash izi ve PC yedek engelleri var. Oranı uydurma.
5. `research/G1_LIQUIDATION_REVIEW_2026-10-13.md`: gerçekleşmiş forceOrder
   arşivi **bekleyen likidasyon haritası değil**. 42,2gün, 143G1, bütünlük/90gün
   kapısı eksik; getiri testi yapılmadı. 1,66M tasfiye =1,66M bağımsız trade değil.
6. `research/ALL_EXECUTION_REVIEW_2026-10-02.md` ve
   `research/EXECUTION_SHADOW_PROTOCOL.md`: S1-extended TP6/SL3; S3 15m teyit ve
   trailing; G2 TP4/SL3 ve kısmi çıkış aday. Eski C daha önce görülmüş; ileri
   doğrulama değil. Canlı ayarları optimum diye değiştirme.
7. `research/G1_ENTRY_COMPARISON_2026-10-11.md`, `G1_LIVE_ENTRY_AUDIT_2026-10-03.md`,
   `G2_MINUTE_REVIEW_2026-10-02.md`, `G2_EXIT_SWEEP_2026-10-02.md`: ölçüm saati,
   kaçırılan giriş, hedef-stop sırası ve gerçek dolum ayrımları.
8. `research/REPORT.md`: tarihsel başlangıç eşikleri, rejimler, geniş evren ve
   başarısız scalping bulguları; sonraki raporlar ve yeni kohortlarla birlikte oku.

## Üç başarı tanımı birbirine karıştırılmayacak

- +%2/%3/%5/%10'a herhangi bir anda dokunma: stopsuz fiyat olayı.
- Stop öncesi TP, kötü gap/same-bar belirsizliği ve zaman çıkışı: emir senaryosu.
- Gerçek fill + ücret + funding + slippage + miktar + bakiye: gerçek hesap PnL.

Hedefe dokunma oranı, seçilmiş son5 başarı veya bootstrap ölçüsü bir sonraki
işlemin kâr olasılığı değildir. %2 **fiyat** hedefi ve kaldıraçlı ROI farklıdır.
Ask en iyi satış kotasyonudur; dolum/kuyruk/derinlik/kayma garantisi değil.
OI artışı yön göstermez; hesap LS oranı short notional çoğunluğu göstermez.
Koşul kaybı ve rejim uyarısı doğrulanmış çıkış stratejisi değildir.

## Verilerin sınıflandırılması

`source=BINANCE`, market, universe, config/rule hash, ölçüm sürümü, kayıt/alınma/
bar/giriş/teslim zamanları korunur. Yeni HL olayları ayrı market ve sürümle
başlar. Geçmişten doldurulan veri forward sayılmaz. Eksik/stale alan UNKNOWN;
pending/NO_ENTRY/rejected/UNAVAILABLE kayıp değildir. Tüm karşılaştırmalarda
gün/hafta bağımlılığı, yoğunlaşma, 95% aralık, MAE/MFE ve maliyet kapsamı gerekir.
