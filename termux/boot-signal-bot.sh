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

# Uvicorn, hem tarama liderini hem mobil /signals/latest API'sini tek proseste
# baslatir. Beklenmeyen (sifirdan farkli) cikista 15 saniye sonra yeniden kalkar.
while [ ! -f "$STOP_FILE" ]; do
  rotate_log
  python -m uvicorn server:app --host 0.0.0.0 --port 8000 \
    >> "$BOT_LOG" 2>&1 &
  child_pid=$!
  wait "$child_pid"
  code=$?
  child_pid=""
  [ -f "$STOP_FILE" ] && break
  if [ "$code" -eq 0 ]; then
    printf '%s uvicorn temiz kapandi; wrapper duruyor\n' \
      "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$BOT_LOG"
    break
  fi
  printf '%s uvicorn beklenmeyen cikti (kod=%s); 15sn sonra denenecek\n' \
    "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$code" >> "$BOT_LOG"
  sleep 15
done

termux-wake-unlock 2>/dev/null || true
