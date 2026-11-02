# G1 çıkış planı gölgesi — ön kayıt (2 Kasım 2026)

Sürüm: `g1-exit-shadow-v1`. Araştırma-only: Telegram bildirimi, emir, G1
koşulu, evren, cooldown, hedef karnesi veya giriş gölgesi (`g1-entry-shadow-v1`)
değişmez. Bu belge sonuçlar görülmeden önce donduruldu; kurallar ileri veri
toplanırken değiştirilmez. Değişiklik gerekirse yeni sürüm ve yeni ileri dönem açılır.

## Soru

Aynı G1 girişinde, aynı ATR-ölçekli stop ve aynı 4 saatlik süre sınırıyla,
dört çıkış planından hangisi olay başına daha iyi maliyet-sonrası sonuç verir?

Motivasyon kişisel işlem geçmişinin örneklem-içi incelemesiydi. O inceleme
**kanıt sayılmaz**: hedef planları orada düzensiz ve birkaç büyük harekete
bağlı sonuç verdi. Karar yalnız bu ön kayıttan sonra gelen olaylarla verilir.

## Kohort

- Bu sürüm tablette çalışmaya başladıktan sonra teslimi doğrulanan, taze
  kotasyonlu, `signal-reference-touch-1m-v2` ölçümlü G1 olayları.
- Olayda point-in-time `atr14_1h_pct` bulunmalı: koşul mumuna kadar kapanmış
  son 14 saatlik true range'in basit ortalaması / son kapanış. Yoksa plan
  `unavailable`; kazanç veya kayıp sayılmaz.
- Eski olaylar geri doldurulmaz; tarihsel/replay sonuçlar bu kohorta katılmaz.

## Ortak kurallar (dört plan için aynı)

- Giriş: teslimden sonraki ilk **tam** 1dk mumunun açılışı (giriş gölgesindeki
  `immediate` ile aynı). O mum eksikse olay `unavailable`; sonraki mum seçilmez.
- Stop: giriş × (1 − 1,5 × ATR%). Stop mesafesi ≥%50 ise `unavailable`.
- Süre: fiyat hedefi olayının bitişi (teslim + 4 saat). Bitişte açık kalan
  kısım son kapanmış 1dk mumunun kapanışından `TIMEOUT` olur.
- Aynı 1dk mumda stop ve hedef birlikte görülürse **stop önce**
  (`AMBIGUOUS_SL`). Açılış stopun altındaysa açılıştan (`SL_GAP`). Açılış
  hedefin üstündeyse hedef fiyatından (iyimser dolum varsayılmaz).
- Yalnız LONG. Maliyet raporda 20 ve 40 bp toplam; funding `not_modeled`.
  Kaldıraç, miktar, dolar PnL veya kişisel risk tutarı üretilmez.

## Planlar

| Anahtar | Kural |
|---|---|
| `tp2` | Tamamı +%2 hedefte kapanır |
| `half_tp2` | Yarısı +%2'de; kalan yarının stopu girişe (başabaş) çekilir, kalan yarı başabaş stopu veya 4 saat bitişiyle kapanır. +%2 mumunda fiyat girişin altına da indiyse kalan yarı başabaşta kapanmış sayılır (muhafazakâr) |
| `tp10` | Tamamı +%10 hedefte kapanır |
| `no_target` | Hedef yok; stop veya 4 saat bitişi |

## Ölçümler

Plan başına: tamamlanan olay sayısı, durum dağılımı, net20/net40 ortalama ve
medyan (%), q10/q90, kazanma oranı, R cinsinden ortalama (R = brüt getiri /
stop mesafesi), en kötü olay, olay günü ve takvim haftası sayısı. Her plan için
`tp2`'ye göre **eşlenmiş fark** (aynı olay) ve gün-blok bootstrap %95 aralığı.

## Hazırlık kapısı ve karar sınırı

- İlk inceleme için en az **30 tamamlanmış olay, 20 ayrı olay günü ve 4 takvim
  haftası**. Kapı geçilmeden rapor yalnız sayıları gösterir, plan sıralaması vermez.
- Bir planın `tp2`'den "daha iyi" denebilmesi için net40 eşlenmiş farkın
  gün-blok %95 aralığının tamamen sıfırın üstünde olması gerekir. Aksi halde
  sonuç "fark gösterilemedi"dir.
- Kapı ve aralık geçilse bile canlı kart, hedef veya emir otomatik değişmez;
  sonuç kullanıcıya sunulur ve karar ayrıca verilir.

## Dosyalar

- Hesap: `g1_entry.advance_exit_shadow` / `finish_exit_shadow`; olay state'i
  `.price_target_state.json` içinde `exit_shadow`.
- Kamuya açık pano yalnız plan durumu, giriş/çıkış zamanı, giriş fiyatı, stop
  mesafesi ve brüt getiriyi yayımlar.
- Rapor: `python research/review_g1_exit_shadow.py` (ağ, Telegram, emir yok).
