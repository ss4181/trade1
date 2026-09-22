# Luna devri — tamamlanan uygulama

Bu release üzerinde piyasa rejimi özelliği uygulanmıştır. Luna’nın sonraki görevi kod incelemesi, release dalının güncel GitHub main ile karşılaştırılması ve yayın sonrası tablet doğrulamasıdır.

Tamamlananlar:

- `market_regime.py`: ağdan bağımsız, sürümlü `btc-daily-regime-v1` hesabı; kapanmış günlük mum, M200, 20g eğim, 30g alt tür, UNKNOWN/bayat doğrulaması.
- `signal_bot.py`: ayrı daemon worker, `/piyasa` ve `/rejim`, **🌐 Piyasa** menü düğmesi. Worker taramayı/komut cevabını bloklamaz.
- Sinyal olaylarında snapshot sürümü, alt türü ve veri kapanış zamanı; pano ve `/health` alanları.
- Eski `market_regime_shadow` health alanı geriye dönük uyumluluk için korunmuştur.
- `tests/test_market_regime.py` ve mevcut offline test sözleşmesi güncellendi.

Kabul: `tests/run_isolated.py` — 29 suite, 0 hata. Üretim kodu ana taramanın HTTP kritik yoluna günlük rejim isteği eklemiyor. Bot emir açmaz/kapatmaz; rejim otomatik filtre değildir.

Yayın sonrası Termux adımları: `cd ~/trade1`, `git pull --ff-only`, mevcut tek-instance `termux/boot-signal-bot.sh` akışıyla yeniden başlat, Telegram’da `/start` ardından **🌐 Piyasa** (veya `/piyasa`) yaz. `/status` içinde `market_regime` worker durumu görünür.

Push/deploy bu committe yapılmadı; önce release diff’i ve GitHub main karşılaştırması yapılmalıdır.
