# Rejim araştırması — TP2/TP3 dokunma yeniden hesabı

Bu ek rapor, 22 Eylül 2026 tarihli rejim çalışmasının zaman çıkışı oranlarını
karar ölçüsü olarak kullanmaz. Her olay için ölçüm girişindeki saatlik açılış
fiyatı alınır; aynı ufuk içinde kapanmış saatlik mumlardan birinin en yüksek
fiyatı girişin **%2 (TP2)** veya **%3 (TP3)** üstüne değerse hedef dokunmuş
sayılır.

Dokunma hesabı brüt fiyat yoludur: stop, ücret, slippage, funding, limit emir
doluluğu ve aynı mum içindeki emir sırası yoktur. Bu yüzden oran, gerçek işlem
kârı veya hedef-stop başarısı değildir. Ufuklar değişmedi: S1/S1+S4 24 saat,
S2 72 saat, S3 4 saat, G1 4 saat. G2 için seçilmiş arşivdeki 24 saatlik MFE
aynı tanıma çevrildi; G2'nin 60 dakika gecikmeli planlı girişi korunmuştur.

Toplam **2.814** olayın tamamında TP2 ve TP3 dokunma verisi mevcuttur. Çekirdek
olaylar 01.07.2024–30.06.2026 saatlik arşivinden, G1 vekili 01.07.2024–
31.12.2025 sabit89 TRAIN arşivinden, G2 ise önceden seçilmiş A/B/C adayından
gelir. G1 satırları canlı dinamik evrenin OOS doğrulaması değildir.

## Ana rejimler

Hücre biçimi **TP2 / TP3 (olay sayısı)** şeklindedir. Rejim, olayın sinyal
referansındaki günlük BTC kapanışından etiketlenmiştir.

| Strateji / evren | BOĞA | GEÇİŞ | AYI |
|---|---:|---:|---:|
| S1 / core30 / 24s | %84,7 / %74,6 (59) | %86,2 / %69,0 (29) | %56,0 / %45,3 (75) |
| S1+S4 / core30 / 24s | %65,9 / %61,0 (41) | %82,1 / %71,4 (28) | %69,1 / %61,8 (68) |
| S2 / core30 / 72s | %78,6 / %71,8 (103) | %81,6 / %72,4 (87) | %69,8 / %58,3 (139) |
| S3 / core30 / 4s | %46,8 / %31,7 (530) | %31,2 / %14,5 (186) | %40,1 / %25,4 (287) |
| S1 / extended59 / 24s | %91,5 / %83,8 (130) | %72,0 / %61,0 (82) | %73,8 / %60,7 (107) |
| S1+S4 / extended59 / 24s | %64,5 / %57,9 (107) | %87,5 / %84,4 (32) | %73,2 / %64,8 (71) |

Bu tablo, boğa rejiminin S1 ve S2'de daha yüksek hedef dokunmasıyla birlikte
görüldüğünü; S3'te ise boğa içindeki geri çekilme alt türünün ana boğa
ortalamasından daha iyi olduğunu gösteriyor. Rejim tek başına otomatik kapı
olarak kullanılmamalıdır; aynı gün çok sayıda coin olayı bağımsız piyasa günü
değildir.

## Boğa alt türleri

| Strateji / evren | Geri çekilme | Ilımlı | Güçlü |
|---|---:|---:|---:|
| S1 / core30 | %72,7 / %63,6 (22) | %93,5 / %80,6 (31) | %83,3 / %83,3 (6) |
| S1+S4 / core30 | %62,1 / %55,2 (29) | %70,0 / %70,0 (10) | %100,0 / %100,0 (2) |
| S2 / core30 | %83,6 / %78,2 (55) | %70,4 / %59,3 (27) | %76,2 / %71,4 (21) |
| S3 / core30 | %60,9 / %51,0 (151) | %30,4 / %16,8 (184) | %51,3 / %30,8 (195) |
| G1 vekili / fixed89 | %50,9 / %35,8 (53) | %56,2 / %45,0 (80) | **%65,6 / %59,0 (61)** |

## G1 için özellikle yeniden hesaplanan bölüm

G1'in tüm 401 olayında TP2 dokunması **%56,1**, TP3 dokunması **%43,1**.
Boğa günlerinde bu oranlar **%57,7 / %46,9**; güçlü boğa alt türünde
**%65,6 / %59,0** (61 olay, 42 gün). Son 90 günlük TRAIN alt penceresinde
73 olay ve 45 gün için TP2 **%64,4**, TP3 **%54,8**; son 180 günde 97 olay ve
69 gün için **%63,9 / %54,6**.

Bu bulgu kullanıcının son dönem gözlemiyle uyumludur: G1'in hedefe dokunma
oranı son arşiv bölümünde yükselmiştir. Aynı 90 günlük pencerede zaman çıkışı
ortalaması +%0,411 iken tüm G1 vekilinde −%0,127, boğa vekilinde −%0,328'dir.
Dolayısıyla TP dokunması güçlü bir iyileşme sinyali olsa da, hedefe değip sonra
geri dönme, stop, spread, limit dolumu ve örneklem seçimi ayrıştırılmadan
"G1 artık kârlı" sonucu çıkarılamaz.

## Sonuç ve sabit sonraki adım

- Rejim raporu artık TP2 ve TP3 dokunma oranlarını ayrı ve açık ölçü olarak
  saklıyor; eski zaman çıkışı tablosu karşılaştırma amacıyla korunuyor.
- G1 için canlı eşikler, güven etiketi veya otomatik boğa filtresi bu sonuçla
  değiştirilmedi. G1'in sonraki 30+ olgun olayı ve en az 30 ayrı günü aynı
  TP2/TP3 protokolüyle biriktirilecek.
- Bir sonraki doğrulama, hedef dokunmasını **TP2/TP3 + stop sırası + gerçek
  bildirim teslimi** olarak ayrı raporlayacak. Bu üç ölçü tek bir başarı oranında
  birleştirilmeyecek.

Yeniden üretim kodu: `research/market_regime_review.py` içindeki `touch_grid`;
özet çıktısı: `research/results/market_regime_touch_review_2026-09-22.json`.
