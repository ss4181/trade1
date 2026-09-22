# Rejim araştırması — uygulama özeti

Bu sonuçlar bilgilendirici, betimleyici ve mevcut arşiv üzerinde geriye dönük hesaplamadır; yeni OOS veya gerçek emir kârı iddiası değildir. BTC spot günlük verisiyle tanım sabitlendi:

- BOĞA: kapanış > M200×1,02 ve M200 20 günlük eğimi pozitif.
- AYI: kapanış < M200×0,98 ve eğim negatif.
- GEÇİŞ: diğer yeterli ve güncel durumlar; veri eksik/bayat ise BELİRSİZ.
- Boğa alt türü: 30 günlük BTC getirisi <0 geri çekilme, %0–10 ılımlı, >%10 güçlü.

2.814 olay incelendi. Saatlik çekirdek motoru 15.904 pencereyle doğrulandı. Tam günlük BTC kapanışları arşivdeki 730 saatlik günle birebir eşleşti.

| Strateji / evren | Boğa | Geçiş | Ayı |
|---|---:|---:|---:|
| S1 / core30 / 24s | 59 olay · %69,5 · +%1,367 | 29 · %62,1 · -%0,100 | 75 · %56,0 · +%0,776 |
| S1+S4 / core30 / 24s | 41 · %53,7 · +%0,966 | 28 · %67,9 · +%4,915 | 68 · %61,8 · +%1,898 |
| S2 / core30 / 72s | 103 · %51,5 · +%1,215 | 87 · %57,5 · +%3,442 | 139 · %50,4 · -%0,181 |
| S3 / core30 / 4s | 530 · %55,7 · +%0,571 | 186 · %48,4 · -%0,021 | 287 · %44,6 · +%0,103 |
| S1 / extended59 / 24s | 130 · %61,5 · +%0,496 | 82 · %35,4 · -%2,659 | 107 · %57,9 · +%2,074 |
| S1+S4 / extended59 / 24s | 107 · %57,0 · +%0,745 | 32 · %75,0 · +%8,895 | 71 · %59,2 · +%1,604 |

Boğa alt türlerinde öne çıkan gözlem S3 / geri çekilme: 151 olay / 44 gün, pozitif %66,9, ortalama +%1,931. En yoğun beş günde 76 olay vardır; 7 günlük blok bootstrap %95 aralığı [-%0,054, +%3,197] ile sıfırı içerir. Bu nedenle hemen rejim filtresi açılmayacak.

G2 (`fade_long_l1_up_d60_e2`, %3 TP / %2 SL / 24s): toplam hedef-önce %40,9 (103/252); güçlü boğa örnekleri 24/7 günde %29,2 (7/24), ortalama -%0,733. Boğada otomatik iyileşme kanıtı yoktur.

G1 mevcut canlı sıralamayla eşdeğer olmayan TRAIN vekilidir (401 olay, boğa ortalama -%0,328). S5/S6 tarihsel dinamik evren üyeliği bulunmadığı için sabit extended sonuçlarına eşitlenmez.

Sonuç: düğme uygulanır; otomatik rejim kapısı/strateji susturma uygulanmaz. İleri dönemde olay snapshot'ları biriktirilir ve her stratejinin kendi ölçümüyle ayrı raporlanır.
