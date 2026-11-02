# Termux ana ekran kısayolları

Bu kısayollar Trade1'i tablette yönetmek içindir. Emir göndermez; botun tarama,
sinyal ve bildirim mantığını değiştirmez. Her düğme bir Termux penceresi açar,
sonucu (`TAMAM` veya `HATA` ve nedeni) gösterir ve Enter'a basınca kapanır.

**3 Kasım 2026:** Eski kurulum düğmeleri arka planda sessiz çalıştırıyordu;
güncelleme durunca nedeni görünmüyordu. Ayrıca Git dışı herhangi bir dosya
(ör. dönen `bot.out.log.1` veya yanlış yazılmış bir dosya adı) bütün
güncellemeleri durduruyordu. Artık yalnız Git'teki dosyalarda yapılmış yerel
değişiklik güncellemeyi durdurur; Git dışı dosyalara dokunulmaz ve listesi
not olarak gösterilir. Yeni düğmeler için kurulum komutunu bir kez yeniden çalıştır.

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

Güncelleme, Git'teki dosyalarda yerel değişiklik, farklılaşmış Git dalı veya
güncellemenin üzerine yazacağı Git dışı bir dosya görürse **hiçbir dosyayı
silmez/geri almaz** ve bot çalışmaya devam ederken ilerlemeyi durdurur. Böyle bir durumda Termux'ta çıktıyı
incele; `.env`, arşiv ve state dosyalarını silme. Kısayol kilitli kaldıysa önce
başka bir widget işleminin çalışmadığını doğrula; ardından yalnız şu kilit
klasörünü kaldırabilirsin:

```sh
rmdir "${TMPDIR:-/data/data/com.termux/files/usr/tmp}/trade1-widget-operation.lock"
```

İlk kurulumdan sonra bir düğmeye bastığında Termux penceresi açılmalı ve sonuç
satırı görünmeli. Android pil ayarlarında Termux ve Termux:Widget'i
kısıtlamasız tut; tablet kapanırsa kısayol botu uzaktan çalıştırmaz.
