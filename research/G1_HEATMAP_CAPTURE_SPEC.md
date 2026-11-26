# G1 modellenmiş likidasyon haritası — veri toplama taslağı

Tarih: 13 Ekim 2026. Durum: **erişim/lisans ve veri sözleşmesi bekliyor**.
Bu belge çalışan entegrasyon veya dondurulmuş strateji ön kaydı değildir.
Collector kurulmadı; ücretli istek, abonelik, emir ve bildirim başlatılmadı.
Mevcut forceOrder arşivi ayrı araştırma olarak korunur.

## Hangi hipotez?

G1 koşulu oluştuğunda fiyatın üzerindeki modellenmiş likidasyon yoğunluğu,
aynı G1 olaylarının hedefe stoptan önce ulaşmasını veya ters hareketini
açıklıyor mu? "Yoğunluk var, fiyat kesin oraya gider" varsayılmayacak.
Şiddetli hareketin yönü ve önce aleyhte hareket olasılığı da ölçülecek.

CoinGlass Model1, piyasa ve kaldıraç girdileriyle hesaplanmış seviyeler sunar;
borsadaki bütün hesapların kesin tasfiye emirleri değildir. İncelenen resmî
sayfada erişim Professional/Enterprise planlarında, kimlik doğrulama
`CG-API-KEY` başlığıyladır. `range=1y`, tek başına bir yıl önce gerçekten
görülebilen değişmez haritanın indirilebildiğini kanıtlamaz: belgelenen
sorguda geçmiş `as_of` seçimi görünmüyor. Bu son cümle dokümandan yapılan
çıkarımdır; sağlayıcıdan ayrıca doğrulanmalı.
[Resmî Model1 API](https://docs.coinglass.com/reference/liquidation-heatmap)

## Kodlamadan önce doğrulanacak veri sözleşmesi

1. Kullanıcı hesabında uygun erişim ve yerel arşivleme izni; bütçe ve kota.
   Anahtar yalnız ortam/secret yönetiminde tutulacak, sohbete yazılmayacak.
2. Binance USD-M perpetual sözleşme eşleşmesi ve kapsanan pariteler.
   `1000...` sözleşmeleri spot sembolle sessizce birleştirilmeyecek.
3. Harita hücresinin zaman ekseni, kesinleşme zamanı, yoğunluk birimi ve
   sonradan revizyon davranışı. Yoğunluğu belgesiz biçimde USD notional veya
   likide olacak gerçek pozisyon miktarı olarak etiketlemeyeceğiz.
4. `provider_asof` varsa anlamı; sunucu/gecikme ölçümü ve model sürümü.
   Geçmiş harita sağlanıyorsa özgün yayımlanma zamanı/revizyon izi gerekli.
5. Sorgu sıklığı, evren, maksimum snapshot yaşı, model, range ve mesafe
   bantları **sonuçlar açılmadan** ayrı protokolde sabitlenecek. Bugün bu
   değerleri seçip "optimum" diye sunmuyoruz.

## Önerilen özel kayıt yapısı

Her HTTP denemesi için kimlik bilgisi içermeyen allowlist metadata:

- `schema_version`, `capture_id`, `provider`, `model`, `exchange`, `contract`,
  `range`, istemci/parser sürümü;
- `requested_at_utc`, `received_at_utc`, varsa belgelenmiş `provider_asof_utc`,
  `latency_ms` ve saat sapması kontrolü;
- `http_status`, doğrulanmış enum hata nedeni, `payload_sha256`, byte sayısı,
  kapsama ve hücre geçerliliği;
- normalleştirilmiş fiyat/zaman/yoğunluk hücreleri ve bunların kaynağı.

Başlıklar, anahtarlar, env dökümleri ve denetlenmemiş hata gövdeleri
kaydedilmez. Geçerli veri yanıtı özel, değişmez, hash'li dosyada tutulur;
revizyon eski dosyanın üstüne yazılmaz. API hataları, 429 ve eksik pariteler
`unavailable` üretir, sıfır yoğunluk sayılmaz. Planlanan collector ayrı
worker olacak; taramayı bloke etmeyecek. Ham lisanslı veri Pages'e/git'e
yüklenmez; özel PC yedeğine dahil edilmesi ayrıca düzenlenir.

## Zamanlama ve sızıntı engeli

- Esas referans, mevcut proxy protokolündeki koşul mumunun kapanışıdır.
  Yalnız **bu andan önce alınmış** snapshot kullanılabilir. Sinyalden sonra
  API'yi çağırıp yanıtı kapanışta biliniyormuş gibi kullanmak yasaktır.
- Harita sürekli/önceden yakalanamıyorsa sonuç `UNKNOWN` kalır. Alternatif
  olarak "sinyal sonrası snapshot + gecikmiş giriş" tamamen ayrı deney
  olarak önceden tanımlanabilir; iki giriş kohortu karıştırılmaz.
- Sonradan indirilen haritanın geçmiş tarihli hücreleri, geçmişteki erişim
  anını kanıtlamaz. Geriye dönük doldurma ileri örneklem sayısını büyütmez.
- Snapshot son fiyatla yeniden ölçeklenip geçmişe taşınmaz; aynı anda
  bilinen referans fiyat ve tamamlanmış veriler kullanılır.
- Veri yokluğu, eskilik, parse/revizyon, kapsanmayan sözleşme ve kota
  sorunları ayrı sayılır. Sadece başarılı coinleri arşivlemek yasaktır.

## Test planının kabul koşulları

Önce sonuçlardan bağımsız veri QA; ardından ayrı protokolün tarih/hash ile
dondurulması. Geçerli snapshot bulunan **aynı olaylar** üzerinde BASE_G1 ile
harita destekli aday karşılaştırılır. Kapsam dışı/kaçırılan olaylar ayrıca
raporlanır; veri olmayan G1'e başarısız veya 0 getiri yazılmaz.

Ölçüler: hedef-stoptan-önce sırası, +%2/+%3 dokunma, 4h getiri, MFE/MAE,
hedefe kadar azami ters hareket, giriş gecikmesi, kaçırılan giriş ve hedefler,
sembol/gün/rejim yoğunlaşması. Varsayımsal referans giriş ile gerçek dolum
ayrılır; ücret/kayma ve funding bilinmiyorsa eksiklik açık yazılır.

Keşif ve sonraki bağımsız OOS ayrıdır. Mevcut proxy'nin 90 günlük takvimi
yeni heatmap verisinin geçmişi sayılmaz. Yeni örneklem, asgari bağımsız gün,
belirsizlik aralığı, çoklu deneme kontrolü ve kabul ölçütleri heatmap ön
kaydında sabitlenmeden getiriye bakılarak eşik aranmaz. Olumlu sonuç tek
başına canlı G1 filtresi veya otomatik emir yetkisi değildir.

## Tamamlanma sınırı

Şu an yalnız bu taslak hazır. Lisanslı point-in-time veri erişimi doğrulanana
kadar gerçek harita arşivi, backtest ve başarı iddiası **yok**. Bu nedenle
mevcut ücretsiz forceOrder proxy araştırması sürerken heatmap canlıya eklenmez.
