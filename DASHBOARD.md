# Pano güncellemesi — 24 Eylül 2026

Pano: https://ss4181.github.io/trade1/

Kodun main'e gönderilmesi çalışan tableti güncellemez. Tablet yeni şablonu
ilk yayında gh-pages dalına, veriyi trade1-data dalına gönderir. Pages dağıtımı
tamamlanınca tarayıcı yeni görünümü alır. Aynı anda ikinci bot başlatmayın.

## Tablette uygula

1. Termux'ta kodu al. Pull hata verirse devam etme; yerel dosyaları silme.

```sh
cd ~/trade1
git pull --ff-only origin main
python configure_dashboard.py --minutes 5
export PUBLISH_INTERVAL_MIN=5
```

2. Sarmalayıcıları ve botu durdur; sonra tek sarmalayıcı başlat.

```sh
touch .stop-signal-bot
pkill -f '[b]oot-signal-bot.sh' 2>/dev/null || true
pkill -f '[p]ython signal_bot.py' 2>/dev/null || true
pkill -f '[u]vicorn server:app' 2>/dev/null || true
sleep 3
pgrep -af '[s]ignal_bot.py|[s]erver:app|[b]oot-signal-bot.sh'
```

Bu kontrolde süreç kalmışsa yeni bir kopya başlatma. Çıktıyı paylaş.
Süreç kalmadıysa:

```sh
rm -f .stop-signal-bot
nohup sh ./termux/boot-signal-bot.sh >/dev/null 2>&1 &
```

3. İlk tarama/yayın ve GitHub Pages dağıtımı için birkaç dakika bekle. Sayfayı
yenile. Üstte “Son yayın” saati, günlük/saatlik/15dk rejim ve “Rejime göre
TP2 / TP3 başarısı” görünmeli. “Canlı bildirim · strateji ufku” seçeneği tablet
kayıtlarını her yayında yeniden özetler. Bot 5 dakikalık tarama döngüsünde yayın
yaptığından ağ/işlem süresine bağlı küçük sapmalar olabilir; sayfa anlık borsa
ekranı değildir.

4. Yayın ilerlemiyorsa şu güvenli çıktıları paylaş; .env dosyasını paylaşma:

```sh
git log -1 --oneline
pgrep -af '[s]ignal_bot.py|[s]erver:app|[b]oot-signal-bot.sh'
tail -n 200 bot.out.log | grep -E 'GitHub|yayin|pano|performans' | tail -n 15
```

## Ölçümlerin anlamı

- Tarihsel süre sınırsız TP2/TP3: en son sürümlü araştırma raporu. Henüz hedefe
  dokunmayanlar bekleyen olarak bütün olayları içeren paydada kalır. Her satırın
  fiyat arşivi bitişi ayrıdır; rapor güncel canlı bildirim başarısı değildir.
  G1_PROXY tarihsel vekildir. S5/S6 tarihsel evreni ve DL1 yönlü ölçümü yoktur.
- Canlı rejim tablosu: teslimi doğrulanmış sinyalin o andaki rejimi; strateji,
  evren, piyasa, yön, config ve motor ayrı. Yalnız mevcut strateji ufku içindeki
  TP2/TP3 dokunmalarıdır. Olgun ölçümler paydada; aktif/eksik/eski rejimsiz
  kayıtlar açıkça gösterilir. Bugünkü rejim geçmiş sinyallere atanmaz.
- G2 karnesi: planlı Binance açılışından TP3 / SL2 sırası; belirsiz aynı mum stop
  sayılır. Bağımsız TP2/TP3 veya Hyperliquid işlem kârıyla birleştirilmez.
- Son 5: Telegramdakiyle aynı ölçüm ve config/yon uyumluluğu; ölçülemeyen kayıt
  daha eski bir kazananla değiştirilmez. DL1 olay bildirimi için uygulanmaz.
- Zaman çıkışı K/Z: sinyal sonrası saat açılışı → ufuk kapanışı; maliyet varsayımı
  sonrası. Aktif satır sadece geçici fiyat referansıdır. Ufuk bitince güncel
  fiyatla hesap yapılmaz; sonuç önbelleği beklenir. Görüntülenen son 400 olayın
  zaman çıkışı özeti ile bütün hedef arşivinin sayıları farklı olabilir.
- Boş ölçüm sıfır başarı değildir. Eski veya eksik kaynaklar uyarı olarak
  gösterilir. Tüm görünen zamanlar Europe/Istanbul (TRT) biçimindedir.

## Doğrulama

`python tests/run_isolated.py` çevrimdışı testleri özel dosya/ağ erişimi olmadan
çalıştırır. `node tests/test_dashboard.js` filtre ve yerel rapor davranışını
kontrol eder. Playwright kurulu ortamda
`node tests/test_dashboard_browser.js <dashboard-json>` masaüstü ve 375px mobil
görünümü, TRT dönüşümünü, rejim seçimlerini ve bozuk/eski veri davranışını
yerel fixture ile doğrular. Gerçek bot veya Telegram başlatılmaz.
