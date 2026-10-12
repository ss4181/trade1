# Tüm stratejiler: giriş, TP/SL ve kârı taşıma araştırması

2 Ekim 2026 · **Araştırma sonucu; canlı emir veya doğrulanmış yatırım planı değildir.**

**3 Ekim kapsam düzeltmesi — güncel G1:** Bu rapordaki G1 reddi eski sabit
89-coin vekili ve stoplu çıkış testi içindir; güncel tüm-coin bildirimlerinin
+%2/+%3 dokunma başarısını ölçmez. İncelenen tablet yedeği 14 Eylül'de bitiyordu;
güncel pano farklı `trade1-data` dalındaymış. Güncel kayıtlarda art arda beş
hedef başarısı bağımsız 1dk fiyatlarla doğrulandı. Giriş fiyatı farkı ve ilk
5dk ölçüm kör noktası ayrıca bulundu. Ayrıntılar:
[G1 canlı giriş denetimi](G1_LIVE_ENTRY_AUDIT_2026-10-03.md).
Funding eksiği, funding dahil PnL'yi engeller; brüt hedef dokunmasını incelemeyi
engellemez. Bu ayrımı önceki özette yeterince açık yapmadık.

## Sonuç

Tek bir TP/SL ayarı bütün stratejiler için uygun çıkmadı. S1'in genişletilmiş
59-coin grubunda daha uzak sabit hedef; S3'te kapanmış mum teyidi ve takip stopu;
G2'de kısmi kâr alma araştırmaya değer adaylar verdi. **Hiçbiri henüz yeni,
görülmemiş ileri dönem verisinde doğrulanmış değil.** S2 ve tarihsel G1 için
giriş/çıkışı değiştirmek güvenilir bir kazanç avantajı üretmedi.

Canlı stratejiler, eşikler, evrenler, cooldown, Telegram, kişisel hedefler ve
emir yürütme değiştirilmedi. Önceki G2 bildirim-zamanlama çalışması ayrı tutuldu.
GitHub'a push/deploy yapılmadı.

## Ne test edildi?

- **2.870 olay**, 2 Temmuz 2024–14 Eylül 2026. 2.814 önceki motor olayı ve
  tablet yedeğinden 49 G1, 5 S5, 2 S6 kaydı. Yedeğin dosya tarihi değil,
  içindeki en son bildirim 14 Eylül esas alındı; bugüne kadar eksiksiz canlı kayıt yok.
- **4.685 sembol-piyasa-gün** doğrulandı: 4.225 resmi 5dk ZIP + mevcut 460
  checksum-doğrulanmış 1dk ZIP'ten 5dk toplulaştırma. Yeni 5dk ZIP'ler 51,3 MB.
  İndirmede eksik/hatalı dosya yok; OHLC ve zaman birimleri kontrol edildi.
- **2.817 olay ölçülebildi.** 10 eski G1 ve 43 canlı G1 olayında pencereyi
  kapsayan funding arşivi yoktu; sıfır funding uydurulmadı. Canlı G1'in kalan
  6 olayı, eski sabit evren testiyle birleştirilmedi.
- Yeterli A/B örneği olan **6 grupta 144'er plan**: 4 giriş × 4 hedef
  (%2/3/4/6) × 3 stop (%1/2/3) × 3 çıkış tipi. Diğer gruplara sahte optimum atanmadı.
- Girişler: ilk uygulanabilir 5dk açılışı, +15dk, +60dk, +15dk mum teyidi.
  Çıkışlar: tam sabit TP, takip stopu, hedefte %50 kapatıp kalanı takip stopuyla taşıma.
- Her olayın son çıkış saati sabit: S1/S1+S4/S5/S6/G2 24 saat, S2 72 saat,
  S3/G1 4 saat. Geç giriş yapan senaryoya fazladan gelecek süre verilmedi.
- Toplam maliyet varsayımları **%0,20 ve %0,40**. USD-M'de funding oranları
  giriş notional'ı üzerinde yaklaşık hesaplandı; spotta funding yok.

Başlangıç tasarımı: [ön-kayıt](PREREG_ALL_EXECUTION.md). Veriler daha önce görülmüş
olduğu için kronolojik C kontrolü **yeni OOS değildir**. Her grup %60/%20/%20
takvim aralığıyla ayrıldı; G2'nin eski A/B/C'si korundu. Sonuç penceresi sonraki
bölüme sarkan 25 olay A/B seçiminden çıkarıldı; ALL betimsel tablolarında tutuldu.

Seçim yalnız A/B'de, maliyet %0,40 iken fırsat başına `net/ilk stop` getirisinin
iki dönemdeki küçüğüne ve yakın parametrelerin medyanına göre yapıldı.
Seçilen kimlikler **C çıkışları hesaplanmadan** `frozen_selection.json` içine yazıldı.
Başarısız C sonucundan sonra ikinci adaya geçilmedi.

## Her strateji için karar

Aşağıdaki getiriler C döneminde **sinyal fırsatı başına** ortalamadır; teyit
gelmediği için açılmayanlar sıfır getiridir. Bunlar hesap/portföy getirisi değildir.
Karşılaştırma: ilk uygulanabilir giriş + sabit TP%3/SL%2; bütün botun mevcut
emirlerinin zaten böyle olduğu iddia edilmiyor.

| Strateji / evren | A/B'nin seçtiği araştırma planı | C fırsat / giriş | Net %0,20 maliyet | Net %0,40 maliyet | Karar |
|---|---|---:|---:|---:|---|
| S1 / çekirdek 30 | 15dk teyit → TP%2 / SL%3 | 38 / 10 | +%0,130 | +%0,078 | A/B stres sonucu negatif; yalnız 10 giriş. Güvenilir optimum yok. |
| S1 / genişletilmiş 59 | İlk uygulanabilir giriş → TP%6 / SL%3 | 59 / 59 | +%0,619 | +%0,419 | İleri teste aday; başka evrene aktarılmaz. |
| S1+S4 / çekirdek 30 | Aday seçilmedi | — | — | — | B'de 62 olay ama yalnız 10 ayrı gün; C 27 olay. |
| S1+S4 / genişletilmiş 59 | Aday seçilmedi | — | — | — | B'de 82 olay ama yalnız 11 ayrı gün; C 24 olay. |
| S2 / çekirdek 30 | İlk giriş → TP%3 / SL%3 | 104 / 104 | −%0,611 | −%0,811 | Reddedildi: 144 planın hiçbiri A ve B'de birlikte pozitif stres getirisi vermedi. |
| S3 / çekirdek 30 | 15dk teyit → +%3'te takip stopu, mesafe %3 | 201 / 68 | +%0,161 | +%0,094 | Kırılgan ileri-test adayı; 133 fırsatta işlem yok. |
| G1 / sabit 89 tarihsel vekil | 15dk teyit → TP%2 / SL%3 | 74 / 21 | −%0,090 | −%0,147 | Reddedildi: A/B de negatif; canlı tüm-coin evreniyle aynı test değil. |
| G1 / gerçek bildirimler | Aday seçilmedi | — | — | — | Funding dahil yalnız 1 teslim kanıtlı + 5 teslimi belirsiz olay ölçülebildi. |
| G2 / sabit 87 | Planlanan giriş → +%6'da yarısını kapat, kalanına %3 takip stopu | 71 / 71 | +%0,430 | +%0,230 | Kırılgan ileri-test adayı; yalnız 22 olay günü. |
| S5 / dinamik gözlem | Aday seçilmedi | — | — | — | 5 olay, yalnız 1'inde teslim kanıtı. |
| S6 / dinamik gözlem | Aday seçilmedi | — | — | — | 2 olay, teslim kanıtı yok. |
| DL1 | Hesaplanmadı | — | — | — | Delist sonrası dış borsa short fikri; doğru kontrat ve uygulanabilir giriş/dolum kanıtı yok. |

S5 mevcut projede dinamik evren S1+S4, S6 dinamik evren S1'dir. Onlara sabit
59-coin grubunun sonuçları kopyalanmadı. S4 ayrıca al-sat yapan bağımsız strateji değil.
S1+S4'ün yüzlerce kaydı olması bağımsız yüzlerce piyasa dönemi anlamına gelmiyor.

S1+S4'te yalnız karşılaştırma planı TP3/SL2 ölçüldü: C'de çekirdek grup net20
−%0,599 (27 olay), genişletilmiş grup +%0,717 (24 olay). Bu küçük ve kümelenmiş
sonuçlar yeni ayar seçmek için kullanılmadı.

## Olumlu adayların gerçek riskleri

| C dönemi | S1 / 59 coin | S3 / çekirdek 30 | G2 |
|---|---:|---:|---:|
| Eski karşılaştırma planı net40 / fırsat | −%0,016 | −%0,200 | −%0,257 |
| Aday net40 / fırsat | +%0,419 | +%0,094 | +%0,230 |
| Aday net40 / açılan giriş | +%0,419 | +%0,276 | +%0,230 |
| Net20 pozitif kapanış oranı | %47,5 | %42,6 | %43,7 |
| Net20 medyan kapanış | −%0,134 | −%0,403 | −%2,226 |
| Net20 en kötü kapanış | −%3,850 | −%3,200 | −%3,220 |
| Medyan açık kalma süresi | 19s 50dk | 3s 45dk | 12s 40dk |
| En iyi 3 giriş çıkarılırsa net40 / fırsat | +%0,142 | −%0,033 | −%0,200 |

**Ortalama kazancı artırmak, daha sık kazanmakla aynı şey değil.** Üç adayda da
C medyanı negatif. S3 ve G2'nin ortalaması az sayıda büyük kazanana duyarlı.
Bunlar birkaç dakikada garantili kâr veren scalping planları değil.

Seçimden sonra yapılan betimsel 7-takvim-gün blok bootstrap (2.000 tekrar)
net40 ortalamasının aralığını S1/59 için **−%0,787…+%1,764**, S3 için
**−%0,195…+%0,412** verdi. Her ikisi sıfırı içeriyor; karşılaştırmaya göre
iyileşmenin aralığı da sıfırı içeriyor. G2'de yalnız 22 olay günü olduğundan
aralık yayımlanmadı. Bu aralıklar çoklu deneme/veri tekrar kullanımını düzeltmez;
gelecekte kâr etme olasılığı veya bildirim güven puanı değildir.

Önceki G2 TP4/SL3 adayı karşılaştırmada tutuldu: aynı 5dk/funding yaklaşımıyla
C net20 **+%0,239**, net40 **+%0,039**. Yeni kısmi çıkış bunu örnek içinde aştı,
ama daha uzun bekleme ve daha düşük pozitif kapanış oranı getirdi. Önceki 1dk
raporuyla küçük sayısal fark, burada 5dk belirsizlik ve mark yerine giriş-notional
funding yaklaşımı kullanılmasından kaynaklanıyor; önceki rapor silinmedi.

## Giriş ve fiyat seviyeleri nasıl hesaplanır?

`E`, **gerçekten girilen borsa ve kontrattaki giriş fiyatı**dır. Bildirimdeki eski
koşul kapanışı değildir. Binance ile Hyperliquid dolumunu eşit varsayma;
1000'lik kontrat ile tek coin fiyatını karıştırma. Aşağıdakiler araştırma formülleri;
borsaya emir gönderilmez ve tick-size yuvarlaması/dolum doğrulaması yapılmaz.

### S1 / genişletilmiş 59: sabit uzak hedef adayı

- Test girişi: saatlik koşul kapanışından **5 dakika sonraki açılış**.
- İlk stop: `E × 0,97`; tam kâr alma: `E × 1,06`.
- En geç ilk referanstan 24 saat sonra çıkış.
- E=100 varsayımsal örneğinde stop 97, hedef 106. Çekirdek S1/S5/S6'ya aktarılmaz.

### S3: teyit ve kazananı taşıma adayı

- `t0 = saatlik kapanış + 5dk`. t0'dan itibaren üç 5dk mumun **kapanmasını** bekle.
- Son kapanış ilk mum açılışından ve önceki kapanıştan yüksek olmalı;
  son mum düşüğü önceki mum düşüğünden düşük olmamalı. Yoksa giriş yok.
- Test girişi `t0+15dk` açılışıdır. Örneğin koşul 10:00'da kapanırsa giriş
  ancak 10:20'de; teyitte kullanılan mumlar 10:05–10:20 aralığıdır.
- İlk stop `E×0,97`. Fiyat `E×1,03`e ulaşınca tam pozisyon için takip stopu
  etkinleşir; burada sabit +%3 kâr satışı **yoktur**.
- Yeni stop `max(eski stop, E, en yüksek kapanmış mum high'ı×0,97)`;
  **yalnız sonraki 5dk mumunda** geçerli. En geç t0+4 saat çıkış.

### G2: kısmi kâr ve kalanını taşıma adayı

- Giriş mevcut planlanan saat: koşul kapanışı +60dk. +55dk hazırlık bildirimi,
  henüz gerçekleşmemiş koşulu önceden biliyormuş gibi girişe çevrilmedi.
- İlk stop `E×0,97`; `E×1,06`da %50 kapatılır.
- Kalan %50 için S3 ile aynı kapanmış-mum takip stopu kuralı uygulanır.
- En geç planlanan giriş +24 saat çıkış. +%6'ya ulaşılmazsa ilk stop/azami süre geçerli.

Takip stopları sürekli tick bazında borsa trailing emri değil, **5dk kapanışıyla
güncellenen** araştırma kurallarıdır. Aynı mumda yeni high'a bakıp daha önceki low'da
kusursuz satış yapılmış sayılmaz. Stop ve hedef belirsiz sıradaysa stop önce sayılır.
Stopun altında açılış varsa daha kötü açılış fiyatı kullanılır; bu yüzden %3 stop
en fazla %3 zarar garantisi değildir. Giriş fiyatına taşınmış stop da maliyetler
sonrası net başabaş garantilemez.

## Neden yükseleni kaçırıp düşeni tutuyormuş gibi görünüyor?

Bir sinyalin sonradan +%10'a gitmesi, önce −%5 düşmediği anlamına gelmez.
Stop sonrası yükseliş, stoplu işlemin kazancı sayılamaz. Ayrıca tepe fiyat ancak
sonradan bilinir. Tam pencere MFE/MAE hesaplandı fakat çıkış seçerken gelecekteki
tepe/dip kullanılmadı. Örneğin G2 C'de medyan tam-pencere MFE +%4,163,
MAE −%3,302; bu iki sayı tek başına uygulanabilir TP/SL vermez.

Çözüm bütün stopları genişletmek değil: girişte teyit, önceden tanımlı zarar
sınırı ve farklı çıkış biçimlerini **net beklenti ve kötü kuyrukla birlikte** ölçmek.
S2 bu testte bunu karşılamadı. G2/S3'te kalan pozisyonu taşımak da her olayda
daha iyi değil; küçük kazançlar geri verilebilir.

## Dosyalar, tekrar çalıştırma ve sonraki adım

- `prepare_all_execution.py`: olayları ayırır, resmi fiyatları indirir/doğrular;
  sırları/logların ilgisiz alanlarını çıktı şemasına taşımaz, logları değiştirmez.
- `all_execution_engine.py`: saf giriş/çıkış, kısmi satış, takip stopu, funding ve seçim.
- `eval_all_execution.py`: A/B seçimi, önce dondurma, sonra C; yalnız yerel araştırma çıktısı.
- `audit_all_execution.py`: seçim sonrası yoğunlaşma/blok bootstrap teşhisi; aday değiştirmez.
- `tests/test_all_execution.py`: 28 test; bütün izole proje paketleri ayrıca çalıştırıldı.
- `research/data/all-execution-2026-10-02/`: plan, normalleştirilmiş olaylar,
  indirme checksum'ları, eğitim tabloları, dondurulmuş adaylar, olay bazlı sonuçlar,
  red kayıtları, rapor ve duyarlılık analizi. Bu ham araştırma klasörü git-ignored;
  bilgisayardadır, otomatik tablette oluşmuş veya yayımlanmış sayılmaz.

Eldeki rapordan verilen bir fiyatın teorik seviyelerini görmek için:

```bash
python research/eval_all_execution.py --show-plan G2 --entry-price 100
python research/eval_all_execution.py --show-plan S3 --entry-price 100
python research/eval_all_execution.py --show-plan S1 --entry-price 100
```

100 yalnız hesap örneğidir. Çıktı `research_only=true` ve değerlendirme kararını
taşır; örneği yetersiz stratejide fiyat seviyesi uydurulmaz. S1 iki evreni ayrı döndürür.

**Sonraki doğru adım:** Bu üç adayı mevcut sinyalleri değiştirmeden yeni ileri
dönem verisinde, aynı maliyet/teyit/stop kurallarıyla gölge ölçmek. Eski C'ye
bakarak yeni hedef/stop seçme döngüsüne girmemek. Funding arşivini güncellemek,
asıl işlem borsasının spread/tick-size/dolum gecikmesini ölçmek ve bekleyen
emir/azami süre davranışını doğrulamak. Bu tur otomatik emir veya yeni canlı
gölge worker başlatılmadı; sınanmış en iyi giriş/çıkış garantisi verilmedi.

Finansal sınırlar: eşzamanlı sinyaller bağımsız değil; sermaye kısıtı, kaldıraç,
tasfiye, limit/ALO dolmama ve portföy maksimum düşüşü modellenmedi. Funding,
mark fiyatı yerine yaklaşık giriş notional'ıyla hesaplandı; 8 saat boşluk
kontrolü, daha kısa funding periyotlarının eksiksizliğini tek başına kanıtlamaz.
Sabit evren ve önceden sonuç verisi yeterli olan arşiv olayları ayrıca seçilim
yanlılığı taşır. Bu nedenlerle bir başarı/güven yüzdesi canlı bildirime eklenmedi.

## Kaynak / denetim izi

- [Binance resmi toplu veri arşivi: yollar, formatlar, checksum ve mikro-saniye değişimi](https://github.com/binance/binance-public-data)
- [Binance resmi funding geçmişi alanları](https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Get-Funding-Rate-History)
- [Bailey vd.: backtest overfitting](https://www.davidhbailey.com/dhbpapers/backtest-prob.pdf)
- Ana sonuç JSON SHA-256: `2d34740e052e0a39ee3b8fe2403ce8f55a6113afce0cc256625ae23e248fd412`.
- Veri ve kod hash'leri `plan.json`, `frozen_selection.json`, `report.json` ve
  `sensitivity.json` içindedir. API anahtarı/Telegram alıcısı yayımlanmaz.
