# G1 güç puanı — ileri test ön kaydı (26 Kasım 2026)

Sürüm: `g1-strength-v1`. Bu belge ve `g1_strength.py` formülü, puanlı hiçbir olayın
sonucu görülmeden donduruldu. Kural, eşik veya formül ileri veri toplanırken
değişmez; değişiklik gerekirse yeni sürüm ve yeni ileri dönem açılır.

## Soru

G1'in dört koşulunu eşiklerin ne kadar üstünde sağlayan olaylar ("güçlü" G1),
aynı stop/hedef/süre planında, zayıf olanlardan daha iyi sonuç veriyor mu?

## Neden tarihsel test değil

Puanın girdilerine yakın özellikler (24s getiri, sıra, hacim oranı) 8 Kasım hedef
filtresi testinde arşivin keşif **ve** ayrılmış döneminde kullanıldı; kötü kovaları
atlayan `skip` politikası pozitif çıkmadı. O raporun kuralı gereği aynı veride
yeniden tarama yapılmaz. Karar yalnız bu ön kayıttan sonra gelen olaylarla verilir.

## Puan (sabit, sonuca göre ayarlanmadı)

Her bileşen 0..1, eşit ağırlık, toplam `25 × Σ` → 0..100:

| Bileşen | 0 | 1 | Ölçek |
|---|---|---|---|
| 24s yükselen sırası | 10. (0,1) | 1. | doğrusal `(11 − sıra) / 10` |
| 1s hacim / önceki 24s medyan | 2x (G1 eşiği) | ≥ 8x | log |
| 1s OI değişimi | %2 (G1 eşiği) | ≥ %8 | log |
| Global short hesap payı | %50 | ≥ %65 | doğrusal |

Tavanlar (4× eşik, %65) önceden seçilen yuvarlak değerlerdir. Alan eksikse puan
`None` olur ve olay bu testte sayılmaz. ATR ve 24s zirveye uzaklık daha önce
sınandığı için bilerek dışarıda.

Dağılım kontrolü (sonuç alanları okunmadan): panodaki 118 canlı G1 olayında puan
14,6–95,0, medyan 57,5. Hacim bileşeni olayların %56'sında tavanda (8x+); formül bu
gözlemden sonra değiştirilmedi.

## Kohort ve ölçüm

- Bu sürüm tablette çalışmaya başladıktan sonra teslim edilen, `g1_strength.version
  = g1-strength-v1` taşıyan ve `g1-exit-shadow-v1` ölçümü tamam (`complete=true`)
  olan G1 olayları. Eski olaylar geri doldurulmaz.
- Plan: mevcut çıkış gölgesinin `tp2` planı — teslimden sonraki ilk tam 1dk
  açılışından giriş, stop `1,5 × ATR14(1s)`, hedef +%2, 4 saat sınırı, aynı mumda
  stop önce.
- Birincil ölçü: `R = (brüt% − 0,20) / stop%` (20 bp maliyet).
- İkincil (tanımlayıcı): +%2 hedefin stoptan önce gelme oranı (`TP` durumu).

## Gruplar ve karar

- Olaylar puana göre üçe bölünür (kesimler yalnız puan dağılımından, sonuçtan değil):
  alt, orta, üst üçte bir.
- **Hazırlık kapısı:** en az **150** tamamlanmış olay, **40** ayrı olay günü,
  **8** takvim haftası ve her üçte birlik grupta en az **40** olay. Kapı geçilmeden
  rapor yalnız sayıları gösterir, grup sonuçlarını göstermez.
- **Fark var (DESTEKLENDİ-göreli):** üst − alt ortalama R farkının gün-blok
  bootstrap %95 aralığının tamamı sıfırın üstünde.
- **Kullanılabilir (DESTEKLENDİ-mutlak):** ayrıca üst grubun ortalama R'si > 0 ve
  gün-blok %95 aralığının alt sınırı > 0.
- Aksi halde: "fark gösterilemedi".

## Sınırlar ve davranış

- Puan Telegram G1 kartında `💪 Güç: NN/100 · test ediliyor, filtre değil` olarak
  görünür. G1 koşulu, bildirim kapısı, hedef ve emir davranışı değişmez.
- Kullanıcının bu puana göre işlem seçmesi ölçümü etkilemez: ölçüm fiyat yolundan,
  her teslim edilen olay için yapılır.
- Funding, kayma ve dolum modellenmez. Sonuç olumlu olsa bile canlı filtre otomatik
  açılmaz; karar kullanıcıya sunulur.

## Rapor

`python research/review_g1_strength.py` (tablet durum dosyası) veya
`--data-json <data.json>` (pano, son 400 olay). Ağ, Telegram, emir yok.
