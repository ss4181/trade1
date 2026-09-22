# Telegram piyasa rejimi

Bu sürüm `/piyasa` ve `/rejim` komutlarını, kalıcı Telegram menüsündeki **🌐 Piyasa** düğmesini ekler. Yanıt yalnız kapanmış Binance spot BTCUSDT günlük mumlarından üretilir:

- `BULL`: kapanış, M200'ün %2 üzerindedir ve M200'ün 20 günlük eğimi pozitiftir.
- `BEAR`: kapanış, M200'ün %2 altındadır ve eğim negatiftir.
- `TRANSITION`: yeterli ve güncel veri vardır, ancak iki kesin koşul birlikte sağlanmıyordur.
- Boğada alt tür: son 30 günlük BTC getirisine göre `bull_pullback`, `bull_moderate`, `bull_strong`.
- Eksik/bayat/geçersiz veri `UNKNOWN` kalır; `TRANSITION` diye gizlenmez.

Hesaplama `market_regime.py` içinde saf ve ağdan bağımsızdır. `signal_bot.py` içindeki `market-regime` daemon worker'ı günlük veriyi yeniler; ana sinyal taraması ve Telegram komutları bu HTTP isteğini beklemez. Snapshot `/health` altında `market_regime` (eski istemciler için `market_regime_shadow` takma adı) olarak görünür.

S1, S1+S4, S2, S3, S5, S6, G1 ve G2 olay kayıtlarına snapshot sürümü, alt türü ve veri kapanış zamanı eklenir. Bu alanlar karar anında dondurulur; eski kayıtlar bugünkü etiketle geriye dönük doldurulmaz. Rejim yalnız bilgilendirme ve ileri araştırma içindir; strateji koşulları, bildirim kapısı, cooldown veya emirler değişmez.

Kullanıcı doğrulaması:

```text
cd ~/trade1
git pull --ff-only
```

Botun mevcut Termux başlatma betiğiyle tek örnek olarak yeniden başlatıldıktan sonra Telegram'da `/start` yazıp **🌐 Piyasa** düğmesine basılabilir. Komut doğrudan `/piyasa` olarak da çalışır. Yanıt günlük kapanış saatini TRT ile gösterir.

Araştırma protokolü ve rejim bazlı karşılaştırmalar çalışma ağacındaki `research/MARKET_REGIME_REVIEW_2026-09-22.md`, `research/MARKET_REGIME_PROTOCOL_2026-09-22.md` ve `research/LUNA_MARKET_REGIME_HANDOFF_2026-09-22.md` dosyalarındadır.
