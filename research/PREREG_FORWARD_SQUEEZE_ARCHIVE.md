# L2 — Pump sonrası short birikimi / squeeze ileri-arşiv ön kaydı

**Kayıt tarihi:** 2026-08-06
**Durum:** Yalnız veri toplama. Canlı strateji, shadow sinyal veya bildirim
değildir. Mevcut S1/S2/S3/S5/S6 mantığını değiştirmez.

## Neden yeni veri dönemi gerekiyor?

L1 deneyi fiyat yükselişi + OI düşüşü + taker alış + funding'in yukarı dönmesini
birleştirdi. Bu, olası squeeze yakıtını değil, short kapanışlarının başlamış
olduğu geç bir aşamayı ölçüyor olabilir. Üstelik resmî geçmişte gerçek USD-M
`forceOrder` akışı yoktu; beş koşul birleşince train'de yalnız bir olay kaldı.

L2, eşikleri L1 testine bakarak gevşetmek yerine **yeni ve ileriye dönük bir
veri dönemi** toplar. Test dönemi yeterli örnek oluşana kadar açılmaz.

## Sabit veri kaynakları

1. Binance USD-M `!forceOrder@arr`: gerçekleşmiş likidasyon snapshot'ları.
   Sembol başına 1000 ms'deki yalnız son olayı yayımladığı için eksiksiz tape
   değildir. Bağlantı ve heartbeat satırları veri boşluklarını işaretler.
2. Binance public-data USD-M günlük `metrics`: 5m OI, global/top long-short ve
   taker buy/sell oranları. Olay tarihinden **sonra** indirilebilir fakat yalnız
   olay anından önce yayımlanan satırlar özelliktir.
3. Binance USD-M funding geçmişi ve 5m perpetual mumları.
4. CoinGlass liquidation heatmap bu veri setine dahil değildir. İleride lisanslı
   snapshot toplanırsa ayrı veri sürümü ve ayrı ön kayıt gerekir.

## Dondurulmuş evren ve zamanlama

- Birincil evren: `2026-07-ek-g` sabit 89 sembol; 1000x kontratlar mevcut
  `PERP_MAP` ile eşlenir. Akış tüm USD-M sembollerini arşivlese de ana sonuç bu
  sabit evrenden hesaplanır.
- Özellik zaman damgası: kapanmış 5m bar. Gelecek satır kullanılmaz.
- Giriş: koşul barından sonraki 5m bar açılışı.
- Birincil çıkış: girişten 4 saat sonraki kapanış.
- Tanısal ufuklar: 15m ve 1h; birincil karar bunlardan seçilmez.
- Maliyet: 12 bp round-trip; ayrıca 20 bp stres sonucu raporlanır.

## Önceden tanımlı hipotez ailesi

Ortak `pump_setup`:

- son 6 saat perpetual getiri `>= +%5`,
- global hesap long/short oranı, sembolün yalnız geçmiş 90 gününden hesaplanan
  yüzde 20'lik alt diliminde (en az 30 gün geçmiş gerekir),
- OI son 1 saatte `>= +%2` (yeni pozisyon birikimi; L1'deki OI düşüşünün tersi).

Train'de yalnız aşağıdaki en fazla üç önceden kayıtlı varyant karşılaştırılır:

1. **L2-A setup:** ortak koşullar + son settled funding `<= 0`.
2. **L2-B breakout:** L2-A + 15m kapanışın önceki dört kapanışın maksimumunu
   aşması + aynı 15m içinde taker buy/sell `> 1.20`.
3. **L2-C realized trigger:** L2-A + son 5 dakikadaki SHORT_LIQUIDATION USD
   toplamının sembolün geçmiş 30 günlük 5m dağılımında yüzde 95'i aşması.

Long/short oranı hesap sayısıdır, notional değildir; OI koşulu bu nedenle
zorunlu tamamlayıcıdır. L2-C'de likidasyon olayı tetik barında kullanılabilir,
ancak giriş yine sonraki bar açılışıdır.

## Başarı kapısı ve tek test bakışı

- Veri süresi: en az 180 takvim günü.
- Train: kronolojik ilk `%70`; test: son `%30`.
- Train'de en az 100 olay, testte en az 30 olay ve testte en az 30 ayrı UTC olay
  günü. Aynı sembol/gün içindeki olaylar 24h cooldown ile tek olaya düşer.
- Train seçim ölçütü: 12 bp sonrası ortalama ve medyan `>0`, win rate `>=%55`,
  gün-kümeli bootstrap `p<=0.05`, q10 `>-%5`.
- En iyi train varyantı önceden belirlenmiş tek test dönemine yalnız bir kez
  uygulanır. Testte ortalama/medyan `>0`, win rate `>=%52` ve gün-kümeli
  `p<=0.05` sağlanmazsa aile RED olur.
- Sembol katkısı, gün kümeleri, q10/q90, maksimum ters hareket ve maliyet stresi
  eksiksiz raporlanır. Tek bir coin veya piyasa gününün sonucu taşıması kabul
  edilmez.

## Yasaklar

- Veri birikirken eşik değiştirmek veya "güzel görünen" coinleri seçmek.
- Heatmap olmadan tahmini likidasyon bölgesi uydurmak.
- Bağlantı heartbeat'i olmayan süreyi sıfır likidasyon kabul etmek.
- Minimum örnek kapısı geçilmeden Telegram bildirimi veya canlı filtre eklemek.
