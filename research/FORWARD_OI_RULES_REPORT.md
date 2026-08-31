# P0–P5 ve Q1: anlaşılır Forward OI araştırma raporu

## Bunlar nedir, ne değildir?

P0–P5 ve Q1, canlı bottaki S1/S2/S3/S5/S6 stratejileri değildir. Yeni bir
fikrin hangi parçasının işe yarayıp yaramadığını ayırmak için kullanılan
**araştırma filtreleridir**. P0'dan P5'e her satır bir önceki satıra yeni koşul
ekler. Q1 ise farklı bir squeeze açıklamasını sınayan bağımsız koldur.

| Kod | Sade tanım | Sorulan soru |
|---|---|---|
| **P0** | Coin, aynı saatte evrendeki en yüksek 10 adet 24 saatlik getiriden birine sahip ve en az %5 yükselmiş | Yalnız “günün yükseleni” olmak yükselişin devamını öngörüyor mu? |
| **P1** | P0 + son görülen 5m taker hacmi, önceki 24 saatten saatlik örneklenen 5m hacimlerin medyanının en az 2 katı | Pump yüksek işlem akışıyla desteklenince sonuç iyileşiyor mu? |
| **P2** | P1 + açık pozisyon miktarı (OI) son bir saatte herhangi bir miktar artmış | Yeni kaldıraçlı pozisyon girişi devamı destekliyor mu? |
| **P3** | P1 + OI son bir saatte en az %2 artmış | Yalnız güçlü OI birikimi seçilince sinyal iyileşiyor mu? |
| **P4** | P3 + global hesap long/short oranı 1'in altında | Hesap sayısında short çoğunluğu squeeze yakıtı oluşturuyor mu? |
| **P5** | P4 + funding son 6 saatte yükselmiş | Funding'in yukarı dönmesi squeeze'in başladığını teyit ediyor mu? |
| **Q1** | P0 + short çoğunluğu + OI son saatte en az %2 düşmüş + taker alış/satış oranı 1'in üstünde | Yeni short birikimi yerine short kapanışı başlamış bir squeeze yakalanıyor mu? |

### Terimler

- **OI (open interest):** Açık vadeli işlem sözleşmelerinin toplamıdır; tek
  başına long mu short mu açıldığını söylemez.
- **Global long/short oranı:** Pozisyon büyüklüğü değil, long ve short tarafta
  bulunan **hesap sayılarının** oranıdır. `<1`, short hesapların çoğunlukta
  olduğunu söyler; short notionalının daha büyük olduğunu kanıtlamaz.
- **Funding yükselişi:** Funding'in mutlaka pozitif olması değildir. Örneğin
  −%0,05'ten −%0,02'ye gelmesi de yükseliştir.
- **Taker alış/satış oranı:** `>1`, incelenen 5m dilimde piyasa alış hacminin
  piyasa satış hacminden yüksek olduğunu gösterir.

## 31 Ağustos 2026 keşif sonucu

P0'ın 4 saatlik net medyanı −%0,57 ve isabeti %39'dur. P1–P3'te hacim ve OI
filtreleri bu yönsel sonucu düzeltmemiştir; güçlü OI artışında medyan −%0,76'ya
gerilemiştir. P4'ün medyanı +%0,35 ve isabeti %55,6 görünse de yalnız 9 olay/5
günden oluşur, ortalaması negatiftir ve q10'u −%4,81'dir. P5 yalnız 2, Q1 yalnız
6 olaydır; bunlardan güvenilir oran çıkarılamaz.

Saatlik hedef-dokunma tanısı, filtrelerin yön seçmekten çok daha oynak coinleri
seçiyor olabileceğini göstermiştir. Özellikle yüksek 24 saatlik +%2/+%3 dokunma
oranı, hedef görülmeden önceki zarar veya aynı dönemde stop görülüp görülmediği
bilinmeden “başarı” sayılamaz.

## Doğru sonraki test

`eval_forward_oi_barriers.py`, aynı olaylar için resmî 5m USD-M mumlarını seçici
indirir ve +%2/+%3 hedef ile −%1/−%1,5/−%2 stop seviyelerinden hangisinin önce
geldiğini ölçer. Aynı mumdaki sıra bilinemezse stop önce kabul edilir. Test
protokolü sonuç görülmeden önce
[`PREREG_FORWARD_OI_BARRIERS.md`](PREREG_FORWARD_OI_BARRIERS.md) içinde
dondurulmuştur.

Çalıştırma:

```bash
python research/eval_forward_oi_barriers.py --dir .
```

İlk çalıştırma gereken günlük ZIP dosyalarını
`research/data/forward_oi_5m/` altında önbelleğe alır. Bu klasör Git'e girmez.
Henüz yayımlanmamış günler eksik görünür; sonraki gün aynı komut yeniden
çalıştırıldığında yalnız eksik dosyalar tamamlanır. Tüm stop hassasiyetlerini
konsolda görmek için `--full`, makine-okunur tam sonuç için `--json` kullanılır.
