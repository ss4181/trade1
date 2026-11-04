# S1+S4 otomatik çalışma — yeniden oynatma (4 Kasım 2026)

**Araştırma sonucu; canlı emir, yatırım planı veya doğrulanmış hesap getirisi değildir.**
Strateji eşikleri, bildirimler ve emir davranışı değişmedi. İleri doğrulama:
[ön kayıt](PREREG_S1S4_ACCOUNT_FORWARD_2026-11-04.md).

## Soru

S1+S4 sinyallerine bir bot otomatik girip çıksaydı ne olurdu; hangi sınırlarla?
G1 için aynı soru olumsuz çıktı ([ATR sonucu](G1_ATR_SPLIT_RESULT_2026-11-03.md)).

## Veri ve yöntem

- **Arşiv:** `research/data/all-execution-2026-10-02/events.jsonl` içindeki 347
  spot S1+S4 olayı (2024-07 → 2026-07-18, 72 olay günü). 2024-07 → 2025-12, S1
  eşiklerinin seçildiği dönemdir; bu dönem bağımsız kanıt sayılmaz.
- **Canlı:** `trade1-data` dalındaki pano anlık görüntülerinden 39 S1+S4 tespiti
  (2026-07-20 → 2026-10-15, 16 gün), kurallar Temmuz'da dondurulduktan sonra.
- Giriş: tespitten sonraki ilk tam dakika açılışı (arşivde ilk uygulanabilir dakika).
  Fiyat: Binance spot 1dk; ATR için 1s. Maliyet 20 bp. Aynı dakikada stop ve hedef
  görülürse stop önce. 386 olayın hiçbiri eksik veri nedeniyle dışarıda kalmadı.
- Hesap modeli: hesap eşit 1x slotlara bölünür, her sinyale bir slot; slotlar
  doluysa sinyal atlanır; aynı dakikadaki sinyaller sembol sırasıyla alınır.
  İlk denemede eşitlikler sonuca göre sıralanıyordu (gelecek bilgisi); düzeltildi
  ve testle kilitlendi.

## Planlar

| Ad | Kural |
|---|---|
| `time24` | Doğrulanmış kural: 24 saat sonra çık, stop yok |
| `disaster15` | 24 saat + %15 felaket stopu |
| `card` / `card4h` | TP +%2 + 1,5×ATR stop; 24 saat / 4 saat sınırı |

## Sonuçlar (20 bp)

Olay başına net getiri (gün-blok %95 aralığı):

| Dönem | Olay / gün | `time24` | `disaster15` | `card4h` |
|---|---:|---:|---:|---:|
| Arşiv 2024-07 → 2026-07 | 347 / 72 | +%2,07 [−0,26, +4,89], kazanma %58 | +%1,47 | −%0,08 |
| Canlı 2026-07 → 2026-10 | 39 / 16 | +%0,91 [−1,98, +3,50], kazanma %62 | +%0,81 | +%0,64 |
| Bağımsız: 2026-01 → 2026-10 | 138 / 48 | +%1,39 [−0,18, +3,11], kazanma %64 | +%0,93 | +%0,30 |

Hesap düzeyi (`time24`): getiri / en büyük düşüş

| Slot | Arşiv | Bağımsız 2026-01 → 2026-10 |
|---:|---:|---:|
| 1 | −%34,7 / −%57,5 | +%11,3 / −%26,9 |
| 5 | +%33,2 / −%13,7 | +%11,8 / −%5,6 |
| 10 | +%33,3 / −%7,5 | **+%12,4 / −%2,8** |

## Yorum

- Doğrulanmış 24 saat kuralı canlıda geçmiş testi tekrarladı (canlı medyan
  +%0,88; Temmuz testi +%0,86). Kazanç, sert düşüş sonrası toparlanmalardan
  ve kümelenen günlerden geliyor; dağılım şişman kuyruklu.
- **Tek slot kırılgan:** sonuç aynı dakikadaki hangi sinyalin alındığına göre
  −%35 ile −%50 arasında oynadı. Kümenin ilk sinyali çoğu kez düşüşün ortasında.
  Birçok küçük eşit pozisyon gerekir.
- **TP2 + stop tarzı** canlıda iyi göründü ama arşivde negatif; stop ve erken kâr
  alma, S1+S4'ün kazandığı toparlanmaları kesiyor. %15 felaket stopu da getiriyi düşürdü.
- Bağımsız dönemin güven aralıkları sıfırı içeriyor; 48 olay günü az. Bu yüzden
  karar ileri doğrulamaya bırakıldı.

## Sınırlar

Dolum, kayma ve spread dakikalık açılışla yaklaşık modellendi; emir defteri
derinliği yok. Spot ve kaldıraçsız varsayıldı; vadeli işlemde funding ve tasfiye
riski bu sonuçlara dahil değil. Arşivin bir kısmı eşik seçim dönemi.

## Tekrar üretim

```bash
python research/replay_s1s4_account.py --events research/data/all-execution-2026-10-02/events.jsonl --until 2026-07-19T00:00:00+00:00
python research/replay_s1s4_account.py --events <trade1-data data.json anlık görüntüleri>
python research/replay_s1s4_account.py --events research/data/all-execution-2026-10-02/events.jsonl <anlık görüntüler> --since 2026-01-01T00:00:00+00:00
```
