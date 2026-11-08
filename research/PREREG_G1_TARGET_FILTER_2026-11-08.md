# G1 hedef filtresi — ön kayıt

Sürüm: `g1-target-filter-v1`. Bu belge ve araç, sonuçlar hesaplanmadan önce yazıldı;
belgenin SHA-256 özeti her çalıştırmanın çıktısına yazılır. Kurallar sonuç
görüldükten sonra değiştirilmez; değişiklik yeni sürüm açar. Canlı G1, bildirim
veya emir davranışı değişmez.

## Soru

Girişte bilinen tek bir özellik, G1 olayına hangi kâr hedefinin uygulanacağını
seçmeye yarıyor mu? Yani özelliğe göre hedef değiştirmek, her olayda aynı hedefi
kullanmaktan daha iyi sonuç veriyor mu?

## Veri ve dönemler

| Dönem | Kapsam | Kullanım |
|---|---|---|
| Keşif | `g1_events.json`, karar zamanı < 2025-07-01 UTC | Eşikler, hedef eşlemesi ve özellik yalnız burada seçilir |
| Ayrılmış | 2025-07-01 ≤ karar zamanı < 2026-08-31 UTC | Tek seferlik karar testi |
| Canlı | Pano anlık görüntülerindeki G1 olayları, karar zamanı ≥ 2026-08-31 UTC | 1 dakikalık yön kontrolü |

Keşif ve ayrılmış dönem saatlik mumludur. Canlı dönem Binance USD-M 1 dakikalık
mumlarıyla ölçülür: giriş teslim veya bildirimden sonraki ilk tam dakikanın açılışı.

## Aday özellikler (yalnız bu beş)

`return_24h`, `rank`, `volume_ratio`, `last_hour_return` (koşul mumunun kapanış/açılış
getirisi), `dist_24h_high` (koşul kapanışının son 24 mumun en yükseğine uzaklığı).

Hariç tutulanlar: ATR (`g1-atr-split-hist-v1` ile sınandı ve desteklenmedi); OI ve
long/short (arşivde saat H, canlı botta bir saat gecikmeli; tanımlar eşit değil).

## Ortak işlem kuralları

- Stop: 1,5×ATR14(1s). Süre sınırı: 4 saat. Maliyet: birincil 20 bp, duyarlılık 40 bp.
  Funding modellenmez. R = (brüt % − maliyet) / stop mesafesi %.
- Hedefler: +%2, +%3, +%5, +%10, hedefsiz.
- Aynı mumda stop ve hedef görülürse stop önce (birincil). Saatlik veride hedef-önce
  iyimser sınır ayrıca raporlanır; karar muhafazakâr sırayla verilir.
- ATR, özellik veya fiyat yolu eksikse olay `unknown` sayılır ve puanlanmaz.

## Keşif dönemindeki mekanik seçim

1. Her özellik için keşif döneminin %33 ve %67'lik noktalarından üç kova oluştur.
2. Her kovada ortalama R'si en yüksek hedefi seç (kovanın hedefi).
3. Her kovası en az 200 olay ve 60 ayrı gün içeren özellikler aday kalır.
4. Her olaya kendi kovasının hedefini uygulayan politikanın (`adaptive`) keşif ortalama
   R'si en yüksek özellik seçilir; eşitlikte listedeki ilk özellik.
5. Karşılaştırma tabanları: kart hedefi (+%2) ve keşifte en iyi tek sabit hedef.

İkincil `skip` politikası: keşifte en iyi hedefin ortalama R'si ≤ 0 olan kovalarda
işlem yapmaz (R = 0). Karar kuralını etkilemez.

## Karar kuralı (ayrılmış dönem, muhafazakâr sıra, 20 bp)

Haftalık blok bootstrap (%95, 4000 tekrar, tohum 0), aynı olaylar üzerinde eşlenmiş fark:

- **DESTEKLENDİ:** `adaptive − kart` ve `adaptive − en iyi sabit` farklarının ikisinin de
  alt sınırı > 0 **ve** canlı dönemde iki farkın nokta tahmini de > 0.
- **KISMİ:** ayrılmış dönemde iki koşul sağlanır ama canlı yön kontrolü sağlanmaz.
- **DESTEKLENMEDİ:** diğer bütün durumlar.

Ayrıca ayrı bir ifade olarak raporlanır: `adaptive` ortalama R'si sıfırdan büyük mü?
Bir hedef filtresi göreli iyileşme sağlasa bile G1'i kârlı yapmayabilir.

## Sonuç ne olursa olsun

Canlı karta, bildirime veya emre otomatik geçiş yoktur. Desteklenirse sonraki adım,
aynı dondurulmuş politikanın ileri gölgede ölçülmesi ve kullanıcının ayrı kararıdır.

Araç: `research/eval_g1_target_filter.py`. Ağ yalnız herkese açık Binance kline
verisi için kullanılır; Telegram, emir veya hesap erişimi yoktur.
