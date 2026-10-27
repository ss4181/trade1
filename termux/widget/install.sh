#!/data/data/com.termux/files/usr/bin/sh
set -eu
TRADE1_DIR="${TRADE1_DIR:-$HOME/trade1}"
SOURCE="$TRADE1_DIR/termux/widget"
SHORTCUTS="$HOME/.shortcuts/tasks"

[ -d "$SOURCE" ] || { printf 'Trade1 widget dosyalari bulunamadi: %s\n' "$SOURCE" >&2; exit 1; }
mkdir -p "$SHORTCUTS"
chmod 700 "$HOME/.shortcuts" "$SHORTCUTS"

install_shortcut() {
  source_file=$1
  target=$2
  if [ -e "$target" ] && ! cmp -s "$source_file" "$target"; then
    backup="$target.backup.$(date +%Y%m%d%H%M%S)"
    cp -p "$target" "$backup"
    printf 'Mevcut kisayol yedeklendi: %s\n' "$backup"
  fi
  cp "$source_file" "$target"
  chmod 700 "$target"
}

install_shortcut "$SOURCE/widget-update" "$SHORTCUTS/01-Trade1-Guncelle-ve-Baslat"
install_shortcut "$SOURCE/widget-restart" "$SHORTCUTS/02-Trade1-Yeniden-Baslat"
install_shortcut "$SOURCE/widget-stop" "$SHORTCUTS/03-Trade1-Durdur"
install_shortcut "$SOURCE/widget-status" "$SHORTCUTS/04-Trade1-Durum"

if command -v am >/dev/null 2>&1; then
  am broadcast -n com.termux.widget/.TermuxWidgetProvider \
    -a com.termux.widget.ACTION_REFRESH_WIDGET --ei appWidgetId 0 >/dev/null 2>&1 || true
fi
printf 'Trade1 kisayollari kuruldu. Termux:Widget uygulamasinda REFRESH yapip ana ekrana widget ekle.\n'
