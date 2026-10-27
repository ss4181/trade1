# Termux ana ekran kısayolları

Bu kısayollar Trade1'i tablette yönetmek içindir. Emir göndermez; botun tarama,
sinyal ve bildirim mantığını değiştirmez. Kısayollar arka plan görevleri olarak
çalışır ve sonuçları Termux bildiriminde gösterir.

## Bir defalık kurulum

1. Termux ve Termux:Widget aynı kaynaktan kurulmuş olmalı (ör. ikisi de F-Droid).
   Farklı imza/kaynakla kurulan eklentiler birbirleriyle çalışmayabilir.
2. Termux'u en az bir kez aç. Proje `~/trade1` konumunda olmalı ve tabletin
   GitHub erişimi çalışıyor olmalı.
3. Termux'ta çalıştır:

   ```sh
   cd ~/trade1
   sh termux/widget/install.sh
   ```

4. Ana ekranda boş alana basılı tut → **Widget'lar** → **Termux:Widget**
   → **Termux:Tasker/Shortcuts** widget'ını ekle. Widget görünmezse
   Termux:Widget'i açıp **REFRESH**'e dokun.

## Düğmeler

- **01-Trade1-Guncelle-ve-Baslat:** `origin/main`'i kontrol eder. Yalnız yerel
  Git değişikliği yoksa, ana dal gerideyse ve fast-forward mümkünse botu
  durdurur, kodu alır, Python dosyalarını ve bildirim politikası sürümünü
  doğrular, sonra tek kopya olarak başlatır. Kontrol başarısız olursa
  otomatik başlatmaz; Termux çıktısını incele.
- **02-Trade1-Yeniden-Baslat:** kodu indirmeden mevcut kurulumu durdurup tek
  kopya başlatır.
- **03-Trade1-Durdur:** yalnız `~/trade1` klasöründen çalışan bot/API
  süreçlerini nazikçe durdurur. Kapatılamayan süreci zorla öldürmez.
- **04-Trade1-Durum:** süreç var mı ve yerel sürüm kısa kimliği nedir gösterir.

Güncelleme, yerel değişiklik veya farklılaşmış Git dalı görürse **hiçbir dosyayı
silmez/geri almaz** ve ilerlemeyi durdurur. Böyle bir durumda Termux'ta çıktıyı
incele; `.env`, arşiv ve state dosyalarını silme. Kısayol kilitli kaldıysa önce
başka bir widget işleminin çalışmadığını doğrula; ardından yalnız şu kilit
klasörünü kaldırabilirsin:

```sh
rmdir "${TMPDIR:-/data/data/com.termux/files/usr/tmp}/trade1-widget-operation.lock"
```

İlk kurulumdan sonra bir düğmeye bastığında Termux'un arka plan görev
bildirimlerini görmelisin. Android pil ayarlarında Termux ve Termux:Widget'i
kısıtlamasız tut; tablet kapanırsa kısayol botu uzaktan çalıştırmaz.
