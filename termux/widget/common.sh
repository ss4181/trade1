#!/data/data/com.termux/files/usr/bin/sh

# Shared safeguards for the Trade1 Termux:Widget shortcuts.
TRADE1_DIR="${TRADE1_DIR:-$HOME/trade1}"
TRADE1_LOCK="${TMPDIR:-/data/data/com.termux/files/usr/tmp}/trade1-widget-operation.lock"

widget_error() {
  printf 'Trade1: %s\n' "$1" >&2
  exit "${2:-1}"
}

widget_begin() {
  [ -d "$TRADE1_DIR/.git" ] || widget_error "Proje bulunamadi: $TRADE1_DIR"
  cd "$TRADE1_DIR" || widget_error "Proje klasorune girilemedi."
  if ! mkdir "$TRADE1_LOCK" 2>/dev/null; then
    widget_error "Baska bir Trade1 widget islemi suruyor. Bitmesini bekle."
  fi
  trap 'rmdir "$TRADE1_LOCK" 2>/dev/null || true' EXIT
  trap 'exit 1' HUP INT TERM
}

widget_owned_processes() {
  for proc in /proc/[0-9]*; do
    [ -r "$proc/cmdline" ] || continue
    pid=${proc##*/}
    [ "$pid" = "$$" ] && continue
    cwd=$(readlink "$proc/cwd" 2>/dev/null || true)
    [ "$cwd" = "$TRADE1_DIR" ] || continue
    cmd=$(tr '\000' ' ' < "$proc/cmdline" 2>/dev/null || true)
    case "$cmd" in
      *boot-signal-bot.sh*) printf '%s wrapper\n' "$pid" ;;
      *"uvicorn server:app"*|*"uvicorn.server:app"*) printf '%s api\n' "$pid" ;;
      *signal_bot.py*) printf '%s bot\n' "$pid" ;;
    esac
  done
}

widget_stop_bot() {
  touch "$TRADE1_DIR/.stop-signal-bot" || widget_error "Durdurma isareti olusturulamadi."
  processes=$(widget_owned_processes)
  [ -n "$processes" ] || {
    printf 'Trade1 zaten calismiyor.\n'
    return 0
  }

  # Ask the boot wrapper to stop first; its trap terminates its child cleanly.
  printf '%s\n' "$processes" | while read -r pid kind; do
    [ "$kind" = wrapper ] || continue
    kill -TERM "$pid" 2>/dev/null || true
  done

  attempt=0
  while [ "$attempt" -lt 10 ]; do
    remaining=$(widget_owned_processes)
    [ -z "$remaining" ] && {
      printf 'Trade1 durduruldu.\n'
      return 0
    }
    sleep 1
    attempt=$((attempt + 1))
  done

  # The wrapper may not exist if the bot was started manually. In that case,
  # terminate only matching processes whose working directory is this repo.
  printf '%s\n' "$remaining" | while read -r pid kind; do
    [ -n "$pid" ] || continue
    kill -TERM "$pid" 2>/dev/null || true
  done
  attempt=0
  while [ "$attempt" -lt 10 ]; do
    remaining=$(widget_owned_processes)
    [ -z "$remaining" ] && {
      printf 'Trade1 durduruldu.\n'
      return 0
    }
    sleep 1
    attempt=$((attempt + 1))
  done
  printf 'Trade1 sureci kapanmadi; otomatik zorla kapatma yapilmadi.\n%s\n' "$remaining" >&2
  return 1
}

widget_start_bot() {
  processes=$(widget_owned_processes)
  [ -z "$processes" ] || widget_error "Trade1 sureci zaten var; ikinci kopya baslatilmadi."
  [ -f "$TRADE1_DIR/termux/boot-signal-bot.sh" ] || widget_error "Baslatma betigi bulunamadi."
  rm -f "$TRADE1_DIR/.stop-signal-bot"
  nohup sh "$TRADE1_DIR/termux/boot-signal-bot.sh" >/dev/null 2>&1 </dev/null &
  sleep 3
  processes=$(widget_owned_processes)
  [ -n "$processes" ] || widget_error "Bot baslamadi. Termux'ta bot.out.log dosyasini kontrol et."
  printf 'Trade1 baslatildi; ikinci kopya acilmadi. Telegram /status ile dogrula.\n'
}
