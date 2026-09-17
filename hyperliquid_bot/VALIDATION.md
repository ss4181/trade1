# Hyperliquid ilk doğrulama — 17 Eylül 2026

**Çalışan ayrı araştırma botu hazır; kazanç üstünlüğü henüz gösterilemedi.**
Bu sürüm araştırma adayları ve ileriye dönük fiyat takibi içindir.

## Gerçek veri kapsamı

- Hyperliquid'den 61 perpetual ve 17 USDC spot piyasa indirildi.
- Seçilen piyasalarda 293.849 kapanmış mum; BTC günlük rejim referansı ayrıca
  2.220 mum. İndirme hatası: 0.
- Perpetual ortak erişim penceresi yaklaşık 21 Şubat–17 Eylül 2026;
  spot serileri coin yaşına göre 1–884 günlük geçmiş sunuyor.
- Mevcut Coinalyze arşivinden 87 coin için 174 saatlik/günlük OI serisi,
  324.327 satır doğrulandı. Kaynak exchange kodu `A`, eski arşivde Binance.
- OI dosyaları yeniden indirilmedi; manifest/dosya hashleri doğrulandı.
  Bu veri ayrı borsa bağlamı olarak kullanılır; Hyperliquid OI'si değildir.

## Son üçte birlik test dönemi

| Araştırma kuralı | Aday | Ölçülebilen dolum senaryosu | Sonuç |
|---|---:|---:|---|
| HL-S, 24 saat | 7 | 2 | İkisi de SL; ortalama −%4,43, funding hariç |
| HL-S, 48 saat | Aynı 7 | Aynı 2 | Aynı stoplar; bağımsız iki ek işlem değil |
| HL-D, 14 gün | 0 | 0 | Başarı ölçülemedi |
| HL-D, 28 gün | 0 | 0 | Başarı ölçülemedi |

HL-S'de kalan 5 adayın 4'ü marketable ALO reddi senaryosu, 1'i dolmayan limit
oldu. Ölçülebilen iki coin NEAR ve INJ'dir. OI bağlamı 7 adayın 3'ünde mevcuttu;
OI artışı alt kümesindeki tek adayda ölçülebilen dolum yoktu.

Spot gelişim döneminde 8 adaydan yalnız bir dolum senaryosu ölçülebildi:
UETH/USDC, ücret/kayma sonrası yaklaşık +%19,75. **Bu, %100 başarı kanıtı
değildir: tek gelişim örneğidir, bağımsız test döneminde örnek yoktur.**
Geleceğin yüksek getirili meme coinini bulduğumuz anlamına da gelmez.

BTC'nin erişilebilir 4.999 saatlik kapanışının yalnız 213'ü seçilen boğa rejimi
koşulunu sağladı. Büyük ham veri miktarı, aynı strateji için büyük ve bağımsız
işlem örneklemi anlamına gelmiyor.

Makinece okunabilir tüm sonuçlar: [evidence/research.json](evidence/research.json).
İndirme özeti: [evidence/coverage.json](evidence/coverage.json).
Motor kimliği: `0e6e36400f17c95c`.

## Yöntem ve pilot açıklaması

Önce en likit 10+10 piyasada bağlantı ve replay pilotu yapıldı. Pilot sonrasında
sinyal eşikleri değiştirilmeden hacim eşiğini geçen tüm evrene genişletildi.
Kod incelemesinde ALO'nun marketable emir reddi senaryosu eksik bulundu ve
eklendi; nihai tablo bu düzeltmeyi içerir. İlk pilotun geçici rakamları nihai
raporun yerine kullanılmaz. BTC rejim hesabı önbelleğe alınarak hızlandırıldı;
rejim koşulu değişmedi.

Güncel evrenle geçmiş test yapıldığı için seçim yanlılığı vardır. Geçmiş
spread/derinlik yoktur; canlı likidite filtresi geçmişte doğrulanamamıştır.
Gerçek dolum, kısmi dolum ve perpetual funding dahil tam net kâr bilinmez.
OI ticker eşleşmeleri kontrat kimliğiyle doğrulanmış değildir. Kural bu
sonuçlarla onaylanmadı; durum `NOT_VALIDATED` olarak kaldı.

## Teknik kontroller

- 21 çevrimdışı test geçti: kaynak eşleşmesi, kapanmamış mumlar, zaman boşlukları,
  geleceği görmeyen rejim, ALO/limit/SL senaryoları, OI hash ve zaman denetimi,
  yeniden başlatma sonrası tekrar önleme, API tekrar sınırı, Telegram ayar
  ayrımı ve özel kanal yetki denetimi.
- Python derleme ve Termux başlatıcı kabuk sözdizimi kontrolü geçti.
- Son gerçek API taramasında 78 piyasa kontrol edildi, hata yoktu; BTC rejimi
  BULL olmasına rağmen o kapanışta koşulları tamamlayan aday çıkmadı. Telegram'a
  test/gerçek mesaj gönderilmedi. [Tarama kaydı](evidence/live-status.json).
- Bağımsız ZIP yalnız kaynak, doküman ve anonim piyasa sonuçlarını içerir;
  ZIP'ten açılan kopyada da aynı 21 test geçti.
- Gerçek Telegram gönderimi kullanıcının yeni bot tokenı/kanalı olmadan
  sınanmadı; kurulumdan sonra `python bot.py test-telegram` yapılmalıdır.
- Android üzerinde arka plan dayanıklılığı bu bilgisayardan doğrulanamaz;
  tablet kurulumu sonrası `status` ve `run.log` kontrol edilmelidir.

Kaynak ve hesap varsayımları: [RESEARCH_PROTOCOL.md](RESEARCH_PROTOCOL.md).
