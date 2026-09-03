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
