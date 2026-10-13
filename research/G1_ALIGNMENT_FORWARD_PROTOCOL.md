# G1 zaman hizalaması ve giriş teyidi — ayrı ileri protokol

Sürüm: `g1-alignment-forward-v1`. Araştırma-only; Telegram sinyali ve emir yok.
13 Ekim 2026 tanısı adayın nedenini belirledi; o tanının olayları bu kohorta
eklenmez. Bu protokol, sonuçlar görülmüş geçmişe yeni bir OOS etiketi koymaz.

## Önceden sabitlenen karşılaştırma

- Canlı `evaluate_g1_snapshot`, G1 sabitleri, evren ve cooldown değişmez.
- Ayrı worker aktif USD-M USDT perpetual listesini ve günlük ticker sırasını
  toplar; ilk-10 listesini ilk başarılı yanıtla o saat için kilitler. Sonradan
  kazanan coinlerle liste yenilenmez. Canlı bildirim anının aynısı değildir;
  iki deney kolunun aynı gözlem anındaki kontrolüdür.
- Eski kol: saat H'de kapanan fiyat/hacim + OI H−2→H−1, LS H−1.
- Hizalı kol: aynı fiyat/hacim + OI H−1→H, LS H.
- İki kolun ortak eşikleri: kapanmış 24h getiri ≥%5, rank≤10, saatlik quote
  hacmi / önceki 24 saat medyanı ≥2, OI artışı ≥%2, LS<1.
- Tam 25 ardışık saatlik mum gerekir. OI ve LS damgaları kesin eşleşmelidir;
  eksik H yerine H−1 veya gelecek H+1 kullanılmaz. Hacim/fiyat sonlu ve pozitif
  olmalı; tekrarlı metrik ve eksik mum UNKNOWN/veri hatasıdır.
- Her iki kol da bilinmedikçe aday kilitlenmez. İlk gözlem H+60s, en geç
  H+600s. Eksik kaynak yalnız bu pencerede tekrar denenir. Sonrasında UNKNOWN;
  sonraki saatten gelen tarihsel değerle eski sinyal yaratılmaz.
- Exchange katalog, ranking ve her kaynak yanıtının gerçek alınma zamanı
  kaydedilir. H örneğinin geçmişteki teorik yayın saati varsayılmaz.
- Aktivasyondan önceki saat geri doldurulmaz; aktivasyon saat ortasındaysa
  sonraki tam saat beklenir. Her kol bağımsız false→true geçiş ve coin başına
  24h cooldown taşır. UNKNOWN false sinyal veya başarısız işlem değildir.

## Giriş–çıkış vekilleri

Her yeni araştırma olayında beş sabit plan: ilk tam 1dk açılışı, 5dk bekleme,
15dk bekleme, 5dk ve 15dk teyit. Teyit, bekleme penceresinin son kapanışının
ilk açılıştan büyük olmasıdır; kararın ardından gelen mum açılışı kullanılır.
Koşul yoksa `no_entry`; eksik pencere `unavailable`. Bunlar gerçek dolum veya
Telegram tesliminden giriş değildir: referans, doğrulanmış gözlem zamanıdır.

TP %3, SL %2, ortak gözlem +4h son saati. İlk/son kısmi dakika kullanılmaz.
Aynı 1dk mumda TP/SL belirsizse stop önce; stop altı gap kötü açılıştan.
20 ve 40 bp ücret/kayma varsayımı; funding `not_modeled`. Gerçek portföy
sermayesi, kaldıraç, miktar ve dolar PnL üretilmez. Olay ufku bitmeden erken
sonuçlanan planlar olgun örneklem özetine seçilmez.

Ölçüm: fırsat/işlem başına net fiyat getirisi dağılımı, TP-before-SL alt/üst
sınırı, MAE/MFE (çıkış mumunun tam aralığı), bekleme süresi ve fiyat farkı,
beklerken kaçırılan TP, no-entry ile kaçırılan kazanç/atlanan kayıp, gün/hafta
yoğunlaşması ve mevcut günlük rejim etiketi. Rejim UNKNOWN ise tahmin edilmez.
Fırsat başına ortalama bir portföy simülasyonu değildir.

## Dürüst kabul sınırı

Her kol için en az 90 gün, 30 beş-planı tam olay ve 28 ayrı olay günü yalnız
örneklem hazırlık kapısıdır; otomatik canlı kabul değildir. Eksik kapsam,
bağımsız hafta sayısı, maliyet duyarlılığı, negatif kuyruklar ve no-entry
seçim etkisi incelenmeden yeni güven oranı veya canlı filtre yayımlanmaz.
İlk incelemeden sonra yeni parametre seçilirse yeni sürüm ve ayrı dokunulmamış
ileri dönem gerekir. Çalışma devam ederken bu eşiklere göre optimizasyon yok.

## Sinyal uyarıları ile gerçek pozisyonlar ayrı

`signal_watch` koşul kaybı kontrolü, canlı G1'in **özgün gecikmeli** koşullarını
yeniden denetler; hizalı araştırma kolunu canlıya taşımış değildir. Yeni saat
sonrası kapanmış verilere bakar; veri yoksa iptal bildirimi üretmez. Bu,
G1 olayının şartları kayboldu demektir, istatistiksel olarak doğrulanmış bir
çıkış kuralı değildir. Geçici koşulun sona ermesi fiyatın mutlaka düşeceği
anlamına gelmez. Kaldıraçlı pozisyon kurtarma modeli değildir.

Referans yapı uyarısı iki kapanmış 15dk mum gerektirir ve hızlı düşüşte geç
kalabilir. Süre bitişi gerçek pozisyon kapanışı değildir. Bot borsa bakiyesini,
cross teminatını, gerçek dolumu ve TP/SL emirlerini bilmiyor. Gerçek pozisyon
takibi ancak kullanıcı borsayı ve işlem bilgilerini açıkça tanımladığında
ayrı, özel ve doğrulanmış entegrasyonla kurulmalıdır; emir yetkisi verilmedi.

## Dosyalar / tekrar

- Özel `.g1_alignment_state.json`: aktivasyon, kilitli saatler, iki ayrı kol,
  değişmez protokol hash'i, fiyat yolu işleme göstergeleri.
- `g1_alignment_observations_YYYY-MM.jsonl` ve `g1_alignment_bars_YYYY-MM.jsonl`:
  Git dışı araştırma kanıtları; günlük yedek kapsamındadır. State kilitlenen
  gözlem için yetkilidir; journal IO hatası giriş saatini yeniden seçtirmez.
- Rapor: `python research/review_g1_alignment.py` — ağ/Telegram/emir yok.
- `G1_ALIGNMENT_SHADOW_ENABLED=true`: sürekli tablet liderinde toplama.
  Bilinen geçici bulut varsayılanı false; `--once` yeni worker başlatmaz.
  Eski `.price_target_state.json`, skor kartları ve QC olayları değiştirilmez.
