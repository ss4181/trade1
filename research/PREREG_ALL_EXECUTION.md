# Tüm stratejilerde giriş/çıkış araştırması — 2 Ekim 2026

Bu çalışma daha önce görülmüş olayları kullanır: yeni OOS değildir. G2 TP4/SL3
adayının önceki sonucu korunur. Sinyal üretimi, evren, cooldown, Telegram,
canlı kişisel hedefler ve emir yürütme değişmez. TP/SL gerçek emir değildir.

## Kapsam ve veri

1. Önceki doğrulanmış motor olayları: core30 S1, S1+S4, S2, S3; extended59 S1
   ve S1+S4 ayrı gruplar. Extended59, dinamik S5/S6 diye yeniden adlandırılmaz.
2. G1 sabit89 tarihsel vekili (yalnız eski TRAIN 2024–2025) ayrı; G2 fixed87 ayrı.
   G1'in henüz açılmamış 2026 fiyat sonuçları üzerinden yeni sinyal üretilmez.
3. Tablet yedeğindeki gerçek S5/S6/G1 olayları ayrı kohort: teslim kanıtlı ve
   yalnız kayıt zamanı bilinenler de ayrılır. Loglar değiştirilmez, alıcı/anahtar
   yayımlanmaz. S5/S6'nın birkaç olayıyla güvenilir en iyi ayar seçilemez.
4. DL1, delist duyurusu ve çapraz borsa işlem fikridir; doğrulanmış yön/kontrat/
   dolum verisi olmadan TP/SL optimizasyonuna alınmaz. Eksikliği raporlanır.
5. Resmi Binance günlük 5dk spot/USD-M mumları, SHA-256 kontrolü. Spot 2025+
   mikro-saniye normalize edilir. G2 için mevcut checksum-doğrulanmış 1dk
   serisinden aynı 5dk OHLC üretilir. Bu tur 1dk diye etiketlenmez.

## Giriş ve çıkış deneyi (sonuç öncesi sabit)

- Tarihsel saatlik olay: kapanıştan 5dk sonra açılış ilk uygulanabilir vekil.
  Telegram'ın tarihsel gerçek teslimi bilinmez. G2 önceki planlanan +60dk
  açılışından başlar; önceden bildirim gelmiş varsayımıdır. Canlı kayıtlar: gerçek
  teslim zamanından, yoksa notified_at'ten kesin sonraki tam 5dk açılışı.
- Giriş seçenekleri: ilk uygulanabilir açılış; +15dk; +60dk; +15dk teyit.
  Teyit için yalnız önceki 3 kapanmış 5dk mum: son kapanış ilk açılıştan ve
  bir önceki kapanıştan yüksek; son düşük bir önceki düşükten düşük değil.
  Teyit yoksa işlem yok; bütün fırsatlar başına getiride sıfır sayılır, kayıp
  veya eksik veri sayılmaz. Tüm seçeneklerin son çıkış saati ilk referans+horizondur.
- Hedef grid: %2,3,4,6; stop grid: %1,2,3. Her giriş için üç çıkış tipi:
  sabit tam TP; TP seviyesinde aktifleştirilen takip eden stop; TP'de yarısı
  kapanıp kalan yarısında takip eden stop. Toplam 4×4×3×3=144 plan/kohort.
- Takip stopu: aktivasyondan sonra en yüksek kapanmış mum high'ının SL%
  altı; en az giriş fiyatı. Yeni stop **yalnız sonraki mumda** geçerlidir;
  aynı mumun high'ını önceki low'a uygulama yok. Aktivasyon anında eski stop
  kontrol edilir. Kısmi satış ve stop aynı mumda ise stop önce. Açılış gap'i
  gerçek açılıştan zarar, hedef gap'i yalnız hedef fiyatından kazanç sayılır.
- Ufuklar korunur: S1/S1+S4/S5/S6/G2 24s, S2 72s, G1/S3 4s. Stop/TP sonrası
  fiyat hareketleri kararına geleceği bilerek müdahale edilmez. MFE tam pencerede
  ayrıca izlenir; gerçekleşmiş kazanç değildir.
- %0,20 ve %0,40 toplam fee/spread/slippage varsayımı. Kısmi satış maliyeti
  miktar ağırlıklı; tam toplam miktar bir kez kapanır. Gerçek ALO/limit dolumu,
  hesap sermayesi, qty, dolar PnL, kaldıraç ve tasfiye modellenmez.
- Perp için eski funding arşivleri birleştirilir. Mark-price yoksa fonlama
  oranları giriş notional'ı üzerinde yaklaşık modellenir. Giriş/çıkış 5dk
  mumundaki belirsiz funding kredi sayılmaz, ödeme sayılır. Kısmi satıştan
  sonra yalnız kalan miktar taşır. Eksik funding sıfır uydurulmaz; böyle
  olaylar ayrı eksik sayılır, aday seçilmez. Spotta funding uygulanmaz.

## Seçim ve risk

Her kohort zaman aralığına göre %60 A / %20 B / %20 C. G2 önceki A/B/C'yi korur.
B veya C başlangıcına sarkan A/B sonuçları purge edilir. A ve B'de en az
30 ölçülebilir olay ve 14 ayrı gün yoksa aday seçilmez. C'de 30 olay/14 gün
yoksa kontrol yetersizdir. Bunlar başarı garantisi veren istatistiksel eşikler değil.

144 ayardan seçim yalnız A/B: %0,40 maliyetle her fırsat başına `net/ilk SL`
ortalamasının A ve B'deki küçüğü. Aynı giriş/çıkış tipindeki yakın hedef/stop
komşularının skor medyanı birinci, kendi skoru ikinci, daha kısa giriş gecikmesi
ve daha basit çıkış tipi eşitlik kırıcı. Kazanan C hesaplanmadan diske yazılır;
C başarısızsa başka aday seçilmez. Yalnız net pozitif oranla seçim yapılmaz.

Rapor: veri/red sayıları, işlem açma oranı, net20/net40, stop başına getiri,
medyan, %10 kuyruk, en kötü sonuç, süre, sonuç türleri, TP öncesi/sonrası hareket.
Sabit TP/SL3/2 ilk uygulanabilir giriş ortak karşılaştırma senaryosudur; eski
botun tüm stratejileri zaten bu emirle işlem yapıyormuş gibi sunulmaz.
Seçilen strateji için giriş E cinsinden TP/SL ve koşullu çıkış formülleri verilir.

Gelecek performans iddiası/otomatik canlı terfi yok. Aynı gün çok coin sinyali
bağımsız örnek değildir. 144 ayar × çok strateji ve zaten görülmüş veri güçlü
seçim yanlılığı taşır. Sonraki ileri dönem doğrulaması ve gerçek borsa maliyetleri
olmadan sinyal güven puanları yükseltilmez.
