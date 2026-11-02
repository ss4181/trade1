# G1 yüksek oynaklık (ATR) hipotezi — tarihsel sonuç (3 Kasım 2026)

**Karar: DESTEKLENMEDİ.** Ön kayıt: [PREREG_G1_ATR_SPLIT_2026-11-03.md](PREREG_G1_ATR_SPLIT_2026-11-03.md)
(SHA-256 `9a8739e5…ae89f`, commit `dd1e0dd0`, test çalıştırılmadan önce).
Canlı strateji, bildirim veya emir davranışı değişmedi.

## Ne test edildi

Canlı 205 G1 olayında (31 Ağu – 2 Kas 2026) ATR14(1s) ≥ %6 olan coinlerde kart
kuralı (TP +%2, 1,5×ATR stop, 4 saat) pozitif görünmüştü (%91 kazanma, +0,057R).
Aynı ayrım, o canlı dönem hariç tutularak 2020-01 → 2026-08-30 arşivindeki
**6.686 G1 olayında** sınandı. Eksik veri nedeniyle dışarıda kalan olay yok.
Saatlik mumda sıra bilinmediği için karar muhafazakâr sırayla (aynı mumda stop
önce) ve 20 bp maliyetle verildi.

## Sonuç (birincil: kart kuralı, muhafazakâr, 20 bp)

| Grup | Olay | Kazanma | Ortalama |
|---|---:|---:|---:|
| ATR ≥ %6 | 752 | %77 | **−0,081R** (haftalık %95 aralık −0,116 / −0,046) |
| ATR < %6 | 5.934 | %62 | −0,071R |

| Dönem | ATR ≥ %6 | ATR < %6 |
|---|---:|---:|
| 2020-01 → 2024-06 | +0,027R (n=98) | −0,054R |
| 2024-07 → 2026-06 | −0,097R (n=578) | −0,083R |
| 2026-07 → 2026-08 | −0,102R (n=76) | −0,115R |

- Göreli şart (her dönemde ATR ≥ %6 daha iyi) 2024-07 → 2026-06 döneminde
  sağlanmadı; mutlak şart (ATR ≥ %6 ortalaması > 0) hiçbir sürümde sağlanmadı.
- ATR çeyreklerinde sıralı bir iyileşme yok (−0,080 / −0,064 / −0,067 / −0,079R).
- **İyimser sınır** (aynı mumda hedef önce) bile ATR ≥ %6 için −0,005R
  (aralık −0,031 / +0,022): en iyi varsayımda sıfır civarı.
- 40 bp duyarlılığında göreli şart üç dönemde sağlandı (KISMİ), ama ortalama
  daha da negatif (−0,098R). TP3 ve hedefsiz 2×ATR planları da birleşik olarak
  negatif; hedefsiz planın tek pozitif hücresi 76 olaylık 2026-07/08 dilimi.

## Yorum

- Yüksek ATR'li coinler **daha sık** +%2'ye değiyor (%77'ye karşı %62) — bu
  canlı gözlemle tutarlı. Ama kazançlar küçük, stop kayıpları büyük; beklenen
  getiri iyileşmiyor. Yüksek isabet, kâr demek değil.
- Canlı 205 olaydaki pozitif sonuç büyük olasılıkla dönem/şans etkisiydi (o
  ayrım ~30 bölme denendikten sonra bulunmuştu).
- Bu, G1'in 4 saatlik tarihsel train sonucunu (RED) ve P0/P1 bulgularını
  değiştirmiyor: **G1'in kurala bağlı otomatik bir sürümü için bu verilerde
  pozitif beklenti yok.**

## Sınırlar

Saatlik çözünürlük 1 dakikalık canlı ölçümle aynı değil; dolum, kayma, spread
ve funding modellenmedi. İleri gölge (`g1-exit-shadow-v1`) ATR'yi kaydetmeye
devam eder; aynı ayrım orada tanımlayıcı olarak izlenir, karar için yeni ön
kayıt gerekir.

Tekrar üretim (yalnız yerel arşiv, ağ yok):

```bash
python research/eval_g1_atr_split.py --output research/data/g1-atr-split-2026-11-03/report.json
```
