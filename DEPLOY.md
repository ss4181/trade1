# Deploy — signal_bot 7/24 (Render, ücretsiz)

Bu rehber botu **kredi kartı gerektirmeden**, bilgisayarın kapalıyken de çalışan
bir Render web servisine kurar. Adımları sırayla yap; her adım ekran görüntüsü
gerektirmeyecek kadar açık.

> **Güvenlik:** Hiçbir API anahtarını/token'ı bu repoya, koda veya git commit'e
> yazma. Tüm gizli değerler yalnızca **Render panelindeki Environment** bölümüne
> girilir. `.env` dosyası `.gitignore`'da — yanlışlıkla push edilmez.

Neden Render? Railway'in ücretsiz planı aylık yalnızca ~1$ kredi verir (sürekli
çalışan bir döngü bunu 1-2 günde bitirir); Fly.io 2024'ten beri yeni kullanıcıya
ücretsiz katman vermiyor ve kart istiyor. Render'ın ücretsiz **web servisi**
kartsız ve 7/24 (750 saat/ay = bir servis için yeterli). Tek şart: 15 dk boşta
kalınca uyur → bunu bir dış "pinger" ile çözüyoruz (Adım 5).

---

## Adım 0 — Gereksinimler (senin bilgisayarında)

- **Git** kurulu olmalı ([git-scm.com](https://git-scm.com/downloads)).
- Bir **GitHub** hesabı ([github.com](https://github.com), ücretsiz).

## Adım 1 — Kodu GitHub'a yükle

`trade1` klasöründe bir terminal aç ve şunları çalıştır:

```bash
git init
git add .
git commit -m "signal bot: 7/24 servis + bildirim + mobil"
```

Sonra GitHub'da **yeni, boş, private bir repo** oluştur (adı örn. `signal-bot`;
"Add a README" işaretleme — boş olsun). GitHub sana repo URL'ini gösterir. Onunla:

```bash
git remote add origin https://github.com/KULLANICI_ADIN/signal-bot.git
git branch -M main
git push -u origin main
```

> `.gitignore` sayesinde `.env`, `signals.log` ve ham araştırma verisi
> yüklenmez — yalnızca kod ve yapılandırma gider.

## Adım 2 — Render hesabı aç

1. [render.com](https://render.com) → **Get Started** → **GitHub ile** kaydol
   (kredi kartı istemez).
2. Render'a GitHub repolarına erişim izni ver (sadece `signal-bot` repo'suna
   izin vermen yeterli).

## Adım 3 — Servisi oluştur (Blueprint ile — en kolay)

Repo kökünde hazır bir `render.yaml` var; Render bunu otomatik okur.

1. Render panelinde **New +** → **Blueprint**.
2. `signal-bot` repo'nu seç → **Connect**.
3. Render `render.yaml`'ı okur ve bir **web servisi** (`signal-bot`, plan:
   **Free**) önerir. Bu ekranda gizli ortam değişkenlerini (`sync:false`
   olanları) girmeni ister — **Adım 4'teki değerleri** buraya yapıştır.
4. **Apply** / **Create** de. Build başlar (birkaç dakika: `pip install`).

Bittiğinde servisin bir adresi olur: `https://signal-bot-XXXX.onrender.com`.
Tarayıcıda aç — bir durum sayfası ve "Tarama thread'i canlı: evet" görmelisin.

> **Alternatif (Blueprint çıkmazsa):** New + → **Web Service** → repo'yu seç →
> Runtime: **Python 3** → Build Command: `pip install -r requirements.txt` →
> Start Command: `uvicorn server:app --host 0.0.0.0 --port $PORT` → Plan:
> **Free** → ortam değişkenlerini **Environment** sekmesinden ekle.

## Adım 4 — Ortam değişkenleri (Render > Environment)

Aşağıdaki **değişken adlarını** Render'ın Environment bölümüne ekle ve
**kendi değerlerini** karşılarına yapıştır (değerleri bana/koda yazma):

| Değişken | Ne | Nereden (aşağıda) |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | Telegram bot token'ı | Adım 4a |
| `TELEGRAM_CHAT_ID` | Sana mesaj gidecek chat id | Adım 4a |
| `RESEND_API_KEY` | Resend email API anahtarı | Adım 4b |
| `NOTIFICATION_EMAIL` | Email'in gideceği adres (kendi email'in) | Adım 4b |
| `EMAIL_FROM` | (opsiyonel) gönderen; boş bırak = sandbox | Adım 4b |

Not: hepsi boş bırakılırsa bot yine çalışır, sadece o kanaldan bildirim atmaz.
Her değişikliğin ardından Render servisi otomatik yeniden başlatır.

### Adım 4a — Telegram token + chat id

1. Telegram'da **@BotFather**'ı aç, `/newbot` yaz, bir isim ver. BotFather sana
   bir **token** verir → `TELEGRAM_BOT_TOKEN`.
2. Yeni oluşturduğun bota Telegram'dan bir "merhaba" mesajı gönder (bu şart —
   yoksa bot sana yazamaz).
3. Chat id'ni öğren: Telegram'da **@userinfobot**'a yaz; sana **Id** değerini
   söyler → `TELEGRAM_CHAT_ID`. (Alternatif: tarayıcıda
   `https://api.telegram.org/botTOKEN/getUpdates` aç, `"chat":{"id":...}`
   değerini al.)

### Adım 4b — Resend email

1. [resend.com](https://resend.com) → ücretsiz kaydol (kalıcı 3000 email/ay).
2. **API Keys** → **Create API Key** → değeri kopyala → `RESEND_API_KEY`.
3. `NOTIFICATION_EMAIL` = email'lerin gitmesini istediğin kendi adresin.
4. **Kendi alan adın yoksa** `EMAIL_FROM`'u boş bırak (varsayılan
   `onboarding@resend.dev`). Bu durumda Resend sandbox kuralı gereği email
   **yalnızca Resend hesabına kayıtlı/doğrulanmış kendi adresine** gider —
   `NOTIFICATION_EMAIL`'i o adresle aynı yap. (İleride kendi alan adını
   doğrularsan istediğin adrese gönderebilirsin.)

## Adım 5 — Uykuyu engelle (keep-alive pinger)

Render ücretsiz web servisi **15 dk** boşta kalınca uyur; ilk istek 30-60 sn
gecikir. Bunu ücretsiz bir pinger'la çözüyoruz:

1. [cron-job.org](https://cron-job.org) → ücretsiz kaydol.
2. **Create cronjob** → URL: `https://signal-bot-XXXX.onrender.com/ping` →
   aralık **her 10 dakika** (`*/10 * * * *`) → kaydet.

Artık her 10 dk'da bir `/ping` çağrılır, servis uyanık kalır.

> **Neden `/ping`, `/health` değil:** `/health` zengin bir teşhis JSON'u
> döndürür ve bazı ücretsiz pinger'lar (cron-job.org dâhil) yakaladıkları cevap
> gövdesini sınırlar → "response larger than allowed limit" hatası. `/ping`
> yalnızca `ok` (2 bayt) döner; keep-alive için tek gereken budur. `/health`'i
> tarayıcıdan durum bakmak için kullanmaya devam et.

> **Neden UptimeRobot değil:** UptimeRobot 2024 sonundan itibaren ücretsiz
> planı "yalnızca ticari olmayan kişisel kullanım" ile sınırladı (ticari/gelir
> getiren kullanım ToS'a göre yasak). Bu bot kişisel/hobi amaçlı olduğu için
> aslında sorun olmazdı, ama cron-job.org'da böyle bir kısıt hiç yok, kurulumu
> aynı derecede kolay ve 15 yılı aşkın süredir bu tür "keep-alive" işleri için
> yaygın kullanılıyor — o yüzden birincil öneri olarak onu seçtim. UptimeRobot'u
> tercih edersen aynı adımlar geçerli, tek fark aralığın sabit 5 dk olması.

> Uyarı: Render workspace'inde **başka ücretsiz servis çalıştırma** — 750
> saat/ay tüm ücretsiz servisler için ortaktır; ikinci bir servis limiti aşar.

## Adım 6 — Doğrula

- `https://signal-bot-XXXX.onrender.com/health` → `"status":"ok"` ve
  `"scan_thread_alive":true` görmelisin.
- `.../signals/latest` → `{"count":0,...}` (henüz sinyal yoksa normal; sinyal
  ürettikçe dolacak).
- İlk gerçek sinyalde Telegram + email gelmeli. (Sinyaller saatte bir, gerçek
  piyasa koşuluna göre üretilir — hemen gelmeyebilir; bu beklenen davranış.)

---

Deploy'u tamamladığında (servis ayakta, `/health` "ok" dönüyor) bana haber ver
— **Faz 3'ün mobil kurulumunu** ([mobile/README.md](mobile/README.md)) birlikte
tamamlarız (o adım da senin telefonunda QR taraman gerektiği için sende).
