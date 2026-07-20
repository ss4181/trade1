#!/data/data/com.termux/files/usr/bin/sh
# Termux:Boot betigi — tablet yeniden baslayinca botu OTOMATIK baslatir.
# Kurulum adimlari: TABLET.md "Otomatik baslatma" bolumu.
#
# DIKKAT: Bu betik kuruluyken tablet acilisinda bot KENDILIGINDEN kalkar.
# Elle ikinci bir kopya BASLATMA (409 Conflict olur). Once kontrol et:
#   pgrep -af signal_bot
termux-wake-lock
cd "$HOME/trade1" || exit 1
exec python signal_bot.py >> bot.out.log 2>&1
