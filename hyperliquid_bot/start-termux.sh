#!/data/data/com.termux/files/usr/bin/sh
# Independent from ~/trade1. Run once; Python enforces one leader.
cd "$(dirname "$0")" || exit 1
BOT_DIR="$(pwd)"
PYTHON="python"
if [ -x "$BOT_DIR/.venv/bin/python" ]; then
    PYTHON="$BOT_DIR/.venv/bin/python"
fi
termux-wake-lock 2>/dev/null || true
exec "$PYTHON" -u "$BOT_DIR/bot.py" run
