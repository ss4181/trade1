# R1 — Cross-sectional relative-strength/momentum ön kaydı

Tarih: 2026-08-06. Kurallar ilk sonuç çalıştırılmadan önce sabitlenmiştir.
Aynı dokunulmamış test döneminde sonuç gördükten sonra ayar yapılmayacaktır.

## Hipotez ve veri

- Spot 1h, 89 sembol, 2024-07-01–2026-06-30.
- Her 72 saatte bir yeniden dengeleme; periyotlar çakışmaz.
- Skor: son 24 saat dışarıda bırakılarak önceki 30 günlük fiyat getirisi.
  Rebalance açılışı `t` için son kullanılan kapanış `t-25h`, başlangıç kapanışı
  `t-745h`; dolayısıyla sinyalde gelecek veri yoktur.
- Evren içindeki pozitif skorlu en yüksek `%20` seçilir.
- Train `<2026-01-01`; train periyodu test fiyatına taşıyorsa purge edilir.
  Test yalnız çekirdek ve genişletilmiş train kapıları geçerse hesaplanır.

## Portföy ve dolum

- LONG/CASH; short ve kaldıraç yok.
- Giriş/çıkış: rebalance anındaki 1h mum açılışı; tutma 72 saat.
- Ağırlıklar, skor hesaplama anına kadar bilinen 30 günlük saatlik
  volatilitenin tersiyle belirlenir. Tek sembol ağırlığı `%25` ile sınırlıdır;
  dört adetten az uygun sembol varsa kalan sermaye nakitte kalır.
- Her 72 saatlik kol için seçilen notional üzerinde 12bp round-trip maliyet.
  Önceki dönemde aynı coin seçilse bile tam maliyet yazılır; bu muhafazakârdır.
- Benchmark: aynı rebalance anında veri bulunan tüm evrenin eşit-ağırlıklı
  72h brüt getirisi. `alpha = strateji net getirisi - benchmark brüt getirisi`.
- Sabit bugünkü evren nedeniyle survivorship riski ayrıca raporlanır.

## Kabul kapıları

Portföy periyotları sembol olayları yerine bağımsız değerlendirme birimidir:

1. Çekirdek-30 train: `N>=100`, net ortalama `>0`, alpha ortalama `>0`, net
   PF `>=1.10`, alpha işaret-çevirme `p<=0.05`, q10 `>-%10` ve maksimum
   bileşik drawdown `>-%35`.
2. Genişletilmiş-59 train: `N>=100`, net ortalama ve alpha ortalama `>0`, net
   PF `>=1.05`.
3. Yalnız iki train kapısı geçerse tüm-89 test açılır: `N>=30`, net ortalama
   ve alpha ortalama `>0`, PF `>=1.05`, alpha `p<=0.05`, q10 `>-%10`, maksimum
   drawdown `>-%35`; çekirdek ve genişletilmiş test alpha ortalamalarının
   ikisi de negatif olamaz.

Bu bir sepet rotasyon stratejisidir; tek coin için bağımsız “kesin al” sinyali
olarak yorumlanmayacaktır.
