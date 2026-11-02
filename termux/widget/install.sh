#!/data/data/com.termux/files/usr/bin/sh
set -eu
TRADE1_DIR="${TRADE1_DIR:-$HOME/trade1}"
SOURCE="$TRADE1_DIR/termux/widget"
# Foreground shortcuts (~/.shortcuts) open a Termux window that shows the
# result; background tasks (~/.shortcuts/tasks) ran silently.
SHORTCUTS="$HOME/.shortcuts"
LEGACY="$SHORTCUTS/tasks"
# Backups live outside ~/.shortcuts so they never show up as widget buttons.
BACKUPS="$HOME/.trade1-shortcut-backups"

[ -d "$SOURCE" ] || { printf 'Trade1 widget dosyalari bulunamadi: %s\n' "$SOURCE" >&2; exit 1; }
mkdir -p "$SHORTCUTS"
chmod 700 "$SHORTCUTS"
stamp=$(date +%Y%m%d%H%M%S)

backup() {
  mkdir -p "$BACKUPS"
  dest="$BACKUPS/$(basename "$1").$stamp"
  mv "$1" "$dest"
  printf 'Eski kisayol yedeklendi: %s\n' "$dest"
}

install_shortcut() {
  source_file=$1
  name=$2
  target="$SHORTCUTS/$name"
  [ -e "$LEGACY/$name" ] && backup "$LEGACY/$name"
  if [ -e "$target" ] && ! cmp -s "$source_file" "$target"; then
    backup "$target"
  fi
  cp "$source_file" "$target"
  chmod 700 "$target"
}

install_shortcut "$SOURCE/widget-update" "01-Trade1-Guncelle-ve-Baslat"
install_shortcut "$SOURCE/widget-restart" "02-Trade1-Yeniden-Baslat"
install_shortcut "$SOURCE/widget-stop" "03-Trade1-Durdur"
install_shortcut "$SOURCE/widget-status" "04-Trade1-Durum"

if command -v am >/dev/null 2>&1; then
  am broadcast -n com.termux.widget/.TermuxWidgetProvider \
    -a com.termux.widget.ACTION_REFRESH_WIDGET --ei appWidgetId 0 >/dev/null 2>&1 || true
fi
printf 'Trade1 kisayollari kuruldu. Termux:Widget uygulamasinda REFRESH yap; dugmeler artik sonucu bir pencerede gosterir.\n'
