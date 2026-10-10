# G1 giriş karşılaştırması — raporlama eki, 2026-10-11

Bu ek 2026-10-03'te dondurulan beş giriş kuralını değiştirmez. Önceden
görülmüş 20 olaylık dakika örneği keşif/tekrar-oynatımdır; yeni test seti
değildir. Bu ekte yeni TP/SL veya teyit eşiği seçilmez.

## Sabit deney

- Tüm aktif USD-M perpetual G1 evreni ve saatlik sinyal koşulları korunur.
- Başlangıç: taze ask sonrası doğrulanmış Telegram tesliminin ardından ilk
  tam 1dk mum açılışı. Bu fiyat gerçek dolum veya bildirilen ask değildir.
- `immediate`: başlangıç açılışı; `wait_5m` / `wait_15m`: 5/15 tam dakika sonra
  açılış. `confirm_5m` / `confirm_15m`: ilgili tamamlanmış pencerenin son
  kapanışı ilk açılıştan yüksekse sonraki dakika açılışı; değilse `no_entry`.
- Hepsinde TP %3, SL %2; teslimden itibaren ortak 4 saat bitişi. Son kısmi
  dakika hariç. Stop ve hedef aynı mumdaysa stop önce; açılış stopun altındaysa
  açılış fiyatı. Ücret + kayma stres varsayımları toplam 20 ve 40bp, gerçek
  ücret iddiası değildir. Funding **not_modeled**, sıfır değil.

## Rapor paydaları ve nedensellik

1. Forward rapor yalnız doğru v3 config, 1m ölçüm, LONG, USD-M, geniş evren,
   4h ufuk ve teslim kanıtını kabul eder. Aynı ID çatışması tamamen dışlanır.
   Eski config, proxy replay, yanlış piyasa ve bozuk kayıtlar ayrı sayılır.
2. Ortak ufuk bitmeyenler pending; süresi geçmiş ama fiyat yolu tamamlanmamış
   kayıtlar overdue/unavailable. Pending bir plan TP olsa bile olgun sonuca
   katılmaz. Eksik kayıt kayıp veya sıfır getiri sayılmaz.
3. İşleme girilenlerde TP-alt/üst (aynı mum belirsizliği), ortalama/medyan,
   q10/q90 net getiri verilir. Fırsat başına getiride yalnız ölçülebilen
   no-entry = 0; unavailable paydadan çıkarılır ve sayısı gösterilir.
   Bu ortalamalar portföy getirisi veya sermaye eğrisi değildir.
4. Her alternatif immediate ile **aynı ölçülebilen olaylarda** eşlenir.
   Teyitsiz kalanlarda ayrıca aynı gecikmedeki koşulsuz girişle karşılaştırma:
   kaçırılan net kazanç / atlanan net kayıp / bilinmeyen. Böylece 7 işlemde
   yüksek isabet, atlanan 12 fırsat gizlenerek sunulmaz.
5. Bekleme sırasında ilk açılışa göre TP3 dokunması, düşüş/yükseliş ve giriş
   fiyatı farkı ölçülür. Bu dokunma, stop-first kazanç değildir.
6. Plan MAE/MFE yalnız girişten çıkışa kadar, **çıkış mumunun tüm aralığı dahil**
   kaydedilir. Mum içi sıra bilinmediği için gerçek dolum öncesi/sonrası hareket
   ayrıştırılamaz. Bunlar konservatif mum-aralığı ölçüleridir. Telemetri geç
   başladıysa complete_from_entry=false; eski eksik MAE/MFE sıfır doldurulmaz.
7. Rejim yalnız sinyal anında kaydedilmiş, veri kapanışı teslimden önce ve
   en fazla 72 saat eski etiketle raporlanır. Eksik/future/stale = UNKNOWN.
   Coin, UTC gün ve hafta yoğunlaşması; her rejimde örnek sayısı gösterilir.
8. Eşlenmiş fırsat getiri farkı için UTC hafta-blok bootstrap, sabit seed ve
   2000 tekrar, %95 aralık. 4 haftadan azsa aralık verilmez. Bu keşifsel
   aralık çoklu karşılaştırma düzeltilmiş kanıt veya kâr olasılığı değildir.

## Karar kapısı

En az 90 günlük **olay zaman aralığı**, 30 olgun olay ve 28 ayrı UTC olay günü
yalnız örnek hazırlık kapısıdır. Eksiksiz beşli kapsam ayrıca gösterilir;
bu kapının açılması canlı onay değildir. Deney sonuna bakarak en iyi pencereyi
seçip aynı veride doğrulanmış saymak yasaktır; aday için sonraki bağımsız,
dondurulmuş ileri doğrulama gerekir. Replay hiçbir koşulda bu kapıyı açmaz.

## Uygulama ve çalışma sınırı

`g1-entry-path-v1` yalnız ek ölçüm telemetrisidir. Sinyal, cooldown, universe,
Telegram teslimi, ana tarama sıklığı ve beş planın karar/çıkış formülleri
değişmez. Emir, yeni bildirim filtresi veya ek ağ isteği yoktur.
Rapor salt okunur; `.env` okumaz, bot import etmez. Kaynak dosya ve protokol
hash'lerini verir. Yerel state/ham snapshot kamuya yayımlanmamalıdır.

```bash
python research/review_g1_entry_shadow.py --format text
python research/review_g1_entry_shadow.py --format json
# Yalnız daha önce görülmüş, hash doğrulamalı dakika önbelleği:
python research/review_g1_entry_shadow.py --replay-dir research/data/g1-live-audit-2026-10-03 --format text
```

State saklama süresi en az 90 günü kapsamalı (varsayılan 365). Tablet
güncellenip yeniden başlatılmadan forward sayısı büyümez. Günlük PC yedeği
state'i taşıyabilir; yedeğin güncel olması çalışan kodun yeni olduğunu kanıtlamaz.
