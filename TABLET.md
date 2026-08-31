# Samsung tablette 7/24 çalıştırma (Termux) — önerilen ücretsiz yol

Evde prize takılı bir Android tablet, bu bot için **ücretsiz bulutlardan daha
iyi** bir sunucudur: ev internetinin IP'si temizdir (Binance bulut paylaşımlı
IP'lerini yasaklıyor — Render'ın bu yüzden öldüğünü gördük), aylık ücret yok,
uyku/idle sorunu yok. Bildirimler Telegram ile geldiği için botun
NEREDE koştuğu fark etmez — tablet evde çalışır, sinyaller telefonuna düşer.

> iPhone bu iş için uygun DEĞİL: iOS, arka planda serbest işlem çalıştırmaya
> izin vermez (birkaç dakikada dondurur). Telefonda Telegram bildirimleri ve
> public GitHub Pages panosu kullanılır.

## Kurulum (bir kez, ~15 dk)

### 1) Termux'u kur
- Tabletin tarayıcısından [f-droid.org](https://f-droid.org) → F-Droid'i indir
  ve kur (bilinmeyen kaynak iznini onayla) → F-Droid içinden **Termux**'u kur.
- **Play Store'daki Termux'u KULLANMA** — eski ve bozuk; F-Droid sürümü gerekir.

### 2) Termux içinde botu kur
Termux'u aç, sırayla yaz:

```bash
pkg update -y && pkg upgrade -y
pkg install -y python
```

Kodu tablete indir (iki yoldan biri):

**Yol A — ZIP (kolay):** Tablet tarayıcısında GitHub'a gir →
`ss4181/trade1` → yeşil **Code** → **Download ZIP**. Sonra Termux'ta:
```bash
termux-setup-storage        # izin sorar, onayla
cd ~
unzip ~/storage/downloads/trade1-main.zip
mv trade1-main trade1
cd trade1
```

**Yol B — git/SSH (güncellemeler kolay, token geçmişe yazılmaz):**
```bash
pkg install -y git openssh
ssh-keygen -t ed25519 -C "trade1-tablet"
cat ~/.ssh/id_ed25519.pub
```
Çıkan public anahtarı GitHub → Settings → SSH and GPG keys bölümüne ekle.
Ardından:
```bash
git clone git@github.com:ss4181/trade1.git
cd trade1
```

Her iki indirme yolundan sonra proje bağımlılıklarını kur:

```bash
cd ~/trade1
pip install -r requirements.txt
```

### 3) .env dosyasını oluştur
```bash
cp .env.example .env
nano .env
```
Şu 2 satırı kendi değerlerinle doldur (değerler sende — BotFather
panelinden; kimseyle paylaşma):
```
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
```
Kaydet: `Ctrl+O`, Enter, `Ctrl+X`.
Dosya izinlerini daralt:
```bash
chmod 600 .env
```

### 4) Test et
```bash
python signal_bot.py --test-notify   # Telegram'a TEST mesaji gelmeli
python signal_bot.py --check         # su an aktif kurulumlar
```

### 5) 7/24 başlat
```bash
termux-wake-lock
python -m uvicorn server:app --host 0.0.0.0 --port 8000
```
Bu birleşik mod hem tarama döngüsünü hem `/signals/latest` JSON API'sini
başlatır. Aynı anda ayrıca `python signal_bot.py` çalıştırma; tek-instance
kilidi ikinci tarayıcıyı reddeder.
Termux bildirimi durum çubuğunda kalır — **kaydırıp kapatma** (kapatırsan
işlem ölür). Ekran kapanabilir, sorun değil.

### 6) Samsung'un botu öldürmesini engelle (ÖNEMLİ)
One UI arka plan uygulamalarını agresif kapatır. İkisini de yap:
- **Ayarlar → Uygulamalar → Termux → Pil → Kısıtlanmamış (Unrestricted)**
- **Ayarlar → Pil (→ Arka plan kullanım limitleri) → Uyuyan uygulamalar**
  listesinden Termux'u çıkar / "Hiç uyutulmayan uygulamalar"a ekle.

Tableti prize takılı ve Wi-Fi açık tut.

## Telegram'dan komutla kontrol (tablete hiç dokunmadan)

Bot çalışırken **Telegram'dan bota komut yazabilirsin** — tabletin başına
gitmene gerek yok. Botunla sohbete şunları yaz:

- **/start** veya **/help** — bot yaşıyor mu + komut listesi
- **/check** — şu an aktif kurulumları getirir (birkaç saniye sürer)
- **/performans** — gerçekleşen sinyal sonuçları vs backtest beklentisi
- **/status** — kaç tarama yapıldı, son tarama ne zaman, hata var mı

Ayrıca her gün saat ~09:00'da (TR) tek satırlık **günlük özet** gelir — bu
mesaj gelmiyorsa bot ölmüş demektir (Termux'u kontrol et).

Güvenlik: bot yalnızca **senin** ve **onayladığın** chat'lerden gelen
komutlara cevap verir; botu bulan bir yabancı yalnızca `/myid` ve `/katil`
kullanabilir (ikisi de hiçbir yetki vermez). Yönetim komutları
(`/onayla`, `/kaldir`, `/aboneler`) **sadece** `TELEGRAM_CHAT_ID`'de çalışır.
Bu kurulum açık port/public URL gerektirmez (bot Telegram'a *dışarı* bağlanır —
ev interneti arkasında sorunsuz).

İstersen komutların Telegram'da menü olarak çıkması için: BotFather'a
`/setcommands` yaz, botunu seç, şunu yapıştır:
```
start - bot yasiyor mu + komutlar
check - su an aktif kurulumlar
performans - canli sonuclar vs backtest
status - bot durumu
katil - botu kullanmak icin izin iste
myid - kendi chat ID'in
aboneler - abone listesi (yalniz sahip)
onayla - bekleyen istegi onayla (yalniz sahip)
kaldir - aboneligi kaldir (yalniz sahip)
```

### Düğmeler (komut yazmadan kullan)

Bota **`/start`** yaz → yazı alanının altında kalıcı düğmeler çıkar:
**🔎 Kontrol · 📊 Performans · ℹ️ Durum · ❓ Yardım** (sende ek olarak
**👥 Aboneler**). Bir daha komut yazmana gerek yok; düğmeler sohbette kalır.
Kaybolursa **`/menu`** yaz.

Ayrıca katılım isteği geldiğinde mesajın altında **✅ Onayla / ❌ Reddet**
düğmeleri çıkar — arkadaş eklemek tek dokunuş. Bu düğmeler yalnız sende
çalışır; başkası dokunursa bot "yalnız bot sahibine açık" der.

### Arkadaş ekleme — Yol 1: Telegram'dan onayla (en kolay, önerilen)

`.env` düzenlemek ve botu yeniden başlatmak **gerekmez**:

1. Arkadaşın botu açıp **`/katil`** yazar.
2. Sana Telegram'dan bildirim düşer: adı, chat ID'si ve **✅ Onayla / ❌ Reddet**
   düğmeleri.
3. **✅ Onayla**'ya dokun (ya da `/onayla <id>` yaz).
4. Bitti — arkadaşın anında onay mesajı alır, sinyaller ona da gitmeye başlar.
   Onaylılar diske yazılır, bot yeniden başlasa da korunur.

Diğer yönetim komutları (yalnız sende çalışır):
- **`/aboneler`** — kimler abone + bekleyen istekler
- **`/kaldir <id>`** — aboneliği kaldır

Güvenlik: `/katil` herkese açık ama **hiçbir yetki vermez** — yalnızca sana
istek iletir. Onaylı arkadaşlar **başka arkadaş ekleyemez** (`/onayla` yalnız
`TELEGRAM_CHAT_ID`'de çalışır). `.env`'deki sabit liste ve senin kendi
aboneliğin `/kaldir` ile silinemez.

### Arkadaş ekleme — Yol 2: Telegram grubu (tek sohbette herkes)

Herkesin aynı akışı görmesini istiyorsan grup kur; arkadaş eklemek tamamen
Telegram'ın kendi davet mekanizmasıyla olur:

1. Telegram'da bir grup oluştur, **botu gruba ekle**.
2. Grupta **`/myid`** yaz → bot grubun ID'sini verir (başında `-` olan negatif
   bir sayı, örn. `-1001234567890`).
3. Grupta **`/katil`** yaz → sana istek düşer → **`/onayla -100…`** de.
4. Artık sinyaller gruba düşer. **Yeni arkadaş eklemek = gruba davet etmek**
   (davet bağlantısı/kişi ekle) — botta hiçbir şey yapmana gerek yok.

Şerh: gruptaki **herkes** komut çalıştırabilir (`/check` gibi) ve tüm
sinyalleri görür; yönetim komutları yine yalnız sende. Gruptan çıkardığın kişi
otomatik olarak sinyalleri görmeyi bırakır. Grupta komutları `/check@botadi`
biçiminde yazmak gerekebilir (Telegram gruplarda böyle yönlendirir) — bot her
iki biçimi de kabul eder.

### Arkadaş ekleme — Yol 3: elle `.env` (eski yöntem)

Arkadaşların da `/check` / `/status` kullanabilsin ve otomatik sinyalleri alsın:

1. Arkadaşın botu Telegram'da açıp **/myid** yazsın → bot ona chat ID'sini verir.
2. Arkadaşın o ID'yi sana iletsin.
3. `.env`'de `TELEGRAM_ALLOWED_CHAT_IDS`'e virgülle ekle, örn:
   ```
   TELEGRAM_ALLOWED_CHAT_IDS=11111111,22222222
   ```
4. Botu yeniden başlat (`Ctrl+C` → `python -m uvicorn server:app --host 0.0.0.0 --port 8000`).

Artık listedekiler komut verebilir **ve** yeni sinyaller onlara da düşer.
İzin listesinde olmayan biri komut yazarsa bot yok sayar (yalnızca /myid'e
cevap verir). Tam açık mod istersen `.env`'e `TELEGRAM_OPEN=true` — ama o zaman
botu bulan herkes komut verebilir (otomatik sinyaller yine sadece listedekilere
gider).

## Günlük kullanım

- Sinyaller kendiliğinden Telegram'a gelir; tablete dokunman gerekmez.
- Push edilen bir sinyalden sonra coin fiyatı bildirim fiyatına göre +%2 veya
  +%3 hedefe ulaşırsa bot ayrıca bir kez hedef bildirimi yollar. Bu yüzde
  **brüt coin fiyat değişimidir; ücret/slippage düşülmez, kaldıraçlı ROE
  değildir** ve bot emri kapatmaz.
  Hedef geçmişi web panosunda da görünür. Kayıt `.price_target_state.json`
  dosyasında tutulur; dosyayı elle silme.
- Anlık kontrol için en kolayı Telegram'dan **/check** yazmaktır; çalışan
  Boot servisini durdurmaya gerek yok.
- Tablet yeniden başlarsa: ya aşağıdaki **Otomatik başlatma**yı kur (önerilir)
  ya da Termux'u açıp `cd trade1 && termux-wake-lock && python -m uvicorn server:app --host 0.0.0.0 --port 8000`.

## Otomatik başlatma (Termux:Boot — önerilir)

Tablet yeniden başladığında bot kendiliğinden kalksın:

1. F-Droid'den **Termux:Boot** uygulamasını kur ve **bir kez aç** (şart —
   açmazsan Android boot iznini vermez).
2. Termux'ta:
   ```bash
   mkdir -p ~/.termux/boot
   ln -sfn ~/trade1/termux/boot-signal-bot.sh \
     ~/.termux/boot/boot-signal-bot.sh
   ```
   Symlink kullanıldığı için sonraki `git pull`, Boot betiğinin güncel
   sürümünü otomatik kullanır; yeniden kopyalama gerekmez.
   `chmod +x` **gerekmez** — betik depoda çalıştırılabilir (`100755`) olarak
   kayıtlı. (2026-08-04'e kadar `100644` idi ve dokümanda `chmod +x` yazıyordu;
   Termux'ta `core.fileMode` açık olduğu için bu chmod *yerel değişiklik* sayılıp
   `git pull`'u bloke ediyordu, stash'lenince de betik `Exit 126` veriyordu.)
3. Test: tableti yeniden başlat → 1-2 dk sonra Telegram'dan `/status` at →
   cevap geliyorsa otomatik başlatma çalışıyor. Çıktılar `~/trade1/bot.out.log`
   dosyasına yazılır.

> Boot betiği kuruluyken bot açılışta zaten çalışır. Elle ikinci kopya
> başlatma; tek-instance kilidi bunu reddeder. Durumu
> `pgrep -af "signal_bot.py|uvicorn server:app"` ile kontrol et
> (FastAPI kuruluysa ayrıca `http://127.0.0.1:8000/health`).

### Boot servisini güvenli durdur / güncelle / başlat

```bash
cd ~/trade1
touch .stop-signal-bot
pkill -f "uvicorn server:app"     # wrapper stop dosyasini gorup yeniden baslatmaz
pkill -f "python signal_bot.py" 2>/dev/null || true  # FastAPI yoksa dogrudan mod
termux-wake-unlock

git pull                          # gerekliyse guncelle
rm -f .stop-signal-bot
nohup ./termux/boot-signal-bot.sh >/dev/null 2>&1 &
```

Temiz kapanış veya stop dosyası wake-lock'u bırakır; gerçek bir çökmede wrapper
yeniden dener (ilk denemelerde 15 sn; 5 ardışık başarısızlıktan sonra 5 dk'ya
çıkar ve loga `DIKKAT: ... Bot AYAKTA DEGIL` yazar).

### Arıza: `No module named uvicorn` / paketler kayboldu

**Belirti:** `bot.out.log` aynı satırı sürekli tekrarlar, `pgrep -af "uvicorn
server:app"` boş döner, Telegram komutları cevapsız kalır (komut dinleyicisi
uygulamanın içinde çalıştığı için bot ayakta değilse hiçbir komut işlemez).

**Sebep:** Termux'ta `pkg upgrade` Python'u yükseltince site-packages sürüm
klasörüyle birlikte görünmez olur ve pip ile kurulmuş **tüm** paketler kaybolur.
2026-08-01'de bu yaşandı (Python 3.14'e geçiş); bot 3 gün ayakta değildi. Bulut
yedeği arada sinyal göndermeye devam ettiği için fark edilmesi gecikti.

**Çözüm:**
```bash
cd ~/trade1
git pull
pip install -r requirements.txt
```
Sonra yukarıdaki "güvenli durdur / güncelle / başlat" bloğunu çalıştır.

### `watchfiles` / `maturin` / Rust derleme hatası

Eskiden `uvicorn[standard]` kuruluyordu; extras içindeki **watchfiles** Rust ile
derleniyor ve Android/aarch64 için hazır wheel yok (`Target triple not supported
by rustup: aarch64-unknown-linux-android`). Bu yüzden bağımlılıklar ikiye
ayrıldı:

| Dosya | İçerik | Gerekli mi? |
|---|---|---|
| `requirements.txt` | `requests` + `websocket-client` — saf Python | **Zorunlu.** Tarama, Telegram ve geriye oynatılamayan USD-M likidasyon arşivi bununla çalışır |
| `requirements-server.txt` | + `fastapi`, `uvicorn` (extras YOK) | Opsiyonel. `/signals/latest`, `/health` ve `/ping` HTTP uçları için |

Boot betiği bunu kendi başına yönetir: çekirdek paket eksikse bir kez kurmayı
dener; FastAPI/uvicorn yoksa bir kez `requirements-server.txt` dener, yine
olmazsa **`python signal_bot.py`** ile doğrudan başlar. Bu modda HTTP API
devre dışıdır, **Telegram komutları ve LAN panosu çalışır**.

## Web panosu (telefondan/bilgisayardan izleme)

Bot çalışırken tablet, ev ağında bir izleme sayfası sunar:

1. Tabletin IP'sini öğren — Termux'ta:
   ```bash
   ifconfig 2>/dev/null | grep -A1 wlan0 | grep inet
   ```
   (ya da bot başlarken yazdığı `web panosu: http://...` satırına bak.)
2. **Aynı Wi-Fi'daki** telefonunun/bilgisayarının tarayıcısında aç:
   `http://<tablet-ip>:8181` — telefonda yer imlerine ekle.

Panoda: geçmiş + güncel tüm sinyaller (sessize alınanlar dahil, etiketli),
giriş referansı ve son çıkış zamanı, **AKTİF** sinyallerde güncel fiyata göre
anlık kâr/zarar, **OLGUN** sinyallerde gerçekleşen sonuç, pozisyon tutarı
girişiyle $ karşılığı, strateji kartlarında backtest-vs-canlı karneler ve bot
durum çipleri. 60 sn'de bir kendini yeniler.

> Güvenlik: sayfa yalnızca ev ağında görünür (şifre yok). Modeminde port
> yönlendirme yapıp internete AÇMA. GitHub Pages yolu da şifreli değildir ve
> yayımlanan sinyal verisi herkese açık olur.

Birleşik Uvicorn ayrıca `0.0.0.0:8000` üzerinde `/signals/latest`, `/health`
ve `/docs` uçlarını LAN'a açar. Bunlarda varsayılan kimlik doğrulama yoktur;
yalnız güvendiğin Wi‑Fi/VPN'de kullan, modemden 8000/8181 port yönlendirmesi
yapma. CORS ayarı curl/native istemcileri engelleyen bir güvenlik duvarı değildir.

Panoda **strateji kartına** tıklayınca o stratejinin nasıl çalıştığı (giriş
koşulu, çıkış, backtest, risk) açılır; **sinyal satırına** tıklayınca o
bildirimin tam olarak hangi koşullarla geldiği ("Neden geldi") + fiyat
senaryoları açılır.

## Her yerden erişim (GitHub Pages — evden uzaktayken de)

LAN panosu sadece ev ağında çalışır. Telefonun mobil veriyle her yerden
erişebilmen için bot, pano verisini GitHub'a yazar ve GitHub ücretsiz bir
sayfa olarak sunar. **Not:** bu sayfa herkese açık olur (sen "sorun yok"
dedin); içinde sır yoktur (sadece sinyaller + fiyatlar — token/chat-id/anahtar
ASLA yayımlanmaz, `.env` gitignore'da).

**1) GitHub'da fine-grained token oluştur** (dar yetkili, güvenli):
- [github.com/settings/tokens](https://github.com/settings/tokens) →
  **Fine-grained tokens** → **Generate new token**.
- **Repository access** → *Only select repositories* → `trade1`.
- **Permissions** → *Repository permissions* → **Contents** → **Read and write**.
- Süre (expiration) uzun seç (örn. 1 yıl). **Generate** → token'ı kopyala.

> **"Zaten `git pull` yapabiliyorum, token'ım var" —** o token büyük olasılıkla
> yalnız **okuma** yetkili (git pull için yeterli). Yayımlama **yazma** ister;
> bot okuma-token'ıyla `403` alıp yayını kapatır ve sana net uyarı yazar. Yani
> yukarıdaki adımda **yazma-yetkili** bir token oluştur.

**2) Tablette `.env`'e ekle:**
```bash
cd ~/trade1
nano .env
```
Tek satır yeter — **repo adı git remote'undan otomatik bulunur**:
```
GITHUB_TOKEN=github_pat_...
```
Kaydet (`Ctrl+O`, Enter, `Ctrl+X`), botu yeniden başlat:
```bash
python -m uvicorn server:app --host 0.0.0.0 --port 8000
```
Açılışta `GitHub Pages yayini ACIK ... https://ss4181.github.io/trade1/`
satırını görmelisin. Bot ilk taramada iki branch'i **otomatik oluşturur**:

- `gh-pages`: yalnız değiştiğinde yazılan statik `index.html`
- `trade1-data`: sık güncellenen `data.json`

Bu ayrım, her veri güncellemesinin gereksiz bir Pages build'i başlatmasını
engeller. Senin git ile branch açman gerekmez.

**3) Repo'yu public yap + Pages'i aç** (ücretsiz Pages public repo ister):
- GitHub'da repo → **Settings** → **General** → en altta **Change visibility**
  → **Public** (onayla). *(Kod zaten sır içermiyor; `.env` yüklenmez.)*
- Repo → **Settings** → **Pages** → **Source: Deploy from a branch** →
  Branch: **gh-pages** / **(root)** → **Save**.
- 1-2 dk sonra `https://ss4181.github.io/trade1/` her yerden açılır (mobil
  veriyle de). Telefonda ana ekrana kısayol ekleyebilirsin.

Pano orada ~15 dakikada bir güncellenir (bot her yayında GitHub'a yazar).
Daha sık/seyrek istersen `.env`'e `PUBLISH_INTERVAL_MIN=10` gibi ekle.
Varsayılan branch adlarını değiştirirsen `GITHUB_PAGES_BRANCH` ile
`GITHUB_DATA_BRANCH` farklı kalmalıdır. Watchdog varsayılan olarak
`trade1-data/data.json` okur.

> İptal etmek istersen: `.env`'den `GITHUB_TOKEN`'ı sil → bot artık yayımlamaz;
> istersen GitHub'da token'ı da revoke et ve repo'yu tekrar private yap.

## Türev arşivi (otomatik — gelecek araştırma verisi)

Bot üç bağımsız arşiv ailesi tutar:

1. Her saat evrendeki sembollerin **OI + bazis + fiyat + genel hesap
   long/short + taker buy/sell + funding görüntüsünü**
   `market_archive_YYYY-MM.jsonl` dosyasına yazar. Long/short oranı hesap
   sayısıdır; yatırılan para/pozisyon büyüklüğü değildir.
2. Ayrı bir WebSocket worker'ı tüm USD-M piyasasındaki gerçekleşmiş
   likidasyon snapshot'larını ve bağlantı/kesinti anlarını
   `liquidation_archive_YYYY-MM.jsonl` dosyasına yazar. Bu, Binance'in sembol
   başına 1000 ms'deki son olayı veren snapshot akışıdır; eksiksiz tape değildir.
3. `shadow_market_YYYY-MM.jsonl` ve `shadow_events_YYYY-MM.jsonl`, G1'in tüm
   aktif USD-M evrenindeki ilk-10 yükselen incelemelerini ve DL1'in resmî
   tam-token delist + Binance/Bybit/OKX snapshot'larını tutar. Bunlar işlem
   değildir; tarihsel kapıları geçmemiş ileri araştırma olaylarıdır.

Yeni sürümü çektikten sonra bağımlılığı ve botu yenile:

```bash
cd ~/trade1
touch .stop-signal-bot
pkill -f "uvicorn server:app" 2>/dev/null || true
pkill -f "python signal_bot.py" 2>/dev/null || true
termux-wake-unlock 2>/dev/null || true
git pull
pip install -r requirements.txt
rm -f .stop-signal-bot
nohup ./termux/boot-signal-bot.sh >/dev/null 2>&1 &
```

Başlangıç logunda `USD-M likidasyon arsivi basladi` ve `golge deneyler acik`
görünmelidir. Başka bir
terminalden dosya kapsamını istediğin an kontrol edebilirsin:

```bash
cd ~/trade1
python signal_bot.py --archive-status
python signal_bot.py --shadow-status
python signal_bot.py --research-status
ls -lh market_archive_*.jsonl liquidation_archive_*.jsonl shadow_*.jsonl 2>/dev/null
```

Telegram'da `/arastirma` yazınca OI/funding/long-short/basis alanlarının
doluluğunu, saat kapsamasını, likidasyon günlerini ve ilk değerlendirmeye kalan
süreyi görürsün. Bot aynı raporu varsayılan olarak her pazartesi 09:00 Türkiye
saatinden sonraki ilk taramada otomatik gönderir. Bu haftalık döngü yalnız veri
sağlığını günceller; strateji eşiklerini otomatik değiştirmez.

Protokol: ilk 90 gün keşif ve veri-kalitesi, ardından aday kuralın ön-kaydı;
`RESEARCH_OOS_START_UTC` bu dondurma anında yazılır ve sonraki 90 gün yalnız
dokunulmamış OOS veri toplanır. 180 günlük döngü tamamlanmadan OI stratejisi
canlı/güvenilir etiketi alamaz.

Henüz likidasyon olayı gelmediyse dosyada yalnız `connected` durum satırı
bulunması normaldir. `--archive-status`, kaç olay ve durum kaydı bulunduğunu,
ilk/son olay zamanını gösterir. Web sunucusu kullanılıyorsa `/health` içindeki
`force_order_archive.connected` alanı canlı bağlantıyı doğrular.

Dosyalar `.gitignore` kapsamındadır; GitHub'a ve public panoya yüklenmez. Ayda
bir harici diske/özel buluta yedeklemek gerekir. Kapatmak istersen `.env` içine
`ARCHIVE_MARKET_DATA=false` veya `ARCHIVE_FORCE_ORDERS=false` ekle. Dosyaları
G1/DL1'i tamamen kapatmak için `SHADOW_EXPERIMENTS_ENABLED=false`, yalnız
Telegram mesajlarını susturup veri toplamayı sürdürmek için
`SHADOW_PUSH_ENABLED=false` ekle. Dosyaları
silme: anlamlı değerlendirme için en az 3–6 ay ve yeterli bağımsız olay günü
gerekecek.

## Sınırlar

- Ev interneti/elektrik kesilirse bot da durur (dönünce elle başlat).
- Bu bir uyarı botudur; işlem açmaz. Yatırım tavsiyesi değildir.
