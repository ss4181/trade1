# ABD & Çin hisse senedi araştırması — SONUÇ: AKTARILAMIYOR

*2026-07-27. Tasarım önceden kayıtlıydı: [ONKAYIT.md](ONKAYIT.md). Kripto
eşikleri taşınmadı; her şey sıfırdan arandı.*

## TL;DR

Kripto botunun strateji aileleri (RSI dönüşü, hacim anomalisi) **ABD, Çin
A-hisseleri ve Hong Kong'da doğrulanamadı.** 336 sembol × 11.5 yıl günlük veri,
11 konfigürasyon × 3 piyasa. Bota eklenecek bir şey çıkmadı.

| Piyasa | Sembol | Train'i geçen | Test sonucu |
|---|---|---|---|
| **ABD** (S&P) | 233 | **hiçbiri** | test dilimine bakılmadı |
| **HK** | 48 | **hiçbiri** | test dilimine bakılmadı |
| **Çin A** | 55 | E2 (RSI≤30), E3 (hacim z≥3) | **ikisi de ÇÖKTÜ** |

## Sonuçlar

### ABD (233 sembol, maliyet 5bp)
Hiçbir aile önceden kayıtlı kuralı (N≥300, p≤0.05, gün-kümesi p≤0.10, edge>0)
geçemedi. En iyi görünümler: E2 30.0 edge +0.022 (p=0.114), E3 3.0 +0.020
(p=0.244) — yani sıfırdan ayırt edilemez.

**Metodolojik ders (önemli):** İlk koşuda evren yanlışlıkla 50 sembolde kalmıştı
(Wikipedia 403 → yedek liste). O dar evrende **E2 25.0 çok umut verici
görünüyordu: edge +0.207, p=0.002, N=296.** Evren 233 sembole çıkarılınca aynı
konfigürasyon **edge −0.021, p=0.830**'a döndü. Yani o "neredeyse geçiyordu"
sonucu tamamen küçük-örneklem gürültüsüymüş. Ön kayıttaki N≥300 eşiği tam da
bunu engellemek içindi ve işini yaptı.

### Hong Kong (48 sembol, maliyet 20bp)
Hiçbir aile geçemedi. E1 30.0 (edge +0.095, p=0.052) sınırdaydı ama gün-kümesi
testinde çöktü (p=0.297) — yani sinyaller piyasa-geneli düşüş günlerine
kümeleniyor, bağımsız bilgi taşımıyor. E3 ve E4 açıkça negatif (net medyan
−0.46%, −0.96%).

### Çin A-hisseleri (55 sembol, maliyet 15bp) — tek "geçen" ve tek çöküş
| | Train | Test (tek atış) |
|---|---|---|
| **E2** RSI≤30, 5g | N=900, edge +0.106, p=0.044, gün-p=0.084, net medyan **+0.80%**, isabet %59 | edge +0.025 (p=0.291), gün-p=0.955, net medyan **−0.33%**, isabet **%46** ❌ |
| **E3** hacim z≥3, 3g | N=358, edge +0.283, p=0.004, gün-p=0.018 | edge −0.023 (p=0.595), net medyan **−0.90%**, isabet **%40** ❌ |

E2'nin testte 1-3 günlük ufuklarında p<0.05 çıkması yanıltıcı: gün-kümesi
p'leri 0.59-0.79 (piyasa betası) **ve** maliyet sonrası net medyan negatif.
İstatistiksel kıpırtı ≠ para.

## Neden aktarılamadı (yorum)

1. **Kısa vadeli dönüş etkisi hisse senedinde fazlasıyla arbitrajlanmış.**
   Kurumsal istatistiksel-arbitraj masaları tam olarak bu kalıbı işliyor;
   kriptoda perakende ağırlığı yüksek olduğu için pay kalıyor.
2. **Piyasa betası.** Hisse sinyalleri piyasa-geneli düşüş günlerine kümeleniyor;
   gün-kümesi bootstrap bunu ayıklayınca geriye bir şey kalmıyor. (Kripto
   çalışmasında da aynı test S3'ün sahte anlamlılığını yakalamıştı.)
3. **Maliyet yapısı.** Çin'de satışta damga vergisi + komisyon (~15bp), HK'de
   ~20bp. Bazı ailelerde vol-normalize edge pozitifken **net medyan zaten
   sıfır/negatifti** — yani ölçülen kıpırtı maliyeti bile karşılamıyordu.

## Piyasa-özgü kısıtlar (uygulanabilirlik açısından, kayıt için)
- **Çin A: T+1** (aynı gün alınan satılamaz) ve **±%10 limit** — limit-up günü
  fiilen alınamaz; bir strateji doğrulansaydı bile bu kısıt uygulanabilirliği
  ayrıca sınırlardı. Ayrıca yabancı erişimi Stock Connect/HK üzerinden.
- **ABD: PDT** kuralı (<25.000$ hesapta haftada 3 gün-içi işlem) — ufuklarımız
  ≥1 gün olduğu için bağlayıcı değil.
- **Veri:** yfinance ücretsiz ve günlük için yeterli; gerçek-zamanlı/intraday
  hisse verisi kriptodaki gibi bedava değil (lisans gerekir) — bot mimarisi
  taşınabilir ama veri maliyeti ayrı bir konu.

## Şerhler
- **Survivorship:** evren bugünkü S&P 500 / büyük Çin-HK isimlerinden kuruldu →
  yukarı yanlı. Negatif sonucu güçlendirir (yanlılık lehimize çalışıyordu, yine
  de bir şey çıkmadı).
- **Sadece günlük bar** test edildi. Intraday hisse verisi ücretsiz olmadığı
  için 1h/15m denenmedi; kripto tarafında intraday zaten olumsuz çıkmıştı
  (Ek A/B).
- **A-hisselerinde işlem durdurma** sıfır-volatilite pencereleri yaratıp
  ilk koşuda `inf` üretmişti (tüm CN p-değerleri sahte çıkmıştı); düzeltildi
  ve sonuçlar yeniden alındı. Aynı hata sessizce geçseydi Çin'de "her şey
  anlamlı" gibi görünecekti.

## Karar
**Bota hisse senedi modülü EKLENMEDİ.** Mevcut kripto botu (S1/S1+S4 çekirdek)
tek doğrulanmış sistem olarak kalıyor. Bu dosya, aynı fikrin ileride yeniden
önerilmesi hâlinde başvurulacak kayıttır.

Yeniden üretim:
```bash
cd research_equity
python download_equity.py <veri_dizini>      # yfinance, ~340 sembol
python sweep_equity.py <veri_dizini> us      # cn / hk
```
