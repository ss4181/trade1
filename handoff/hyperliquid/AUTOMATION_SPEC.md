# Hyperliquid otomasyon tasarımı — uygulama sözleşmesi

13 Ekim 2026. Henüz uygulanmış sistem değil. Amaç sinyali otomatik emre çevirmek
ve gerçek pozisyonu güvenli izlemek; otomasyon bir negatif stratejiyi kârlı yapmaz.

## Sermaye ve yetki sınırı

İlk etap **100 USDC sanal bakiye**, papertrade; ardından Hyperliquid testnet.
Olası ana-ağ küçük pilotu için önerilen başlangıç bütçesi **100 USDC**.
Bu risk bütçesi tasarımıdır; protokol minimumu, yatırma talimatı, garanti veya
onaylanmış ana-ağ başlatma değildir. Daha çok sermaye/kaldıraçla veri eksikliği
çözülmez. Sadece tamamen kaybedilebilir ayrı fon/cüzdan; Binance açık işlemleri
ve mevcut diğer HL hesapları bu projeyle yönetilmeyecek.

| Pilot varsayımı | Limit |
|---|---|
| Kaldıraç / marjin | 1x, isolated; destek/doğrulama yoksa giriş yok |
| Aynı anda pozisyon | Toplam1; coin başına1; stacking/averaging yok |
| İşlem notional üst sınırı | 25 USDC |
| Planlı işlem riski | Bakiye×%0,5; ücret/kayma bütçesi dahil |
| Başlangıç100USDC için risk | En fazla0,50USDC planlı; gap/tasfiye kaybı aşabilir |
| Günlük zarar durdurma | Gün başı equity'nin %2'si; gerçekleşen+UPnL+ücret/funding |
| Equity tepesinden drawdown | %5; kalıcı pause ve insan incelemesi |
| Yeni girişler | Pilot azami3/gün; eski sinyal peşinden koşma yok |

Zarar/drawdown kapısı yeni girişleri durdurur; **açık pozisyon koruması devam
eder**. Stratejiye özel kanıtlanmamış koşul kaybını birden hard-exit yapma.
Zaman çıkışı/sabit TP/SL/trailing önceden dondurulmuş deney sürümüyle tanımlansın.
Bir plan çalışmıyorsa risk azaltılır veya giriş yapılmaz; zararda hedef/stop
uzaklaştırma, martingale ve kurtarma stratejisi yok.

`qty = risk_budget / (abs(entry-stop) + entry*cost_and_slippage_fraction)`;
notional üst sınırı ve serbest isolated teminatla daha da kısıtla. Miktarı
`szDecimals` ile **aşağı** yuvarla. Resmî minimum notional/precision karşılanmazsa
SKIP; emri büyüterek veya kaldıraç ekleyerek minimumu zorlama. Çok küçük kısmi
çıkış yerine pilotta tam çıkış; kısmi dolum/toz kapatma hataları yine test edilsin.

## Ayrı aşamalar / kabul kapıları

1. **ENVANTER/VERİ:** salt-okunur HL meta, book, 1m/5m/15m/1h/4h/1d, funding/OI
   topla. Sinyal zamanı, kaynak zamanı, gerçek alınma zamanı ve kaliteden oluşan
   ledger. Binance ham verisi ayrı referans, HL OI geçmişi uydurulmaz.
2. **PAPER:** strateji eklentileri ve aday giriş/çıkış planları; fill/orderbook
   kısıtlı simülasyon, no-fill ve missed opportunity dahil. Spot→perp ve
   Binance→HL yeni sürüm. Eski güven etiketlerini devralma.
3. **TESTNET:** demo emir yaşam döngüsü, kısmi fill, restart, trigger/stop, rate
   limit, reddedilen emir ve ağ kesintisi. Testnet kârlılığı/mainnet likiditesi
   kanıtı değil. Sentetik sinyaller yalnız testnet/test fixture içinde.
4. **ANA AĞ KAPISI:** en az90takvim günü ve30tamolay/28olaygünü veri hazırlığı;
   net beklenti, blok-bootstrap CI, yoğunlaşma, kuyruklar/funding/fill kapsamı
   ayrıca değerlendirilsin. Pozitif muhafazakâr net beklenti kanıtı ve tüm
   operasyon senaryoları olmadan ana-ağ otomatik açılmaz. Başarısız kapıdan sonra
   ikinci holdout seçimi yok; yeni kural yeni ileri dönem.
5. **SINIRLI CANLI:** yalnız ayrıca açık insan onayı, doğrulanan özel API agent,
   parametre/rule hash ve 100USDC bütçe. Geçerli onay yoksa safe refusal.

90/30/28 kapısı tek başına yeterli güven/başarı değildir. Adaylar az sinyal
üretirse eşiği sonuçlara bakarak gevşetme; daha uzun ileri süre veya önceden
tanımlanmış uygun HL evreniyle çalış. Kullanıcının erken pilot isteği bile
korumasız veya doğrulanmış kâr diye sunulan canlı emir yetkisi değildir.

## Emir makinesi ve pozisyon koruması

`SIGNAL → RISK_APPROVED → ENTRY_SUBMITTED → RECONCILING → PARTIAL/FILLED →
PROTECTION_CONFIRMED → OPEN → EXIT_PENDING → CLOSED`.
Hata/timeout ayrıca `UNKNOWN`, `UNPROTECTED`, `PAUSED` olarak saklansın.

- SQLite işlem/outbox, tek lider dosya kilidi, idempotent client-order kimliği
  ve kalıcı nonce; her action/ack/fill saatini ayrı kaydet. Timeoutte yeniden
  kör emir verme; önce exchange order+fills+position uzlaştır.
- Market/IOC ile ALO ayrı planlardır. ALO gönderildi diye giriş oldu sayma;
  TTL/no-fill/partial gerçektir. Canceled order=trade/loss değil.
- Ortalama gerçek fill'e ve gerçek qty'ye göre TP/SL hesapla. Emir fiyatı,
  sinyal close/ask'i ve mark'i ayrı alanlardır. Kârı da gerçek fill'den ölç.
- Borsada reduce-only koruma emirlerini kurup **sorgulayarak** doğrula. Batch
  gönderme atomik bracket garantisi değildir. Her kısmi fill'de korunan qty'yi
  uzlaştır. Parent kısmi dolumu iptal edildiğinde child TP/SL kalkabilir:
  koruma yoksa yeni girişleri kes, tekrar koru; doğrulanamazsa önceden yetkili
  reduce-only kapatma ve kritik alarm. Bu fail-safe yalnız kendi pilot
  pozisyonlarını kapsar; başka manuel pozisyonu otomatik kapatma yok.
- Stop tetiklenmesi dolum garantisi değildir; mark trigger/limit guard/slippage
  ve gap etkisi kaydedilsin. TP/SL'nin parent/position anlamı resmî API ile test.
- Websocket fills/order updates + periyodik REST reconciliation. Bot kapalıyken
  exchange trigger emirleri durmalı; restartta önce mevcut pozisyon/koruma
  uzlaştır, sonra tarama. Pozisyon varken bakım modunda korumayı iptal etme.
- Kill-switch yeni girişleri keser. `flatten` ayrı, açık kullanıcı yetkisi ve
  reduce-only doğrulaması gerektirir. Ağ yokken kapatmayı başardım deme.
- Subaccount/account ayrımı, agent signer, precision, rate limits ve master
  adresle hesap sorgulama. Seed/master key isteme; sadece agent secret'in
  yerelde girileceği değişken adını söyle. Transfer/withdraw action kodu yok.
- Telegram yalnız açıklama/manuel pause ve durum; emir yönetimi Telegram
  erişilebilirliğine bağlı değil. Email/Expo/mobil app geliştirme yok.

## Gerçek raporlama

Public panoda cüzdan/kimlik/anahtar/bakiye yayınlama. Özel arayüzde strateji,
koşullar, referans/fill, qty, SL/TP, koruma durumu, açık/gerçekleşmiş PnL,
funding+fees, risk bütçesi, kayma, arşiv sağlığı, no-fill ve skip nedenleri.
Olay, papertrade, testnet ve live ledger ayrı. Başarı paydası/fiyat hedefi,
stop-first ölçümü ve gerçek net PnL ayrı gösterilsin.

## Resmî kaynaklar — 13 Ekim 2026 kontrolü

- [Minimum/precision hataları](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/error-responses): perp emir minimumu10$; payload/batch içi hatalar ayrı.
- [Ücretler](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/fees): native perp taban taker%0,045/maker%0,015; kullanıcının gerçek tarifesi yeniden sorgulanacak.
- [TP/SL](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/take-profit-and-stop-loss-orders-tp-sl): mark tetiklemesi, partial parent iptali koruma sorunu; trigger≠fill.
- [Info](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint): candleSnapshot yalnız son5000mum; 10yılHL1m geçmişi varsayılamaz.
- [Agent/nonce](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/nonces-and-api-wallets): sorgu gerçek hesap adresiyle, signer/agent ayrı.
- [Exchange](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/exchange-endpoint): ack/resting/filled/error ayrımı, reduce-only, trigger ve grouping güncel şemayla doğrulanacak.

100USDC ve risk limitleri bu projeye önerilen tasarımdır, bu kaynaklardan
kanıtlanmış optimum değil. HL'de resmî global hesap LS kaynağı doğrulanmadan
negatif funding'i eşdeğer saymayın. Tarihsel/üçüncü-taraf veri lisansı ve
point-in-time erişim ayrıca doğrulanmalı; kısıtlamaları aşma yöntemi yok.
