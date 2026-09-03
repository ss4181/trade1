# S2 + Global Long/Short Oranı Araştırması (S2-LS-v1)

Tarih: 2026-09-02
Karar: **RED — canlı S2 değiştirilmedi; dokunulmamış test açılmadı.**

## Soru ve yöntem

Hipotez, mevcut S2 funding-squeeze LONG koşulu oluştuğunda short hesap sayısı
long hesap sayısından fazlaysa yükseliş olasılığının artacağıydı. Mevcut S2
olayları, eşiği veya cooldown'u değiştirilmedi. Binance USD-M daily metrics
arşivindeki `count_long_short_ratio` kullanıldı ve yalnız sinyal zamanından
önceki son tamamlanmış 5 dakikalık kayıt eşleştirildi.

Sonuca bakmadan önce [karar kapıları](PREREG_S2_LONG_SHORT_FILTER.md) yazıldı.
Birincil ufuk 72 saat, giriş sonraki saat açılışı, piyasa USD-M perpetual ve
round-trip maliyet 12 bp olarak donduruldu.

## Train sonucu (2024-07–2025-12)

| Grup | N | Gün | Sembol | Net ort. | Net medyan | İsabet | q10 | q90 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Tüm S2 | 228 | 175 | 16 | +%1.539 | +%0.662 | %53.5 | −%9.67 | +%13.01 |
| Metrics eşleşen S2 | 222 | 172 | 16 | +%1.702 | +%0.865 | %54.5 | −%9.24 | +%12.88 |
| **Long/short < 1** | **13** | **13** | **6** | +%2.666 | +%0.061 | %53.8 | −%9.15 | +%12.86 |
| Long/short >= 1 | 209 | 161 | 16 | +%1.642 | +%0.881 | %54.5 | −%9.17 | +%12.79 |

- Metrics kapsamı: **%97.4**.
- LS<1 ortalaması karşı gruptan +1.024 yüzde puan yüksek görünse de gün-kümeli
  bootstrap p-değeri **0.3565**; istatistiksel kanıt yok.
- Filtreli medyan (+%0.061), karşı grubun medyanından (+%0.881) daha düşük.
- Yalnız 13 olay ve 6 sembol var; olayların %92.3'ü ilk beş sembolde.

## Neden canlıya eklenmedi?

Ön-kayıtlı train kapısı altı ayrı nedenle geçilmedi: N<50, bağımsız gün<30,
sembol<8, top-5 yoğunluğu>%70, p>0.10 ve medyan üstünlüğü yok. Test dönemini
bu sonucu gördükten sonra açmak, aynı dokunulmamış testi yeni fikirler için
tekrar tekrar kullanmak olurdu; bu nedenle 2026H1 sonuçları bilinçli olarak
hesaplanmadı.

## Yorum

Bu örneklemde negatif funding oluştuğunda global hesap oranının çoğu kez
zaten 1'in üzerinde olduğu görülüyor. `LS<1` nadir ve birkaç coinde yoğun.
Ayrıca global oran yalnız hesap sayısını ölçer; short pozisyonların dolar
büyüklüğünü ölçmez. Dolayısıyla hipotezin yönü sezgisel olsa da mevcut tarihsel
veri zorunlu bir S2 filtresini desteklemiyor.

Canlı S2 mantığı, eşiği, bildirim politikası ve güven etiketi aynen kaldı.
İleri dönem OI/long-short arşivi birikmeye devam edebilir; ancak bu ön-kayıtlı
çalışmanın başarısız sonucunu sonradan eşik değiştirerek yeniden adlandırmamak
gerekir. Yeni bir hipotez ayrı bir ön kayıt ve yeni ileri dönem verisi ister.
