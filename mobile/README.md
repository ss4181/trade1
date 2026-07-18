# Signal Bot — iPhone izleyici (Expo Go)

Sunucudaki (`server.py`) `/signals/latest` endpoint'ini pollayıp yeni sinyalde
**yerel bildirim** gösteren basit bir Expo uygulaması.

## Gerçek sınırlama (önce bunu oku)

Expo Go, SDK 53'ten itibaren **uzak (remote) push** bildirimini desteklemez.
Bu uygulama bunun yerine **uygulama açıkken** sunucuyu her ~45 sn'de bir yoklar
ve yeni sinyal geldiğinde `expo-notifications` ile **local notification**
gösterir. Sonuç:

- ✅ Uygulama açık/ön plandayken yeni sinyalde anında bildirim + liste güncellenir.
- ❌ Uygulama **tamamen kapalı veya uzun süre arka planda** ise bildirim gelmez.
- ➡️ "Hiç kaçırmadan" 7/24 uyarı için **Telegram ve email** kanalları var; mobil
  uygulama bir *izleme/görüntüleme* aracıdır, tek başına bir push sistemi değil.

Bu, native build (EAS/TestFlight) gerektirmeden Expo Go'da çalışması için
bilinçli bir mimari tercihtir.

## Kurulum

Bilgisayarında Node.js kurulu olmalı. Sonra:

```bash
cd mobile
npm install
# expo-notifications & async-storage sürümlerini Expo SDK'na göre hizala:
npx expo install expo-notifications @react-native-async-storage/async-storage
npx expo start
```

Terminalde bir **QR kod** çıkar. iPhone'da **Expo Go** uygulamasını App
Store'dan kur, kamerayla (veya Expo Go içinden) QR'ı tara. Uygulama telefonda
açılır.

> iPhone ve bilgisayarın **aynı Wi-Fi ağında** olmalı. Değilse `npx expo start
> --tunnel` ile başlat (biraz yavaş ama farklı ağdan da çalışır).

## Kullanım

1. Uygulamada **Ayarlar** sekmesine geç.
2. **Sunucu adresi** alanına Render URL'ni gir (örn.
   `https://signal-bot-xxxx.onrender.com`), **Kaydet**'e bas.
3. İlk açılışta iOS bildirim izni ister — **İzin Ver**.
4. **Sinyaller** sekmesi son sinyalleri kart olarak listeler; uygulama açık
   kaldıkça yenilenir, yeni sinyalde bildirim düşer.

İlk yüklemede mevcut (eski) sinyaller için bildirim **yağdırmaz** — yalnızca o
andan sonra gelen yeni sinyaller bildirim üretir.

## Notlar

- Ücretsiz Render servisi uykudaysa ilk istek 30-60 sn gecikebilir; "Zaman
  aşımı" görürsen birkaç saniye sonra kendiliğinden tekrar dener.
- Sunucu adresi yanlışsa Ayarlar > Durum bölümünde bağlantı hatası görünür.
