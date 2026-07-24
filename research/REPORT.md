# Sinyal Botu Eşik Araştırması — Rapor

*Oturum: 2026-07-17. Veri: Binance, 2024-07-01 → 2026-06-30 (24 ay), 30 sembol, 1h.*

## TL;DR — Karar tablosu

| Strateji | Karar | Eski → Yeni | Test kanıtı (2026H1, ayı rejimi) |
|---|---|---|---|
| S1 RSI uyumsuzluğu (long) | **KORUNDU, eşik gevşetildi** | OS 20 → **22.5** | 24h edge +0.31 vol, p=0.006, N=111, WR %59 |
| S1 RSI uyumsuzluğu (short) | **KALDIRILDI** | OB 80 → yok | Tüm eşiklerde (70–90) negatif train edge; testte anlamsız |
| S2 funding squeeze | **KORUNDU, sertleştirildi** | −0.02% tek okuma → **−0.03% + persistence 2** | 72h edge +0.14, p=0.08 (marjinal; izlenmeli) |
| S3 hacim anomalisi | **YENİDEN TASARLANDI** | ham z 3.0, iki yön → **log-z 3.0, sadece yukarı-bar** | 4h edge +0.25 vol, p<0.001, N=246 |
| S4 confluence (YENİ) | **EKLENDİ (etiket)** | — | S1+hacim: 24h edge +0.38, p=0.006; 72h WR %66 |

"Edge" = sinyal sonrası volatilite-normalize log-getiri − aynı sembolün aynı dönemdeki
koşulsuz ortalaması (piyasa sürüklenmesinden arındırılmış fazla getiri, vol birimi cinsinden).

---

## 1. Veri

**Kaynak.** `data.binance.vision` aylık zip arşivi (birincil): spot 1h klines,
USDⓈ-M perp 1h klines (`futures/um/monthly/klines`), funding rate
(`futures/um/monthly/fundingRate` — arşivde mevcut olduğu doğrulandı, API'ye gerek
kalmadı). Tek istisna: PEPE perp'i `1000PEPEUSDT` adıyla indirildi (Binance vadelide
1000'lik kontrat). REST API (fapi) yalnızca canlı botta kullanılıyor.
İndirme repo script'leri yerine aynı URL şemasına giden ~120 satırlık paralel
indiriciyle yapıldı (`download_data.py`) — daha az bağımlılık.

**Pencere: 24 ay (2024-07 → 2026-06).** Gerekçe: (a) tek rejime sıkışmamak —
pencere 2024H2 boğasını (Q4 +48%), 2025 tepesini ($126K, Eki 2025) ve 2025H2→2026H1
ayısını (üç çeyrek üst üste −23/−22/−14%) içeriyor; (b) 3+ yıl geriye gitmemek —
eski mikroyapı + orta boy coinlerin listeleme tarihleri (SEI 08/23, TIA 10/23)
sepeti deler; (c) hesap yükü (sembol başına 17.520 bar) taramalar için rahat.

**Semboller (30).** 13 majör + 17 orta boy; hem spotu hem perp'i olan, 24 ay
kesintisiz listeli USDT çiftleri. Doğrulama: 60 seri × 17.520 bar, **sıfır boşluk**;
funding 2.190 kayıt/sembol. Şerhler: TIA funding'i 4h aralıklı (eşik yorumu farklı
ölçekte; sinyal mantığı okuma-başına olduğundan aynen bırakıldı). Survivorship:
"bugün likit" seçimi hayatta kalanlara yanlı; bot da çalışma anında likit evreni
tarayacağı için değerlendirme-deploy tutarlılığı adına bilinçli kabul edildi.

**Train/test.** Kronolojik: train 2024-07→2025-12 (18 ay, karma rejim), test
2026-01→2026-06 (6 ay, saf ayı). Tüm eşik seçimleri yalnız train'de yapıldı;
test'e strateji başına tek atış (S3'teki istisna §5'te dürüstçe işaretli).

## 2. Metodoloji

- **Olay çalışması.** Sinyal bar t kapanışında üretilir; giriş t+1 açılışı
  (lookahead yok; elle doğrulandı). İleri getiriler girişten 1–72h, log.
- **Kenar-tetikleme + cooldown** (S1/S3 12h, S2 24h): süren koşul streak'i tek
  olay — hem istatistiksel bağımsızlık hem "uyarı botu" gerçekliği.
- **Vol-normalizasyon.** Getiri / (son 168h gerçekleşen vol × √ufuk) → semboller
  ve rejimler arası karşılaştırılabilir.
- **Baseline ve anlamlılık.** Sembol-eşleşmeli koşulsuz ortalamaya karşı fark
  ("edge"); sembol-eşleşmeli bootstrap (güncel kod: 2.000 çekiliş ve sıfır
  p-değerini önleyen plus-one düzeltmesi); ayrıca
  **gün-kümesi bootstrap** (aynı UTC gününe düşen olaylar tek küme) — coinler
  birlikte hareket ettiği için olay-düzeyi p'ler bağımsızlığı abartır, küme
  düzeyi bunu düzeltir (S3'ün train'deki "anlamlılığının" sahte çıkmasını bu yakaladı).
- **Sınır purge (2026-07-24 sertleştirmesi).** Train olayının ileri getiri
  ufku test dönemine taşıyorsa yalnız ilgili ufuk NaN yapılır; baseline ve
  bootstrap havuzu aynı horizon-aware maskeyi kullanır. Bu rapordaki kayıtlı
  konsol tabloları ham veri repoda olmadığı için yeniden üretilmedi; eski
  snapshot'larda `p=0.000` ve sınırdaki birkaç olay güncel kodla küçük fark
  gösterebilir.
- **Seçim kriteri (önceden tanımlı):** train'de birincil ufukta edge maksimizasyonu;
  kısıtlar N≥100, p≤0.05, plato tercihli (sivri tepe değil), uyarı bütçesi
  ≤~2 sinyal/sembol/ay.
- **Modellenmeyenler:** işlem maliyeti/slipaj (uyarı botu), fonlama maliyeti,
  gecikme. Edge'ler bp cinsinden de raporlandı (24–72h'te +60…+220bp; taker
  ücreti ~15bp gidiş-dönüş → sinyaller maliyet sonrası da anlamlı büyüklükte,
  ama bu bir backtest-PnL iddiası değildir).

## 3. S1 — RSI Uyumsuzluğu

**Short tarafı çöktü.** Train'de OB 70→90 tüm eşiklerde negatif edge (24h:
−0.13…−0.85 vol; p≈1.0), divergence'lı ya da sade fark etmiyor. 1h RSI aşırı
alımı kripto'da dönüş değil momentum işareti. Testte (ayı rejiminde bile!)
OB=80 diverjanslı short: +0.153, p=0.146 — anlamsız. En lehte rejimde dahi
kanıt üretemeyen sinyal kaldırıldı; `RSI_OVERBOUGHT` artık yok.

**Long tarafı güçlü ve monoton.** Train, diverjanslı (24h edge / N):
20→+0.55/92, **22.5→+0.35/205 (p=0.000)**, 25→+0.11/409, 27.5→+0.08/805,
30→−0.02. Divergence şartının katkısı: aynı eşikte (20) sade RSI +0.084/661'e
karşı diverjanslı +0.55/92 → filtre sinyali ~7× seyreltip edge'i ~6× yoğunlaştırıyor.

**Seçim: OS=22.5** (N≥100 kısıtını sağlayan en güçlü eşik; 20 muhafazakâr
alternatif olarak kayıtta). **Test:** +0.312 (p=0.006), WR %59, medyan +67bp,
gün-kümesi tüm-veri CI90 (+0.007, +0.337). Dört yarıyılın dördünde pozitif
(+0.89/+0.19/+0.15/+0.26) — rejim-dayanıklı. Sembol konsantrasyonu düşük (top-5 %25).

## 4. S2 — Funding Squeeze

**Mevcut ayar (−0.02%, tek okuma) anlamsızdı:** train 72h +0.077 (p=0.016 ama
gün-kümesi p=0.15), ayda sembol başına 2.1 sinyal.

**Yapı:** edge ufukla büyüyor (24h'te zayıf, 72h'te güçlü — pozisyon çözülmesi
günler alıyor) ve **persistence=2** (üst üste iki settled funding eşik altı)
aynı eşikte edge'i belirgin artırıyor: −0.02/p2 → 72h +0.183 (p=0.000, N=470);
−0.03/p2 → +0.287 (p=0.000, N=228); plato −0.02…−0.04 boyunca sağlam.

**Seçim: −0.03% + persistence 2, ufuk 72h.** **Test:** +0.135 (p=0.082) —
yönü doğru ama marjinal; yarıyıl kırılımı hep pozitif fakat azalan
(+0.35/+0.47/+0.11/+0.06). Tüm-veri gün-kümesi p=0.005. İki şerh:
(1) sinyallerin ~%60-70'i 5 sembolde (kronik negatif funding coinleri);
(2) ayı rejiminde negatif funding daha çok "haklı" konumlanma → squeeze yakıtı
azalıyor. **Denenen yeniden tasarım:** sembol-göreli funding z-skoru (son 90
settlement'a göre) — train'de parlak (72h +0.17…+0.30, p=0.000), **testte tüm
eşiklerde negatif** (WR %38-43) → reddedildi. Ders: funding'de mutlak seviye
önemli (derin negatif = longlara gerçek nakit akışı); göreli "alışılmadıklık"
genellemiyor. S2 korunuyor ama "izleme listesinde": canlıda 3-6 ay sinyal
başına gerçekleşen getiri loglanıp yeniden bakılmalı.

## 5. S3 — Hacim Anomalisi

**Mevcut ayar (ham z=3.0) spam + önemsiz:** ayda sembol başına ~9.7 sinyal
(30 sembolde günde ~10 uyarı), train edge +0.07, test +0.01. Saatlik ham hacim
aşırı kalın kuyruklu; ham z=3 "anomali" değil.

**Log dönüşümü + yön asimetrisi.** log1p(hacim) z'si dağılımı düzeltiyor;
train'de yukarı-bar patlamaları (pump devamı) güçlü (z=3.0: 4h +0.24 / 24h
+0.28), aşağı-bar shortları zayıf/kırılgan.

**Dürüstlük şerhi (çoklu hipotez).** Önceden seçtiğim birincil konfigürasyon
(log z=3.5, iki yön) testte ÇÖKTÜ (−0.060, p=0.798; rejim kırılımı vahşi:
+0.18/−0.13/+0.57/−0.05 — train sonucunu büyük ölçüde 2025H2 taşımış; bunu
gün-kümesi p'sinin train'de bile 0.45 olması önceden haber veriyordu).
Bunun üzerine train'in en güçlü yüzü olan **yukarı-bar-yalnız** varyantını
(train'de zaten kayıtlıydı) test ettim: **z=3.0 up: test 4h +0.253 (p=0.000)**,
train ile aynı (+0.236); 24h'te +0.100 (p=0.068)'e sönümleniyor. Bu, test
setine İKİNCİ bakış → güven düzeyi "orta" olarak işaretli; canlıda izlenmeli.

**Seçim: log-z eşik 3.0, pencere 168h, sadece yukarı-bar, LONG, ufuk 4–12h,
cooldown 12h.** Sinyal frekansı 1.4/sembol/ay (~1.4 uyarı/gün, 30 sembolde) —
spam sorunu çözüldü. Not: WR ~%49-55 — edge kazanç asimetrisinden geliyor
(kazançlar kayıplardan büyük), isabet oranından değil.

## 6. S4 — Confluence ("hacimli kapitülasyon dibi") — YENİ

Tanım: S1 tetiklendiğinde son 24h içinde S3 düzeyinde (log-z≥3.0, yön fark
etmeksizin) hacim patlaması varsa → STRONG.

| | N | 24h edge (p) | 72h edge (p) | 72h WR |
|---|---|---|---|---|
| S1 + hacim (train) | 94 | +0.55 (0.000) | +0.69 (0.000) | %72 |
| S1 yalnız (train) | 111 | +0.17 (0.048) | +0.29 (0.010) | %71* |
| **S1 + hacim (test)** | **50** | **+0.38 (0.006)** | **+0.28 (0.020)** | **%66** |
| S1 yalnız (test) | 61 | +0.26 (0.024) | +0.23 (0.038) | %56 |

*WR yakın ama getiri büyüklüğü ~2×. Train'de kuruldu, testte ilk bakışta geçti.
Bağımsız tarayıcı değil, S1 uyarısını yükselten etiket olarak eklendi (yeni
eşik yok; S1+S3 parametrelerini yeniden kullanıyor) — S2/S3 kombinasyonları
denenmedi (örtüşme az, örneklem küçük; bkz. §7).

## 7. Örtüşme

±24h aynı sembol: S1∩S2 %8, S1∩S3 %36, S2∩S3 %18. Hiçbir çift gereksiz-kopya
düzeyinde örtüşmüyor (üçü ayrı bilgi taşıyor); S1-S3 etkileşimi §6'daki
confluence sinyaline dönüştürüldü.

## 8. Değişen dosyalar

- **signal_bot.py** — yeniden oluşturuldu (klasör boş geldi; arayüz tarife uygun:
  `calc_rsi()`, `calc_volume_zscore()` [artık log-z], `scan_symbol()`, aynı sabit
  adları). Kenar-tetikleme + cooldown durumu, S4 etiketi, sadece `requests`
  bağımlılığı, `--once` modu. Bot mantığı == araştırma mantığı doğrulaması:
  4 sembol test dönemi yeniden oynatması, S1 18/18, S3 29/29 birebir.
- **.env.example** — yeni eşikler + tek satır gerekçeler.
- **README.md** — eşik tablosu, kaldırılanlar, sınırlar.
- **research/** — `download_data.py`, `build_cache.py`, `common.py`,
  `strategies.py`, `sweep_s1|s2|s3.py`, `eval_final.py`, `explore_variants.py`,
  `results/*.csv|txt` (tarama tabloları + konsol çıktıları), bu rapor.

## 9. Yeniden üretim

```bash
pip install pandas numpy pyarrow requests scipy
cd research
python download_data.py <veri_dizini>          # ~2160 zip, birkac dk
python build_cache.py <veri_dizini>            # fwd/vol kolonlari
python sweep_s1.py <veri_dizini> train         # (test/all da olur)
python sweep_s2.py <veri_dizini> train
python sweep_s3.py <veri_dizini> train
python eval_final.py <veri_dizini>             # secilen konfig + ortusme
python explore_variants.py <veri_dizini>       # S3-up / S2-z / confluence
```

## Ek A — 5m scalping araştırması (2026-07-19): NEGATİF SONUÇ

**Soru:** Dakika ölçeğinde (%1-3 hedefli) işlem sinyali üretilebilir mi?
**Veri:** Aynı 30 sembol, aynı 24 ay, 5 dakikalık spot klines (6.3M bar).
**Yöntem:** 3 önceden-kayıtlı aday aile; gidiş-dönüş 12bp maliyet modeli
(taker 2×5bp + spread); karar kuralı *önceden* sabit: train'de net ort > 0
VE net medyan > 0 VE gün-kümesi p ≤ 0.05 VE N ≥ 300; geçen aile test'e
tek atış. Sonuçlar: `results/fast_sweep_train.csv`.

**Sonuç: üç aile de train'de kaldı → test'e bakılmadı, S5 eklenmedi.**

| Aile | En iyi görünüm | Neden red |
|---|---|---|
| F1 hacim momentum (30dk) | z=5: net +44bp ama N=155, medyan −5bp, p=0.47; z=6: +287bp ama **N=14** | Brüt edge yalnız aşırı uçta; olaylar yılda sembol başına ~0.3'e düşüyor — "dakikada %1-3" tam da bu nadir kuyruklar, hasat edilemiyor |
| F2 kaskad sıçraması (60dk) | k=3: medyan +5.5bp, p=0.005 ama **net ort −6.2bp** | Tipik gün kazandırıyor, kaskad günleri (aynı anda çok tetik) olay-ağırlıklı ortalamayı batırıyor — gerçek trader tam o günlerde korele pozisyon taşır |
| F3 kırılım devamı (60dk) | En iyisi net +1.8bp, medyan −17bp, p=1.0 | Maliyet sonrası ölü; kazanma oranı %41-43 |

**Yapısal ders:** 5dk tipik hareket ~0.24%, maliyet 0.12% — maliyet/hareket
oranı saatlik ufkun ~6 katı. Ufuk kısaldıkça hareket √t ile küçülür, maliyet
sabit kalır → 1m'de kapı daha da kapalı. Bu evrende, bu maliyetlerle,
dakika-ölçeği perakende scalping edge'i **yok** (denenen aileler için).
Test dilimi hiç kullanılmadığı için gelecekteki bir aday aynı protokole
girebilir.

## Ek B — Zaman dilimi çeşitlendirme + hedef/stop (bracket) analizi (2026-07-19)

**B1. Zaman dilimi taraması** (`sweep_timeframes.py` →
`results/timeframe_sweep_console.txt`): S1 ve S3, 15m/30m/1h/2h/4h mumlarda
aynı protokolle (duvar-saati ufuk/cooldown/vol-penceresi; seçim train'de,
strateji başına tek test atışı).

- **S1**: 15m'de edge NEGATİF (hızlı mumlarda ölüyor — Ek A ile tutarlı);
  2h train'de parlak görünüp (+0.45) testte +0.27'ye geriledi — mevcut
  1h/22.5'in testini (+0.31) GEÇEMEDİ. **Karar: 1h/22.5 kalır.**
- **S3**: train kazananı 2h/z3.5 (+0.64) testte ÇÖKTÜ (−0.32, WR %36) —
  uç-konfig overfit'i. **Karar: 1h/z3.0 kalır.**
- Meta-bulgu: iki train-kazananı da testte geriledi; mevcut 1h ayarları
  OOS'ta hâlâ en iyi. Çeşitlendirme status quo'yu doğruladı.

**B2. Hedef/stop dokunma + bracket analizi** (`bracket_analysis.py`, 5m yol
çözünürlüğü → `results/bracket_analysis_console.txt`):

- Dokunma olasılıkları bildirimlere eklendi (STRATEGY_STATS): ör. S1 sonrası
  24h'te +2%'ye dokunma %71 — ama −2%'ye dokunma da %69. Giriş anları
  fırtınalı; kazanç kapanış dağılımından (WR %62) ve sağ kuyruktan geliyor.
- **Bracket'ler (hedef/stop emir çiftleri) hiçbir stratejide zaman çıkışını
  yenemedi.** S1: en iyi bracket +3bp ≈ hiç (zaman çıkışı ~+150bp net) —
  sıkı stoplar %69-84 dokunma sıklığıyla kazananları buduyor. S2: train'in
  en iyisi (+5/−3, +24bp) testte −61bp → red. S3: geniş (+5/−5) testte
  +24bp ile zaman çıkışına eşdeğer, üstün değil. **Doğrulanmış çıkış kuralı
  ZAMAN ÇIKIŞI olarak kalır; bracket önerilmez.**
- Şerhler: dolumlar 5m bar uçlarıyla yaklaşık (aynı-bar çift dokunuşta
  muhafazakâr stop sayıldı); S2 yolları spot 5m ile yaklaşık (araştırma perp
  1h idi); ücret 10bp RT.

## Ek C — Dış AI önerilerinin (Gemini/Kimi) deneysel denetimi (2026-07-19)

Kullanıcının ilettiği öneri setleri aynı protokolle test edildi
(`sweep_squeeze.py`, `explore_proposals.py` → `results/squeeze_sweep_console.txt`,
`results/proposals_console.txt`). Kararlar:

| Öneri | Deney sonucu | Karar |
|---|---|---|
| Gemini-1 / Kimi-S10: HTF trend/RSI filtresi (S1/S3) | S1×EMA-trend: geçen olay **0/199** (kapitülasyonda 4h EMA'lar yükselmez — botun en iyi stratejisini tamamen susturur). S1×RSI<50: 199/199 geçer (boş filtre). S3×EMA: geçen +0.199 < elenen +0.265. S3×RSI>45: geçen +0.092 ≪ elenen **+0.669** — filtre en iyi sinyalleri atıyor | **RED** (dördü de) |
| Gemini-2 / Kimi-S9: ATR'li TP/SL (1.5/3.0) | S1: E[net] **+8bp** vs zaman çıkışı ~+167bp (olayların %58'i önce stop'a değiyor — dokunma tablolarının öngördüğü gibi). S3: +28bp vs ~+37bp | **RED** — zaman çıkışı kalır |
| Gemini-3: Volatility Squeeze Breakout (BB⊂KC + hacim) | Train'de tek geçen konfig (L=12, zc=2.0; edge24 +0.209, p=0.022, N=108) → **testte çöktü** (h4 −0.11, h24 +0.02, WR %41-44, medyanlar negatif) | **RED** (test bakışı harcandı) |
| Kimi-S5 (VWAP MR + ADX), S6 (rejim anahtarı), S7 (order block/FVG) | Test edilmedi: S5 short bacağı kanıtla çelişir, S6'nın "yüksek volde S1 kapat" önermesi S1'in 4/4 rejim pozitifliğiyle çelişir, S7 tanımı serbestlik-derecesi çok yüksek | **ERTELENDİ** — istenirse S5-long tek aday olarak sıradaki döngüde |
| Kimi-S8 (Funding+OI+Basis) | Test **edilemez**: Binance OI geçmişi ~30 günle sınırlı; 24 aylık backtest kurulamaz | **RED (veri yok)** |
| Kimi ek kurallar: backtest protokolü, min örneklem, 2. bakış yasağı | Zaten bu raporun protokolü | Uygulanıyor ✓ |

**Meta-not:** İki bağımsız AI'ın önerdiği 6+ mekanizmanın tamamı ya deneyde
çöktü ya da test edilemez çıktı. "Makul fikir" ≠ edge; bu ekin varlık sebebi
gelecek oturumların aynı önerileri yeniden eklemeye kalkmaması.

**Aynı döngüde eklenen operasyonel özellikler (eşik/mantık değişmedi):**
tarama 60→15 dk (sinyal seti değişmez; S2 tespiti ve restart yakalama hızlanır),
güven kademeleri (S1+S4=ÇOK YÜKSEK, S1=YÜKSEK, S3=ORTA, S2=DÜŞÜK) +
`NOTIFY_MIN_CONFIDENCE=ORTA` (S2 push'u varsayılan sessiz — log/API'de kalır),
bildirimlere güven satırı + son-çıkış zaman damgası.

## Ek D — S2 bazis filtresi denemesi (2026-07-19): MEKANİK OLARAK BOŞ

Hipotez: negatif funding + perp spot'a primli (bazis>0) = "gerçek" squeeze.
Sonuç (`sweep_s2_basis.py` → `results/s2_basis_console.txt`): train'de 227
S2 olayının **yalnızca 1'inde** bazis > 0 — filtre fiilen boş küme. Sebep
yapısal: funding oranı zaten premium/bazisten TÜRETİLİR; üst üste derin
negatif funding ≈ perp'in spot altında işlem görmesi demek. "Negatif funding
ama pozitif bazis" durumu tanım gereği neredeyse imkânsız. (Tek istisna olay
da −%8.3 ile kapanmış.)

**S2 iyileştirme yollarının bilançosu — hepsi denendi:**
eşik/persistence taraması (mevcut ayar optimum), sembol-göreli funding
z-skoru (testte çöktü, §4), bazis filtresi (mekanik boş, bu ek), OI+bazis
kombinasyonu (OI geçmişi ~30 gün — test edilemez, Ek C), ATR bracket
(testte −61bp, Ek B). **Eldeki veriyle S2'yi iyileştirmenin yolu kalmadı.**
Kalan tek plan yürürlükte: sessiz-kayıt + `/performans` canlı ölçümü;
30+ olgun canlı S2 sinyali birikince kaldır/tut kararı veriyle verilecek.

## Ek E — 5+ yıllık günlük-mum araştırması (2026-07): HİÇBİRİ GEÇEMEDİ

**Soru:** Günlük mumlarda (kullanıcının önerdiği S1-günlük dahil) doğrulanabilir
strateji var mı? **Veri:** 24 majör, 2019-01→2026-06 (~60K günlük bar; COVID
çöküşü + 2021 çifte boğa + 2022 çöküş + 2023 yatay + 2024 boğa + 2025-26 ayı).
**Split:** train <2025-01 (6y), test 2025-01→2026-06 (18 ay, aile başı tek atış).
Sonuçlar: `results/daily5y_console.txt`, script `sweep_daily5y.py`.

| Aile | Train | Test | Karar |
|---|---|---|---|
| D1 günlük S1 (RSI div ± hacim) | OS=25: **N=12** (wr %92, med +5.9% — ama 6 yılda 12 olay!); N≥100 sağlayan tek konfig (OS=30, N=117) p=0.14 | — (kural geçilmedi) | **KANIT YETERSİZ** — günlük divergence yapısal olarak çok seyrek; N=12'nin parlaklığı 10-konfig seçim etkisi + 2020/2022 kuşak-dipleri örneklemi |
| D2 sade günlük oversold (RSI≤25) | N=151, edge +0.25, p=0.015, gün-p=0.010 ✅ | 7g: **−0.019 (p=0.59)** ❌ | **RED** — train'i geçti, testte çöktü |
| D3 günlük hacim patlaması (z≥2.5) | N=407, edge +0.22, p<0.001, gün-p=0.03 ✅ | 3g: +0.15 (p=0.14) ns; 14g: −0.15, wr %34 ❌ | **RED** |

**Sonuç: bota hiçbir günlük strateji eklenmedi; 1h S1/S1+S4 tek OOS-doğrulamalı
sinyaller olarak kalıyor.** Bu, "train kazananı testte geriler" deseninin
DÖRDÜNCÜ bağımsız gözlemi (1h TF taraması, squeeze, bracket, şimdi günlük) —
2025-26 rejimi uzun-yönlü ortalama-dönüşe günlük ölçekte de düşmanca. Ayrıca
pratik not: günlük sinyaller doğrulansaydı bile yılda ~2-25 uyarı üretirdi —
uyarı botu kullanım amacına zaten uygun değil. D1'in N=12 kuyruğu ileride
(daha fazla borsa/sembol/yıl verisiyle) yeniden ziyarete değer tek iz.

## Ek F — Canlı takip ilk bulgusu: EVREN KONTAMİNASYONU (2026-07)

İlk 34 olgun canlı sinyalin `/performans` çıktısı backtest'ten dramatik saptı:

| | Canlı N | Canlı medyan | Backtest medyan | Canlı isabet | Canlı ORT |
|---|---|---|---|---|---|
| S1 | 8 | **−22.15%** | +0.93% | %25 | −26.0% |
| S2 | 10 | −8.97% | +0.24% | %30 | **−26.9%** |
| S3 | 16 | +1.57% | +0.16% | %50 | +1.26% |

**Teşhis:** S3 (kısa-vadeli momentum) backtest'le tutarlı; S1/S2 felaket.
S2'nin ortalaması (−27%) medyanından (−9%) çok daha kötü → birkaç sinyal
−80%/−100% (ölen coinler). Kök neden: **canlı dinamik evren (81 coin) araştırma
evrenindeki 30 coinden 54 tanesi FAZLA içeriyordu** — TRUMP, BONK, PENGU, WLFI,
KAITO, HOME, ASTER, hatta `币安人生USDT` gibi meme/pump-dump/yeni-listeleme
coinleri. Edge bu coinlerde hiç ölçülmemişti. S1 (dip al) ve S2 (kalabalık
short al), ayı piyasasında ölmekte olan bir coine uygulanınca yıkılıyor; S3
(momentum) rejime dayanıklı olduğu için hayatta kalıyor.

**Düzeltme:** `SYMBOL_AUTO` varsayılanı **False** yapıldı → bot artık
araştırma-doğrulamalı 30 coini tarıyor. Dinamik evren açık opt-in
(`SYMBOL_AUTO=true`, riski kullanıcının). Bu, dinamik-evren genişletmesinin
(kullanıcı isteğiyle eklenmişti) bir aşırı-uzanım olduğunun kanıtlı düzeltmesi.

**Ders + meta-not:** Bu, takip sisteminin AMACINA hizmet ettiği ilk somut an —
kâğıt üzerinde, gerçek para riske atılmadan, edge sapması yakalandı. Eşiklere
DOKUNULMADI (sorun eşik değil, evrendi). S1/S2'nin temiz evrende bile ayı
rejiminde zayıflayıp zayıflamadığı ancak temiz veri birikince ölçülebilir;
mevcut −22% sayısı kontamine olduğu için S1/S2 hakkında YARGI DEĞİL.

## Ek G — 89-coin genişletilmiş evren doğrulaması (2026-07): KADEMELİ GEÇTİ

**Soru:** Doğrulanmış (donmuş) konfigürasyonlar daha geniş evrende tutuyor mu?
**Evren:** Bugün likit top-150 perp adayından 2024-07'den beri **kesintisiz**
verisi olanlar → 89 coin (56 genç listeleme — Ek F'nin çöp sınıfı — otomatik
elendi). Seçimsiz doğrulama: eşik araması YOK, mevcut ayarlar aynen; kırılım
eski-30 vs yeni-59 + hacim kademeleri. Konsol: `results/eval100_console.txt`.

| Donmuş konfig | Yeni-59 TRAIN | Yeni-59 TEST | Karar |
|---|---|---|---|
| S1+S4 | **+0.294 (p=0.000)** | **+0.360 (p=0.014), med +1.4%, WR %66** | ✅ genişle (YÜKSEK güven) |
| S1 (22.5 div) | +0.046 (p=0.23, nötr) | **+0.430 (p=0.000), med +1.1%** | ⚠️ genişle ama ORTA güvenle (tek dönem kanıtı) |
| S2 (−0.03 p2) | +0.060 (med −%0.7) | −0.010 (p=0.57, med **−%1.8**, WR %39) | ❌ yeni coinlerde ÇALIŞMAZ |
| S3 (logz3 up) | +0.014 (nötr) | **−0.282 (p=1.0, WR %38)** | ❌ yeni coinlerde ÇALIŞMAZ |

Eski-30 sonuçları önceki raporla birebir tutarlı (S1 test +0.31, S3 +0.25 vb.).
Eşik taraması (train-89, yalnız rapor): optimumlar KAYMADI (S1 22.5 bölgesi,
S3 z=3.0, S2 −0.03 hâlâ en iyi) → eşik değişikliği yok.

**Uygulama (kademeli genişleme):** Bot artık statik **30 çekirdek + 59 geniş**
= 89 coin tarar. Geniş evrende yalnız S1 ailesi çalışır: S1+S4 → YÜKSEK güven,
sade S1 → ORTA güven (push edilir ama kademesi düşük); S2/S3 geniş evrende
hiç hesaplanmaz (funding API çağrısı da yapılmaz). Beklenen ek hacim: ~10-15
S1-ailesi sinyali/ay, çoğu S1+S4 kalitesinde.

**Şerhler:** (1) sade S1'in yeni-59 kanıtı tek döneme (2026 ayısı) dayanıyor —
train'de nötrdü; rejim dönerse ORTA güven düşürülebilir; canlı takip
(/performans) izleyecek. (2) Kademe-3 (67+) train'de negatifti, testte en
iyiydi — kademe seçimi YAPILMADI (post-hoc olurdu). (3) 15m/5m mumlar bu
çalışmaya bilerek dahil edilmedi: Ek A (5m: 3 aile maliyet netinde ölü) ve
Ek B (S1@15m edge negatif) zaten cevapladı; coin sayısı artışı o yapısal
sonuçları değiştirmez.

## 10. İzleme önerileri (bir sonraki değerlendirme için)

1. ~~`signals.log`'a düşen her sinyal için gerçekleşen getiriyi loglayan takip
   script'i ekleyin~~ → **UYGULANDI (2026-07-19):** `realized_performance()` +
   Telegram `/performans` komutu — olgunlaşan her sinyalin gerçek getirisini
   ölçüp backtest medyanı/isabetiyle karşılaştırır. 30+ olgun sinyal birikince
   S2/S3 kararlarını bu veriyle gözden geçir.
2. S2: 3-6 ay canlı veriyle yeniden bak; edge erimeye devam ederse kaldır.
3. S3: "orta güven" — 3 ay canlı isabet takibi; 4h edge kaybolursa kaldır.
4. Eşikleri yeniden kalibre ederken bu penceredeki train/test protokolünü koru;
   tek pencerede "en iyi"yi alma.
