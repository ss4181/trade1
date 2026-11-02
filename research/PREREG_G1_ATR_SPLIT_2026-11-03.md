# G1 yüksek oynaklık (ATR) hipotezi — tarihsel ön kayıt (3 Kasım 2026)

Sürüm: `g1-atr-split-hist-v1`. Bu belge tarihsel sonuçlar hesaplanmadan önce
yazıldı ve commit'lendi. Kurallar sonuç görüldükten sonra değiştirilmez;
değişiklik gerekirse yeni sürüm açılır ve bu sürümün sonucu ayrıca raporlanır.

## Hipotezin kaynağı (kanıt sayılmaz)

31 Ağustos – 2 Kasım 2026 canlı 205 G1 olayında, kart kuralıyla (TP +%2,
1,5×ATR stop, 4 saat) ATR14(1s) ≥ %6,03 olan üçte birlik grup %91 kazanma ve
+0,057R; kalan grup −0,099R verdi. Bu ayrım ~30 bölme denendikten sonra
bulundu; şans eseri olabilir. Bu yüzden aynı canlı olaylar bu testte
**kullanılmaz**.

## Veri

- `research/data/historical-universe-2026-10-05/g1_events.json`: resmî Binance
  USD-M 1s arşivinden, canlı G1 ile aynı koşullar ve kenar-tetikleme + coin
  başına 24 saat bekleme ile üretilmiş olaylar (`PREREG_HISTORICAL_G1_METRICS_2026-10-06.md`).
- Fiyat: aynı klasördeki `1h/<SEMBOL>.parquet` saatlik mumlar.
- **Hariç:** `decision_ms` ≥ 2026-08-31 00:00 UTC (hipotezin bulunduğu canlı
  dönemle çakışan olaylar). Böylece dönemler: `older_history` (2020-01 → 2024-06),
  `previously_seen` (2024-07 → 2026-06), `recent_control` (2026-07-01 → 2026-08-30).

## Tanımlar

- Koşul mumu: `entry_index − 1`. ATR14: koşul mumu dahil son 15 kapanmış saatlik
  mumdan 14 true range'in basit ortalaması / koşul mumu kapanışı × 100
  (canlı `atr14_1h_pct` ile aynı). 15 mum ardışık değilse olay `unknown`.
- Grup eşiği önceden sabit: **ATR ≥ %6,0** (canlı tercil sınırı %6,03'ün yuvarlağı).
- Giriş: `entry_index` mumunun açılışı (koşul kapanışından sonraki saat açılışı).
- Yol: giriş mumu dahil 4 saatlik mum; dördüncü mumun kapanışı süre çıkışı.
  4 mum ardışık değilse `unknown`. Eksik/`unknown` olay kazanç veya kayıp sayılmaz.
- R = (brüt % − maliyet) / stop mesafesi %.

## Planlar

| Plan | Hedef | Stop | Rol |
|---|---|---|---|
| `card` | +%2 | 1,5×ATR | **Birincil** |
| `tp3` | +%3 | 1,5×ATR | İkincil, tanımlayıcı |
| `no_target` | yok | 2×ATR | İkincil, tanımlayıcı |

Saatlik mumda sıra bilinmez. **Birincil sıra muhafazakârdır:** açılış stopun
altındaysa açılıştan çıkış; mumda stop ve hedef birlikte görülürse stop önce.
Açılış hedefin üstündeyse hedef fiyatından çıkış. Ayrıca aynı mumda hedef-önce
varsayan iyimser sınır raporlanır; karar yalnız muhafazakâr sırayla verilir.
Maliyet: birincil 20 bp, duyarlılık 40 bp. Funding modellenmez.

## Karar kuralı (birincil plan, muhafazakâr sıra, 20 bp)

- **DESTEKLENDİ:** (a) üç dönemin her birinde ATR ≥ %6 grubunun ortalama R'si
  ATR < %6 grubundan büyük **ve** (b) dönemler birleşik ATR ≥ %6 ortalama R'si
  sıfırdan büyük, haftalık blok bootstrap (%95, 4000 tekrar, tohum 0) alt sınırı > 0.
- **KISMİ:** (a) sağlanır, (b) sağlanmaz — göreli iyileşme var, mutlak avantaj yok.
- **DESTEKLENMEDİ:** (a) sağlanmaz.

Ek olarak tanımlayıcı: ATR çeyreklerinde ortalama R (monoton mu), kazanma
oranları, dönem tabloları, 40 bp ve iyimser sıra sonuçları. Bunlar karar
kuralını değiştirmez.

## Sonuç ne olursa olsun

- DESTEKLENDİ bile canlı strateji, bildirim filtresi veya emir değişikliği
  otomatik değildir. Sonraki adım ileri gölgede (`g1-exit-shadow-v1`, ATR
  kayıtlı) aynı ayrımın doğrulanması ve kullanıcı kararıdır.
- Saatlik çözünürlük 1 dakikalık canlı ölçümle aynı değildir; giriş/kayma/
  dolum modellenmez.

Araç: `research/eval_g1_atr_split.py` (ağ, Telegram, emir yok; yalnız yerel arşiv).
