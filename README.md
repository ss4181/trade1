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

## Yeni gölge araştırmalar — G1 / DL1

Bu iki kanal mevcut stratejilere karışmaz; `GOZLEM` etiketiyle bildirim ve
ileri veri üretir:

| Ad | Evren ve olay | Dondurulmuş ölçüm | Mevcut kanıt |
|---|---|---|---|
| **G1** | Tüm aktif Binance USD-M perpetual sözleşmelerinde ilk-10 24s yükselen + 1s hacim ≥2x + OI ≥%2 + global hesap L/S <1 | sonraki 1s açılış → 4s kapanış, 12bp | **RED:** train N=401, net medyan −%0,30, WR %45,9 |
| **DL1** | Resmî Binance tam-token spot delist duyurusu; Binance spot + Bybit/OKX perp snapshot | PRE: duyuru→delist; POST: dış borsada 4/24/72s short, veri birikince | **PRE RED:** N=107, medyan −%53,58, WR %8,4. POST henüz test edilemez |

G1 her 5 dakikada bir çalışan döngü içinde yalnız yeni kapanmış saat için bir
kez değerlendirilir; sıralama evreni likidite filtresiz **tüm aktif USDT-marjinli
perpetual** sözleşmelerdir. DL1 pair/margin/futures kaldırma duyurularını kabul
etmez. Dış borsa “VAR” alanı short önerisi değil, o andaki point-in-time
bulunabilirlik kaydıdır.

G1 bildirimindeki **Fiyat**, tarama anındaki USD-M perpetual ticker fiyatıdır.
Koşulu doğuran son kapanmış 1 saatlik mumun kapanışı ayrı bir `Koşul mumu
kapanışı` satırında, dondurulmuş araştırma girişi ise `Ölçüm girişi` satırında
gösterilir. Böylece gecikmiş taramada eski mum kapanışı güncel giriş fiyatı gibi
sunulmaz. Performans hesabı değişmemiştir: sonraki 1 saatlik mum açılışı → +4
saat kapanış.

`shadow_market_YYYY-MM.jsonl` tüm G1 ilk-10 incelemelerini ve aktif DL1
snapshot'larını; `shadow_events_YYYY-MM.jsonl` yalnız tetiklenen olayları tutar.
Dosyalar Git'e/Pages'e gitmez. Durum: `python signal_bot.py --shadow-status`.
Kapatma: `SHADOW_EXPERIMENTS_ENABLED=false`; yalnız bildirimi susturma:
`SHADOW_PUSH_ENABLED=false`. Dondurulmuş kurallar:
[`PREREG_GAINER_SHORT_CROWD.md`](research/PREREG_GAINER_SHORT_CROWD.md) ve
[`PREREG_DELIST_EVENT.md`](research/PREREG_DELIST_EVENT.md).

### S2 türev ileri-test gölgesi

S2 için iki türev hipotez tarihsel train bölümünde ön-kayıtlı olarak ölçüldü:

- **OI-short build:** mevcut S2 + son 8 saatte OI artışı + top-trader pozisyon
  long/short oranı `<1`.
- **Funding-L/S uyumsuzluğu:** funding daha negatife giderken global hesap
  long/short oranının son 8 saatte artması.

İlk aday olumlu görünse de bağımsızlık/anlamlılık kapısını geçmedi (N=62,
57 gün, net medyan +%1,878; gün-kümeli p=0,2563 ve ilk 5 sembol yoğunluğu
%85,5). İkinci aday mevcut S2'yi iyileştirmedi. Bu nedenle ikisi de **canlı
strateji veya güven oranı değildir**. Bot yalnız gerçek bir S2 olayı olduğunda
özellikleri point-in-time olarak `shadow_events_YYYY-MM.jsonl` içine kaydeder;
Telegram/email/emir üretmez ve S2'nin eşiğini, cooldown'unu veya push kararını
değiştirmez. `S2_DERIVATIVES_SHADOW_ENABLED=false` ile kapatılabilir.

Top-trader pozisyon oranının güncel Binance ucu API anahtarı istediğinden,
`.env` içindeki `BINANCE_MARKET_DATA_API_KEY` alanına yalnız market-data/okuma
yetkili; işlem ve para çekme yetkileri kapalı bir anahtar girilmelidir. Anahtar
yoksa global L/S uyumsuzluğu kaydı sürer fakat OI-short adayı “eksik” kalır.
Haftalık `/arastirma` raporu olay, tam kayıt ve aday sayılarını ayrıca gösterir.
Araştırma ayrıntıları:
[`S2_DERIVATIVES_V2_REPORT.md`](research/S2_DERIVATIVES_V2_REPORT.md) ve
[`PREREG_S2_DERIVATIVES_V2.md`](research/PREREG_S2_DERIVATIVES_V2.md).

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
5 dakikalık fiyat yolu analizinde hedef/stop dokunmaları ayrıca ölçüldü; ancak
sabit bracket çıkışları doğrulanmış zaman çıkışını istikrarlı biçimde yenemedi
([araştırma raporu](research/REPORT.md), Ek B2). Bu nedenle **bunlar tavsiye
veya otomatik emir değildir**; kaldıraç kayıpları/tasfiye riskini büyütür.

Kullanıcının “coin fiyatı +%2 görünce çıkıyorum” yaklaşımını ayrıca ölçmek için
bot, yalnız Telegram'a gerçekten gönderilmiş sinyalleri bildirim fiyatından
itibaren kapanmış 5 dakikalık mumlarla izler. Panoda TP2/TP3/TP5/TP10 dokunma
oranları, Wilson %95 belirsizlik aralığı, ilk dokunma zamanı, hedefe ulaşmadan
önceki ters hareket ve sinyal ufkundaki MFE/MAE görünür. Telegram hedef mesajı
varsayılan olarak yalnız +%2 ve +%3 için gider; +%5/+%10 sessiz analitiktir.

“Başarılı” sınıfı, stratejinin ufku tamamlandıktan sonra coin fiyatının +%2'ye
dokunmuş olmasıdır. Aktif olaylar paydaya alınmaz ve `N<30` küçük örnek olarak
işaretlenir. Hedefin görüldüğü 5 dakikalık mumdaki en düşük fiyatın hedefe göre
önce mi sonra mı oluştuğu bilinmediği için “hedef öncesi düşüş” muhafazakâr
olarak o mumun tüm aralığını içerir. Bu oranlar **coinin kaldıraçsız brüt fiyat
değişimidir; ücret/slippage düşülmez ve ROE değildir**. Bot pozisyon açmaz veya
kapatmaz. Eski hedef kayıtları yeni şemaya sessizce tamamlanır; geçmiş hedefler
gecikmiş Telegram mesajı üretmez. İlgili ayarlar: `PRICE_TARGET_*` ve
`USER_SUCCESS_TARGET_PCT`.

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

Telegram sinyal mesajı önce strateji/sembol/yönü, ardından fiyat-ufuk-piyasa,
tetikleyen ölçümler, “neden geldi?” özeti, dondurulmuş test ve hedef/ters
dokunma karnesi, mekanik referanslar ve kişisel TP seviyeleri şeklinde okunur.
S2'nin güveni **DÜŞÜK** kalır; kullanıcı talebiyle varsayılan olarak yalnız
`ARAŞTIRMA` etiketiyle push edilir (`S2_RESEARCH_PUSH=true`). Bu özel izin genel
`NOTIFY_MIN_CONFIDENCE` eşiğini düşürmez. S2'yi sessiz ölçmeye döndürmek için
`.env` içine `S2_RESEARCH_PUSH=false` yaz; stratejiyi tamamen kapatma.

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
  Binance'in 23 Nisan 2026'da kapattığı eski `/ws/` yolu kullanılmaz; güncel
  `/market/ws/` yolu ve birleşik UM/CM akışında yalnız `st=1` USD-M olayları
  kabul edilir. Heartbeat olup gerçek olay yoksa `/arastirma` arıza uyarısı verir.
- `shadow_market_YYYY-MM.jsonl` / `shadow_events_YYYY-MM.jsonl`: G1 ilk-10
  piyasa fotoğrafları ile DL1 delist/dış-borsa snapshot ve olayları.

Arşiv sinyal üretmez, güven puanını değiştirmez ve emir açmaz. Kapsamı görmek:

```bash
python signal_bot.py --archive-status
python signal_bot.py --shadow-status
python signal_bot.py --research-status
```

### Günlük bilgisayar yedeği

Termux/tablet sürümünde ham araştırma arşivi ilk sürekli çalışmada hemen,
sonrasında **24 saatte bir** `~/storage/shared/trade1-backup` aktarım klasörüne
otomatik olarak aynalanır. Syncthing-Fork bu klasörü Windows bilgisayardaki
`Documents\Trade1-Backup` hedefine aktarır. Yedek taramadan ayrı bir arka plan
işinde çalışır;
başarısız olması canlı sinyal döngüsünü durdurmaz. Değişmeyen dosyalar atlanır,
değişen dosya önce geçici bir dosyaya yazılıp atomik olarak yerine geçirilir.
`.env`, Telegram tokenı ve GitHub anahtarı hiçbir zaman seçilmez. Yedek hatası
Telegram'a aynı sorun için en fazla 24 saatte bir bildirilir.

Android ortak depolamasına ilk kez erişirken tablette bir kez:

```bash
termux-setup-storage
cd ~/trade1
python signal_bot.py --backup-now
python signal_bot.py --backup-status
```

İlk komutta Android'in dosya erişim iznini onayla. `--backup-status` son deneme,
son başarı, kopyalanan/atlanan dosya sayısı ve varsa hatayı gösterir. Ayarlar
`ARCHIVE_BACKUP_*` değişkenleriyle değiştirilebilir; Termux dışındaki
ortamlarda güvenli varsayılan kapalıdır.

Tabletteki klasör yalnız aktarım kuyruğudur; gerçek yedek ancak Windows'ta
eşitleme tamamlanınca oluşur. Tablet `Send Only`, Windows `Receive Only` ve
Windows sürümleme süresi 365 gün olmalıdır. Kurulum ve doğrulama adımları:
[`PC_BACKUP.md`](PC_BACKUP.md). Public GitHub/Pages ham arşiv ve abone durumları
için uygun değildir.

G1 ile gerçekleşmiş likidasyon yoğunluğu/fiyat kümelerini veri sızıntısız
karşılaştıran manuel keşif testi:

```bash
python research/eval_g1_liquidation_proxy.py --dir .
```

Bu test iki proxy ölçer: sinyalden önceki 1 saatte short-likidasyon patlaması
(`LQ1`) ve önceki 24 saatte koşul fiyatının üstünde gerçekleşmiş short-
likidasyon fiyat kümesi (`LQ2`). `forceOrder` verisi bekleyen pozisyonların
gerçek bir likidasyon haritası değildir; yalnız gerçekleşmiş, örneklenmiş
olaylardır. Sonuçlar en az 90 takvim günü, 30 gerçek likidasyon olay günü ve 30
olgun G1 olayı olmadan canlı filtreye veya güven oranına dönüştürülmez. Dondurulan
protokol: `research/PREREG_G1_LIQUIDATION_PROXY.md`.

Bot her pazartesi 06:00 UTC'den (Türkiye 09:00) sonraki ilk turda sahibine
Telegram'dan haftalık araştırma hazırlık raporu gönderir. Aynı rapor istenen
anda `/arastirma` komutuyla alınabilir. Rapor satır/süre, saat kapsaması, OI,
funding, long/short ve basis doluluğu ile likidasyon günlerini gösterir.
Raporun `Kaynak` satırı mesajın Termux/tablet mi yoksa Render/bulut sürecinden
mi geldiğini gösterir. Otomatik raporu gönderen süreç hiç piyasa arşivi
görmüyorsa sıfırlı normal rapor yerine açık bir `ARŞİV BULUNAMADI` uyarısı
gönderilir; manuel `/arastirma` teşhisi çalışmaya devam eder.

Bu döngü modeli her hafta yeniden eğitmez. İlk 90 gün keşif/veri-kalitesi
dönemidir. Kalite kapısı geçilince OI+funding+long/short+likidasyon adayı ayrıca
ön-kaydedilip kural dondurulur ve o an `RESEARCH_OOS_START_UTC` yazılır. Sonraki
90 gün dokunulmamış OOS testidir; ancak bu ikinci dönem tamamlanınca kabul/ret
kararı verilir. Böylece haftalık yeniden ayarlamanın yaratacağı overfitting ve
"sonuca ikinci bakış" önlenir.

Birleşik 90 günlük sayaç, tam OI alanları ile onarılmış WebSocket'ten gelen ilk
gerçek likidasyon olayının daha geç olanında başlar. Heartbeat satırları başlangıç
sayılmaz; eski bozuk akışın süresi araştırma yaşına eklenmez.

Mevcut keşif verisini eşik değiştirmeden hemen incelemek için:

```bash
python research/explore_forward_oi.py --dir .
```

Çıktı aynı sabit merdivende top-10 yükselen, 5m taker-hacim anomalisi, OI artışı,
short hesap çoğunluğu ve funding değişiminin 4 saatlik net sonuca kademeli
katkısını gösterir. Ayrıca kullanıcının fiilî çıkış davranışına uygun olarak
+%2/+%3 hedefe 4/12/24 saat içinde dokunma oranlarını raporlar. Arşiv saatlik
snapshot içerdiği ve mum içi `high` içermediği için hedef oranları muhafazakâr
bir alt sınırdır. Bu tablo OOS değildir; yalnız bottleneck/hipotez keşfidir.

P0–P5/Q1 kodlarının sade açıklaması ve mevcut yorum:
[`research/FORWARD_OI_RULES_REPORT.md`](research/FORWARD_OI_RULES_REPORT.md).
Hedefin stoptan önce görülüp görülmediğini resmî, checksum-doğrulanmış USD-M
5m mumlarıyla ölçen ön-kayıtlı keşif testi:

```bash
python research/eval_forward_oi_barriers.py --dir .
```

İlk çalıştırma yalnız gereken günlük mum ZIP'lerini Git dışındaki
`research/data/forward_oi_5m/` önbelleğine indirir. Birincil rapor +%2/+%3
hedef, −%1,5 stop ve 4/12/24 saat ufuklarını gösterir; `--full` −%1/−%2 stop
hassasiyetlerini de basar. Bu da OOS değildir ve canlı sinyal üretmez.

Bot aynı tam hedef/stop testini varsayılan olarak **her 30 günde bir** ayrı bir
alt süreçte yeniden çalıştırır. İlk rapor, yeni sürümle ilk başarılı sürekli
taramadan 30 gün sonra; sonraki raporlar 30'ar gün arayla Telegram sahibine
gelir. Mesaj P0–P5/Q1 için örnek/gün sayısını, 4 saatte +%2 ve +%3 hedefin
−%1,5 stoptan önce görülme oranını, net ortalama/medyanı ve günlük bootstrap
`p(nonpoz)` değerini içerir; Claude'a doğrudan yapıştırılabilecek kadar kısa
tutulur. Test tüm birikimli arşivi kullanır, yalnız son ayı değil. Ağ veya
Telegram hatasında canlı tarama durmaz ve rapor 24 saat sonra yeniden denenir.

Bu aylık döngü yalnız ölçüm ve bildirimdir: strateji, eşik, güven etiketi,
sembol evreni ve push davranışını otomatik değiştirmez. `ARCHIVE_MARKET_DATA`
ve Telegram açık olmalıdır. Kapatmak için `.env` içine
`FORWARD_OI_30D_REPORT_ENABLED=false` yazılabilir; süre gerekiyorsa
`FORWARD_OI_REPORT_INTERVAL_DAYS=30` ile ayarlanır. Sayaç ve 5dk önbelleği
`.gitignore` kapsamındadır; hiçbir token veya `.env` değeri rapora girmez.

Dosyalar Git'e veya GitHub Pages'a gönderilmez. Varsayılan iki kanal da açıktır;
`ARCHIVE_MARKET_DATA=false` ve/veya `ARCHIVE_FORCE_ORDERS=false` ile kapatılabilir.
Gölge kanal ayrıca `SHADOW_EXPERIMENTS_ENABLED=false` ile kapatılabilir.
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
- **Bildirim düzeni:** Tüm raporlar ortak bir kart düzenindedir. Sinyallerde
  başlık → fiyat/ufuk → tetikleyen ölçümler → “neden geldi?” → kanıt/risk →
  mekanik referans sırası kullanılır. Günlük özet olay/bildirim/sessiz kayıt
  ayrımını ve kısa canlı karnesini gösterir; `/performans` doğrulanmış
  kohortları, ayrı gözlem kanalını ve kişisel hedef dokunmalarını ayrı
  bölümlerde verir. `/check` yalnız o andaki aktif koşulları gösterir ve
  bildirim göndermez; `/status` çalışma/bildirim/erişim durumunu tek bakışta
  özetler. Bu raporların hiçbiri emir açmaz.
- **Web panosu:** bot çalışırken `http://<cihaz-ip>:8181` (yalnız yerel ağ) —
  sinyal geçmişi, aktiflerde anlık K/Z, olgunlarda gerçekleşen sonuç,
  TP2/TP3/TP5/TP10 dokunmaları, hedef öncesi düşüş, MFE/MAE ve kişisel +%2
  başarı karnesi. Alt tablo; metin, strateji, durum, güven, bildirim, hedef
  sonucu ve dönemle filtrelenebilir; tarih/MFE/MAE/K-Z ile sıralanabilir.
  **Strateji kartına** tıkla → nasıl
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
