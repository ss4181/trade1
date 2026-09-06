# Tablet → Windows günlük araştırma yedeği

Amaç, tabletteki ham OI/funding/likidasyon araştırma verisinin ikinci kopyasını
aynı cihazda değil Windows bilgisayarda tutmaktır.

Akış şöyledir:

1. Bot her 24 saatte bir güvenli aktarım kopyasını tablette
   `/storage/emulated/0/trade1-backup` içine yazar.
2. Syncthing-Fork bu klasörü Windows bilgisayara şifreli olarak eşitler.
3. Windows hedefi `C:\Users\serha\Documents\Trade1-Backup` klasörüdür.
4. Windows klasörü **Receive Only**, tablet klasörü **Send Only** olmalıdır.
5. Windows'ta **Staggered File Versioning / 365 gün** etkin olmalıdır.

Bu yapı public GitHub veya bir bulut depolama hesabına ham veri yüklemez.
Bilgisayar kapalıysa tablet kopyası bekler; iki cihaz yeniden çevrimiçi olduğunda
aktarılır.

## Tablet kurulumu

Resmî Syncthing Android uygulaması artık sürdürülmediği için güncel
**Syncthing-Fork** uygulamasını F-Droid'den veya projenin doğrulanmış GitHub
Releases sayfasından kur:

- https://github.com/researchxxl/syncthing-android/releases

Samsung pil ayarlarında Syncthing-Fork için `Kısıtlanmamış` arka plan kullanımını
seç. Uygulamaya dosya erişim izni ver ve tercihen yalnız Wi-Fi'da çalıştır.

1. Windows'ta `http://127.0.0.1:8384/` adresini aç.
2. `Actions → Show ID` ile bilgisayarın QR kodunu göster.
3. Tablette Syncthing-Fork'u aç, `Devices → Add Device` ile QR kodunu tara.
4. Windows arayüzünde gelen tablet eşleştirme isteğini kabul et.
5. Windows'ta `Trade1 Research Backup` klasörünü düzenle, `Sharing` bölümünde
   tableti seç ve kaydet.
6. Tablette gelen klasör paylaşımını kabul et:
   - Folder ID: `trade1-backup`
   - Folder path: `/storage/emulated/0/trade1-backup`
   - Folder type: `Send Only`
7. İlk eşitleme bitince iki tarafta da `Up to Date` görünmelidir.

## Doğrulama

Tablette önce yeni bir güvenli kopya üret:

```bash
cd ~/trade1
python signal_bot.py --backup-now
python signal_bot.py --backup-status
```

Windows'ta şu klasörü aç:

```text
C:\Users\serha\Documents\Trade1-Backup
```

Burada `market_archive_*.jsonl`, `liquidation_archive_*.jsonl`,
`shadow_market_*.jsonl` ve bot durum dosyaları görünmelidir. `.env` bulunmaması
doğrudur; token ve API anahtarları yedek paketine alınmaz.

Syncthing'de Windows klasör ayarları:

- Folder Type: `Receive Only`
- File Versioning: `Staggered File Versioning`
- Maximum Age: `365 days`

Kaynak tablet kaybolursa Windows kopyasını değiştirmeden önce başka bir klasöre
kopyala. Windows'taki `Revert Local Changes` veya tabletteki `Override Changes`
düğmelerini ne yaptığından emin olmadan kullanma.
# Günlük PC bütünlük kontrolü (7 Eylül 2026)

Tablet `--backup-now` veya günlük yedek turunda `backup_manifest.json` üretir.
Bu dosya arşiv/state dosyalarının SHA-256 ve boyutlarını içerir; sır içermez.
Yedek dosyalarının kendileri kullanıcı/chat kimliği gibi **özel** veriler
içerebilir: Syncthing klasörünü GitHub Pages'e veya herkese açık depoya koymayın.

Bilgisayarda, proje klasöründen:

```powershell
.\.venv\Scripts\python.exe -B backup_verify.py 'C:\Users\serha\Documents\Trade1-Backup'
```

Bu kontrol manifest tarihini (en fazla 36 saat), her dosyanın hash/boyutunu,
JSON/JSONL okunabilirliğini ve boş disk alanını denetler. `ok: true` yalnız
**bu bilgisayarda doğrulanan bu snapshot** içindir. Eski yedeklerde manifest
bulunmayabilir; tablet güncellendikten sonra yeniden yedek alıp eşitleyin.
Eşitleme devam ederken hash uyuşmazlığı geçici olabilir; bitince tekrar kontrol
edin. Mevcut bozuk JSON satırları silinmez, doğrulama başarısız gösterir.

Günlük yerel kontrolü kurmak/güncellemek için:

```powershell
.\pc\register-backup-check.ps1
```

Windows görevi: **Trade1 PC Backup Verify**, her gün yerel saat **12:45**.
Bilgisayar kapalıysa açılınca uygun ilk fırsatta çalışır; kullanıcı oturumu
gerektirir. Botu başlatmaz, yedekleri değiştirmez. Sonuç özel
`.pc_backup_status.json` dosyasına yazılır. Windows görev sonucu 0 başarı,
1 müdahale gerektiren durumdur. Bu PC kontrolü Telegram uyarısı göndermez ve
tablete “uzak teslim onayı” döndürmez; botun yerel yedek başarısıyla karıştırmayın.

Geri yükleme provası (hedef klasör **önceden bulunmamalıdır**):

```powershell
.\.venv\Scripts\python.exe -B backup_verify.py 'C:\Users\serha\Documents\Trade1-Backup' --restore-to 'C:\Users\serha\Documents\Trade1-Restore-Rehearsal'
```

Kaynaklar silinmez/üzerine yazılmaz; yeni kopya tekrar doğrulanır, bot çalışmaz.
Kaynak tabletin günlük snapshot'ı dosya bazında alınır, bütün dosyalar için
tek işlemsel an garantisi yoktur. Aktif JSONL'nin tamamlanmamış son satırı yalnız
**yedek kopyasında** kesilir; kaynak arşiv değişmez. Tam, tutarlı sistem geri
dönüşü gerektiğinde ayrıca bot durdurularak son yedek alınmalıdır.

## Syncthing: aynı dizine iki klasör tanımı olmamalı

Önceki incelemede aynı Windows dizinine iki farklı Folder ID bağlıydı. İşleyen
17 dosyalı tanımda **Receive Only + Staggered File Versioning / 365 days**
olduğunu kontrol edin. Eski/boş tanımı önce **Pause** yapın. **Revert Local
Changes** düğmesine basmayın: ikinci tanım dosyaları yerel ilave sanıp silebilir.
Dosya sürümleme ayarı diğer Folder ID'de açık diye çalışan klasör korunmuş olmaz.
Bu ayarların bilgisayarda yapıldığı ayrıca doğrulanmalıdır.
