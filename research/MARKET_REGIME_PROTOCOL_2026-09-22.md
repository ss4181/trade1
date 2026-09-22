# Piyasa rejimi incelemesi — hesap öncesi sabit protokol

Amaç: Telegram `/piyasa` düğmesi için açıklanabilir bir durum tanımı ve mevcut stratejiler için betimleyici rejim karşılaştırması hazırlamak. Canlı stratejiler, eşikler, bildirim izinleri ve emir sistemi bu çalışmada değişmez. Bu yeni bir bağımsız test veya yatırım tavsiyesi değildir.

## Sabit tanım: btc-daily-regime-v1

- Kaynak: Binance **spot** BTCUSDT, UTC günlük mumları; yalnız kapanmış, kesintisiz veriler. Vadeli fiyat serisiyle birleştirme yok.
- C: son kapanış; M200: son 200 günlük kapanışın aritmetik ortalaması; eğim: M200 / 20 gün önceki M200 - 1. En az 220 günlük mum gerekir.
- BOĞA: C > 1.02 × M200 **ve** eğim > 0.
- AYI: C < 0.98 × M200 **ve** eğim < 0.
- GEÇİŞ: yeterli ve güncel veride diğer bütün durumlar (ortalama yakınlığı veya fiyat/eğim uyuşmazlığı).
- Eksik, bayat veya geçersiz veri: BELİRSİZ. “Geçiş” eksik verinin karşılığı değildir.
- Yalnız BOĞA içinde: son 30 günlük basit getiri < 0 ise `bull_pullback`; 0–%10 (uçlar dahil) ise `bull_moderate`; > %10 ise `bull_strong`.
- %2 bant, 20 günlük eğim ve %10 alt-rejim sınırı yorumlanabilir ilk tasarımdır; performansa göre seçilmeyecek/değiştirilmeyecek. Kesin piyasa gerçeği olarak sunulmaz.
- Bir sinyalin etiketi karar anında kapanmış en son günlük muma dayanır. Günün ilerleyen fiyatı/geçerli bugünkü etiket geçmişe uygulanmaz. Günlük kapanış UTC 00:00, Türkiye 03:00; kullanıcıya saatler TRT gösterilir.

## Araştırma kapsamı ve ölçüler

1. S1, S1+S4, S2, S3: canlı `strategy_engine.CoreRules` matematiğiyle idealize saatlik replay; sabit mevcut core30 evreni. Aynı sembol + aynı rejim + aynı takvim bölümü içindeki tüm geçerli saatlik girişler karşılaştırma tabanı. Tarihsel evren üyeliği ve gerçek teslim/emir dolumu iddiası yok.
2. Giriş: karar saatindeki sonraki saatlik mum açılışı; çıkış: S1 ailesi 24, S2 72, S3 4 saat sonunda kapanış. Basit yüzde getiri. Brüt ve 12 baz puan toplam maliyet varsayımı sonrası getiri ayrı; S2 fonlama hariç olduğu açıkça belirtilir. Fiyat ölçümü, limit emir kârı değildir.
3. Mevcut 24 aylık çekirdek veri daha önce araştırılmıştır. 2026-01-01 öncesi/sonrası ayrı gösterilir; ufuk sınırı aşan olaylar dışlanır. “Yeni OOS” denmez. Veri başındaki eksik 249 mumluk pencere dışlanır.
4. G1: eski `eval_gainer_short_crowd` TRAIN örneklemi, sabit 89 sözleşme sıralaması nedeniyle yalnız vekil araştırma. Daha önce açılmamış G1 TEST bu çalışma için açılmaz. Canlı tüm-piyasa sıralamasıyla eşdeğer sayılmaz.
5. G2: önceden seçilmiş `fade_long_l1_up_d60_e2` adayının mevcut A/B/C sonuçları; tekrar aday taraması yok. Hedef %3 / stop %2 / 24 saat, sinyal mumu kapanışından 60 dakika sonra referans giriş; rejim etiketi gecikmiş girişe değil sinyal mumu kapanışına atanır. Muhafazakâr 20 bp + fonlama maliyeti; C ayrıca gösterilir. Bunlar Binance/Coinalyze fiyat senaryolarıdır, Hyperliquid limit dolumu değildir.
6. S5/S6: tarihsel dinamik evren kaydı yoksa performans uydurulmaz. DL1: yönlü stratejiyle ortak başarı sıralaması yapılmaz.
7. Her hücrede N, ayrı UTC gün sayısı, sembol sayısı, pozitif getiri oranı, ortalama/medyan; çekirdekte ayrıca aynı-rejim tabanına göre fark. G2 hedef/stop/zaman çıkışı ayrılır.
8. Belirsizlik: 7 günlük takvim bloklarıyla 2.000 tekrar, sabit seed; aynı gündeki semboller birlikte örneklenir. En az 30 olay ve 28 ayrı olay günü yoksa güven aralığı yayımlanmaz. Bu çoklu karşılaştırmaları düzeltilmiş anlamlılık testi değildir.
9. Rejim filtresi açılmaz. Güçlü görünen hücreler, ileri dönemde sabit tanımla sınanacak hipotezlerdir; küçük N veya yalnız pozitif ortalama başarı kanıtı değildir.

### TP2/TP3 dokunma ek ölçüsü

Her olayın ölçüm girişindeki saatlik açılışından itibaren stratejinin sabit
ufkunda (S1/S1+S4 24s, S2 72s, S3/G1 4s) gelecekteki kapanmış saatlik
`high` değerleri taranır. Girişin %2 veya %3 üstüne en az bir kez çıkılması
`tp2_touch` / `tp3_touch` olarak kaydedilir. Bu, brüt ve stop'suz bir fiyat
dokunmasıdır; ücret, funding, slippage, emir dolumu ve aynı mum sırası
hesaplanmaz. G2'nin seçilmiş 24 saatlik arşivi için mevcut MFE, 60 dakika
gecikmeli giriş korunarak aynı dokunma tanımına çevrilir. Dokunma oranı hedef-
stop sırası veya gerçek işlem başarısı yerine geçmez.

## Canlı uygulama sınırları

Yeni HTTP çağrısı bildirim taramasının veya komut yanıtının kritik yoluna konmaz. Bağımsız arka plan yenilemesi + atomik cache gerekir; ağ yoksa son durumun yaşı/hatası gösterilir. Tüm stratejilerin rejim metadata'sı karar anında dondurulur. UTC saklama korunur, sunum TRT olur. Bot emri açmaz/kapatmaz.

Kaynaklar: [Binance spot mum sözleşmesi](https://developers.binance.com/en/docs/catalog/core-trading-spot-trading/api/rest-api/market), [Telegram ReplyKeyboardMarkup](https://core.telegram.org/bots/api#replykeyboardmarkup).

## Kapsam eki (çekirdek sonuçlarından sonra, extended hesaplarından önce)

Canlı varsayılan evrenin tamamını kapsamak için aynı sabit hesap extended59'a da uygulanır; yalnız o evrende çalışan S1 ve S1+S4 değerlendirilir. Çekirdek sonuçlarıyla birleştirilmez. Rejim tanımı, maliyet, ufuk ve eşikler değişmez. Bu ek, yeni bir bağımsız doğrulama iddiası taşımaz. Replay ilk tam 249 mumla boş state'ten başlar; izleyen 72 saat state ısınması için performanstan çıkarılır. Günlük spot seri, arşivdeki 730 tam BTC gününün saatlik son kapanışıyla karşılaştırılır.
