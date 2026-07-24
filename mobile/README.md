# Signal Bot — iPhone izleyici (Expo Go)

Sunucudaki (`server.py`) `/signals/latest` endpoint'ini pollayıp sunucunun mobil
bildirime açıkça izin verdiği yeni sinyaller için **yerel bildirim** gösteren
basit bir Expo uygulaması.

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

## Bildirim politikası

Mobil uygulama güvenli bir **varsayılan-kapalı** politika uygular:

- Yalnızca API kaydında `push_allowed: true` bulunan ve
  `suppressed: true` olmayan sinyaller yerel bildirim üretir.
- Eski sunucu sürümlerinden gelen, `push_allowed` alanı bulunmayan kayıtlar
  listede gösterilir ama telefonda bildirim üretmez.
- `suppression_reason` alanı sunucunun sinyali neden sessiz bıraktığını
  açıklar; mobil istemci bu kararı geçersiz kılmaz. Bu kayıtlar listede
  "Sessiz kayıt" etiketi ve nedeniyle görünür.
- Tekrar bildirimleri önlemek için öncelikle `event_id` kullanılır. Eski
  kayıtlarda olay zamanı, sembol, strateji, yön, fiyat ve ufuktan sabit bir
  kimlik oluşturulur.
- Gözlenen, başarıyla teslim edilen ve teslimi başarısız olan olaylar ayrı
  tutulur. Bildirim zamanlaması geçici olarak başarısız olursa en fazla üç
  deneme yapılır; denemeler 15 dakika sonunda sona erer. Böylece geçici hata
  tolere edilirken eski bildirimlerin sonradan topluca yağması engellenir.
- Bir poll turunda en fazla beş yeni yerel bildirim üretilir ve 15 dakikadan
  eski kayıtlar yalnızca listede gösterilir. Uygulama uzun süre kapalı kaldıktan
  sonra geçmiş uyarılar telefona topluca düşmez.
- Teslim durumu her normalize edilmiş sunucu adresi için ayrı saklanır. İlk
  kurulumda, bu sözleşmeye ilk geçişte veya yeni bir sunucu adresine geçildiğinde
  mevcut kayıtlar o adresin başlangıç çizgisi kabul edilir.
- API'den gelen kayıtlar gösterilmeden önce doğrulanır. Geçersiz zaman, fiyat,
  ufuk veya zorunlu kimlik alanları taşıyan bozuk satırlar sessizce düşürülür;
  tek bir bozuk satır listenin tamamını bozmaz.

## Kurulum

Proje güncel Expo Go ile uyumlu **Expo SDK 57**'ye kilitlidir. Bilgisayarında
Node.js 22 kurulu olmalı. Sonra:

```bash
cd mobile
npm ci
npm run check
npm run doctor
npx expo start
```

Terminalde bir **QR kod** çıkar. iPhone'da **Expo Go** uygulamasını App
Store'dan kur, kamerayla (veya Expo Go içinden) QR'ı tara. Uygulama telefonda
açılır.

> iPhone ve bilgisayarın **aynı Wi-Fi ağında** olmalı. Değilse `npx expo start
> --tunnel` ile başlat (biraz yavaş ama farklı ağdan da çalışır).

## Kullanım

1. Uygulamada **Ayarlar** sekmesine geç.
2. **Sunucu adresi** alanına tablet/VPS adresini gir (aynı Wi‑Fi'da örn.
   `http://192.168.1.50:8000`), **Kaydet**'e bas.
3. iOS yerel ağ ve bildirim izni isterse ikisine de **İzin Ver**.
4. **Sinyaller** sekmesi son sinyalleri kart olarak listeler; uygulama açık
   kaldıkça yenilenir. Yeni sinyal ancak sunucu `push_allowed: true` kararı
   vermişse bildirim düşer.

İlk yüklemede mevcut (eski) sinyaller için bildirim **yağdırmaz** — yalnızca o
andan sonra gelen, açıkça push izni verilmiş yeni sinyaller bildirim üretir.

## Notlar

- Sunucu adresi yanlışsa Ayarlar > Durum bölümünde bağlantı hatası görünür.
- Yerel IP kullanıyorsan iPhone ve tablet aynı güvenilir Wi‑Fi'da olmalı.
  Native/development build için `app.json`, yalnız yerel ağa izin veren iOS
  açıklamasını ve ATS `NSAllowsLocalNetworking` ayarını içerir.
- Polling yalnızca uygulama ön plandayken çalışır. iOS uygulamayı arka plana
  aldığında polling durur; uygulama yeniden aktif olduğunda hemen tekrar
  başlar. Bu uygulama APNs/Expo remote push servisi değildir.
- Sunucu adresi değiştirildiğinde eski adrese ait devam eden istek iptal edilir;
  eski cevabın yeni ekranı veya bildirim durumunu ezmesine izin verilmez.
- GitHub Pages'te yayımlanan `data.json` dashboard'a özel bir veri yapısıdır;
  mobil bildirim akışı değildir. Mobil uygulama yalnızca `server.py`
  `/signals/latest` sözleşmesiyle kullanılmalıdır.
