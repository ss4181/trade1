# Ayrı Hyperliquid araştırma botu

Bu klasör tek başına çalışır. `trade1` modüllerini, `.env` dosyasını, Telegram
kimliğini veya bildirim arşivini kullanmaz. Klasörü `~/hyperliquid-bot` konumuna
kopyalamak yeterlidir. İki bot aynı tablette ayrı süreçler olarak çalışabilir.

- **HL-S:** boğa rejiminde 24–48 saatlik perpetual LONG adayı.
- **HL-D:** boğa rejiminde 14–28 günlük spot LONG izleme adayı.
- Canlı piyasa verisi yalnız Hyperliquid'in ücretsiz, anahtarsız API'sinden gelir.
- Daha önce indirdiğin Coinalyze OI arşivi araştırmada **ayrı borsa bağlamı**
  olarak kullanılabilir. Binance OI'si Hyperliquid OI'si yerine geçirilmez.
- Sinyaller araştırma adayıdır. Bot cüzdan bağlamaz, emir açmaz; özel anahtar istemez.
  Limit fiyatı ve TP/SL bir test senaryosudur, garantili dolum veya kâr değildir.

Kurallar, kısıtlar ve maliyetler: [RESEARCH_PROTOCOL.md](RESEARCH_PROTOCOL.md).
Doğrulama sonucu: [VALIDATION.md](VALIDATION.md).

## 1. Kodu tablete koy

GitHub üzerinden ilk kurulum için Termux'ta:

```sh
cd ~/trade1
git pull --ff-only
test ! -e "$HOME/hyperliquid-bot" && cp -R hyperliquid_bot "$HOME/hyperliquid-bot"
cd ~/hyperliquid-bot
python -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
cp -n .env.example .env
python -m unittest -v test_bot
python bot.py doctor
```

Kopyalama satırı mevcut `~/hyperliquid-bot` klasörünü üzerine yazmaz. Yeni bot
çalışma klasörü ayrı kalır. GitHub deposundaki klasör kaynak dağıtımı içindir.

Alternatif: bağımsız kaynak paketini tabletin Download klasörüne aktardıysan:

```sh
termux-setup-storage
pkg install unzip
cd ~
unzip -n ~/storage/downloads/hyperliquid-bot.zip
cd ~/hyperliquid-bot
python -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
cp -n .env.example .env
python -m unittest -v test_bot
python bot.py doctor
```

ZIP `hyperliquid-bot/` klasörünü içerir. `unzip -n` mevcut dosyaları üzerine
yazmaz; bu ilk kurulum içindir. Güncellemede kaynak dosyaları yenilenir,
`.env` ve `data/` korunur. Mevcut `~/trade1` klasörünü silme/yeniden adlandırma.
`doctor` Hyperliquid katalog sayıları ve kural kimliğini gösterir; token göstermez.

## 2. Veriyi indir ve eski OI arşivini kullan

```sh
cd ~/hyperliquid-bot
. .venv/bin/activate
python -u bot.py bootstrap
```

Bu ilk indirme birkaç–onlarca dakika sürebilir. Ekranda coin ve alınan kapanmış
mum sayısı ilerler. Bot henüz Telegram'a mesaj göndermez. API her zaman tüm
5.000 mumu vermeyebilir; yeni coinlerin geçmişi daha kısadır.

Önce mevcut Coinalyze manifestini bul:

```sh
find ~/trade1/research/data/coinalyze -name manifest.json
```

Eski toplu indirmenin yolu aşağıdakiyle aynıysa:

```sh
python bot.py import-oi ~/trade1/research/data/coinalyze/bot89-2026-09-13/manifest.json
```

Yol farklıysa `find` çıktısındaki **toplu indirme manifestinin** tam yolunu
son argümana yaz. Dosyaları taşıma; içe aktarma eski arşivi değiştirmez. Yeni
Coinalyze anahtarı veya tekrar indirme gerekmez. Ardından:

```sh
python bot.py research
python bot.py scan
```

Rapor `data/research.json` ve okunabilir `data/research.md`, anlık tarama
`data/status.json` olur. `scan` açıkça
`--send` verilmedikçe mesaj göndermez. Boğa rejimi yoksa ya da koşullar birlikte
oluşmazsa sıfır aday normaldir; bunu başarısız bağlantıyla karıştırma.
Hatalar varsa `data/coverage.json` ve `status.json` içindeki hata alanlarına bak.
Canlı taramalarda kaydedilen adayların sonraki fiyat takibi ayrıca
`data/forward.json` içine yazılır. `python bot.py paper` bunu yeniden hesaplar.
Bu da gerçek işlem/dolum değil, aynı limit senaryosunun ileriye dönük takibidir.
Coin evrenden çıkıp yeni mum gelmezse sonuç ölçülemedi olarak kalabilir.

## 3. Ayrı Telegram botu ve kanal oluştur

1. Telegram'da doğrulanmış **@BotFather** hesabını aç.
2. `/newbot` yaz. Örneğin adını `Hyperliquid Araştırma`, benzersiz kullanıcı
   adını da `..._bot` olarak belirle.
3. Verilen tokenı yalnız tablete gireceksin; sohbete veya GitHub'a yapıştırma.
4. Telegram'da **Yeni Kanal** oluştur. Yeni botu yönetici ekle ve **Mesaj
   gönderme** yetkisini aç. Eski G1/G2 kanalını kullanma.
5. Kanalın herkese açık bir `@kanaladi` varsa onu kullan. Özel kanalda botu
   yönetici yaptıktan sonra kanala kendin bir `kurulum` mesajı yaz; aşağıdaki
   kurulumda kanal alanını boş bırakabilirsin.
6. Termux'ta:

```sh
cd ~/hyperliquid-bot
. .venv/bin/activate
python bot.py setup-telegram
python bot.py test-telegram
```

Token yazarken ekranda görünmemesi normaldir; yapıştırıp Enter'a bas.
`setup-telegram` yalnız bu klasörün `.env` dosyasını yazar. Test mesajı yeni
kanalda görünmeden sürekli çalıştırmaya geçme. Bot tokenı dışında borsa veya
cüzdan anahtarı girilmeyecek.

## 4. Sürekli çalıştır

```sh
cd ~/hyperliquid-bot
mkdir -p data
nohup sh ./start-termux.sh > data/run.log 2>&1 &
pgrep -af '[h]yperliquid-bot/bot.py run'
```

Bir süreç görmelisin. Kilit, aynı yeni botun ikinci kopyasının başlamasını
engeller. Eski `signal_bot.py` çalışmaya devam eder. İlk taramadan sonra:

```sh
cd ~/hyperliquid-bot
. .venv/bin/activate
python bot.py status
tail -n 20 data/run.log
```

Durum çıktısında `delivery.pending` bekleyen, `acknowledged` Telegram API'sinin
kabul ettiği, `failed_or_expired` denemeleri tükenen/eski mesaj sayısıdır.
API kabulü telefona ulaştığı anı ölçmez.

Tarama her saat kapanışından 20 saniye sonra başlar. Tüm evrenin seri taranması
ek süre alır; bu sürüm için 30 saniye içinde tüm sinyalleri bitirme iddiası yoktur.
Günlük spot mumu normal UTC gününü kullanır; bildirim saatleri **Türkiye saati**
olarak gösterilir. Veri dosyalarında karşılaştırma için UTC/epoch tutulur.

Android ayarlarında Termux için pil optimizasyonunu kapat. Başlatıcı wake-lock
alır; Android yine süreci kapatabilir. Bu paket mevcut Termux:Boot dosyanı
değiştirmez. Tablet yeniden başlarsa yukarıdaki `nohup` komutunu yeniden çalıştır.

Yalnız yeni botu durdurmak için:

```sh
pkill -f "$HOME/hyperliquid-bot/bot.py run"
```

İçe aktarma / toplu indirme / araştırma komutları aynı anda çalışan yeni botun
kilidini alamaz. Bunlar için önce yeni botu durdur, iş bitince yeniden başlat.
Eski botun durması gerekmez.

## Ayarlar ve beklenti

`.env` içinde `HL_MARKET_LIMIT=0` hacim eşiğini geçen tüm evreni tarar. Tablette
yük fazla olursa `20` yazmak her piyasa türünü en likit 20 coinle sınırlar; bu
durumda araştırma evreni de daralır. Eşikler ve emir defteri sınırları aynı
dosyada bulunur. Değişiklikten sonra yalnız yeni botu yeniden başlat.

Telegram'da bildirim gelmemesi her zaman hata değildir. `regime=OTHER/UNKNOWN`
veya `candidates=[]` koşulların oluşmadığını gösterebilir. `errors` alanı doluysa
veri bağlantısı/kapsamını ayrıca kontrol et. Telegram başarısız gönderimler 60
saniye arayla en çok 4 kez denenir; çok eski adaylar gönderilmez. API'nin yanıt
kaybolması halinde yeniden deneme nadiren mükerrer mesaj oluşturabilir.

Bu bot geleceğin SHIB/DOGE'sini bildiğini iddia etmez. Hyperliquid'de listelenen,
yeterince likit ve fiyat/hacim gücü artan coinleri filtreler. Arz açılımı, ekip,
sosyal ilgi ve tüm zincirlerde yeni token keşfi bu veri setinde yoktur. Daha
yüksek getiri hedefi, daha sağlam sinyal veya daha düşük kayıp garantisi vermez.

`data/` içindeki SQLite ve araştırma dosyalarını düzenli yedekle. Kaynak paketi
token, cüzdan bilgisi veya piyasa arşivi içermez.
