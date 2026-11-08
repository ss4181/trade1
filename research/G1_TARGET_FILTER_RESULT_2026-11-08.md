# G1 hedef filtresi — sonuç (8 Kasım 2026)

**Karar: DESTEKLENMEDİ.** Ön kayıt: [PREREG_G1_TARGET_FILTER_2026-11-08.md](PREREG_G1_TARGET_FILTER_2026-11-08.md)
(SHA-256 `2a831f4a…11c8b`). Canlı G1, kart, bildirim ve emir davranışı değişmedi.

## Ne test edildi

Girişte bilinen beş özellikten biri (`return_24h`, `rank`, `volume_ratio`,
`last_hour_return`, `dist_24h_high`) olayın hedefini seçmeye yarıyor mu? Hedefler
+%2/+%3/+%5/+%10/hedefsiz; stop 1,5×ATR, 4 saat sınırı, 20 bp maliyet.

| Dönem | Olay | Kullanım |
|---|---:|---|
| Keşif, 2020-01 → 2025-06 | 4.397 | Seçim |
| Ayrılmış, 2025-07 → 2026-08-30 | 2.289 | Tek seferlik karar (saatlik, stop önce) |
| Canlı, 2026-08-31 → | 226 | 1 dakikalık yön kontrolü |

Eksik veri nedeniyle dışarıda kalan olay yok.

## Keşif

Sabit hedeflerin hepsi birbirine yakın ve negatif (ortalama R): +%2 −0,055 · +%3 −0,050 ·
+%5 −0,053 · +%10 −0,045 · hedefsiz −0,040. Mekanik seçim `dist_24h_high` özelliğini
verdi: 24 saatlik zirveden %3,32'den uzak → +%2; arada → hedefsiz; %1,5'ten yakın → +%10.

## Sonuç (ortalama R, haftalık blok %95 aralık)

| | Filtre | Kart +%2 | En iyi sabit (hedefsiz) | Filtre − kart | Filtre − en iyi sabit |
|---|---:|---:|---:|---:|---:|
| Keşif | −0,026 | −0,055 | −0,040 | +0,029 [+0,009, +0,049] | +0,014 [−0,002, +0,029] |
| **Ayrılmış** | **−0,097** | −0,106 | −0,068 | +0,009 [−0,023, +0,040] | −0,029 [−0,070, +0,009] |
| Ayrılmış, iyimser sıra | −0,045 | −0,010 | −0,068 | −0,034 [−0,068, −0,002] | +0,023 [−0,021, +0,065] |
| Canlı, 1 dakikalık | −0,049 | −0,029 | −0,048 | −0,020 [−0,107, +0,067] | −0,001 [−0,102, +0,093] |

- Keşifteki iyileşme ayrılmış dönemde kayboldu; canlıda yön ters.
- Kötü kovalarda işlem yapmayan ikincil `skip` politikası da pozitif değil: ayrılmış
  −0,014R, canlı −0,021R.
- Saatlik veride aynı mumdaki sıra bilinmediği için kart hedefinin sonucu varsayıma
  çok bağlı (−0,106R / −0,010R). 1 dakikalık canlı ölçümde bu belirsizlik yok.

## Yorum

Hedef değiştirmek kazanma oranını ve kazanç/kayıp dağılımını değiştiriyor, ortalamayı
değil. Sınanan özelliklerin hiçbiri G1'de hedef seçimini güvenilir biçimde iyileştirmedi.
Bu aile için aynı verilerle yeniden tarama yapılmamalı; yeni bir aday, yeni ön kayıt ve
görülmemiş ileri veri gerektirir. `g1-exit-shadow-v1` ileri ölçümü ayrı olarak sürer.

## Sınırlar

Arşiv saatlik; dolum, kayma ve funding modellenmedi. OI ve long/short canlıda bir saat
gecikmeli olduğu için aday yapılmadı. ATR daha önce sınandığı için dışarıda bırakıldı.

Tekrar üretim:

```bash
python research/eval_g1_target_filter.py --live <trade1-data data.json anlık görüntüleri> --output research/data/g1-target-filter/report.json
```
