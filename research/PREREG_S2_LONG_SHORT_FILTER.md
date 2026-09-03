# S2 Long/Short Filtresi — Ön Kayıt (S2-LS-v1)

Tarih: 2026-09-02
Durum: Sonuçlara bakılmadan dondurulmuştur.

## Hipotez

Mevcut S2 funding-squeeze LONG olayı sırasında global hesap long/short oranı
`1.0` değerinin altındaysa (short hesap sayısı long hesap sayısından fazlaysa),
72 saatlik ileri getiri diğer S2 olaylarından daha yüksek olur.

Bu çalışma yalnız bu tek eşiği sınar. Sonuca bakarak `0.8`, `0.9`, `1.1` gibi
alternatif eşikler arasından seçim yapılmayacaktır.

## Dondurulmuş tasarım

- Evren: mevcut botta S2 çalıştırılan sabit çekirdek 30 sembol.
- Dönem: 2024-07-01 00:00 UTC–2026-06-30 23:00 UTC.
- Train: 2024-07-01–2025-12-31; dokunulmamış test: 2026-01-01–2026-06-30.
- S2 olayı: funding `<= -0.03%`, art arda en az 2 settlement, 24 saat cooldown.
- Long/short ölçümü: Binance USD-M daily metrics içindeki
  `count_long_short_ratio` (hesap sayısı oranı; pozisyon büyüklüğü değildir).
- Zaman hizası: olay zamanından **kesinlikle önceki** son tamamlanmış 5 dakikalık
  metrics kaydı; azami yaş 15 dakika. Sonraki timestamp kullanılmaz.
- Aday filtre: `count_long_short_ratio < 1.0`.
- Giriş: sinyal saatinden sonraki 1 saatlik USD-M perpetual mumun açılışı.
- Çıkış: girişten 72 saat sonraki kapanış.
- Getiri: LONG yönlü; brüt ve 12 bp round-trip maliyet sonrası net raporlanır.
- Eksik fiyat/oran uydurulmaz. Kapsam ayrıca raporlanır.

## Önceden belirlenmiş karar kapıları

Önce yalnız train değerlendirilir. Train kapısı geçmezse test sonuçlarına
bakılmaz ve canlı S2 değiştirilmez.

Train kapısı:

1. Long/short eşleşme kapsamı en az %90.
2. Filtreli grupta en az 50 olay, 30 bağımsız UTC günü ve 8 sembol.
3. Net ortalama ve medyan pozitif; net isabet en az %52.
4. Filtreli grubun net ortalaması `LS>=1` grubundan en az +0.25 yüzde puan
   yüksek; medyanı da daha yüksek.
5. Gün-kümeli bootstrap ile ortalama farkın sıfırdan büyük olma tek taraflı
   p-değeri en çok 0.10.
6. En çok olay üreten beş sembolün payı en fazla %70.

Train geçerse dokunulmamış test kapısı:

1. Kapsam en az %90; filtreli N>=30, bağımsız gün>=20, sembol>=8.
2. Net ortalama ve medyan pozitif; isabet en az %52.
3. `LS<1` ortalama ve medyanı `LS>=1` grubundan yüksek.
4. Gün-kümeli bootstrap tek taraflı p<=0.10.
5. Filtreli q10, karşı grubun q10 değerinden 1 yüzde puandan fazla kötü değil.
6. Top-5 sembol payı en fazla %70.

Tüm kapılar geçmeden canlı strateji, güven etiketi veya Telegram metni
değiştirilmeyecektir. Kapı geçerse değişiklik ayrıca kod/test denetiminden
geçirilecektir.

## Yorum sınırları

`count_long_short_ratio < 1`, daha fazla hesabın short tarafta olduğunu söyler;
short pozisyonların toplam dolar büyüklüğünün daha fazla olduğunu söylemez.
Funding ile aynı kavram değildir ve ek bilgi taşıyıp taşımadığı bu testin
konusudur. Bu bir emir veya yatırım tavsiyesi çalışması değildir.
