# Hisse senedi araştırması — ÖN KAYIT (sonuçlara bakmadan yazıldı)

Tarih: 2026-07-27. Amaç: kripto botunun stratejilerinin ABD (NYSE/NASDAQ) ve
Çin (Şanghay/Shenzhen + Hong Kong) hisse piyasalarında geçerli olup olmadığını
**aynı disiplinle** ölçmek. Kripto eşikleri (RSI 22.5 / log-z 3.0 / funding
−0.03%) buraya TAŞINMAZ — sıfırdan aranacak.

## Veri
- Kaynak: yfinance (ücretsiz), **günlük** OHLCV, `auto_adjust=True`
  (split ve temettü düzeltmeli — düzeltmesiz veri sahte sinyal üretir).
- Dönem: 2015-01-01 → 2026-06-30 (~11.5 yıl; birden çok rejim: 2015 Çin
  çöküşü, 2018 düzeltmesi, 2020 COVID, 2021 balonu, 2022 ayısı, 2023-26).
- Piyasalar: **US** (NYSE/NASDAQ), **CN-A** (.SS/.SZ), **HK** (.HK).

## Ayrım (tek atış kuralı)
- Train: 2015-01-01 → 2022-12-31
- Test:  2023-01-01 → 2026-06-30
- Eşik araması YALNIZ train'de. Aile başına **tek** test atışı.

## Önceden kayıtlı aday aileler
- **E1 — S1 analoğu:** RSI(14) ≤ OS **ve** fiyat son 60 günün dibinin altında
  **ve** RSI o dipten yüksek (bullish divergence). OS ∈ {20, 25, 30}.
- **E2 — sade oversold:** RSI(14) ≤ OS (divergence şartı yok). OS ∈ {20, 25, 30}.
- **E3 — S3 analoğu:** log-hacim z(60g) ≥ Z **ve** yeşil gün. Z ∈ {2.0, 2.5, 3.0}.
- **E4 — gap-down dönüşü (hisseye özgü, kriptoda karşılığı yok):** açılış
  önceki kapanışın ≥ %G altında **ve** gün yeşil kapanış. G ∈ {3, 5}.
- S2 (funding) **yok**: hisse senedinde funding oranı diye bir şey yoktur.

## Ufuklar
1, 3, 5, 10 işlem günü. Birincil: E1/E2 → 5 gün, E3/E4 → 3 gün.
Giriş: sinyal gününden **sonraki** günün açılışı (lookahead yok).
Çıkış: ufuk sonundaki kapanış (zaman çıkışı — kriptoda doğrulanan tek kural).

## Metrik (kripto çalışmasıyla aynı)
- Volatilite-normalize getiri (60g gerçekleşen vol × √ufuk).
- Edge = koşullu − sembol-eşleşmeli koşulsuz ortalama.
- Anlamlılık: sembol-eşleşmeli bootstrap **ve** gün-kümesi bootstrap.
  Gün-kümesi hisse senedinde ŞART: piyasa betası nedeniyle aynı gün tüm
  hisseler birlikte hareket eder, olay-düzeyi p bağımsızlığı abartır.
- Kazananlara ek sağlamlık: **endekse göre fazla getiri** (US: SPY, CN-A:
  000300.SS, HK: ^HSI) — "sadece piyasa betası mı?" kontrolü.

## Karar kuralı (önceden sabit)
Train'de: N ≥ 300 **ve** bootstrap p ≤ 0.05 **ve** gün-kümesi p ≤ 0.10
**ve** edge > 0 → aile başına tek test atışı. Test'te aynı yönde ve
istatistiksel olarak ayakta kalırsa "aday"; aksi halde RED.

## Maliyet varsayımı (net olarak raporlanacak)
- US: ~5bp gidiş-dönüş (komisyonsuz broker + spread).
- CN-A: ~15bp (satışta %0.05 damga vergisi + komisyon + spread).
- HK: ~20bp (damga vergisi dahil).

## Piyasa-özgü kısıtlar (rapora yazılacak, stratejiyi etkiler)
- **CN-A T+1:** aynı gün alınan satılamaz → ufuk ≥ 1 gün olduğu için
  tasarımımız uyumlu, ama 1 günlük ufuk pratikte sınırda.
- **CN-A ±%10 limit** (STAR/ChiNext ±%20): limit-up günü fiilen alınamaz →
  kazananlarda "girişte limit-up muydu?" kontrolü yapılacak.
- **ABD PDT:** <25.000$ hesapta haftada 3 gün-içi işlem sınırı; ufuklarımız
  ≥1 gün olduğu için gün-içi sayılmaz.
- **Survivorship:** evren bugünkü likit/endeks üyelerinden kuruluyor →
  yukarı yanlı. Rapora şerh düşülecek (kriptodaki gibi).
