# C1 — Delta-nötr spot/perp carry ön kaydı

Tarih: 2026-08-06. Kurallar ilk sonuç çalıştırılmadan önce sabitlenmiştir.
Aynı dokunulmamış test döneminde sonuç gördükten sonra parametre ayarlanmaz.

## Veri ve nedensellik

- Spot long + aynı baz varlık miktarında USD-M perpetual short.
- Spot ve perp 1h açılış/yüksek/düşük/kapanışları resmî Binance toplu
  arşivinden; settled funding geçmişi resmî Binance API önbelleğinden.
- 1000/1000000 kontrat fiyatları bir spot baz varlık birimine çevrilir.
- Funding olayı `t` anında gözlenir; giriş en erken `t+1h` açılışında yapılır.
  Giriş ve çıkışla aynı zamana denk gelen funding iyimser biçimde yazılmaz.
- Train `< 2026-01-01`; test `>= 2026-01-01`. Test yalnız iki train evreni
  kapısını da geçerse hesaplanır.

## Sabit kurallar

- Son 72 saatte gerçekleşmiş funding toplamının yıllıklandırılmış oranı
  `>= %15` ve son 3 settlement oranının her biri pozitif olmalı.
- Sinyal anındaki perp/spot açılış basis'i `>= %0.05` olmalı.
- Giriş: sonraki 1h açılışında spot long + eşit baz miktarında perp short.
- Kaldıraç varsayılmaz: short bacağı için perp notional kadar ayrı marjin;
  başlangıç sermayesi `spot notional + perp notional` kabul edilir.
- Çıkış sinyali: saatlik kapanış basis'i `<=0`, basis `>=%2`, 72h funding APR
  `<%5` veya son iki funding oranı `<=0`. Dolum sonraki saat açılışıdır.
- Azami tutma 30 gün. Perp aynı saat içinde girişin `1.8×` fiyatına ulaşırsa
  ayrı marjin stresi kabul edilir ve iki bacak muhafazakâr fiyatlarla kapanır.
- Funding PnL, pozisyon açıkken gerçekleşen settlement oranı × o andaki
  düzeltilmiş perp fiyatıdır. Sıfır veya ileriye dönük oran uydurulmaz.
- Her dört dolum için taker+slippage toplamı `7bp/fill`; maliyet gerçekleşen
  bacak notional'larından hesaplanır. Exchange/default riski sayısallaştırılmaz
  ve sonuçta ayrıca belirtilir.

## Kabul kapıları

Carry stratejisinden yönlü trend stratejisine göre daha dar kuyruk ve daha
istikrarlı isabet beklenir:

1. Çekirdek-30 train: `N>=100`, net ortalama ve medyan `>0`, isabet `>=%55`,
   PF `>=1.25`, q10 `>-%1`, giriş-günü kümeli `p<=0.05`, marjin-stres oranı
   `<=%1`.
2. Genişletilmiş-59 train: `N>=100`, net ortalama/medyan `>0`, PF `>=1.10`,
   q10 `>-%1`.
3. Yalnız iki train kapısı geçerse tüm-89 test açılır: `N>=50`, net
   ortalama/medyan `>0`, PF `>=1.10`, q10 `>-%1`, kümeli `p<=0.05`; çekirdek
   ve genişletilmiş test ortalamalarının ikisi de negatif olamaz.

Backtest başarılı olsa bile exchange iflası, transfer gecikmesi, marjin
ayrışması, ADL ve gerçek hesap ücretleri ayrıca operasyonel kabul gerektirir.
