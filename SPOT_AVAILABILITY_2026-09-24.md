# VANRY tarama hatası ve ortamda kalan kapanış payı

Teşhis: tablette `SCAN_CLOSE_DELAY_SECONDS=10` süreç ortamına aktarılmış.
Bot `.env` dosyasını `os.environ.setdefault` ile okuduğundan açık ortam
değişkeni dosyanın ve yeni 5 saniyelik varsayılanın önüne geçer.

VANRYUSDT ayrı bir sorun: [resmî Binance duyurusuna](https://www.binance.com/en-GB/support/announcement/binance-will-delist-acx-hft-pivx-pyr-vanry-vic-on-2026-08-17-64cf7544b98e4f2ca7f54ba11fd72d9d)
göre spot işlemler 17 Ağustos 2026 03:00 UTC'de (06:00 TRT) durdu. Salt okunur
canlı API kontrolü `status=BREAK`, `isSpotTradingAllowed=true` ve son saatlik
mum açılışı `2026-08-17T02:00:00+00:00` döndürdü. İzin bayrağı tek başına
güncel işlem yapılabildiğini göstermez. Güncel mum zorunluluğu doğru biçimde
bu eski veriden sinyal üretilmesini engelliyordu.

## Düzeltme

- Başlangıçta spot `exchangeInfo` kataloğu alınır; normal sürekli çalışmada
  piyasa rejimi worker'ının varsayılan saatlik turunda yenilenir. Her taramada
  yeni katalog isteği yapılmaz.
- `TRADING` olmayan veya spot izni açıkça kapalı semboller, hem seri hem
  paralel spot tarama yollarından ve gözlem kanalından ayrılır. `/check`
  içindeki doğrudan sembol kontrolü de bu duruma uyar.
- `/status`: `Spot tarama dışı: VANRYUSDT (BREAK)` ve varsa katalog hatası.
  Ayrılan semboller tarama hatası sayılmaz; diğer gerçek veri hataları kalır.
- Katalog okunamazsa son bilinen durum korunur. Boş/bozuk yanıt evreni
  silmez; katalogda bilinmeyen sembol delist kabul edilmez. Mum tazeliği
  kontrolü bütün bu durumlarda devam eder.
- Sonraki başarılı katalog yenilemesinde tekrar `TRADING` olan sembol
  taramaya geri alınır. Statik araştırma listesi ve geçmiş ölçümler değişmez.
  Bu filtre G1/G2'nin vadeli evrenini spot durumuyla daraltmaz.
- `configure_scan_timing.py --seconds 5` yalnız proje `.env` dosyasındaki
  kapanış payını değiştirir; anahtarları yazdırmaz. Çalışan süreç ortamını
  değiştiremez: Termux'ta ayrıca `export` ve botu yeniden başlatma gerekir.

## Tablet adımları

1. Güncelle; git hatasında sonraki adıma geçme:

```bash
cd ~/trade1
git pull --ff-only origin main
python configure_scan_timing.py --seconds 5
export SCAN_CLOSE_DELAY_SECONDS=5
printenv SCAN_CLOSE_DELAY_SECONDS
```

Son satır 5 olmalı. Dosya kaydı sonraki başlangıçlar içindir, export bu
terminalin yeni çocuk süreçleri içindir. Yeni bir terminalde değişken yine
10 çıkarsa terminal başlangıç ayarı onu yeniden atıyordur; botu çalıştırmadan
önce export'u tekrarla ve başlangıç ayarının kaynağını ayrıca düzelt.

2. Eski süreçleri durdur:

```bash
touch .stop-signal-bot
pkill -f '[b]oot-signal-bot.sh' 2>/dev/null || true
pkill -f '[u]vicorn server:app|[p]ython signal_bot.py' 2>/dev/null || true
sleep 3
pgrep -af '[b]oot-signal-bot.sh|[u]vicorn server:app|[p]ython signal_bot.py'
```

3. Kontrol boşsa yeniden başlat:

```bash
rm -f .stop-signal-bot
nohup sh ./termux/boot-signal-bot.sh >/dev/null 2>&1 &
```

4. İlk tarama tamamlandıktan sonra Telegram `/status`: kapanış payı 5 sn;
   spot tarama dışı VANRYUSDT (BREAK). Başka veri sorunu yoksa tarama hatası 0.
   Eski hata satırları logda korunur; yeniden başlatmadan önceki loglarla
   yeni çalıştırmanın hata sayısını karıştırma.

Doğrulama: işlem dışı sembol, yeniden açılma, katalog hatası, önbellek,
seri/paralel yol, gerçek hata sayısı ve gizli ayarların korunması test edildi.
