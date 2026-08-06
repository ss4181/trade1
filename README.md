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

## Gözlem kanalı — S5 / S6 (doğrulanmamış, ayrı kova)

Doğrulanmış 89 coinin **dışında** kalan dinamik evren sembollerinde (perp/spot
likidite süzgecinden geçenler) **yalnız S1 ailesi** çalışır:

| Ad | Karşılığı | Ufuk |
|---|---|---|
| **S5** | dinamik evrende S1+S4 (hacimli kapitülasyon) | 24s |
| **S6** | dinamik evrende sade S1 | 24s |

Ölçülen hacim (2026-08, 28 evren-dışı sembol, son 30 gün): S5 ~0.1/gün,
S6 ~0.4/gün. Karşılaştırma için doğrulanmış akış ~1.8/gün.

| | Doğrulanmış yol | Gözlem kanalı |
|---|---|---|
| Eşikler | değişmedi | değişmedi (aynı S1 eşiği) |
| Güven kademesi | ÇOK YÜKSEK…DÜŞÜK | **yok** (`GOZLEM`) |
| Backtest referans seviyeleri | gösterilir | **gösterilmez** |
| `/performans` | strateji kovaları | **ayrı blok**, karşılaştırma yok |
| `qc_export` paketi | girer | **girmez** (`observation_channel`) |
| `/health` hata oranı | sayılır | **sayılmaz** (en iyi çaba) |

**Neden var:** Evren dışı coinlerde seçilmiş birkaç kurulumun sonucu, Ek F'nin
ölçümüyle çelişiyor. Ek F o evrenin ürettiği **tüm** sinyalleri 24s
zaman-çıkışıyla ölçtü (canlı S1 medyanı −22%); tekil olumlu örnekler ise hem
küçük sayıda hem de seçim etkisi taşıyor — kanıt değil. Kanal bu çelişkiyi
2–3 ayda sistematik ölçümle kapatmak için var. Ek F'nin asıl zararı
doğrulanmamış coinlerin ana akışa **karışmasıydı**; ayrı kova bunu yapısal
olarak engelliyor.

Kapatma: `OBSERVE_ENABLED=false` · Sadece susturma (ölçüm sürer):
`OBSERVE_PUSH=false`

Varsayılan `OBSERVE_PUSH=true` olduğundan, istek üzerine S5/S6 Telegram
bildirimleri açıktır. `GOZLEM` etiketi bir başarı/güven seviyesi değil;
backtest bulunmadığını özellikle anlatır.

Yeni bağımsız strateji adayı olarak sabit kurallı long-only VWAP mean-reversion
(`S7`) sınandı. Çekirdek-30 train'de N=251, net ortalama −%0.219, isabet %51.8
ve gün-kümeli p=0.8803 çıktığı için önceden kayıtlı kapıda elendi; test dilimine
bakılmadı ve canlı bota eklenmedi. Ayrıntı: `research/REPORT.md` Ek L.

Ön-kayıtlı 4h Donchian long/flat trend adayı (`D1`) da sınandı. Net beklenti
pozitif görünmesine rağmen coinler arası gün kümelenmesi nedeniyle çekirdek
train anlamlılık kapısını geçmedi (`p=0.1580`); test dilimine bakılmadı ve canlı
veya shadow kanala eklenmedi. Ayrıntı: `research/REPORT.md` Ek M.

Delta-nötr spot long + perp short carry adayı (`C1`) 89 sembolün eksiksiz
spot/perp/funding verisiyle sınandı. Funding geliri maliyet ve basis PnL'ını
karşılamadı (train net ortalama çekirdek −%0.124, geniş −%0.094); test dilimine
bakılmadı ve canlı bota eklenmedi. Ayrıntı: `research/REPORT.md` Ek N.

Cross-sectional relative-strength sepeti (`R1`) de ön-kayıtlı olarak sınandı.
Çekirdekte alpha anlamlı değildi (`p=0.1816`, max drawdown −%64.4); bağımsız
geniş evrende net ve alpha negatifti. Test dilimine bakılmadı ve canlı/shadow
kanala eklenmedi. Ayrıntı: `research/REPORT.md` Ek O.

Pump + short-crowding + OI düşüşü + agresif alış + funding sıçraması (`L1`)
resmî USD-M metrics verisiyle sınandı. Gerçek USD-M liquidation bölgesi arşivi
olmadığı için OI/taker yalnız gerçekleşmiş squeeze vekiliydi. Train'de
çekirdekte 0, geniş evrende 1 olay kaldı; istatistik üretilemedi, test dilimine
bakılmadı ve canlı/shadow kanala eklenmedi. Ayrıntı: `research/REPORT.md` Ek P.

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

## Bilgisayar kapalıyken bulut taraması

`Trade1 cloud scanner` GitHub Actions iş akışı doğrulanmış 89 coinlik evreni
`*/5` hedefiyle tek tur tarayan **best-effort yedektir**. GitHub scheduled
workflows kesin zamanlayıcı değildir; yoğunlukta dakikalar, ölçülen durumda
1–3 saat gecikebilir. Gerçek 5 dakikalık çalışma tablet/7×24 süreçten gelir.
`.bot_state.json` ve sinyal günlüğü
koşular arasında taşındığı için False→True kenar tetiklemesi ile cooldown
korunur; her koşu Serhan / Lab proje kartını gerçek tarama sonucuyla günceller.
Bulut ortamında `TELEGRAM_BOT_TOKEN` ve `TELEGRAM_CHAT_ID` repository secret
olarak birlikte tanımlanır. İş akışı emir üretmez.

**`--check` vs `--once` farkı (önemli):**
- **`--check`** → "şu an uygun kurulum var mı?" sorusunun cevabı. O anda **aktif
  olan tüm koşulları** listeler (kenar-tetikleme aranmaz), bildirim göndermez,
  sadece terminale yazar. İstediğin an, elinle çalıştırdığın komut budur.
- **`--once` / sürekli döngü** → *canlı bildirim* mantığı: sinyal yalnızca koşul
  yeni **oluştuğunda** (False→True geçiş) üretilir, spam olmasın diye. Bu yüzden
  `--once` soğuk başlangıçta çoğu zaman "0 sinyal" der — bu bir hata değil,
  tasarım; anlık durumu görmek için `--check` kullan.

Binance için API anahtarı gerekmez (yalnızca halka açık uçlar). Sinyaller
stdout'a ve `signals.log`'a (JSONL) yazılır; push izni varsa **Telegram**'a
gönderilir.

## Türev araştırma arşivi

Sürekli çalışan bot, strateji kurallarından tamamen ayrı iki ileriye-dönük veri
seti biriktirir:

- `market_archive_YYYY-MM.jsonl`: saatlik fiyat, OI, bazis, genel hesap
  long/short oranı, taker buy/sell oranı ve funding görüntüsü. Long/short alanı
  hesap sayısı oranıdır; pozisyon büyüklüğü değildir.
- `liquidation_archive_YYYY-MM.jsonl`: Binance USD-M `!forceOrder@arr`
  WebSocket akışındaki gerçekleşmiş likidasyon snapshot'ları ve bağlantı/kesinti
  kayıtları. Binance sembol başına her 1000 ms'de yalnız son olayı yayımladığı
  için bu veri eksiksiz işlem bandı olarak yorumlanmaz.

Arşiv sinyal üretmez, güven puanını değiştirmez ve emir açmaz. Kapsamı görmek:

```bash
python signal_bot.py --archive-status
```

Dosyalar Git'e veya GitHub Pages'a gönderilmez. Varsayılan iki kanal da açıktır;
`ARCHIVE_MARKET_DATA=false` ve/veya `ARCHIVE_FORCE_ORDERS=false` ile kapatılabilir.
Araştırma kararı en az 3–6 aylık veri ve önceden dondurulmuş train/test protokolü
oluşmadan canlı stratejiye dönüştürülmez. Kurallar veri gelmeden önce
[`research/PREREG_FORWARD_SQUEEZE_ARCHIVE.md`](research/PREREG_FORWARD_SQUEEZE_ARCHIVE.md)
dosyasında dondurulmuştur.

7/24 web servisi ve JSON API ile çalıştırmak için aşağıdaki
**tek birleşik modu** kullan. Aynı anda ayrıca `python signal_bot.py` başlatma;
tek-instance kilidi ikinci kopyayı reddeder:

```bash
uvicorn server:app --host 0.0.0.0 --port 8000
# /ping = proses liveness
# /health = tarama readiness; ölü/eski taramada HTTP 503
# /signals/latest = son sinyallerin JSON sözleşmesi
```

`--workers 2` gibi çok-worker kullanma: sinyal tamponu proses içi olduğu için
sunucu başlangıçta tek tarama liderini zorunlu kılar ve lider olamayan worker'ı
reddeder. Ölen tarama thread'i watchdog tarafından yeniden başlatılır.

## 7/24 çalıştırma + Telegram + web panosu

- **7/24 çalıştırma (önerilen, ücretsiz):** evdeki Android tablet + Termux —
  [TABLET.md](TABLET.md). (Render yolu ölü: Binance bulut paylaşımlı IP'lerini
  yasaklıyor — 451/418; ayrıntı [DEPLOY.md](DEPLOY.md) başındaki uyarıda.)
- **Bildirim testi:** `python signal_bot.py --test-notify` — .env'deki
  anahtarlarla Telegram'a TEST mesajı yollar; gerçek sinyal beklemeden
  kurulumu doğrular.
- **Telegram düğmeleri:** `/start` → kalıcı menü klavyesi (Kontrol/Performans/
  Durum/Yardım); katılım isteklerinde satır-içi **Onayla/Reddet** düğmeleri
  (yalnız sahip). Kaybolursa `/menu`.
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
- **QC dışa aktarımı (çevrimdışı analiz):** `python qc_export.py -o qc_out` —
  `signals.log`'dan olay-bazlı CSV paketi üretir (olaylar, sonuçlar, strateji
  özeti, reddedilenler + manifest). Evren dışı/test kayıtlarını gerekçesiyle
  karantinaya alır; **trade journal değildir** (bot emir açmaz, dolar PnL yok).
  Olay kimlikleri `signals.log` ile birebir eşleşir (32-hex kanonik kimlik).
- **Arkadaş paylaşımı:** `TELEGRAM_ALLOWED_CHAT_IDS`'e eklenen chat'ler komut
  verebilir ve otomatik sinyalleri alır (abone). Arkadaş kendi ID'sini `/myid`
  ile öğrenir. Listede olmayan biri yalnızca `/myid` alır, gerisi yok sayılır.
  Tam açık mod: `TELEGRAM_OPEN=true`.
- **Bildirimler:** push izni verilen sinyaller Telegram'a gider. Anti-spam tek
  kapıdan yönetilir (`ScanState` kenar-tetikleme + strateji-başı cooldown).
  Eşik altı ve tarama tavanını aşan kayıtlar `push_allowed=false`,
  `suppressed=true` ve gerekçesiyle API/log'da kalır. Anahtar adları:
  `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` (bkz. `.env.example`).
- E-posta/Resend kanalı ve Expo mobil istemcisi 2026-08-06'da kullanıcı isteğiyle
  kaldırıldı. Telefon erişimi Telegram ve public GitHub Pages panosuyla sağlanır.

## Dışarıdan gelen değişiklikler (başka bir AI / kişi)

Doğrudan `main`'e uygulama — `main` tablette çalışan canlı bot. Önce bir dala
koy, PR aç, testlerin yeşilini bekle: adım adım [KATKI.md](KATKI.md).

## Bilinen sınırlar

- Uyarı botudur; emir vermez ve yatırım tavsiyesi değildir. Pano ve
  `/performans`, ham getiriden varsayılan **12bp round-trip** maliyet düşerek
  net sonuç gösterir; bu bir varsayımdır, gerçek borsa/hesap maliyeti değildir.
  S2 funding maliyeti modellenmez ve açıkça `not_modeled` yazılır.
- Canlı karneler strateji + piyasa + evren + güven + config sürümü bazında ayrı
  kohortlardır. N<30 `small_sample` işaretlenir; net isabet için %95 Wilson
  güven aralığı ve q10 kuyruk getirisi gösterilir. Farklı evrenler tek başarı
  sayısında birleştirilmez.
- S3 için BTC son kapanmış günlük mum / SMA200 `BULL|BEAR` etiketi ileriye dönük
  **shadow gözlemdir**; sinyali filtrelemez, güveni veya bildirimi değiştirmez.
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
```
