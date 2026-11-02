#!/data/data/com.termux/files/usr/bin/sh
# Foreground shortcuts open a Termux window; keep it until Enter so the
# result (or the reason an update stopped) can actually be read.
set -u
sh "$HOME/trade1/termux/widget/$1"
code=$?
if [ "$code" -eq 0 ]; then
  printf '\nTAMAM. Kapatmak icin Enter.\n'
else
  printf '\nHATA (kod %s): yukaridaki mesaji oku. Kapatmak icin Enter.\n' "$code"
fi
read -r _ || true
exit "$code"
