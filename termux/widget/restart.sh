#!/data/data/com.termux/files/usr/bin/sh
set -eu
. "$HOME/trade1/termux/widget/common.sh"
widget_begin
widget_stop_bot || widget_error "Eski surec durmadi; yeni kopya baslatilmadi."
widget_start_bot
