# S2 OI/Pozisyon ve Funding–LS Uyumsuzluğu (S2-DERIV-v2)

Tarih: 2026-09-03
Karar: **RED — canlı S2 değiştirilmedi; dokunulmamış test açılmadı.**

## Denenen iki aday

Mevcut S2 olayı (`funding <= −%0.03`, iki settlement, 24h cooldown) aynen
korundu. Sonuç görülmeden önce iki aday
[`PREREG_S2_DERIVATIVES_V2.md`](PREREG_S2_DERIVATIVES_V2.md) içinde donduruldu:

1. **OI_SHORT_BUILD:** Son 8 saatte OI artıyor ve büyük yatırımcıların pozisyon
   long/short oranı 1'in altında.
2. **FUNDING_LS_DIVERGENCE:** Funding önceki settlement'a göre daha negatife
   giderken global hesap long/short oranı son 8 saatte yükseliyor.

Özellikler yalnız olaydan önceki tamamlanmış 5m metrics satırlarından üretildi.
Giriş sonraki saat USD-M perp açılışı, çıkış 72h kapanışı ve maliyet 12bp'dir.
İki aday olduğu için train anlamlılık sınırı Bonferroni ile p<=0.025 olarak
donduruldu.

## Train sonuçları (2024-07–2025-12)

| Aday | N | Gün | Sembol | Tutulan | Net ort. | Net medyan | İsabet | Uplift | p(day) | Top-5 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| OI_SHORT_BUILD | 62 | 57 | 9 | %28,4 | +%2,644 | +%1,878 | %61,3 | **+0,860 puan** | 0,2563 | %85,5 |
| FUNDING_LS_DIVERGENCE | 55 | 51 | 11 | %25,2 | +%1,491 | +%0,113 | %50,9 | **−0,719 puan** | 0,6881 | %74,5 |

OI adayının ilk beş kaynağı: SEI 19, TIA 14, TRX 11, XLM 5, ATOM 4 olay.
Funding–LS adayının ilk beşi: SEI 13, TIA 12, BCH 6, TRX 6, APT 4 olay.

## Karar

**OI_SHORT_BUILD umut verici ama güvenilir değil.** Ortalama, medyan ve isabet
iyi görünmesine rağmen karşı gruba üstünlük günler arasında tutarlı değil
(p=0,2563) ve sonuç birkaç coine aşırı yoğun. Train kapısı bu iki nedenle
geçilmedi.

**FUNDING_LS_DIVERGENCE reddedildi.** İsabet %52 altında; ortalama ve medyan
karşı gruptan daha kötü; p=0,6881. “Funding daha negatife giderken hesap oranı
yükseliyor” tanımı S2'yi güçlendirmedi.

Sonuç olarak canlı S2 eşiği, persistence, cooldown, güven etiketi ve Telegram
bildirimleri değiştirilmedi. OI adayı yalnız ileri-dönem araştırma adayı olarak
kalabilir. Aynı tarihsel train üzerinde eşik taramak (`OI +%1`, oran 0,8 vb.)
bu sonucu aşırı uyuma dönüştüreceği için yapılmadı.
