# Samsung tablette 7/24 çalıştırma (Termux) — önerilen ücretsiz yol

Evde prize takılı bir Android tablet, bu bot için **ücretsiz bulutlardan daha
iyi** bir sunucudur: ev internetinin IP'si temizdir (Binance bulut paylaşımlı
IP'lerini yasaklıyor — Render'ın bu yüzden öldüğünü gördük), aylık ücret yok,
uyku/idle sorunu yok. Bildirimler Telegram/email ile geldiği için botun
NEREDE koştuğu fark etmez — tablet evde çalışır, sinyaller telefonuna düşer.

> iPhone bu iş için uygun DEĞİL: iOS, arka planda serbest işlem çalıştırmaya
> izin vermez (birkaç dakikada dondurur). iPhone'un rolü izleyicilik
> (Telegram bildirimleri / istersen mobile/ altındaki Expo uygulaması).

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
pip install requests resend
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

**Yol B — git (güncellemeler kolay olur):** GitHub'da okuma-izinli bir
fine-grained token oluştur (Settings → Developer settings → Tokens), sonra:
```bash
pkg install -y git
git clone https://KULLANICI:TOKEN@github.com/ss4181/trade1.git
cd trade1
```

### 3) .env dosyasını oluştur
```bash
cp .env.example .env
nano .env
```
Şu 4 satırı kendi değerlerinle doldur (değerler sende — BotFather ve Resend
panelinden; kimseyle paylaşma):
```
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
RESEND_API_KEY=...
NOTIFICATION_EMAIL=...
```
Kaydet: `Ctrl+O`, Enter, `Ctrl+X`.

### 4) Test et
```bash
python signal_bot.py --test-notify   # Telegram + email'e TEST mesaji gelmeli
python signal_bot.py --check         # su an aktif kurulumlar
```

### 5) 7/24 başlat
```bash
termux-wakelock              # cihaz uyusa da islem calissin
python signal_bot.py
```
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

Güvenlik: bot yalnızca **senin** chat'inden (`.env`'deki `TELEGRAM_CHAT_ID`)
gelen komutlara cevap verir; botu bulan bir yabancı komut veremez. Bu, açık
port/public URL gerektirmez (bot Telegram'a *dışarı* bağlanır — ev interneti
arkasında sorunsuz).

İstersen komutların Telegram'da menü olarak çıkması için: BotFather'a
`/setcommands` yaz, botunu seç, şunu yapıştır:
```
start - bot yasiyor mu + komutlar
check - su an aktif kurulumlar
performans - canli sonuclar vs backtest
status - bot durumu
myid - kendi chat ID'in
```

### Arkadaşlarını ekleme

Arkadaşların da `/check` / `/status` kullanabilsin ve otomatik sinyalleri alsın:

1. Arkadaşın botu Telegram'da açıp **/myid** yazsın → bot ona chat ID'sini verir.
2. Arkadaşın o ID'yi sana iletsin.
3. `.env`'de `TELEGRAM_ALLOWED_CHAT_IDS`'e virgülle ekle, örn:
   ```
   TELEGRAM_ALLOWED_CHAT_IDS=11111111,22222222
   ```
4. Botu yeniden başlat (`Ctrl+C` → `python signal_bot.py`).

Artık listedekiler komut verebilir **ve** yeni sinyaller onlara da düşer.
İzin listesinde olmayan biri komut yazarsa bot yok sayar (yalnızca /myid'e
cevap verir). Tam açık mod istersen `.env`'e `TELEGRAM_OPEN=true` — ama o zaman
botu bulan herkes komut verebilir (otomatik sinyaller yine sadece listedekilere
gider).

## Günlük kullanım

- Sinyaller kendiliğinden Telegram + email'e gelir; tablete dokunman gerekmez.
- Anlık kontrol için artık en kolayı: Telegram'dan **/check** yaz. (Alternatif:
  Termux'ta `Ctrl+C` → `python signal_bot.py --check` → tekrar
  `python signal_bot.py`.)
- Tablet yeniden başlarsa Termux'u açıp `cd trade1 && termux-wakelock &&
  python signal_bot.py` yazman yeterli. (Tam otomatik istersen F-Droid'den
  **Termux:Boot** eklentisi kurulabilir — opsiyonel.)

## Sınırlar

- Ev interneti/elektrik kesilirse bot da durur (dönünce elle başlat).
- Bu bir uyarı botudur; işlem açmaz. Yatırım tavsiyesi değildir.
