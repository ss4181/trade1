# Boğa rejimlerinde süre sınırı olmadan TP2 / TP3 — 22 Eylül 2026

**Ölçü:** Olay başına zaman limiti ve stop yok. Mevcut fiyat arşivinin sonuna kadar +%2 veya +%3 en az bir kere görüldüyse başarılı. Henüz görülmeyen hedef **bekliyor**; başarısız sayılmıyor. Oranın paydası bekleyenler dahil bütün olaylar. Geleceğin tamamı gözlenmiş değildir.

Önceki raporun aynı 2.814 olay kimliği kullanıldı; yeni strateji/eşik seçilmedi. Sinyalin oluştuğu gündeki boğa alt türü sabittir, sonraki rejimler hedef takibini durdurmaz. Giriş önceki hesapla aynıdır: S1/S1+S4/S3 spot sonraki saat açılışı; S2/G1 vadeli sonraki saat açılışı; G2 sinyalden 60 dakika sonraki vadeli açılış.

**Veri sınırı:** S1/S1+S4/S2/S3 ve G1 için 01.07.2026 03:00 TRT (30 Haziran son kapanışı); G2 için 13.09.2026 03:00 TRT. G1 sinyalleri Temmuz 2024–Aralık 2025 tarihsel sabit89 vekilidir; bu istek doğrultusunda takip 2026 verisine de uzatıldı. Eski TRAIN sınırı bir çıkış olarak kullanılmadı. Bu ileri veri artık bu analizde görülmüştür; yeni OOS iddiası yok. Güncel tablet G1 bildirimi değildir.

## Boğa alt türlerine göre

Her hedef hücresi: **dokunma yüzdesi (başarılı / toplam; bekliyor)**. Geri çekilme BTC 30g getirisi <0, ılımlı %0–10 dahil, güçlü >%10; günlük boğa tanımı değişmedi.

| Strateji / evren | Boğa alt türü | Olay / gün | TP2 | TP3 | TP2 / TP3 medyan süre |
|---|---|---:|---:|---:|---:|
| G1 vekili / fixed89_proxy | Geri çekilme | 53 / 44 | %92.5 (49/53; 4 bekliyor) | %92.5 (49/53; 4 bekliyor) | 4.0 / 9.0 saat |
| G1 vekili / fixed89_proxy | Ilımlı | 80 / 56 | %97.5 (78/80; 2 bekliyor) | %93.8 (75/80; 5 bekliyor) | 3.0 / 8.0 saat |
| G1 vekili / fixed89_proxy | Güçlü | 61 / 42 | %100.0 (61/61; 0 bekliyor) | %100.0 (61/61; 0 bekliyor) | 2.0 / 2.0 saat |
| G2 / fixed87 | Güçlü | 24 / 7 | %79.2 (19/24; 5 bekliyor) | %66.7 (16/24; 8 bekliyor) | 8.5 / 12.3 saat |
| S1 / core30 | Geri çekilme | 22 / 10 | %100.0 (22/22; 0 bekliyor) | %100.0 (22/22; 0 bekliyor) | 4.5 / 12.0 saat |
| S1 / core30 | Ilımlı | 31 / 6 | %100.0 (31/31; 0 bekliyor) | %100.0 (31/31; 0 bekliyor) | 7.0 / 10.0 saat |
| S1 / core30 | Güçlü | 6 / 4 | %100.0 (6/6; 0 bekliyor) | %100.0 (6/6; 0 bekliyor) | 5.5 / 17.0 saat |
| S1 / extended59 | Geri çekilme | 48 / 13 | %100.0 (48/48; 0 bekliyor) | %97.9 (47/48; 1 bekliyor) | 3.0 / 8.0 saat |
| S1 / extended59 | Ilımlı | 67 / 13 | %100.0 (67/67; 0 bekliyor) | %98.5 (66/67; 1 bekliyor) | 4.0 / 5.5 saat |
| S1 / extended59 | Güçlü | 15 / 6 | %100.0 (15/15; 0 bekliyor) | %100.0 (15/15; 0 bekliyor) | 4.0 / 9.0 saat |
| S1+S4 / core30 | Geri çekilme | 29 / 5 | %100.0 (29/29; 0 bekliyor) | %100.0 (29/29; 0 bekliyor) | 6.0 / 14.0 saat |
| S1+S4 / core30 | Ilımlı | 10 / 5 | %90.0 (9/10; 1 bekliyor) | %90.0 (9/10; 1 bekliyor) | 3.0 / 4.0 saat |
| S1+S4 / core30 | Güçlü | 2 / 1 | %100.0 (2/2; 0 bekliyor) | %100.0 (2/2; 0 bekliyor) | 9.5 / 11.0 saat |
| S1+S4 / extended59 | Geri çekilme | 76 / 8 | %92.1 (70/76; 6 bekliyor) | %90.8 (69/76; 7 bekliyor) | 11.0 / 16.0 saat |
| S1+S4 / extended59 | Ilımlı | 25 / 9 | %96.0 (24/25; 1 bekliyor) | %96.0 (24/25; 1 bekliyor) | 5.0 / 10.0 saat |
| S1+S4 / extended59 | Güçlü | 6 / 5 | %83.3 (5/6; 1 bekliyor) | %83.3 (5/6; 1 bekliyor) | 3.0 / 8.0 saat |
| S2 / core30 | Geri çekilme | 55 / 38 | %96.4 (53/55; 2 bekliyor) | %94.5 (52/55; 3 bekliyor) | 8.0 / 15.5 saat |
| S2 / core30 | Ilımlı | 27 / 24 | %100.0 (27/27; 0 bekliyor) | %92.6 (25/27; 2 bekliyor) | 20.0 / 24.0 saat |
| S2 / core30 | Güçlü | 21 / 19 | %100.0 (21/21; 0 bekliyor) | %100.0 (21/21; 0 bekliyor) | 14.0 / 51.0 saat |
| S3 / core30 | Geri çekilme | 151 / 44 | %97.4 (147/151; 4 bekliyor) | %96.0 (145/151; 6 bekliyor) | 2.0 / 4.0 saat |
| S3 / core30 | Ilımlı | 184 / 63 | %98.4 (181/184; 3 bekliyor) | %96.2 (177/184; 7 bekliyor) | 11.0 / 20.0 saat |
| S3 / core30 | Güçlü | 195 / 60 | %97.4 (190/195; 5 bekliyor) | %96.4 (188/195; 7 bekliyor) | 4.0 / 10.0 saat |

## G1 yorumu

- Güçlü boğadaki 61 olayın 61’i TP2 ve TP3 gördü: **%100 / %100**. TP2’de 21, TP3’te 25 olay eski 4 saatlik ufuktan sonra başarıya dönüştü.
- Bütün boğa alt türleri birlikte: TP2 **188/194 (%96,9)**, TP3 **185/194 (%95,4)**. Bekleyenler sırasıyla 6 ve 9.
- Bütün rejimler birlikte: TP2 **391/401 (%97,5)**, TP3 **387/401 (%96,5)**. Bekleyenler 10 ve 14.
- Bu tanım altında G1’in tarihsel hedef dokunması yüksektir. Son haftalardaki canlı G1 başarısını ölçmek için tabletin güncel kayıtları gerekir; yereldeki eski log bunu doğrulamaz.

## Yorumlama ve doğrulama

Süre limiti kalkınca S1 çekirdek boğa örneklerinin tamamı da her iki hedefe dokunuyor. Bu ölçü stratejileri ayırmakta sınırlı kalıyor: bekleme süresi ve hedef öncesindeki düşüş bu başarı oranında cezalandırılmıyor. Örnekte bazı TP3 dokunmaları 11.131 saat sonra geliyor. Medyan süre yalnız dokunan olaylar içindir; saatlik/5 dakikalık mum kapanışı, ilk dokunma zamanının üst sınırıdır. G1 ve çekirdek örnekler G2’den çok daha uzun izlenebildiğinden oranları eşit takip süresi varmış gibi karşılaştırmayın.

S5/S6 için tarihsel dinamik evren yok; sabit extended59 satırları bu kanalların testi değildir. DL1 yönlü bir işlem stratejisi değildir. G2 geri çekilme/ılımlı boğa örneği yoktur. Eksik hücreler sıfır başarı değildir.

**Önceki G2 hesabının düzeltmesi:** `search_outcomes` içindeki MFE ilk TP/SL çıkışında kesiliyordu. Önceki raporda bu alan yanlışlıkla stop olmadan 24 saatlik dokunma sayıldı. O kolonlar geri çekildi. Buradaki G2 oranları checksum ile doğrulanmış ham Binance 5dk fiyatlarından, stop sonrası mumlar dahil yeniden hesaplandı. TP3/SL2 sırası ölçüsü ayrıca geçerlidir; bu rapor onu değiştirmez.

Olay, fiyat sözleşmesi ve giriş fiyatı eşleşmesi kontrol edildi. 2.814 olayda eksik ölçüm yok. Geçersiz giriş, fiyat boşluğu, dönem sonu, sonradan dokunma ve bekleyenlerin paydada kalması regresyon testleriyle doğrulandı. Sinyal seçimi, canlı karne/Telegramdaki mevcut süre ölçüsü bu araştırma isteğiyle değiştirilmedi.

## Yeniden üretim

```powershell
python research/regime_eventual_touch.py --events research/data/regime-touch-review-2026-09-22/events.jsonl --data '<saatlik spot/um arşivi>' --search research/data/coinalyze/search-2026-09-14 --g2-prices research/data/coinalyze/study-2026-09-13 --output research/data/regime-eventual-review-2026-09-22
```

Kaynak arşivler yerel araştırma girdileridir; git pull ham fiyatları indirmez. Kod: `research/regime_eventual_touch.py`; özet ve hash kayıtları: `research/results/regime_eventual_touch_2026-09-22.json`.
