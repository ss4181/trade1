#!/data/data/com.termux/files/usr/bin/sh
# Termux:Boot betigi — tablet yeniden baslayinca botu OTOMATIK baslatir.
# Kurulum adimlari: TABLET.md "Otomatik baslatma" bolumu.
#
# DIKKAT: Bu betik kuruluyken tablet acilisinda bot KENDILIGINDEN kalkar.
# Elle ikinci bir kopya BASLATMA. Once kontrol et:
#   pgrep -af "uvicorn server:app"
termux-wake-lock
cd "$HOME/trade1" || exit 1

BOT_LOG="bot.out.log"
STOP_FILE=".stop-signal-bot"
child_pid=""
rm -f "$STOP_FILE"

cleanup() {
  if [ -n "$child_pid" ]; then
    kill "$child_pid" 2>/dev/null || true
    wait "$child_pid" 2>/dev/null || true
  fi
  termux-wake-unlock 2>/dev/null || true
  exit 0
}
trap cleanup INT TERM HUP

rotate_log() {
  [ -f "$BOT_LOG" ] || return 0
  size="$(wc -c < "$BOT_LOG" 2>/dev/null || echo 0)"
  if [ "$size" -ge 5242880 ]; then
    mv -f "$BOT_LOG" "$BOT_LOG.1"
  fi
}

log() {
  printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$1" >> "$BOT_LOG"
}

# Termux "pkg upgrade" Python'u yukseltince site-packages surum klasoruyle
# birlikte gorunmez olur ve TUM pip paketleri kaybolur. 2026-08-01'de tam
# bunu yasadik: uvicorn kayboldu, sarmalayici 3 GUN boyunca 15 saniyede bir
# ayni hatayla yeniden denedi ve kimse fark etmedi.
#
# CEKIRDEK bagimlilik yalnizca `requests` (saf Python, her zaman kurulabilir).
# Bot bununla TAM calisir: tarama, Telegram komutlari, bildirimler, LAN panosu.
ensure_core_deps() {
  if python -c 'import requests' 2>/dev/null; then
    return 0
  fi
  log "cekirdek bagimlilik eksik -> pip install -r requirements.txt deneniyor"
  python -m pip install -r requirements.txt >> "$BOT_LOG" 2>&1
  if python -c 'import requests' 2>/dev/null; then
    log "cekirdek bagimliliklar onarildi"
    return 0
  fi
  log "CEKIRDEK BAGIMLILIK YOK — elle: pip install -r requirements.txt"
  return 1
}

# FastAPI/uvicorn OPSIYONEL: yalnizca mobil uygulamanin uc noktalari icin.
# Android'de kurulamayabilir (2026-08-04: Python 3.14'te uvicorn[standard]
# icindeki Rust tabanli watchfiles derlenemedi). Kurulamiyorsa bot dogrudan
# signal_bot.py ile kosar — mobil uc nokta gider, geri kalan her sey calisir.
have_server_stack() {
  python -c 'import fastapi, uvicorn' 2>/dev/null
}

# Uvicorn, hem tarama liderini hem mobil /signals/latest API'sini tek proseste
# baslatir. Beklenmeyen (sifirdan farkli) cikista yeniden kalkar: ilk
# denemelerde 15sn, israrli basarisizlikta 5dk.
# Sunucu katmanini BIR KEZ kurmayi dene (dongude tekrar tekrar deneme).
if ensure_core_deps && ! have_server_stack; then
  log "fastapi/uvicorn yok -> requirements-server.txt bir kez deneniyor"
  python -m pip install -r requirements-server.txt >> "$BOT_LOG" 2>&1
  if have_server_stack; then
    log "sunucu katmani kuruldu (mobil uc nokta aktif)"
  else
    log "sunucu katmani KURULAMADI -> signal_bot.py dogrudan kosacak; mobil uc nokta devre disi, Telegram komutlari ve LAN panosu CALISIR"
  fi
fi

fails=0
while [ ! -f "$STOP_FILE" ]; do
  rotate_log
  started="$(date +%s)"
  if ! ensure_core_deps; then
    code=127                      # cekirdek yok: baslatmayi hic deneme
  else
    if have_server_stack; then
      python -m uvicorn server:app --host 0.0.0.0 --port 8000 \
        >> "$BOT_LOG" 2>&1 &
    else
      python signal_bot.py >> "$BOT_LOG" 2>&1 &
    fi
    child_pid=$!
    wait "$child_pid"
    code=$?
    child_pid=""
  fi
  # Uzun sure ayakta kaldiysa bu "israrli hata" degil, tekil bir cokme:
  # sayaci sifirla ki hizli yeniden baslatma hakkini geri kazansin.
  if [ "$(( $(date +%s) - started ))" -ge 300 ]; then
    fails=0
  fi
  [ -f "$STOP_FILE" ] && break
  if [ "$code" -eq 0 ]; then
    log "uvicorn temiz kapandi; wrapper duruyor"
    break
  fi
  fails=$((fails + 1))
  # Ayni hatayla saniyede bir log doldurup 3 gun sessiz kalmayalim: 5
  # basarisiz denemeden sonra araligi 15sn -> 5dk yap ve durumu YUKSEK SESLE
  # yaz. Bot uzun sure ayaga kalkmiyorsa bunun logda goze batmasi gerekir.
  if [ "$fails" -ge 5 ]; then
    delay=300
    log "DIKKAT: $fails ardisik basarisiz baslatma (son kod=$code). Bot AYAKTA DEGIL."
  else
    delay=15
    log "uvicorn beklenmeyen cikti (kod=$code); ${delay}sn sonra denenecek"
  fi
  sleep "$delay"
done

termux-wake-unlock 2>/dev/null || true
