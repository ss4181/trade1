# Luna devri — tamamlanan uygulama

Bu release üzerinde piyasa rejimi özelliği uygulanmıştır. Luna’nın sonraki görevi kod incelemesi, release dalının güncel GitHub main ile karşılaştırılması ve yayın sonrası tablet doğrulamasıdır.

Tamamlananlar:

- `market_regime.py`: ağdan bağımsız, sürümlü `btc-daily-regime-v1` hesabı; kapanmış günlük mum, M200, 20g eğim, 30g alt tür, UNKNOWN/bayat doğrulaması.
- `signal_bot.py`: ayrı daemon worker, atomik snapshot, `/piyasa` ve `/rejim`, **🌐 Piyasa** menü düğmesi. Worker taramayı/komut cevabını bloklamaz.
- Tüm sinyal yollarında (`S1`, `S1+S4`, `S2`, `S3`, `S5`, `S6`, `G1`, `G2`, `DL1`) snapshot metadata’sı; pano ve `/health` alanları.
- Eski `market_regime_shadow` health alanı geriye dönük uyumluluk için korunmuştur.
- `tests/test_market_regime.py` ve mevcut offline test sözleşmesi güncellendi.
- TP2/TP3 dokunma yeniden hesabı `MARKET_REGIME_TOUCH_REVIEW_2026-09-22.md`
  ve `research/results/market_regime_touch_review_2026-09-22.json` içinde
  ayrı ölçü olarak eklendi. G1 için son 90/180 günlük alt pencereler raporlandı;
  otomatik filtre açılmadı.

Kabul: `tests/run_isolated.py` — 29 suite, 0 hata. Üretim kodu ana taramanın HTTP kritik yoluna günlük rejim isteği eklemiyor. Bot emir açmaz/kapatmaz; rejim otomatik filtre değildir.

Yayın sonrası Termux adımları:

1. `cd ~/trade1`
2. `git pull --ff-only`
3. Mevcut tek-instance `termux/boot-signal-bot.sh` akışıyla yeniden başlat.
4. Telegram’da `/start`, ardından **🌐 Piyasa**; gerekirse doğrudan `/piyasa`.
5. Yanıtta rejim, alt tür ve günlük kapanışın TRT saatini kontrol et.
6. `/status` içinde `market_regime` worker durumu görünür; yeni sinyal sonrası mevcut delivery status ile gecikmeyi ölç.

Bu değişiklikler mevcut rejim release'ine ek bir araştırma commit'i olarak
yayınlanmalıdır; tablet botunun canlı eşikleri değiştirilmez. Luna'nın inceleme
kapısı: TP2/TP3 dokunması, TP/SL sırası ve teslim gecikmesi ayrı raporlanmalı,
tek başarı oranında birleştirilmemelidir.
