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
  bootstrap havuzu aynı horizon-aware maskeyi kullanır.
- **Sertleştirme sonrası yeniden üretim (2026-07-26 denetimi).** Yukarıdaki
  purge + 2.000 çekiliş + plus-one değişiklikleri, doğrulanmış dört
  konfigürasyon için 30-coin panelinde yeniden çalıştırıldı ve **hiçbir sonuç
  değişmedi**: S1 train +0.348 / test +0.312 · S1+S4 +0.550 / +0.376 ·
  S3 +0.236 / +0.253 · S2 +0.292 / +0.135. Yalnız p-değerleri plus-one
  düzeltmesiyle mikro kaydı (ör. 0.000→0.002, 0.082→0.086); tüm kabul/red
  kararları aynı yerde. Yani metodoloji artık daha muhafazakâr ve
  başlıklar sağlam.
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

## Ek H — S3 destekleyici metrik araştırması (2026-07-30): EKLENMEDİ

**Soru:** S3'e (log-hacim z≥3.0 + yeşil bar, 4h) eklenecek ikinci bir teyit
koşulu güvenilirliği artırır mı? **Adaylar** (hepsi sinyal barının kendi
verisinden, sızıntısız): (A) taker alım oranı, (B) kapanışın bar içindeki
konumu, (C) ortalama işlem büyüklüğü z-skoru, (D) olayın coin'e özgü mü
piyasa-geneli mi olduğu. 13 konfigürasyon. Script: `sweep_s3_confirm.py`,
konsol: `results/s3_confirm_console.txt`.

**Protokol (önceden kayıtlı):** tasarım yalnız çekirdek-30 train'de; kazanan
İKİ bağımsız kümede sınanır — çekirdek-30 test **ve** geniş-59 (S3
araştırmasında hiç kullanılmamış, gerçek bağımsız sembol kümesi).

| Aşama | Kazanan aday (kapanış konumu ≥ 0.7) |
|---|---|
| Çekirdek-30 train | edge +0.283, p=0.001, medyan +28.1bp ✅ |
| Çekirdek-30 test | edge +0.351, p=0.002 ✅ ama **medyan −9.8bp, isabet %45** |
| **Geniş-59 (bağımsız)** | **edge −0.035, p=0.87** ❌ (filtresiz referans −0.067) |

**Karar: EKLENMEDİ.** Bağımsız sembol kümesinde çöktü — bu, "train kazananı
OOS'ta sönüyor" deseninin BEŞİNCİ bağımsız gözlemi. Ayrıca filtre örneklemi
yarıya indirirken (245→119) medyanı ve isabeti DÜŞÜRÜYOR: vol-normalize
edge'i yükseltmesi tamamen kuyruk yoğunlaşmasından.

**Asıl bulgu — S3'ün kendisi hakkında (yan ürün):**

| S3 (filtresiz, kanonik) | N | edge | medyan | isabet |
|---|---|---|---|---|
| çekirdek-30 train | 761 | +0.228 | +22.7bp | %55 |
| çekirdek-30 test | 245 | +0.248 (p=0.001) | **+0.0bp** | %49 |
| geniş-59 (tüm dönem) | 2308 | −0.067 (p=1.00) | **−44bp** | %43 |
| **canlı** (2026-07, N=7) | 7 | — | −34bp | %43 |

S3'ün vol-normalize edge'i çekirdek-30'da istatistiksel olarak gerçek, ama
**medyan işlem sıfıra inmiş** — yani ~12bp gidiş-dönüş maliyetten sonra tipik
S3 işlemi zarar ediyor; pozitif edge yalnız sağ kuyruktan geliyor. Üç bağımsız
kaynak (test medyanı, geniş evren, canlı) aynı yöne işaret ediyor.

**Öneri (eşik değişikliği değil, yapılandırma):** `NOTIFY_MIN_CONFIDENCE=YUKSEK`
→ S3 push'u susar (log/panoda kalır), telefona yalnız S1 ve S1+S4 gelir.
S3 kaldırılmıyor; canlı kayıt birikmeye devam ediyor.

## Ek I — Funding hasadı ("yüksek FR'de ödemeyi al") (2026-08-03): NEGATİF

**Soru:** S2'yi yönlü bir sinyal olarak değil, **funding ödemesini toplayan**
bir kurulum olarak kullanabilir miyiz? Funding oranı uç değerlere çıktığında
(|FR| ≥ %1.5–2 gibi) ödemeyi ALAN tarafa geçip ödemeyi cebe atmak.

**Adım 1 — böyle oranlar gerçekten oluyor mu?** 89 coin × 24 ay = 243.361
funding kaydı (aralık dağılımı: 8h %58, 4h %41).

| \|FR\| ≥ | olay | tüm kayıtların %'si | evren genelinde ayda |
|---|---|---|---|
| %0.30 | 771 | 0.317% | 32.1 |
| %0.50 | 346 | 0.142% | 14.4 |
| %1.00 | 98 | 0.040% | 4.1 |
| %1.50 | 34 | 0.014% | 1.4 |
| %2.00 | 17 | 0.007% | 0.7 |

Olaylar var ama nadir, ve uçlar **tamamen negatif** tarafta (kalabalık short →
long alır); değerler funding TAVANINA (−%2, tek seferde −%3) yapışıyor.

**Adım 2 — ödeme fiyat riskini karşılıyor mu?** Kasıtlı **iyimser** kurulum:
giriş sinyali olarak SETTLED oran kullanıldı — bu lookahead'dir (gerçekte
yalnız tahmini oran görülebilir), yani ölçüm gerçekte ulaşılabilecek olanın
ÜST SINIRI. Maliyet 10bp gidiş-dönüş. Yalnızca **train** (2024-07→2025-12).

1h çözünürlük, ödemeden sonra 1 bar tutma:

| eşik | N | funding (medyan) | fiyat (medyan) | **net** | isabet |
|---|---|---|---|---|---|
| %0.50 | 141 | +0.76% | −1.28% | **−0.65%** | %39 |
| %1.00 | 49 | +1.29% | −2.44% | **−1.08%** | %33 |
| %1.50 | 18 | +1.72% | −2.68% | **−1.14%** | %39 |
| %2.00 | 8 | +2.00% | −3.61% | **−1.21%** | %38 |

**Adım 3 — fikrin en güçlü hali** (5m çözünürlük; ödemeden **5 dk önce** gir,
**5 dk sonra** çık = toplam ~10 dakika fiyat riski). "Kapanışa 5 dk kala
bildirim gönder, ödemeyi al" önerisinin birebir ölçümü:

| eşik | N | funding | fiyat | **net (medyan)** | isabet |
|---|---|---|---|---|---|
| %0.50 | 141 | +0.76% | −0.89% | **−0.08%** | %48 |
| %0.75 | 74 | +1.11% | −1.34% | **−0.37%** | %43 |
| %1.00 | 49 | +1.29% | −1.48% | **−0.50%** | %37 |
| %1.50 | 18 | +1.72% | −2.99% | **−1.06%** | %44 |
| %2.00 | 8 | +2.00% | −3.88% | **−1.91%** | %12 |

**Karar: EKLENMEDİ. Test dilimine BAKILMADI** (train'de her eşikte ve her
tutma penceresinde negatif — protokol gereği test atışı harcanmadı).

**Mekanizma (neden böyle olmak zorunda):** Uç negatif funding, perp'in
endekse göre derin **iskontoda** işlem görmesi demektir. Funding ödemesi tam
olarak bu iskontonun tazminatıdır ve iskonto ödeme anının çevresinde kapanır.
10 dakikalık pencerede bile fiyat, funding'in ~1.2–1.7 katını geri alıyor.
Funding bedava para değil; dislokasyonun ters tarafını tutmanın ücreti.
Dikkat: eşik yükseldikçe sonuç **kötüleşiyor** — "daha uç FR, daha iyi hasat"
sezgisi verinin tam tersi.

**Frekans şerhi:** İşe yarasaydı bile |FR| ≥ %1.5 evren genelinde **ayda ~1.4
kez**, ≥ %2.0 **ayda ~0.7 kez** oluyor — bildirim hacmi olarak da neredeyse
hiç.

**Not:** Delta-nötr baz işlemi (spot al + perp short) bu ekin kapsamı DIŞINDA;
o farklı bir ürün (iki bacaklı, spot bakiyesi gerektirir) ve bu bot tek-bacaklı
perp sinyali üretiyor. Tekrar sorulursa bu ek gösterilsin.

**Script:** `sweep_funding_harvest.py` · **konsol:**
`results/funding_harvest_console.txt`

## Ek J — "Daha çok sinyal + güçlendirici metrik" araması (2026-08-03): UYGULANMADI

**Soru:** S1'in RSI eşiğini gevşetip daha çok sinyal üretelim, ama her sinyali
değerlendiren bir metrik ekleyerek isabeti %55+ ve medyanı maliyetin üstünde
tutalım. Böyle bir metrik var mı?

**Önceden kayıtlı ölçüt:** isabet ≥ %55 **ve** medyan ≥ 12bp (gidiş-dönüş
maliyet) **ve** sinyal sayısı mevcut RSI≤22.5 havuzundan fazla.
**Adaylar (10):** uyumsuzluk gücü, RSI dönüşü, 168h zirveden düşüş, dip kırma
derinliği, bar-içi kapanış konumu, sinyal barı hacim z'si, volatilite rejimi,
ardışık düşüş sayısı, likidite oranı, BTC'nin o andaki RSI'ı.
Script: `sweep_s1_filters.py` + `sweep_s1_filters_refine.py`, konsol:
`results/s1_filter_console.txt`.

**Aşama 1 — filtresiz havuzlar (çekirdek-30 train)** eşik gevşemesinin
bedelini gösteriyor: RSI≤22.5 → 0.38 sinyal/ay, %64, +114bp · 25.0 → 0.76,
%58, +84bp · 27.5 → 1.49, %56, +59bp · 30.0 → 2.52, %54, +44bp.

**Aşama 2 — train'de 127 konfigürasyon ölçütü geçti.** Kazananların tamamı iki
mekanizmanın varyantıydı: sinyal barında **hacim patlaması** ve 168h zirveden
**derin düşüş**. (127 sayısı kanıt değil — ~240 denemede beklenen sayı.)

**Aşama 3 — bağımsız küme (geniş-59, S1 filtre tasarımında kullanılmadı):**
ilk 12 adayın **12'si de** aynı ölçütü geçti. Ek H'deki "bağımsız kümede
çöküş" deseni burada **görülmedi** — bu yüzden test atışı hak edildi.

**Aşama 4-5 — sağlamlık:** RSI≤30 · vol_z≥1.5 üç alt dönemde de pozitif
(2024H2 %61/+189bp, 2025H1 %65/+183bp, 2025H2 %59/+99bp); sinyallerin %91'i
mevcut konfigin üretmediği yeni sinyaller, %43'ü zaten S4 koşulunu taşıyor.

**Aşama 6 — TEST 2026H1 (tek atış, konfig önceden donduruldu):**

| Kurulum (tüm 89) | sin/ay | isabet | medyan | edge | p |
|---|---|---|---|---|---|
| KARAR: RSI≤30 · vol_z≥1.5 | 0.67 | %56 | +51bp | 0.228 | 0.000 |
| MEVCUT: RSI≤22.5 | 0.45 | %60 | +82bp | 0.375 | 0.000 |

Toplam beklenti (sinyal/ay × medyan): aday 34 vs mevcut 37 — **daha çok
sinyal, toplamda daha az getiri.**

**Ayrıştırma (aynı atışın alt kümesi) — kararı belirleyen bulgu:**

| | train edge | test edge | test medyan |
|---|---|---|---|
| Yeni bant 22.5<RSI≤30, **filtresiz** | **−0.044** (p=0.99) | **+0.186** (p=0.000) | +49bp |
| Yeni bant + **vol_z≥1.5** | **+0.196** (p=0.000) | **+0.188** (p=0.001) | +36bp |
| Mevcut S1 (RSI≤22.5) | +0.199 | **+0.474** | +100bp |

**Karar: UYGULANMADI.** İki bağımsız sebep:
1. **Filtre test'te hiçbir şey katmıyor.** Train'de değersiz bir bandı
   (edge −0.044) S1 seviyesine çıkarıyordu (+0.196); test'te filtreli ve
   filtresiz edge aynı (0.188 vs 0.186) ve filtreli medyan daha **düşük**
   (36 vs 49bp). Yani "güçlendirici metrik" iddiası OOS'ta doğrulanmadı —
   train'deki gücü aşırı uydurmaydı.
2. **Gevşetilmiş bandın kendisi dönemler arası işaret değiştiriyor**
   (train −0.044 → test +0.186). Bir dönemde negatif, diğerinde pozitif olan
   şey edge değil rejim şansıdır.

Mevcut RSI≤22.5 test'te her ölçütte üstün kaldı (edge 0.474, %60, +100bp).

**Maliyet:** Bu hipotez ailesi için **test atışı harcandı**. Aynı fikir
(S1 gevşetme + bar-bazlı teyit metriği) yeniden test EDİLEMEZ; yeni bir veri
dönemi birikmeden bu kapıya dönülmemeli.

**Kayda değer yan bulgu:** Hacim teyidinin train'de bu kadar güçlü, test'te
bu kadar etkisiz olması, S4'ün (zaten doğrulanmış hacim mekanizması) neden
sadece *etiket* olarak tutulduğunu destekliyor.

## Ek K — Rejim kırılımı: boğa piyasasında sinyaller ne olur? (2026-08-03)

**Tanımsal analiz** — yeni strateji/eşik ARANMADI, test atışı harcanmadı.
Mevcut canlı konfigürasyonun rejime göre hem **sıklığı** hem **sonucu**.
Rejim: BTC kapanışı 200 günlük (4800 saat) SMA'nın üstünde → BOĞA.
Script: `regime_breakdown.py`, konsol: `results/regime_console.txt`.

**Örneklem gerçekten iki rejim içeriyor:** 24 ayın %55'i boğa (~11.5 ay),
%45'i ayı (~9.2 ay). Yani aşağıdakiler ekstrapolasyon değil, ölçüm.

| Strateji | Rejim | sinyal/sembol/ay | isabet | medyan | edge |
|---|---|---|---|---|---|
| **S1** (24h) | BOĞA | **0.29** | **%67** | **+158bp** | 0.154 |
| | AYI | **0.53** | %53 | +31bp | 0.157 |
| **S3** (4h) | BOĞA | **1.63** | **%58** | **+43bp** | 0.359 |
| | AYI | 1.23 | %47 | **−8bp** | 0.106 |
| **S2** (72h) | BOĞA | 0.46 | %50 | +10bp | 0.192 |
| | AYI | 0.75 | %49 | 0bp | 0.172 |

BTC'nin 30 günlük getirisine göre uçlar (küçük N şerhiyle):

| Strateji | BTC 30g > +%10 | BTC 30g < −%10 |
|---|---|---|
| S1 | 0.06 sin/ay, %67, **+216bp** (N=24) | 0.72 sin/ay, %58, +79bp |
| S3 | 1.79 sin/ay, %54, +33bp | 1.21 sin/ay, %54, +32bp |
| S2 | 0.29 sin/ay, %41, **−162bp** (N=41) | 0.98 sin/ay, %48, −9bp |

**Okunuşu:**

1. **S1 boğada seyrekleşir ama güçlenir.** Sinyal sayısı neredeyse yarıya
   iner (0.53 → 0.29), isabet %53'ten %67'ye, medyan +31bp'den +158bp'ye
   çıkar. Güçlü yükselişte (BTC +%10/30g) neredeyse hiç tetiklenmez
   (0.06 sin/ay ≈ sembol başına 16 ayda bir) ama tetiklendiğinde medyan
   +216bp. Mekanik olarak beklenen: S1 bir kapitülasyon sinyali; her şey
   yükselirken derin aşırı-satım nadirdir, olduğunda da hızlı toparlar.
2. **S3 boğada hem çoğalır hem işe yarar; ayıda zarar eder.** Boğa medyanı
   +43bp, ayı medyanı **−8bp** (yani ~12bp maliyetten sonra kayıp).
   S3'ün genel zayıflığı (Ek H: test medyanı 0bp) bu iki rejimin
   ortalamasıymış.
3. **S2 güçlü yükselişte aktif olarak zararlı** (%41 isabet, −162bp, N=41):
   ralli sırasında negatif funding "sıkışma adayı" değil, çoktan sıkışmış
   pozisyonun kalıntısı oluyor.
4. **Toplam bildirim hacmi rejimle pek değişmiyor, KARIŞIM değişiyor:**
   çekirdek-30'da boğa ≈ 0.29 (S1) + 1.63 (S3) ≈ 1.9; ayı ≈ 0.53 + 1.23 ≈
   1.8 sinyal/sembol/ay. Boğada S3 ağırlıklı, ayıda S1 ağırlıklı bir akış.

**Bu bir kural DEĞİLDİR.** "Ayıda S3'ü kapat / boğada S1'i gevşet" gibi bir
rejim anahtarı, Ek C'de (Kimi-S6) zaten reddedilmiş bir fikrin yeniden
denenmesi olur ve YENİ bir test atışı gerektirir — Ek J ile S1 ailesinin
atışı harcandığı için şu an mümkün değil. Ayrıca rejim etiketi gerçek zamanda
gecikmelidir (200g SMA geç döner). Ayı piyasasında S3 gürültüsünden rahatsız
olunursa **eşik değiştirmeyen** mevcut çözüm geçerli: `NOTIFY_MIN_CONFIDENCE=
YUKSEK` (Ek H önerisi) S3 push'unu susturur, kayıt devam eder.

## Ek L — S7 VWAP mean-reversion tek-atışı (2026-08-06): RED

**Aday:** Kimi-S5'in yalnız LONG ve sabit biçimi; 1h spotta VWAP24
iskontosu (`Z20 < -2`), `ADX14 < 20`, yeşil bar, sonraki bar açılışı giriş,
`Z >= -0.2`/24h çıkış ve `1.8×ATR14` stop. Maliyet 12bp. Parametre taraması
yapılmadı; karar kapısı script çalıştırılmadan önce sabitlendi.

| Train kümesi | N | Net ortalama | Net medyan | İsabet | Gün-kümeli p |
|---|---:|---:|---:|---:|---:|
| çekirdek-30 | 251 | **−%0.219** | +%0.152 | %51.8 | 0.8803 |
| geniş-59 | 458 | +%0.143 | +%0.680 | %59.8 | 0.2104 |

**Karar: RED.** Önceden kayıtlı çekirdek train kapısını (net ortalama >0,
isabet ≥%55 ve p≤0.05) geçemedi; test dilimine bakılmadı. Strateji canlı bota
eklenmedi. Yeniden eşik ayarlayıp aynı test dilimine bakmak yasaktır. Script:
`eval_vwap_mr.py`; çıktı: `results/vwap_mr_console.txt`.

## Ek M — D1 4h Donchian trend tek-atışı (2026-08-06): RED / shadow adayı değil

**Ön kayıt:** `PREREG_DONCHIAN_4H.md`. Spot 1h verisi UTC 4h mumlara
çevrildi; önceki 20 bar tepe kırılımı, sonraki bar açılışı giriş, önceki 10 bar
dip çıkışı, `2×ATR20` stop, `%1` risk bütçeli ve kaldıraçsız volatilite ölçeği,
12bp maliyet kullanıldı. Parametre taraması yapılmadı.

| Train kümesi | N | Net ort. | Medyan | İsabet | PF | Ölçekli ort. | p(gün) |
|---|---:|---:|---:|---:|---:|---:|---:|
| çekirdek-30 | 1.524 | +%0.673 | −%2.841 | %32.2 | 1.24 | +%0.243 | **0.1580** |
| geniş-59 | 2.872 | +%0.244 | −%3.820 | %29.9 | 1.07 | +%0.089 | 0.2826 |

Ham beklenti ve PF pozitif olsa da çekirdek kapının önceden belirlenmiş
`p<=0.05` şartı geçmedi. Sinyaller coinler arasında aynı giriş günlerinde
kümeleniyor; görünen işlem sayısı bağımsız kanıt sayısını abartıyor. Sağ kuyruk
güçlü (`q90 +%9.85/+%11.20`) fakat tipik işlem negatif ve stop oranı
`%38–40`. **Karar: RED.** Test dönemi hesaplanmadı, canlı bota veya shadow
bildirim kanalına eklenmedi. Script: `eval_donchian_4h.py`; çıktı:
`results/donchian_4h_console.txt`.

## Ek N — C1 delta-nötr spot/perp carry (2026-08-06): RED

**Ön kayıt:** `PREREG_DELTA_NEUTRAL_CARRY.md`. Resmî arşivden 89/89 sembolün
24 aylık USD-M perp 1h verisi eksiksiz indirildi; spot long + eşit baz miktarda
perp short, son 72h funding APR `%15`, üç pozitif settlement, basis `≥%0.05`,
30 gün tavanı ve dört dolumda `7bp/fill` kullanıldı. Funding yalnız pozisyon
settlement öncesinde açıkken yazıldı; 1000-kontratlar baz birime çevrildi.

| Train kümesi | N | Net ort. | Medyan | İsabet | PF | Funding | Basis PnL | Maliyet | p(gün) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| çekirdek-30 | 193 | **−%0.124** | −%0.067 | %33.2 | 0.38 | +%0.132 | −%0.114 | %0.143 | 0.9473 |
| geniş-59 | 796 | **−%0.094** | −%0.098 | %13.8 | 0.22 | +%0.053 | −%0.007 | %0.140 | 1.0000 |

**Mekanizma sonucu:** funding tahsil edildi, fakat çekirdekte basis'in girişten
sonra aleyhe genişlemesi ve her iki evrende dört dolum maliyeti carry'yi aştı.
Çekirdekte `%2.6` marjin-stres olayı da ön-kayıtlı `%1` tavanını geçti. Bu,
funding'in tek başına net arbitraj olmadığını iki bacaklı muhasebeyle doğrular.
**Karar: RED.** Test dönemi hesaplanmadı ve canlı bota eklenmedi. Exchange
iflası/ADL/transfer riski backtest edilemediğinden gerçek risk sonuçtan daha
düşük değil, daha yüksektir. Script: `eval_delta_neutral_carry.py`; veri aracı:
`download_um89.py`; çıktı: `results/delta_neutral_carry_console.txt`.

## Ek O — R1 cross-sectional relative-strength (2026-08-06): RED

**Ön kayıt:** `PREREG_CROSS_SECTIONAL_MOMENTUM.md`. Her 72 saatte son 24 saati
atlayan 30 günlük getiri sıralandı; pozitif ilk `%20`, geçmiş 30 günlük
volatilitenin tersiyle ve coin başına `%25` tavanla long/cash sepete alındı.
Her kolda 12bp maliyet düşüldü. Edge, aynı evrenin eşit-ağırlıklı brüt 72h
getirisine göre `alpha` olarak da ölçüldü.

| Train kümesi | N dönem | Net ort. | Medyan | PF | Alpha | p(alpha) | q10 | Max DD |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| çekirdek-30 | 167 | +%0.299 | −%0.174 | 1.13 | +%0.253 | **0.1816** | −%8.20 | **−%64.4** |
| geniş-59 | 169 | **−%0.416** | −%0.257 | 0.88 | **−%0.300** | 0.7860 | −%11.49 | **−%82.2** |

Çekirdek sonuç küçük pozitif görünse de alpha anlamlı değil ve drawdown kabul
kapısının çok dışında. Genişletilmiş bağımsız evrende hem mutlak getiri hem
alpha işaret değiştirdi. Bu nedenle sonuç piyasa/evren şansı olarak kabul
edildi. **Karar: RED.** Test dönemi hesaplanmadı; canlı veya shadow strateji
eklenmedi. Survivorship riski sonucu daha güçlü değil, daha zayıf yorumlamayı
gerektirir. Script: `eval_cross_sectional_momentum.py`; çıktı:
`results/cross_sectional_momentum_console.txt`.

## Ek P — L1 pump + short crowding + squeeze vekili (2026-08-06): RED / veri sınırı

**Ön kayıt:** `PREREG_PUMP_SHORT_SQUEEZE.md`. Resmî USD-M daily `metrics`
arşivinden, önceden sabit `%5/6h` pump görülen 14.259 sembol-günü indirildi:
89/89 sembol, 4.106.519 adet 5m satır, eksik gün ve ağ hatası yok. Resmî USD-M
`liquidationSnapshot` yolu aynı tarihte 404 olduğu için “likidasyon bölgesi”
uydurulmadı. Fiyat↑ + OI↓ + agresif alış, yalnız **gerçekleşmiş squeeze vekili**
olarak adlandırıldı.

Sabit birleşim: pump `≥%5/6h`, genel hesap L/S `<0.80`, OI 1h `≤−%3`, saatlik
medyan taker buy/sell `>1.20`, son settled funding değişimi `≥+0.0001` ve en
fazla 4 saat eski. Sonraki saat açılışı giriş, 4h çıkış, 12bp maliyet.

| Train kümesi | N | 4h net | Medyan | p(gün) | Pump tabanı | Karar |
|---|---:|---:|---:|---:|---:|---|
| çekirdek-30 | **0** | — | — | — | N=2.619 | RED |
| geniş-59 | **1** | +%0.398 | +%0.398 | 0.4953 | −%0.075 | RED |

**Örneklem çöküşü:** train'de 39.606 pump-saatinin 1.862'si short-crowded;
OI filtresiyle 68, taker filtresiyle 3, funding değişimiyle **1** kaldı. Tek
olayın 24h'de +%6.25 olması edge değildir; seçim etkisine açık bir anekdottur.
Minimum örnek kapısı çok büyük farkla geçilmediği için test dönemi hesaplanmadı
ve eşikler gevşetilmedi. Canlı/shadow sinyal eklenmedi.

**Sonuç:** fikir mekanik olarak makul fakat kamu verisinde gerçek USD-M
likidasyon seviyeleri yok; test edilebilen dürüst proxy ise istatistik üretmeye
yetecek sıklıkta birlikte gerçekleşmiyor. İleri çalışma ancak gerçek force-order
akışı ve oranların aylarca önceden arşivlenmesiyle yeni bir veri döneminde
yapılabilir. Script: `eval_pump_short_squeeze.py`; indirici:
`download_pump_metrics.py`; çıktı: `results/pump_short_squeeze_console.txt`.

## Ek Q — L2 ileri-arşiv başlangıcı (2026-08-06): VERİ TOPLANIYOR

Ek P'nin veri sınırını dürüstçe çözmek için `!forceOrder@arr` USD-M akışı ayrı,
yeniden bağlanabilen bir worker ile aylık JSONL'e alınmaya başladı. Olayların
yanında `connected` / `heartbeat` / `disconnected` satırları tutulur; böylece
collector'ın kapalı olduğu süre "likidasyon yoktu" diye kodlanamaz. Mevcut
saatlik arşiv de OI+bazis+fiyata ek olarak global hesap L/S, taker buy/sell ve
funding görüntüsü taşır. Akış tüm USD-M sembollerini toplar, fakat ilk araştırma
evreni değişmeyen 89 semboldür.

Bu bir strateji eklemesi değildir. Eşikler, minimum örnek kapısı, giriş/çıkış ve
tek test bakışı veri gelmeden önce
`PREREG_FORWARD_SQUEEZE_ARCHIVE.md` içinde donduruldu. En az 180 gün, train'de
100 ve testte 30 olay oluşmadan Telegram/shadow sinyal üretilmeyecek. Binance
force-order akışının sembol başına 1000 ms'de yalnız son snapshot'ı verdiği ve
CoinGlass-benzeri ileri likidasyon bölgesi sağlamadığı sonuçlarda açıkça
korunacaktır.

## Ek R — G1 günün yükseleni + yeni short birikimi (2026-08-31): RED / gölge

**Ön kayıt:** `PREREG_GAINER_SHORT_CROWD.md`. Sabit 89 sembolün 24 aylık
USD-M 1h fiyat panelinde aynı saat içindeki 24s getirisi `%5+` ve ilk 10'da
olan 11.510 sembol-günü belirlendi. UTC 00:00 OI değişimi için önceki gün
bağlamıyla 17.761 sembol-gün ve resmî daily metrics arşivinden 4.814.075 adet
5m OI/global hesap L/S satırı kullanıldı; 89/89 sembol, eksik gün ve ağ hatası
yok. Güncel saat rolling hacim medyanına sokulmadı.

Sabit koşul: ilk-10 + `%5/24s`, 1s quote volume önceki 24 tamamlanmış saatin
medyanının `≥2x`i, OI 1s `≥%2`, global hesap L/S `<1`, 24s cooldown. Sonraki
1s açılış giriş, 4s kapanış çıkış, 12bp maliyet. Long/short alanı hesap
sayısıdır; notional değildir.

| Train kümesi | N | 4s net ort. | Medyan | İsabet | p(gün) | İlk-10 taban edge | q10 |
|---|---:|---:|---:|---:|---:|---:|---:|
| çekirdek-30 | 84 | +%0.046 | −%0.065 | %47.6 | 0.4563 | +%0.074 | −%4.28 |
| geniş-59 | 317 | **−%0.173** | **−%0.415** | %45.4 | 0.6974 | +%0.066 | −%5.94 |
| tüm-89 | 401 | **−%0.127** | **−%0.300** | %45.9 | 0.6676 | +%0.055 | −%5.71 |

12s/24s ortalama sağ kuyruk nedeniyle pozitif görünse de medyan ve isabet
negatiftir; bunlar ön-kayıtlı birincil ufuk değildir ve seçim için
kullanılmadı. İki bağımsız train parçası kapıyı geçmediği için test dönemi
açılmadı. **Karar: RED.** Kullanıcının açık talebiyle yalnız `G1/GOZLEM`
kanalında, tüm aktif Binance USD-M perpetual evreni sıralanarak ileri olay
toplanır; bu statü kabul anlamına gelmez. Scriptler:
`download_gainer_metrics.py`, `eval_gainer_short_crowd.py`; çıktı:
`results/gainer_short_crowd_console.txt`.

## Ek S — DL1 tam-token delist olayı (2026-08-31): PRE RED / POST veri topluyor

**Ön kayıt:** `PREREG_DELIST_EVENT.md`. Resmî Binance Delisting kataloğunda
son beş yıldaki başlığı tam-token kalıbına uyan 36 makale/146 token incelendi.
Pair/margin/futures/Alpha kaldırmaları dışlandı. Kesin işlem durdurma zamanı
makale gövdesindeki UTC metninden alındı; fiyat yalnız resmî spot 1h arşiviydi.

DL1-PRE giriş duyurudan sonraki ilk 1s açılışı, çıkış delistten önceki son 1s
kapanış ve maliyet 12bp:

| Ölçülebilir N | Token | Net ort. | Medyan | İsabet | q10 | q90 | p(gün) |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 107 | 107 | **−%45.44** | **−%53.58** | **%8.4** | −%85.24 | −%7.04 | 1.0000 |

Dönem içi maksimum olumlu hareket medyanı `+%18.58` olsa da bu ex-post MFE,
önceden bilinen çıkış kuralı değildir; aynı penceredeki MAE medyanı `−%60.24`.
Dolayısıyla “deliste kadar yükselir/tut” hipotezi açıkça **RED**.

DL1-POST geçmişte test edilmedi: bugün Bybit/OKX'te görünen kontratı geçmişe
taşımak survivorship/data leakage olurdu. Bot bundan sonra duyuru anındaki
Binance spot ve Bybit/OKX perpetual bulunabilirlik/last/mark/bid/ask/OI/funding
snapshot'larını delistten 72s sonrasına kadar saklar. Minimum 30 olgun ve 20
token olmadan karar yoktur. Çıktı: `results/delist_event_console.txt`.

## Ek T — Canlı örneklem yeterliliği (2026-08-31)

GitHub Pages veri dalındaki son görünür durum 2.466 taramadır. Kanonik zaman
çıkışı ve 12bp varsayımıyla olgun örnekler:

| Strateji | Olgun N | Net medyan | İsabet | N≥30? | Kısa karar |
|---|---:|---:|---:|---|---|
| S1+S4 | 15 | −%0.12 | %40.0 | Hayır | Yetersiz |
| S1 | 16 | −%0.27 | %43.8 | Hayır | Yetersiz |
| S2 | 21 | −%2.87 | %38.1 | Hayır | Yetersiz ve şu an zayıf |
| S3 | 63 | +%0.29 | %54.0 | Evet | İlk ara değerlendirmeye yeterli |
| S5 | 3 | −%0.77 | %33.3 | Hayır | Çok yetersiz |
| S6 | 1 | −%6.75 | %0.0 | Hayır | Çok yetersiz |
| G1 / DL1 | 0 / 0 | — | — | Hayır | Yeni ileri dönem başlıyor |

S3'ün güncel karşılaştırılabilir `core30` kohortu da N=52 ile küçük örnek
uyarısını aşmıştır; yine de tek piyasa rejimi nihai güvenilirlik kanıtı değildir.
S1/S1+S4/S2 ve özellikle S5/S6 için N<30 nedeniyle eşik değişikliği yapmak
erken olur. S2'nin işareti kötü olsa da minimum kapı dolmadan yalnız düşük
güven/sessiz-kayıt politikası korunur. Tablet market/force-order arşivleri
Git'e bilerek gönderilmediğinden bu checkout onların gün sayısını kanıtlayamaz;
cihazda `--archive-status` ve yeni `--shadow-status` kullanılmalıdır.

## Ek U — OI araştırması için otomatik değerlendirme döngüsü (2026-08-31)

OI verisinin biriktirilip unutulmaması için `research_monitor.py` ile sabit bir
takvim bağlandı. Bot her pazartesi 06:00 UTC sonrası ilk turda ve Telegram
`/arastirma` komutunda şu alanları ölçer: saatlik market satır/kapsama süresi,
OI/funding/global-LS/basis/taker doluluğu, force-order olay ve gözlenen gün
sayısı, G1/DL1 ileri olayları. Aynı çıktı terminalde `--research-status` ile
alınır. Ölçüm eşik veya strateji kararına otomatik yazmaz.

Araştırma protokolü iki ardışık ve ayrık dönemdir:

1. **İlk 90 gün — keşif/freeze:** En az %80 saat kapsaması, %90 OI, %80 funding
   ve global-LS doluluğu, son 48 saatte taze kayıt ve en az 30 force-order
   gözlem günü aranır. Kapı geçerse OI+funding+long/short+likidasyon hipotezi
   analiz edilir ve tek kural ön-kaydedilir.
2. **Sonraki 90 gün — dokunulmamış OOS:** Freeze anı
   `RESEARCH_OOS_START_UTC` olarak kaydedilir. Bu dönemde parametre veya seçim
   değiştirilmez. Dönem bitince minimum olay sayısı, maliyetli net getiriler,
   medyan/kuyruklar ve bağımsız olay günleriyle kabul/ret yapılır.

Dolayısıyla ilk gerçek strateji-iyileştirme görüşmesi 90 günlük kalite kapısı
geçildiğinde, güvenilirlik kararı ise en erken 180 günlük döngü sonunda yapılır.
Haftalık yeniden optimizasyon bilinçli olarak yasaktır; yalnız veri sağlığı
raporlanır.

Tablet denetiminde 24,9 günlük tam-alanlı market verisi (45.123 satır, 135
sembol, saat kapsaması %84,3) bulundu; bu keşif için kullanılabilir fakat OOS
değildir. `research/explore_forward_oi.py` top-10 yükselen → 5m taker-hacim
anomalisi → OI artışı → short hesap çoğunluğu → funding yükselişi filtrelerini
sabit sırayla ayrıştırır; giriş sonraki saatlik snapshot, çıkış +4 saat ve maliyet
12bp'dir. Sonuç yalnız hipotez/bottleneck tanısıdır.

Aynı denetimde 23 gün ve 8.109 stream-status satırına karşın sıfır force-order
olayı görüldü. Kök neden Binance'in eski WebSocket `/ws/` yolunu 23 Nisan
2026'da kapatmasıdır. Arşiv `/market/ws/!forceOrder@arr` yoluna taşındı; birleşik
UM/CM payload'larında yalnız `st=1` USD-M kaydedilir. Kalite kapısı artık
heartbeat gününü değil en az 30 gerçek force-order olay gününü ister ve bağlantı
varken olay yoksa açık arıza uyarısı üretir. Kayıp dönem geriye doldurulamaz.
Birleşik keşif saati, tam market alanlarının başlangıcı ile onarılmış akıştaki ilk
gerçek force-order olayının daha geç olanından itibaren 90 gün sayılır; dolayısıyla
önceki `2026-11-04` tahmini artık birleşik strateji için geçerli değildir.

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
