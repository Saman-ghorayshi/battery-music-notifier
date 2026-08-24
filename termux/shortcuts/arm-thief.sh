#!/data/data/com.termux/files/usr/bin/bash
# Termux:Widget shortcut -- arm the thief catcher.
# Sends THIEF_ALERT to the worker when the charger is unplugged.
termux-wake-lock 2>/dev/null || true
exec battery-music arm --mode both 2>&1
