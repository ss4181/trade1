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

## Sembol evreni (otomatik)

`SYMBOLS` env'i boşsa bot evreni kendisi kurar: **USDT spot çifti + aktif
USDⓈ-M perp'i olan coinler, perp 24h hacmine göre sıralı ilk
`SYMBOL_MAX_COUNT` (varsayılan 120)** — perp hacmi ≥ 10M$, spot ≥ 1M$
tabanlarıyla. Sıralama perp hacmiyle yapılır: işlem perp'te açılır ve mutlak
spot eşiği rejime göre kırılır (ayıda spot hacimler çöker). Evren günde bir
yenilenir; stabil/pegli varlıklar (USDC, PAXG, WBTC…) hariç.
Bu kural araştırma evreninin tanımıyla aynıdır ("likit + hem spot hem perp") —
eşikler likit-dışı coinlerde **doğrulanmadı**, hacim filtresi bilerek var.

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
python signal_bot.py            # 7/24 dongu: saatte bir tarar, tetikte Telegram+email atar
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

7/24 web servisi olarak (mobil endpoint dâhil) çalıştırmak için:

```bash
uvicorn server:app --host 0.0.0.0 --port 8000
# /health, /signals/latest, / (durum sayfasi)
```

## 7/24 Deploy + bildirimler + iPhone

- **7/24 çalıştırma (önerilen, ücretsiz):** evdeki Android tablet + Termux —
  [TABLET.md](TABLET.md). (Render yolu ölü: Binance bulut paylaşımlı IP'lerini
  yasaklıyor — 451/418; ayrıntı [DEPLOY.md](DEPLOY.md) başındaki uyarıda.)
- **Bildirim testi:** `python signal_bot.py --test-notify` — .env'deki
  anahtarlarla her iki kanala TEST mesajı yollar; gerçek sinyal beklemeden
  kurulumu doğrular.
- **Bildirimler:** her sinyal **hem Telegram hem email** ile gider (biri
  diğerinin yerine geçmez). Anti-spam tek kapıdan yönetilir (`ScanState`
  kenar-tetikleme + strateji-başı cooldown); iki kanal aynı deduplike sinyali
  alır. Anahtar adları: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`,
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
