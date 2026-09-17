# G1 gecikme düzeltmesi — 17 Eylül 2026

Tabletten gelen son olay: G1, Telegram API kabulü 17:08:01 Türkiye saati.
Kapanış → tespit 482,344 sn; tespit → kuyruk 0,006 sn;
kuyruk → API kabulü 0,352 sn. Toplam 482,702 sn.
Bu kayıt beklemenin tespitten önce olduğunu kanıtlar; tarama başlangıcı
paylaşılmadığından 482 saniyenin ne kadarı zamanlama, ağ veya cihaz uykusu
henüz belirlenemedi. Eski strateji medyanları yeni sürüm ölçümü sayılmaz.

## Değişiklikler

- G1 saatlik kontrolü ana taramadan ve DL1 sorgularından bağımsız, 5 saniyede
  bir çalışan lider işçisine taşındı. Saat sınırında mevcut 10 sn payı korunur.
- İlk 10 aday en fazla 8 eşzamanlı sorgu zinciriyle incelenir. Hazır G1 sinyali
  yavaş coini beklemeden gönderilir. Sıralama, koşullar ve cooldown korunur.
- G1/DL1 aynı durum dosyasına yazarken yalnız kendi alanlarını günceller;
  diğer işçinin yeni kayıtlarını ezmez. G1 cooldown gönderimden önce kaydedilir.
- Tespit zamanı her adayın değerlendirmesinde alınır. Mesajdaki gecikme artık
  yalnız taramaya başlama gecikmesini değil tespit süresini de içerir.
- `reference_to_scan` ve `scan_to_detect` eklendi. `--since` eski teslimleri
  rapordan ayırır; kuyruktaki tüm bekleyen olaylar yine görünür.
- Çalışan botun durum raporu yalnız bu süreç başladıktan sonra kuyruğa giren
  olayları ölçer. Komut satırı varsayılanı son 20 olay olmaya devam eder.
- Sade G1 kartı, ticker satırının kaldırılması ve Telegram kartlarında Türkiye
  saatleri bu pakettedir. Saat dilimi veritabanı olmayan kurulumda UTC+3
  yedeği botun başlatılabilmesini sağlar.

Testler ağ bağlantısı kapalı geçici kopyada çalıştırıldı. Yavaş coin sürerken
erken teslim, bağımsız işçi/tek lider, paralellik sınırı, karar/cooldown
eşitliği, ortak durum dosyası ve tarih filtresi doğrulandı.
Gerçek tablette 30 sn altı henüz doğrulanmadı; API ve cihaz beklemeleri
yeni aşama ölçümleriyle ayrıca değerlendirilecek.

## Tablette sırayla

1. Eski botu ve yeniden başlatma sarmalayıcısını durdur:

```bash
cd ~/trade1
touch .stop-signal-bot
pkill -TERM -f '[b]oot-signal-bot.sh' 2>/dev/null || true
pkill -TERM -f '[p]ython.*signal_bot.py|[u]vicorn.*server:app' 2>/dev/null || true
sleep 3
pgrep -af '[s]ignal_bot.py|[s]erver:app|[b]oot-signal-bot.sh'
```

Son komutun çıktısı boş olmalı. Süreç kaldıysa ikinci kopya başlatma.

2. Kodu al ve derleme kontrolü yap:

```bash
git pull --ff-only origin main
git log -1 --oneline
python -m py_compile signal_bot.py shadow_experiments.py notification_delivery.py
```

Pull veya derleme hata verirse devam etme; çıktıyı paylaş. Reset uygulama.
Yeni Python paketi veya Python sürüm yükseltmesi gerekmez.

3. Yeni ölçüm başlangıcını kaydet ve bir kez başlat:

```bash
mkdir -p tmp
date -u +%Y-%m-%dT%H:%M:%SZ > tmp/notification-check-since.txt
termux-wake-lock
nohup sh ./termux/boot-signal-bot.sh >/dev/null 2>&1 &
sleep 10
pgrep -af '[s]ignal_bot.py|[s]erver:app|[b]oot-signal-bot.sh'
```

Bir sarmalayıcı ve bir Python bot/sunucu beklenir. Başlatma betiği
`.stop-signal-bot` işaretini kendisi kaldırır.

4. Yeniden başlatmadan sonraki yeni mum kapanışı için sinyal geldiğinde:

```bash
python notification_delivery.py --status --since "$(cat tmp/notification-check-since.txt)"
```

Başlatma anında eski bir kapanış yakalanırsa o olay doğal olarak geç görünebilir;
gecikme hedefini bot çalışırken gerçekleşen yeni kapanışta kontrol et.
`sample_events: 0` henüz bu dönemde bildirim olmadığı anlamına gelir.
`reference_to_scan` başlangıç beklemesi, `scan_to_detect` tarama süresi,
`reference_to_ack` toplam süredir. Son aşama Telegram API kabulüdür,
telefon ekranına düşme zamanı değildir. Bu çıktıyı paylaş.
