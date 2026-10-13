# Yeni oturuma yapıştırılacak prompt

Bağımsız `hyperliquid-auto-pilot` projesini hazırlamanı istiyorum. Trade1'de
Binance tabanlı sinyal/araştırma sistemi var; referans paketini bu klasöre
getirdim. Artık amaç, sinyalleri kaçırmadan ve pozisyonları korumasız bırakmadan
Hyperliquid'de otomatik takip/emir yeteneği geliştirmek. Kâr garantisi istemiyorum;
işlem maliyeti, negatif kuyruklar ve borsa koruması açıkça ölçülsün.

Önce `handoff/hyperliquid/README.md`, `STRATEGIES_AND_FINDINGS.md`,
`AUTOMATION_SPEC.md` ve ZIP'ten çıkan `manifest.json` dosyalarını oku. Paketin
yol yapısı farklıysa bu isimleri bul. `reference/trade1/` içindeki protokol ve
araştırma kaynaklarını stratejiye göre seçerek oku. Kaynak commit'i ile yerel
taslak hash'lerini ayır. Önce git status ve AGENTS.md'yi incele; kullanıcının
değişikliklerini koru. Referans Trade1'i, diğer `hyperliquid-bot` taslağını veya
Binance'deki mevcut açık pozisyonlarımı değiştirme/yönetme.

İlk sürüm varsayılan `MODE=paper`, `LIVE_TRADING_ENABLED=false` olsun.
100USDC sanal equity, 1x isolated tasarım, 1açık pozisyon, 25USDC notional üst
sınırı, planlı risk equity×%0,5 (masraflar dahil), günlük%2 ve equity zirvesinden
%5 zarar kapısı, azami3yeni giriş/gün. Minimum/precision karşılanmazsa SKIP;
kaldıraç/notional artırarak zorlamayacaksın. Bunlar tasarım başlangıcı; optimum
olduğu iddia edilmeyecek. Binance testnet pilotunu aktive etme. Şimdilik gerçek
para yatırma, seed/ana cüzdan private key isteme veya ana-ağ emir verme yetkisi yok.

Sıralı iş:

1. Strateji/envanter ve veri haritası çıkar. S1/S1+S4/S2/S3/S5/S6/G1/G2/DL1 ve
   P0…P5/Q1, AMD/POC, Donchian/carry gibi adayları birbirine karıştırma. S5/S6
   mevcut kodda VWAP/rejim değil, observe-evren S1 türevleri. S2/G1 ve birçok
   kontrol kabul kapısını geçmedi. Hedef dokunması net kârlı işlem demek değil.
2. Salt-okunur HL veri adaptörü kur: native crypto perps, doğru sembol/çarpan,
   kapalı 1m/5m/15m/1h/4h/1d, OI, funding, book/spread/derinlik, gerçek response
   alınma zamanı. Binance'deki LS<1'i negatif HL funding'e çevirip aynı strateji
   diye sunma; doğrulanmış eşdeğer veri yoksa UNKNOWN veya yeni ön-kayıtlı deney.
   candleSnapshot son5000mum sınırını ve saatlik funding farkını dikkate al.
3. Eski verileri ayrı `source=BINANCE` referans deposunda oku. Önce manifest/hash
   kontrolü. 13Ekim PC kontrolünde 16hash uyuşmazlığı vardı; yeni doğrulama
   olmadan tam veri/başarı iddiası yok. Tarihsel ZIP/Parquet gerekiyorsa mevcut
   özel cache'e salt-okunur erişim iste, sır/env isteme. Eksik veri UNKNOWN;
   geçmişi forward diye etiketleme. Bot state/outbox/subscribers devralma.
4. Saf, test edilebilir strateji eklentileri ve bağımsız paper ledger kur.
   Eski algoritma farklarını (Wilder RSI, volume window, gainer/OI saat farkı)
   golden testlerle koru. HL uyarlamaları yeni isim/rule hash alır. G1 legacy
   ile hizalı kontrol ve anlık/5m/15m bekleme/teyidi ayrı shadow ölç. S1/S3/G2
   giriş/çıkış adaylarını protokolleri bozmadan karşılaştır. Bütün stratejileri
   birden canlıya açmak yerine kanıtı en güçlü adaylar sırayla ilerlesin.
5. Tek lider, SQLite/outbox, dedup/idempotent order id, restart ve reconciliation
   mekanizması kur. Paper, testnet ve live ayrı hesap/DB/konfig olsun. Gerçek
   fill≠ask≠sinyal close. Emir ack≠fill; no-fill/partial ve kaçan fırsatı ölç.
6. Hyperliquid testnet emir adaptörü hazırla. İşlem fill'ine göre exchange-native
   reduce-only SL/TP kurup sorgula; partial entry iptalinde çocuk koruma kalkma
   senaryosunu test et. Koruma doğrulanamazsa yeni giriş kesilsin, yalnız kendi
   test pozisyonunda fail-safe close denenip doğrulansın. Kapatıldı demek için
   exchange qty/fill doğrulaması gerekir. Bot kapalıyken SL borsada kalmalı.
7. OOS/protokol ve kabul raporu üret: en az90gün/30tamolay/28gün hazırlık,
   ayrıca bağımlılığı hesaba katan net CI, funding/fee/fill kapsamı, kuyruk,
   MAE/MFE, missed/no-entry sonuçları. Testnet başarı=kârlılık değil. Kural
   optimizasyonu sonrası aynı holdout'a tekrar bakma veya başarısız adayı sessiz
   değiştirerek "güvenilir" yapma. Yeterli kanıt yoksa mainnet BLOCKED kalır.
8. Anlaşılır özel durum/Telegram raporu hazırla: neden sinyal/skip, gerçek entry,
   SL/TP, koruma doğrulaması, fees/funding, net PnL, risk cap, açık pozisyon ve
   bağlantı sağlığı. Public Pages'e hesap adresi/bakiye/anahtar taşıma. Email
   ve mobil uygulama kapsam dışı; borsa yönetimi Telegram'a bağımlı olmasın.

İlk teslimde çalışan proje iskeleti, deterministik offline testler, sahte/gerçek
işlem ayrımı, paper çalıştırma komutu ve veri-kalite durumunu göster. Ardından
testnet aşamasını hazırla. Mainnet için ileride ayrıca açık onay, agent wallet
kurulumu ve kabul raporu gerekecek; mevcut prompt gerçek emir yetkisi vermiyor.
Her aşamada yaptığın/yalnız tasarladığın/kanıtlanmamış olanı açıkça ayır.
Hiçbir token, .env içeriği veya private key'i çıktı/log/commit'e yazma. Gerekli
secret için yalnız değişken adını ve yerelde nasıl gireceğimi söyle.
