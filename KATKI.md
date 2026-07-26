# Başka bir AI'dan gelen değişiklikleri güvenli alma (branch/PR)

Amaç: dışarıdan (ChatGPT, Gemini, başka bir Claude oturumu…) gelen kod
doğrudan `main`'e girmesin; önce ayrı bir dalda (branch) beklesin, testler
otomatik koşsun, sen (ve istersen ben) bakıp onaylayınca `main`'e geçsin.

**Neden:** `main` = tablette çalışan canlı bot. `git pull` yaptığın anda o kod
gerçek bildirim üretmeye başlar. Bir dalda beklerse hiçbir riski olmaz ve
GitHub Actions testleri PR'da **otomatik** koşar (`.github/workflows/tests.yml`
zaten `pull_request` olayını dinliyor).

---

## Durum A — AI'ın GitHub erişimi VAR (Codex / Copilot agent / Jules vb.)

Görev metninin sonuna şunu ekle (kopyala-yapıştır):

> Değişiklikleri `main` dalına DOĞRUDAN gönderme. `inceleme/<kısa-konu>`
> biçiminde yeni bir dal aç, commit'leri oraya at ve `main`'e bir Pull Request
> oluştur. PR açıklamasında ne değiştirdiğini ve nedenini madde madde yaz.
> Eşik değerlerini ve strateji mantığını değiştirme (bkz. research/REPORT.md).

Sonra GitHub'da **Pull requests** sekmesinde PR'ı görürsün → aşağıdaki
"PR'ı inceleme" bölümüne geç.

## Durum B — AI sadece kod/dosya veriyor (ChatGPT web gibi) ← senin durumun

Dosyaları alıp **dalda** uygula. `trade1` klasöründe:

```bash
git checkout main
git pull
git checkout -b inceleme/chatgpt-$(date +%m%d)
```

Şimdi AI'ın verdiği dosyaları klasöre kopyala/kaydet. Sonra:

```bash
git add -A
git commit -m "ChatGPT incelemesi: <kisa aciklama>"
git push -u origin HEAD
```

Son komut sana şuna benzer bir bağlantı yazdırır:

```
remote: Create a pull request for 'inceleme/chatgpt-0726' on GitHub by visiting:
remote:      https://github.com/ss4181/trade1/pull/new/inceleme/chatgpt-0726
```

O bağlantıyı aç → **Create pull request** de. Bu kadar. `main`'e hiçbir şey
girmedi, tablette çalışan bot etkilenmedi.

---

## PR'ı inceleme (yeşil ışık / kırmızı ışık)

1. **Testleri bekle.** PR sayfasının altında GitHub Actions sonucu çıkar
   (~2-3 dk). ✅ yeşilse kod en azından derleniyor ve 40+ test geçiyor.
   ❌ kırmızıysa **birleştirme**; hatayı bana getir.
2. **Değişikliğe bak.** PR'daki **Files changed** sekmesi neyin değiştiğini
   satır satır gösterir. Özellikle dikkat: `signal_bot.py` içindeki
   `RSI_OVERSOLD`, `FUNDING_*`, `VOLUME_ZSCORE_*`, `CONFLUENCE_*` sabitleri ve
   `DEFAULT_SYMBOLS` / `EXTENDED_SYMBOLS_DEFAULT` listeleri **değişmemeli**
   (bunlar araştırma çıktısı — research/REPORT.md).
3. **Bana danış (önerilir).** Bu oturumda ya da yeni bir Claude oturumunda
   sadece şunu söyle: *"şu PR'ı incele: <PR bağlantısı>"*. Repo public olduğu
   için PR'ı okuyup satır satır denetleyebilirim.
4. **Birleştir:** PR sayfasında **Merge pull request** → **Confirm merge**.
   Sonra tablette:
   ```bash
   cd ~/trade1 && git pull
   ```
   ve botu yeniden başlat.
5. **Reddet:** PR sayfasında **Close pull request**. Dal kalır, `main` temiz.
   İstersen dalı da silebilirsin (**Delete branch**).

---

## Yanlışlıkla `main`'e girdiyse ne yapılır

Panik yok, geri alınabilir. Bana söyle; ya da kendin:

```bash
git checkout main
git pull
git revert --no-commit <commit-hash>   # degisiklikleri tersine cevir
git commit -m "Geri alma: <sebep>"
git push
```

`<commit-hash>`'i `git log --oneline -5` ile bulursun. `revert` geçmişi
silmez, üstüne "geri alma" commit'i ekler — güvenli yoldur.

---

## İstersen: `main`'i teknik olarak kilitle (opsiyonel)

GitHub'da doğrudan `main`'e push'u engelleyebilirsin:
**Settings → Branches → Add branch protection rule** →
Branch name pattern: `main` → **Require a pull request before merging** işaretle
→ **Create**.

Dürüst şerh: repo sahibi (sen) yönetici olduğun için bu kural seni
"Do not allow bypassing the settings" seçeneğini de işaretlemediğin sürece
tam durdurmaz; ayrıca işaretlersen **benim** düzeltmelerim de her seferinde PR
gerektirir (yavaşlar). Bu yüzden varsayılan olarak açmadım — karar senin.
Yukarıdaki Durum B akışı, kural olmadan da işi görür.
