# signal_bot — veriyle doğrulanmış kripto sinyal botu

Binance spot/perp piyasalarını saatlik tarar, üç stratejiden sinyal üretir.
Tüm eşikler **24 aylık (2024-07 → 2026-06), 30 sembollü, 1 saatlik** Binance
verisiyle test edilerek seçildi — metodoloji, tarama tabloları ve gerekçeler:
[research/REPORT.md](research/REPORT.md).

## Fable Araştırma Bulguları — stratejiler ve güncel eşikler

> ⚠️ **Bu eşikler bir backtesting araştırmasının (Fable 5, 2024-07→2026-06)
> çıktısıdır — keyfî değiştirilmemeli.** Tam gerekçe zinciri, tarama tabloları
> ve train/test protokolü [research/REPORT.md](research/REPORT.md)'de. Değişiklik
> gerekiyorsa oradaki §10 (izleme) yöntemini izle; tek pencerede "en iyi"yi seçme.

| | Sinyal | Eşik (eski → yeni) | Yön | Ufuk | Test (2026H1, ayı) kanıtı |
|---|---|---|---|---|---|
| **S1** | RSI uyumsuzluğu | `RSI_OVERSOLD` 20 → **22.5** | Sadece LONG | ~24h | edge +0.31 vol, p=0.006, WR %59 |
| **S2** | Funding squeeze | `-0.02` → **−0.03%** + **persistence 2** | LONG | ~72h | edge +0.14, p=0.08 (marjinal — izle) |
| **S3** | Hacim anomalisi | ham z 3.0 → **log-z 3.0 + sadece yukarı bar** | Sadece LONG | ~4h | edge +0.25 vol, p<0.001 |
| **S4** | Confluence etiketi | S1 + son 24h'te hacim patlaması → **STRONG** | LONG | 24–72h | edge +0.38, p=0.006, WR %64 |

"Edge": sinyal sonrası volatilite-normalize getiri − aynı sembolün koşulsuz
ortalaması (yani piyasa sürüklenmesinden arındırılmış fazla getiri).

### Kaldırılanlar (ve neden)

- **RSI_OVERBOUGHT / short sinyali**: 70–90 arası her eşikte negatif edge.
  Kripto'da 1h RSI aşırı alımı dönüş değil momentum devamı işareti çıktı.
- **Ham hacim z-skoru**: saatlik hacim aşırı kalın kuyruklu; ham z=3.0 ayda
  sembol başına ~10 sinyal (spam) ve önemsiz edge üretiyordu.
- **Hacim patlamasında short (aşağı-bar devamı)**: test döneminde negatif.
- **Funding'de sembol-göreli z-skoru** (denenen yeniden tasarım): train'de
  parlak, testte çöktü → mutlak seviye eşiği korundu.

## Sembol evreni (varsayılan statik)

`SYMBOLS` env'i boşsa bot varsayılan olarak araştırmayla doğrulanmış
**30 çekirdek + 59 genişletilmiş = 89 statik coin** tarar. Genişletilmiş
59 coinde yalnız S1 ailesi çalışır; S2 ve S3 bu grupta OOS başarısız olduğu
için hesaplanmaz.

Hacme göre dinamik ilk 120 coin evreni yalnızca `SYMBOL_AUTO=true` ile açılır.
Bu mod, yeni/pump-dump coinleri içeri alabildiği ve canlı takipte ciddi evren
kontaminasyonu ürettiği için varsayılan değildir. Ayrıntılı uyarılar ve filtreler
`.env.example` içindedir.

## Bildirimlerdeki referans seviyeleri

Her sinyal, 24 aylık backtest dağılımından türetilen **mekanik referanslar**
içerir: giriş referansı (bar kapanışı), **zaman çıkışı** (backtest'te
doğrulanan tek çıkış kuralı: S1 ~24h, S2 ~72h, S3 ~4h), tarihsel medyan /
kötü %10 / iyi %10 senaryolarının fiyat karşılıkları ve ±1σ dalgalanma bandı.
**Bunlar tavsiye değildir**; fiyat-bazlı stop/hedef backtest'te test edilmedi
ve kaldıraç kayıpları/tasfiye riskini büyütür.

## Çalıştırma (yerel)

```bash
pip install -r requirements.txt
cp .env.example .env            # bildirim anahtarlarini doldur (opsiyonel)
python signal_bot.py --check    # ŞU AN aktif kurulumlar (bildirim yok) — istedigin an calistir
python signal_bot.py            # 7/24 döngü: varsayılan 5 dakikada bir tarar
python signal_bot.py --once     # tek dongu adimi (kenar-tetikleme; canli davranis testi)
```

**`--check` vs `--once` farkı (önemli):**
- **`--check`** → "şu an uygun kurulum var mı?" sorusunun cevabı. O anda **aktif
  olan tüm koşulları** listeler (kenar-tetikleme aranmaz), bildirim göndermez,
  sadece terminale yazar. İstediğin an, elinle çalıştırdığın komut budur.
- **`--once` / sürekli döngü** → *canlı bildirim* mantığı: sinyal yalnızca koşul
  yeni **oluştuğunda** (False→True geçiş) üretilir, spam olmasın diye. Bu yüzden
  `--once` soğuk başlangıçta çoğu zaman "0 sinyal" der — bu bir hata değil,
  tasarım; anlık durumu görmek için `--check` kullan.

Binance için API anahtarı gerekmez (yalnızca halka açık uçlar). Sinyaller
stdout'a ve `signals.log`'a (JSONL) yazılır; ayrıca **Telegram + email**
gönderilir (anahtar tanımlıysa — yoksa o kanal sessizce atlanır).

7/24 web servisi olarak (mobil endpoint dâhil) çalıştırmak için aşağıdaki
**tek birleşik modu** kullan. Aynı anda ayrıca `python signal_bot.py` başlatma;
tek-instance kilidi ikinci kopyayı reddeder:

```bash
uvicorn server:app --host 0.0.0.0 --port 8000
# /ping = proses liveness
# /health = tarama readiness; ölü/eski taramada HTTP 503
# /signals/latest = mobil sinyal sözleşmesi
```

`--workers 2` gibi çok-worker kullanma: sinyal tamponu proses içi olduğu için
sunucu başlangıçta tek tarama liderini zorunlu kılar ve lider olamayan worker'ı
reddeder. Ölen tarama thread'i watchdog tarafından yeniden başlatılır.

## 7/24 Deploy + bildirimler + iPhone

- **7/24 çalıştırma (önerilen, ücretsiz):** evdeki Android tablet + Termux —
  [TABLET.md](TABLET.md). (Render yolu ölü: Binance bulut paylaşımlı IP'lerini
  yasaklıyor — 451/418; ayrıntı [DEPLOY.md](DEPLOY.md) başındaki uyarıda.)
- **Bildirim testi:** `python signal_bot.py --test-notify` — .env'deki
  anahtarlarla her iki kanala TEST mesajı yollar; gerçek sinyal beklemeden
  kurulumu doğrular.
- **Telegram komutları** (7/24 döngü çalışırken): bota `/start`, `/check`
  (şu an aktif kurulumlar), `/status`, `/myid` yazabilirsin. getUpdates
  long-polling ile çalışır (public URL/açık port gerekmez).
  Kapatmak: `TELEGRAM_COMMANDS=false`.
- **Web panosu:** bot çalışırken `http://<cihaz-ip>:8181` (yalnız yerel ağ) —
  sinyal geçmişi, aktiflerde anlık K/Z, olgunlarda gerçekleşen sonuç,
  backtest-vs-canlı strateji karneleri. **Strateji kartına** tıkla → nasıl
  çalışır; **sinyal satırına** tıkla → neden geldi. Ayrıntı: [TABLET.md](TABLET.md).
- **Her yerden erişim (GitHub Pages):** `GITHUB_TOKEN`+`GITHUB_REPO`
  tanımlıysa bot panoyu `https://<kullanıcı>.github.io/<repo>/` adresine
  yayımlar (public). Kurulum: [TABLET.md](TABLET.md) "Her yerden erişim".
- **Arkadaş paylaşımı:** `TELEGRAM_ALLOWED_CHAT_IDS`'e eklenen chat'ler komut
  verebilir ve otomatik sinyalleri alır (abone). Arkadaş kendi ID'sini `/myid`
  ile öğrenir. Listede olmayan biri yalnızca `/myid` alır, gerisi yok sayılır.
  Tam açık mod: `TELEGRAM_OPEN=true`.
- **Bildirimler:** push izni verilen her sinyal **hem Telegram hem email** ile gider (biri
  diğerinin yerine geçmez). Anti-spam tek kapıdan yönetilir (`ScanState`
  kenar-tetikleme + strateji-başı cooldown); iki kanal aynı deduplike sinyali
  alır. Eşik altı ve tarama tavanını aşan kayıtlar `push_allowed=false`,
  `suppressed=true` ve gerekçesiyle API/log'da kalır; mobil istemci bu kararı
  geçersiz kılmaz. Anahtar adları: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`,
  `RESEND_API_KEY`, `NOTIFICATION_EMAIL` (bkz. `.env.example`).
- **iPhone:** [mobile/](mobile/) — Expo Go uygulaması. Sunucuyu pollar, yeni
  sinyalde **yerel bildirim** gösterir. Kısıt: yalnızca uygulama **açıkken**
  çalışır (Expo Go SDK 53 uzak push desteklemez); 7/24 kaçırmasız uyarı için
  Telegram/email vardır. Kurulum: [mobile/README.md](mobile/README.md).

## Bilinen sınırlar

- Uyarı botudur; işlem maliyeti/slipaj modellenmedi, yatırım tavsiyesi değildir.
- S2 edge'i ayı rejiminde zayıfladı ve sinyaller az sayıda sembolde
  yoğunlaşıyor (top-5 payı ~%60) — canlıda takip edilmeli.
- S3'ün nihai biçimi test verisine ikinci bakışla seçildi (rapor §S3'te
  açıklanan çoklu-hipotez şerhi) → güven düzeyi "orta".
- Sembol seti bugün likit olan coinlerden kuruldu (survivorship);
  bot da aynı evreni taradığı için deploy ile tutarlı, ama "her coin'de
  çalışır" iddiası yok.
- `/signals/latest` varsayılan olarak kimlik doğrulamasızdır. İnternete
  açacaksan VPN/Tailscale veya ters proxy kimlik doğrulaması kullan; GitHub
  Pages yayınının herkese açık olduğunu unutma.
- `0.0.0.0:8000` ile çalıştırıldığında `/signals/latest`, `/health` ve `/docs`
  aynı yerel ağdaki cihazlara açıktır. `CORS_ALLOW_ORIGINS` tarayıcı
  kısıtlamasıdır, kimlik doğrulama değildir; yalnız güvendiğin LAN/VPN'de aç.

## Doğrulama testleri

```bash
python -B tests/offline_tests.py
python -B tests/server_tests.py
cd research && python -B -m unittest -v test_methodology.py
cd ../mobile && npm ci && npm run check && npm run doctor
```
