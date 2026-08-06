# D1 — 4h Donchian trend stratejisi ön kaydı

Tarih: 2026-08-06. Bu kurallar ilk sonuç çalıştırılmadan önce sabitlenmiştir.
Sonuç başarısız olursa aynı test diliminde eşik ayarı yapılmayacaktır.

## Hipotez ve veri

- Spot 1h verisi UTC sınırlarında eksiksiz 4h OHLCV mumlarına çevrilir.
- Evren: `manifest_spot89.json` sırasındaki çekirdek 30 ve genişletilmiş 59
  sembol. Dönem: 2024-07-01–2026-06-30.
- Train `< 2026-01-01`; test `>= 2026-01-01`. Göstergeler yalnız geçmiş
  mumları kullanır. Test sonuçları yalnız iki train kapısı da geçerse açılır.
- Tek konfigürasyon denenir; parametre taraması yoktur.

## İşlem kuralları

- Yön: yalnız LONG/FLAT; kaldıraç ve short yok.
- Giriş sinyali: 4h kapanış, önceki 20 tamamlanmış mumun en yüksek değerini
  aşar ve koşul bir önceki barda yanlışken bu barda doğru olur.
- Dolum: sinyal mumundan sonraki 4h mumun açılışı.
- ATR: nedensel Wilder ATR(20), yalnız 4h mumları.
- İlk/fiks stop: gerçekleşen girişten `2.0 × sinyal ATR` aşağıda. Mum stopu
  boşlukla aşarsa stop ile açılışın long için daha kötü olanı kullanılır.
- Normal çıkış: kapanış önceki 10 tamamlanmış mumun en düşüğünün altındaysa
  bir sonraki 4h mumun açılışı. Zaman aşımı yoktur.
- Aynı sembolde tek pozisyon; eksik 4h veri diziyi keser.
- Round-trip maliyet: 12 baz puan. Funding modellenmez çünkü spot stratejidir.
- Volatilite ölçeği: stop mesafesinde portföyün en çok `%1` kaybı hedeflenir:
  `weight = min(1, 0.01 / (2 × ATR / entry))`. Kaldıraç kullanılmaz.

## Önceden belirlenmiş kabul kapıları

Trend stratejisinin doğası gereği medyan ve isabetin %50 üzerinde olması şart
değildir; az sayıdaki büyük kazanan kayıpları karşılayabilir. Bu nedenle net
beklenti, profit factor, pozitif sağ kuyruk ve kümeli anlamlılık kullanılır.

1. Çekirdek-30 train: `N>=100`, net ortalama `>0`, PF `>=1.10`, volatilite
   ölçekli ortalama `>0`, `q90 > abs(q10)` ve giriş günü kümeli `p<=0.05`.
2. Genişletilmiş-59 train: `N>=100`, net ortalama `>0`, PF `>=1.05` ve
   volatilite ölçekli ortalama `>0`.
3. Yalnız 1 ve 2 geçerse tüm-89 test açılır. Test: `N>=50`, net ortalama `>0`,
   PF `>=1.05`, ölçekli ortalama `>0`, kümeli `p<=0.05`; ayrıca çekirdek ve
   genişletilmiş test ortalamalarının ikisi de negatif olamaz.

Bu kapılar geçilse bile canlı entegrasyondan önce sonuçlar maliyet, kuyruk,
sembol yoğunlaşması ve uygulanabilirlik açısından ayrıca incelenir.
