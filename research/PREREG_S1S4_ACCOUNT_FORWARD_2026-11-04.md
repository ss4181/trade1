# S1+S4 otomatik çalışma — ileri doğrulama ön kaydı (4 Kasım 2026)

Sürüm: `s1s4-forward-v1`. İleri dönemin ilk olayından önce yazıldı ve commit'lendi.
Kurallar veri toplanırken değiştirilmez; değişiklik yeni sürüm ve yeni ileri dönem
açar. Bu çalışma emir, bildirim veya strateji eşiği değiştirmez.

## Neyi doğruluyoruz

[Yeniden oynatma raporu](S1S4_AUTOMATION_REPLAY_2026-11-04.md): doğrulanmış
S1+S4 kuralı (24 saat zaman çıkışı, stop yok), hesap 10 eşit 1x spot slota
bölünüp her sinyale bir slot ayrıldığında, eşik seçiminde kullanılmayan
2026-01 → 2026-10 döneminde pozitif ve düşük düşüşlü göründü. Bu ön kayıt aynı
sonucun **bundan sonraki** olaylarda tekrarlanıp tekrarlanmadığını ölçer.

## Kohort

- Giriş zamanı **2026-11-05 00:00 UTC** veya sonrası olan bütün S1+S4 tespitleri
  (Telegram'a gidip gitmediğinden bağımsız; otomatik bot tespitte işlem yapar).
- Kaynak: tabletin `signals.log` dosyası (yetkili, tam kayıt). PC'de herkese açık
  `data.json` anlık görüntüleri yedek kaynaktır; aynı (sembol, sinyal mumu) tekilleşir.
- S1+S4 yapılandırması `2026-07-24-v2` dışındaysa ileri dönem durur; yeni sürüm gerekir.
- Fiyat: Binance spot 1dk/1s, araç önbelleğiyle. Eksik veya ardışık olmayan yol
  `unknown`; kazanç/kayıp sayılmaz.

## Kurallar (araç: `research/replay_s1s4_account.py`, `s1s4-account-replay-v1`)

- Giriş: tespit kaydından sonraki ilk tam dakikanın açılışı. Çıkış: 24 saat sonra
  son dakikanın kapanışı. Maliyet 20 bp (komisyon + kayma); kaldıraç yok.
- Hesap: **10 eşit slot** (birincil) ve 5 slot (ikincil); bütün slotlar doluysa
  sinyal atlanır; aynı dakikadaki sinyaller sembol sırasıyla alınır, sonuca göre değil.
- Tanımlayıcı karşılaştırmalar: %15 felaket stopu, TP2 + 1,5×ATR (24s ve 4s).

## Hazırlık kapısı

En az **40 puanlanmış olay, 15 ayrı olay günü ve 8 takvim haftası**. Kapıdan önce
ara raporlar yalnız sayıları gösterir; karar verilmez. Bugünkü sıklıkla kapı
yaklaşık 3–4 ay sürer.

## Karar kuralı (birincil: 24s kuralı, 10 slot, 20 bp)

- **DOĞRULANDI:** 10 slot hesap getirisi > 0, olay başı ortalama net > 0 ve medyan net > 0.
- **GÜÇLÜ:** ek olarak gün-blok %95 aralığının alt sınırı > 0.
- **DOĞRULANMADI:** hesap getirisi ≤ 0 veya olay başı ortalama ≤ 0.

DOĞRULANDI sonucu demo (sanal para) otomasyonunu kurmayı gerekçelendirir; gerçek
para için en az GÜÇLÜ sonuç, demo dolum/kayma kanıtı ve kullanıcının ayrı kararı
gerekir. Hiçbir sonuç canlı emri kendiliğinden açmaz.

## Çalıştırma

Tablette (ağ yalnız herkese açık Binance kline verisi için kullanılır):

```bash
cd ~/trade1
python research/replay_s1s4_account.py --events signals.log --since 2026-11-05T00:00:00+00:00
```
