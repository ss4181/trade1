# G1 v3 — yayın ve tablet kabul kontrolü

Bu paket G1'in fiyat referansını ve hedef ölçümünü düzeltir. G1 koşulları,
saatlik sinyal mumu, eşikleri, tüm aktif USD-M perpetual evreni, cooldown ve
5dk ana tarama sıklığı değişmez. Diğer stratejilerin işlem/sinyal kuralları,
G2 bildirim zamanlaması ve Telegram teslim politikası korunur. Bot emir açmaz.

## Değişen ölçüm

- Config: `G1-prereg-2026-10-03-v3-fresh-ask`.
- Hedef ölçümü: `signal-reference-touch-1m-v2`.
- Koşul teyidinden sonra alınan taze best ask gösterilir; dolum değildir.
  Yaş ve spread açıklanır. Kotasyon isteği tek deneme/5sn ile sınırlıdır;
  mevcut rate-limit kapısını atlamaz.
- Taze kotasyon yoksa sinyal gizlenmez. Kotasyon alınamaz veya doğrulanmış
  teslimde 30sn'den eskiyse yeni hedef karnesine alınmaz.
- Hedef/MFE/MAE yalnız teslimden sonraki ilk tam 1dk mumundan ölçülür.
  Kısmi ilk dakika bilinmiyor; alarm güncellemesi mevcut tarama sıklığındadır.
- Eski G1 5dk olayları yeniden yazılmaz. Yeni kohort oluşunca eski kart
  `G1 · 5m (eski)` adıyla ayrılır. Veri eksikliği başarısız işlem sayılmaz.
- Kanonik next-hour-open → 4h kapanışı performansı ayrı kalır. Dokunma
  oranı, maliyet/funding sonrası TP/SL kazancı veya gelecek başarı olasılığı değildir.

## Ayrı gölge giriş deneyi

Her yeni ve teslim kanıtlı G1'de ilk tam dakika açılışı, 5/15dk bekleme ve
5/15dk kapanış teyidi ayrı ölçülür. Teyit, tamamlanmış pencerenin son kapanışının
ilk açılıştan yüksek olmasıdır; giriş sonraki dakika açılışıdır. TP3/SL2,
aynı mumda stop önce, bütün girişlerde aynı 4h bitişi ve 20/40bp maliyet
varsayımı sabittir. Funding `not_modeled`. Bu deney filtre veya emir değildir;
en az 90 ileri gün, 30 olgun olay ve 28 ayrı olay günü otomatik terfi sağlamaz.

## Tablet güncellemesi

Her komutun başarıyla bitmesini bekleyin; hata varsa sonraki adıma geçmeyin.
Anahtarları veya `.env` içeriğini sohbete göndermeyin.

```bash
cd ~/trade1
touch .stop-signal-bot
pkill -f 'uvicorn server:app' 2>/dev/null || true
pkill -f 'python signal_bot.py' 2>/dev/null || true
```

Wrapper'ın durması için birkaç saniye bekleyin, sonra:

```bash
pgrep -af 'boot-signal-bot.sh|uvicorn server:app|python signal_bot.py'
```

Bot veya wrapper görünüyorsa henüz yeni wrapper başlatmayın. Wrapper yalnız
uyku döngüsünde kaldıysa stop dosyası varken sonlanmasını bekleyin.

```bash
git pull --ff-only origin main
git --no-pager log -1 --oneline
python -c "import g1_entry; print(g1_entry.CONFIG_VERSION); print(g1_entry.MEASUREMENT)"
```

`v3-fresh-ask` ve `signal-reference-touch-1m-v2` doğrulandıktan sonra:

```bash
rm -f .stop-signal-bot
nohup ./termux/boot-signal-bot.sh >/dev/null 2>&1 &
```

Başlangıçtan sonra `pgrep` kontrolünde tek tarayıcı (doğrudan Python veya
uvicorn) bulunmalı. Sır içermeyen log satırlarıyla başlangıcı kontrol edin:

```bash
grep -E 'signal_bot basladi|tarama bitti' bot.out.log | tail -5
python research/review_g1_entry_shadow.py --format text
```

Boş ileri rapor ilk yeni, taze kotasyonlu G1 teslimine kadar normaldir.

## Kabul kontrolü

1. Güncel panonun `status.g1_entry_config_version` alanı yukarıdaki v3 config;
   `status.g1_entry_measurement_version` alanı yeni 1dk sürümü olmalı.
   Diskteki dosyanın güncellenmesi çalışan eski süreci güncellemez.
2. İlk yeni G1 bildirimi ask, yaş/spread ve dolum olmadığı bilgisini göstermeli.
   Kotasyon alınamadıysa açık uyarı beklenir; bu durumda hedef oranı üretilmez.
3. Teslim ve taze kotasyon kanıtı olan yeni olayın `price_target.measurement_version`
   alanı 1dk sürümü ve `bar_interval_minutes` alanı `1` olmalı.
4. Eski kayıtların config/5dk ölçümü değişmemeli; S1/S2/S3/G2 davranışı korunmalı.
5. İlk tam mumlar kapanınca `entry_shadow` planları oluşmalı. Pending veya
   unavailable kayıtlar kazanmış/kaybetmiş varsayılmamalı.

GitHub CI geçmesi tablet deploy'u veya gerçek Telegram teslimi kanıtı değildir.

## Giriş karşılaştırması raporu (11 Ekim eki)

`research/G1_ENTRY_COMPARISON_PROTOCOL.md` beş sabit planın ölçüm/payda
kurallarını, `research/G1_ENTRY_COMPARISON_2026-10-11.md` ilk karşılaştırmayı
açıklar. `--format json` ayrıntılı maliyet, rejim, kaçırılan fırsat ve
eşlenmiş karşılaştırmayı verir. `--state /yedek/.price_target_state.json`
ile PC yedeği salt okunur incelenebilir. Kopyada yeni v3 teslim yoksa rapor
boştur; eski sinyaller ileri doğrulama sayılmaz.

Ek telemetri sürümü `g1-entry-path-v1`, panonun
`status.g1_entry_path_version` alanında görünür. Bu sürüm yalnız MAE/MFE,
timeout zamanı ve sinyal-anı rejim kanıtı ekler; G1 giriş kuralları, TP3/SL2,
bildirim ve tarama davranışı değişmez. Ham state'i kamuya yüklemeyin.
Tablet erişimi olmadan bu kabul adımlarının tamamlandığı iddia edilmez.
