# Telegram gecikmesi ve tablet güncellemesi — 11 Eylül 2026

Kullanıcı gecikmeyi **mum kapanışına göre** ölçüyor. Kodda 90 saniyelik sabit
kapanış beklemesi vardı; ana bildirimler ana ve gözlem evrenlerinin tamamı
tarandıktan sonra gönderiliyordu. Retry işçisi yalnız tur sonunda başlıyordu.
Bu üç bekleme düzeltildi. Tabletin gerçek logları bu çalışma sırasında
okunmadı; bildirilen yaklaşık üç dakikanın tümü tek bir nedene atfedilmiyor.

## Uygulanan plan

1. Varsayılan kapanış payı **90 → 10 saniye**. `SCAN_INTERVAL_MINUTES=5`
   korunuyor. Açık 1h mum yine hesaplamaya alınmaz. Zamanlayıcı, mevcut
   sınırın +10 sn anı henüz gelmemişse bu aralığı yanlışlıkla atlamaz.
2. Ana evren tamamlanınca sinyaller aynı öncelik ve aynı push tavanıyla
   gönderilir; gözlem taraması bundan sonra çalışır. Gözlem kanalının kendi
   tavanı, sinyal eşikleri, evren ve cooldown değişmedi.
3. Sürekli çalışan tek liderde retry vadesi **5 saniyede bir** denetlenir;
   tarama veya uyku bunu bekletmez. 60/120/240 sn geri çekilme, 4 deneme,
   15 dakika TTL ve aynı alıcıya eşzamanlı ikinci istek engeli korunur.
   `--once` arka plan retry işçisi başlatmaz. Lider kilidi bırakılmadan
   işçi ve devam eden isteği sonlandırılır.
4. Sinyalin referans zamanı, tespit, kuyruğa giriş ve ilk Telegram API kabulü
   ayrı ölçülür. Saatlik sinyalde `bar_time` mumun **açılışıdır**; referans
   bir saat sonraki kapanıştır. S2'de referans funding zamanıdır.
5. Ana dalın `b97b0a6` durumundaki QC tekilleştirme/retry ve eski ölçüm ayrımı
   korundu. Luna kapsamındaki sunum, yerel paper raporu, filtreler, veri
   doğrulama ve test düzeltmeleri aynı teslim paketine dahil edildi.

Yalnız sabit paydaki kazanım **80 saniye**. Ana evrenin seri taraması,
Binance/ağ gecikmesi, S2 gölge veri toplama ve Telegram isteği hâlâ zaman
alır. Bu değişiklik “her mesaj 10 saniyede gelir” garantisi değildir.
Hedef dokunma (TP) alarmları kapalı 5m veriyi tarama sonrasında işlemeyi sürdürür;
onların olay-tespit gecikmesi yeni ana sinyal gecikmesiyle aynı ölçüm değildir.

## Senin yapacakların — sırayla

**1. Kodun aktarımını tamamla.** Mevcut çalışma yerelde hazırlanmıştır;
önceki push/deploy sınırı sürüyor. `main`e gönderildiği teyit edilmeden
mevcut tablet botunu durdurma. İstenirse yerel Git paketiyle aktarım da
yapılabilir; yalnız `git pull` yayımlanmamış kodu getirmez.

**2. Paket main'e gönderildikten sonra, Termux'ta önce kontrol et.**

```bash
cd ~/trade1
git status --short
python signal_bot.py --backup-now
python signal_bot.py --backup-status
```

Takip edilen kodda yerel değişiklik varsa veya yedek hata verirse burada dur;
çıktıyı paylaş. `.env` içeriğini paylaşma. Değişiklikleri silme/resetleme.

**3. Tek botu durdur ve kodu çek.**

```bash
cd ~/trade1
touch .stop-signal-bot
pkill -f "python signal_bot.py" 2>/dev/null || true
pkill -f "uvicorn server:app" 2>/dev/null || true
git pull --ff-only origin main
```

`git pull` hata verirse sonraki adıma geçme. Çıktıyı paylaş; `reset --hard`
kullanma. Başarılıysa yeni dosyanın geldiğini ve sürümü kontrol et:

```bash
git --no-pager log -1 --oneline
test -f TELEGRAM_LATENCY.md && echo "gecikme paketi geldi"
python -m py_compile signal_bot.py notification_delivery.py server.py strategy_engine.py paper_execution.py
```

**4. Ayarı kontrol et.** `nano .env` aç. `SCAN_INTERVAL_MINUTES` varsa **5**
olarak bırak. `SCAN_CLOSE_DELAY_SECONDS` yoksa eklemek zorunda değilsin;
varsayılan **10**. Önceden eklenmişse `SCAN_CLOSE_DELAY_SECONDS=10` yap.
Başka ayarı değiştirme. Kaydet: **Ctrl+O → Enter → Ctrl+X**.
Yeni zorunlu paket yok; bu düzeltme için Python/Termux yükseltmesi gerekmez.

**5. Wrapper'ın durduğunu doğrula, sonra bir kez başlat.**

```bash
pgrep -af "boot-signal-bot.sh|uvicorn server:app|python signal_bot.py"
```

Eski wrapper veya bot görünüyorsa henüz yeniden başlatma; `.stop-signal-bot`
yerinde kalsın, kapanmasını bekle. Wrapper yeniden başlatma beklemesindeyse
en fazla 5 dakika sürebilir. Liste boşalınca:

```bash
rm -f .stop-signal-bot
nohup sh ./termux/boot-signal-bot.sh >/dev/null 2>&1 &
```

**6. Çalışmayı doğrula.**

```bash
pgrep -af "boot-signal-bot.sh|uvicorn server:app|python signal_bot.py"
python notification_delivery.py --status
python signal_bot.py --backup-status
python signal_bot.py --research-status
```

Beklenen: bir wrapper ve bir ana bot (Uvicorn veya doğrudan Python).
Telegram'da bota **`/status`** yaz: kapanış payı **10 sn**, tekrar kontrolü
**5 sn** görünmeli. Bu komut yalnız durum cevabı üretir; yeni sinyal zorlamaz.
Yeni sinyal gelmediyse gecikme alanlarının `null` olması normaldir.

**7. Bir sonraki doğal sinyali ölç.** Mesajdaki **Mum kapanışı** ve **Tespit**
saatlerini kontrol et (UTC; Türkiye saati +3). Sonra:

```bash
python notification_delivery.py --status
```

Bu çıktıyı ve `git log -1 --oneline` sonucunu paylaşabilirsin. Komut salt
okunurdur; mesaj göndermez, tarama başlatmaz, token/alıcı ID'si/log içeriği
çıktıya yazmaz. `--test-notify` mum kapanışından gerçek tarama süresini
ölçmediği için bu kontrolün yerine geçmez.

## Gecikme çıktısını okuma

`latency_seconds`, en son 20 kuyruk olayının geçerli ölçümlerindeki N/medyan/en
yüksek süreyi verir; eski kayıtta tespit zamanı yoksa uydurmaz. Başarısız/henüz
teslim edilmemiş olayın API kabul süresi boş kalır. Son API kabulünün süreleri
ayrıca `latest_ack_latency_seconds` içindedir.

| Alan | Anlamı / yüksekse sonraki kontrol |
|---|---|
| `reference_to_detect` | Mum kapanışı/funding → tespit; zamanlama, piyasa API'si, ana evren ve S2 gölge veri süresi |
| `detect_to_queue` | Tespit → kuyruğa giriş; ana evrenin kalan kısmı ve önceki öncelikli mesajlar |
| `queue_to_ack` | Kuyruk → ilk başarılı Telegram API yanıtı; ağ hatası, timeout, retry ve alıcı sırası |
| `reference_to_ack` | Mum kapanışı/funding → ilk Telegram API kabulü; ilk üç aşamanın toplamı |
| `pending_events` | Henüz en az bir alıcıya teslimi tamamlanmamış kuyruk olayları |

API kabulü telefonun bildirim gösterme zamanı değildir. API kabulü hızlı
olduğu halde telefonda geç görünürse Telegram/Android bildirim ve pil ayarları
ayrıca kontrol edilir. Kısmi teslimde ölçülen ilk alıcının zamanıdır; tüm
alıcılar aynı anda teslim almış sayılmaz.

## Doğrulama ve kalan sınırlar

25 izole Python test paketi ve iki Node pano kontrolü geçti. Yeni 10 regresyon
testi zamanlama sınırları, ana/gözlem sırası ve ayrı push tavanları, funding/
mum zamanı ayrımı, aşama süreleri, salt okunur/sır içermeyen çıktı, retry
vadeleri, yavaş alıcı sonrası TTL, tarama sırasında retry, lider kapanışı ve
`--once` davranışını kapsıyor. Canlı mesaj veya tablet müdahalesi yapılmadı.

Gerçek yeni paper kohortu, funding nakit akışı ve gelecekteki OOS kanıtı
veri gerektirir; bitmiş araştırma olarak gösterilmedi. Ayrıntılar:
[yerel işlerin durumu](research/CORE_EXECUTION_COMPLETION_2026-09-11.md).
