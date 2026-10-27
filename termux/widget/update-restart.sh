#!/data/data/com.termux/files/usr/bin/sh
set -eu
. "$HOME/trade1/termux/widget/common.sh"
widget_begin

branch=$(git branch --show-current)
[ "$branch" = main ] || widget_error "Dal main degil ('$branch'); hicbir sey degistirilmedi."

changes=$(git status --porcelain --untracked-files=normal)
[ -z "$changes" ] || {
  printf 'Trade1 dosyalarinda korunmasi gereken yerel degisiklik var; guncelleme durduruldu.\n%s\n' "$changes" >&2
  widget_error "Degisiklikleri kaybetmemek icin elle incele; otomatik temizleme yapilmadi."
}

GIT_TERMINAL_PROMPT=0 git fetch --quiet origin main || widget_error "GitHub erisimi basarisiz; bot calismaya devam ediyor. Termux'ta git pull erisimini duzelt."
git merge-base --is-ancestor HEAD origin/main || widget_error "Yerel dal uzak main ile ayrismis; bot calismaya devam ediyor."
local_head=$(git rev-parse HEAD)
remote_head=$(git rev-parse origin/main)
[ "$local_head" != "$remote_head" ] || {
  processes=$(widget_owned_processes)
  if [ -n "$processes" ]; then
    printf 'Trade1 zaten guncel ve calisiyor; yeniden baslatilmadi.\n'
  else
    printf 'Trade1 zaten guncel; calismadigi icin baslatiliyor...\n'
    widget_start_bot
  fi
  exit 0
}

printf 'Yeni surum bulundu. Bot guvenli sekilde durduruluyor...\n'
widget_stop_bot || widget_error "Bot durdurulamadi; guncelleme uygulanmadi."

if ! git merge --ff-only origin/main; then
  widget_error "Fast-forward guncellemesi basarisiz. Bot duruyor; dosyalar korunuyor. Elle incele."
fi

if ! python -m py_compile signal_bot.py signal_watch.py; then
  widget_error "Kod kontrolu basarisiz; bot yeniden baslatilmadi. Termux'ta hatayi incele."
fi
policy=$(python -c 'import signal_watch; print(signal_watch.CRITICAL_POLICY)' 2>/dev/null) ||
  widget_error "Bildirim politikasi dogrulanamadi; bot yeniden baslatilmadi."
[ -n "$policy" ] || widget_error "Bildirim politikasi bos; bot yeniden baslatilmadi."

widget_start_bot
printf 'Guncelleme tamamlandi: %s | %s\n' "$(git rev-parse --short HEAD)" "$policy"
