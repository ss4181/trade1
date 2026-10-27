#!/data/data/com.termux/files/usr/bin/sh
set -eu
. "$HOME/trade1/termux/widget/common.sh"
widget_begin
processes=$(widget_owned_processes)
if [ -n "$processes" ]; then
  printf 'Trade1 calisiyor:\n%s\n' "$processes"
else
  printf 'Trade1 su anda calismiyor.\n'
fi
printf 'Surum: %s\n' "$(git rev-parse --short HEAD 2>/dev/null || echo bilinmiyor)"
if [ -f "$TRADE1_DIR/.stop-signal-bot" ]; then
  printf 'Durdurma isareti: var\n'
else
  printf 'Durdurma isareti: yok\n'
fi
