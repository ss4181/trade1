# G1 5dk / 15dk giriş karşılaştırması — 11 Ekim 2026

Sonuç: araştırma ölçümü ve karşılaştırmalı rapor hazır. Canlı giriş filtresi
değiştirilmedi. Daha iyi giriş kuralı **henüz ileri veride doğrulanmadı**.

## Canlı durum kontrolü

Halka açık `trade1-data/data.json` yayınının zamanı **11 Ekim 2026 01:40 TRT**.
Kaynak `Termux / tablet`; G1 v3 sürüm alanları bu yayında yok. Panoda 13 eski
v1, 123 v2 G1 kaydı var. Bu, son yayın gözlemidir; tabletin daha sonra yeniden
başlatılmadığının kesin kanıtı değildir.

Bilgisayardaki yedek state'te 136 G1, **0 entry_shadow**, **0 uygun v3 ileri
olay** var. En son G1 başlangıcı 10 Ekim 2026 18:00:12 UTC. Dosya mtime'ı
yerine olay zamanı kullanıldı. Eski kayıtlar yeni ileri kohorta çevrilmedi.
İleri deney için tabletin güncel kodla çalışması ve yeni teslimler gereklidir.

## Eski dakika verisiyle kontrol — yeni OOS değildir

Önceden görülmüş, değiştirilmeden korunan 3 Ekim snapshot'ının son 20 teslimi:
26 Eylül–3 Ekim 2026; 19 olgun + 1 pending; 8 UTC olay günü, 2 takvim haftası,
7,33 günlük olay aralığı. Bu **bugünün son 20 sinyali değildir**.
20/20 yerel dakika önbelleği SHA-256 ve istek parametreleriyle doğrulandı;
yeni piyasa verisi indirilmedi, kaynak dosyalar yeniden yazılmadı.

Başlangıç ilk tam dakika açılışıdır; gerçek ask dolumu değil fiyat proxy'si.
TP %3 / SL %2, ortak 4h ufuk; aynı mumda stop önce. Net40 toplam %0,40
maliyet varsayımıdır; funding modellenmemiştir. Net sütunları olay başına
aritmetik ortalama olup portföy/sermaye getirisi değildir.

| Giriş | Girilen | TP / SL | Giriş yok | TP önce oranı | Net20 / fırsat | Net40 / fırsat |
|---|---:|---:|---:|---:|---:|---:|
| İlk tam dakika | 19 | 9 / 10 | 0 | %47,37 | +%0,168 | −%0,032 |
| 5dk bekle | 19 | 11 / 8 | 0 | %57,89 | +%0,695 | +%0,495 |
| 15dk bekle | 19 | 12 / 7 | 0 | %63,16 | +%0,958 | +%0,758 |
| 5dk kapanış teyidi | 7 | 5 / 2 | 12 | %71,43 | +%0,505 | +%0,432 |
| 15dk kapanış teyidi | 7 | 5 / 2 | 12 | %71,43 | +%0,505 | +%0,432 |

Fırsat paydası her satırda aynı 19 olaydır. Teyitte giriş yapılmayan 12 olay
sıfır fırsat getirisi, **kazanan işlem değil**. Girilen işlem başına net40
ortalaması iki teyit kolunda +%1,171; bunu 19 fırsatın ortalamasıyla karıştırma.
Bu örnekte aynı mum TP/SL belirsizliği yok; alt/üst oranlar eşit.

## Beklemenin ve teyidin bedeli

- 5dk bekleme, immediate'a göre ortalama +0,526 yüzde puan fark; medyan giriş
  fiyatı %0,221 daha düşük. İlk 5 dakikada 19 olayın 1'i ilk açılıştan +%3'e
  dokunmuş. Dokunma, stop öncesi kazanılmış işlem anlamına gelmez.
- 15dk bekleme: +0,789 puan fark; medyan giriş fiyatı %0,352 daha düşük.
  İlk 15 dakikada 4/19 olay +%3'e dokunmuş. Beklemek bazı erken hareketleri
  kaçırıyor; bu örnekte net avantaj göstermesi geleceği garanti etmez.
- 5dk teyidi: girilmeyen 12 olayda, aynı zamandaki koşulsuz 5dk girişe göre
  **6 net kazanç kaçırıldı / 6 net kayıp atlandı**.
- 15dk teyidi: **7 net kazanç kaçırıldı / 5 net kayıp atlandı**.
- Teyitli girişlerin medyan fiyatı immediate'a göre sırasıyla %0,578 ve
  %1,380 daha yüksek. “Teyit almak” her zaman ucuz giriş demek değil.

## Giriş sonrası fiyat riski

| Plan | Medyan MAE | Medyan MFE | Ölçülen N |
|---|---:|---:|---:|
| İlk tam dakika | −%2,023 | +%2,612 | 19 |
| 5dk bekle | −%1,485 | +%3,073 | 19 |
| 15dk bekle | −%1,007 | +%3,198 | 19 |
| 5dk teyit | −%1,314 | +%3,163 | 7 |
| 15dk teyit | −%0,843 | +%3,198 | 7 |

MAE düşüşü, MFE yükselişi gösterir. **Çıkış mumunun tamamı dahil** olduğu için
stop sonrası dip veya TP sonrası tepe aynı mumda bu değerlere girebilir.
Bu tablo gerçek pozisyonun yaşadığı kesin zarar/kâr değildir; stop mesafesi
%2 iken MAE'nin %2'yi aşabilmesi bundan ve açılış boşluklarından kaynaklanır.

Yalnız 2 takvim haftası olduğundan hafta-blok güven aralığı üretilmedi.
Eski snapshot rejim etiketlerinin veri-kapanış zamanı saklanmadığından bu
örnekte rejim **UNKNOWN**; sonradan bugünkü boğa/ayı etiketi yapıştırılmadı.

## Uygulanan ekler

- Beş girişin birlikte raporu: pending / eksik / no-entry ayrımı, maliyet
  sonrası ortalama, medyan, q10/q90, eşlenmiş farklar ve kaçırılan fırsatlar.
- Yeni ileri olaylarda giriş–çıkış MAE/MFE telemetrisi; eski/yarım ölçüm
  otomatik tamamlanmış sayılmaz. Ortak timeout bitiş zamanı açık kaydedilir.
- Sinyal anındaki rejim ve veri kapanış zamanı saklanır; rejim filtre değildir.
- Yinelenen aynı kayıt tek sayılır, çatışan ID dışlanır. Replay ileri örnek
  kapısını açamaz. Sıra, config, piyasa, evren ve teslim kanıtı doğrulanır.
- JSON ve okunabilir Türkçe CLI çıktısı; rapor kaynak hash'leri. Ağ, emir,
  Telegram gönderimi veya kaynak veriye yazma yoktur.

Kod: `g1_entry.py`, `signal_bot.py`, `research/g1_entry_comparison.py`,
`research/g1_entry_replay.py`, `research/review_g1_entry_shadow.py`.
Protokol: `research/G1_ENTRY_COMPARISON_PROTOCOL.md`.
Testler: `tests/test_g1_entry.py`, `tests/test_g1_entry_comparison.py`.

Doğrulama: çalışma ağacındaki 44 Python test dosyası geçti; seçici yayın
paketinin temiz kopyasında 37 Python test dosyası ve pano JavaScript
kontrolleri geçti. 16 yeni saf karşılaştırma testi eklendi. İlk sandbox
koşusunda Windows geçici dosya izin hatası vardı; aynı izole paket normal
Temp dizininde yeniden geçti. Canlı sır/state okunmadı, test ağı kapalıydı.
AST karşılaştırması G1 koşulları, eşikler, evren, cooldown ve beş planın
karar/çıkış mantığının değişmediğini doğruladı; yalnız telemetri eklendi.

## Sonraki adım

`G1_RELEASE.md` içindeki tablet güncelleme/tek-süreç yeniden başlatma adımlarını
uygula. Rapor komutu:

```bash
cd ~/trade1
python research/review_g1_entry_shadow.py --format text
```

Güncel sürümde `status.g1_entry_path_version=g1-entry-path-v1` görünmeli.
Yeni sinyaller geldiğinde karşılaştırma botun mevcut taramasında otomatik
toplanır; ayrı ikinci bot veya yeni zamanlayıcı açılmaz. En az 90 gün, 30 tam
olgun olay ve 28 ayrı tam olay günü dolmadan tercih yapılmaz; bunlar dolsa
bile kazanç güvencesi veya otomatik canlı terfi değildir. Rapor dağılımları ve
rejimler incelenip aday daha sonraki bağımsız ileri dönemde doğrulanmalıdır.

Tekrar üretim:

```bash
python research/review_g1_entry_shadow.py --replay-dir research/data/g1-live-audit-2026-10-03 --format text
```

Eski snapshot SHA-256:
`86c0024553aeded7f591f2fca3babe59ac6009f8c39e48b79006713e56035df8`

Kontrol edilen özel yedek state SHA-256 (dosya yayımlanmadı):
`e27d2126481edb91e2328f67ed453555785d2a06e544e6c93228cf21b467f434`
