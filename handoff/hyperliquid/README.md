# Trade1 → bağımsız Hyperliquid otomasyon projesi

13 Ekim 2026. Bu teslim bir araştırma/devralma paketidir; çalışan Hyperliquid
emir botu, canlı deploy, yatırılmış para veya doğrulanmış kâr avantajı değildir.
Binance testnet pilotu beklemede; onu Hyperliquid'e bağlayarak çalıştırmayın.

## Başlamak

1. Yeni ve boş bir proje klasörü oluştur: örneğin `hyperliquid-auto-pilot`.
   Mevcut `hyperliquid-bot` veya Trade1 klasörünü ezme. Ayrı repo, sanal ortam,
   veri dizini, Telegram tokenı ve deney kimlikleri kullan.
2. Özel ZIP'i yeni klasöre aç. `reference/trade1/` yalnız okunacak kanıttır;
   buradaki `signal_bot.py` çalıştırılmayacak ve eski `.env` taşınmayacak.
3. Yeni Codex/Claude Code oturumunu bu klasörde aç. `START_PROMPT.md` metnini
   yapıştır. Önce `STRATEGIES_AND_FINDINGS.md`, `AUTOMATION_SPEC.md` ve paket
   `manifest.json` okunmalı. Bütün raporları tek seferde bağlama doldurmak yerine
   stratejiye göre ilgili ön-kayıt/rapor/kanıt açılmalı.
4. İlk hedef: 100 USDC **sanal** bakiye ile papertrade ve Hyperliquid testnet
   emir yaşam döngüsü. Şimdilik gerçek para yatırma veya ana cüzdan anahtarı
   paylaşma. Kâr kapısı ile operasyon güvenliği kapısı ayrı ayrı geçilecek.
5. Ana ağ, ayrıca açık onay gelmeden kapalı kalacak. Aşağıdaki 100 USDC canlı
   deneme bütçesi bir öneridir; onaylanmış yatırma talimatı değildir.

## Paketi yeniden üretmek

Trade1 kökünde (Windows'ta `python` yerine `.venv\Scripts\python.exe`):

```bash
python -B tools/build_hyperliquid_handoff.py --output handoff/private/hyperliquid-handoff.zip
```

Varsayılan paket kaynak kodu/testleri, bütün araştırma Markdown raporlarını,
protokolleri ve varsa 13 Ekim G1 tanısının JSON/cache kanıtlarını taşır.
Manifest her dosyanın SHA-256'sını, kaynak commit'ini ve dosyanın o commit'e
göre değiştirilmiş/taslak olup olmadığını gösterir. Yerel taslak, GitHub'da
yayımlanmış uygulama veya onaylanmış strateji diye sunulmaz. ZIP özel/Git dışı.
`.env`, anahtarlar, aboneler, outbox, gerçek pozisyonlar ve bot runtime state'i
dahil edilmez. Aynı hedef dosya varsa üzerine yazılmaz.

Ham ileri arşivler isteğe bağlıdır; önce tablette `--backup-now` çalıştır,
Syncthing aktarımını bitir ve PC'de `backup_verify.py` ile doğrula. Ardından:

```powershell
python -B tools/build_hyperliquid_handoff.py --output handoff/private/hyperliquid-with-archives.zip --archive-dir 'C:\Users\serha\Documents\Trade1-Backup'
```

Bu komut **tüm yedek manifesti güncel/doğru değilse paketi üretmez**. Yalnız
piyasa/likidasyon/gölge olay JSONL'lerini alır; `.subscribers.json`, outbox,
`signals.log` ve hesap/state dosyalarını taşımaz. Kaynaklar değişiyorsa veya
sır alanı/bozuk JSON varsa durur; kaynak arşivler onarılmaz/silinmez.

13 Ekim 2026 21:05 TRT kontrolü: 14 dosya doğrulandı, 16 hash uyuşmazlığı,
manifest yaşı 68,74 saat; dolayısıyla PC arşivi **şu anda doğrulanmış tam
güncel veri değildir**. Bu eski okuma, tabletin anlık durumu değildir.

## Büyük tarihsel veri nerede?

ZIP varsayılan olarak gigabaytlarca ham Binance ZIP/Parquet taşımıyor.
Yeni projede ayrı, özel `reference-data/binance/` alanı olarak erişim ver:

- `research/data/historical-universe-2026-10-05/`: 895 kontrat fiyat arşivi,
  `manifest.json`, `metrics_manifest.json`, `results.json`, `g1_results.json`.
- `research/data/extended-history-2026-10-03/`: 5m/15m/1h uzun geçmiş.
- `research/data/all-execution-2026-10-02/`, `g2-exit-sweep-2026-10-02/`,
  `g2-minute-review-2026-10-01/`: giriş/çıkış adayları ve fiyat cache'leri.
- `research/data/s2-review-2026-10-12/`, `g1-liquidation-review-2026-10-13/`:
  veri hazırlığı denetimleri; kapı geçmedi = sonuç doğrulandı demek değildir.
- PC günlük yedeği: aylık OI/funding/long-short/likidasyon/gölge kayıtları.

Tam tarihsel klasörleri yeniden indirmeyin; önce bu kaynaklara salt-okunur
erişim verip kendi kaynak manifestlerini doğrulayın. Eksik erişimi görünür
raporlayın; yalnız sonuç Markdown'ı ham veri doğrulaması yerine geçmez.
Veriyi public GitHub/Pages'e göndermeyin. Binance geçmişi HL geçmişi değildir.

## Eski Hyperliquid taslağı

PC'de bağımsız `hyperliquid-bot/HL_G1_PROTOCOL.md` ve `g1.py`/`g1_paper.py`
var; protokol bu oturumda okunarak doğrulandı. O taslak %2 TP/%2 SL, 100 USDC
sanal notional ve 4h ufuk kullanır; bu **100 USDC bakiye modeli değildir**.
10 açık sanal işlem ve negatif funding vekili vardır; yeni canlı risk tasarımı
bunları aynen devralmaz. Eski 56-test bilgisi önceki denetimdendir, güncel
test/deploy/kârlılık doğrulaması olarak kullanılmaz. İstenirse yalnız ayrı
okuma kaynağı olur; yeni çalışma onu değiştirmez.
