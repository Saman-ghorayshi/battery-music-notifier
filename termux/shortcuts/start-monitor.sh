#!/data/data/com.termux/files/usr/bin/bash
# Termux:Widget shortcut -- start the battery monitor client.
termux-wake-lock 2>/dev/null || true
exec battery-music start 2>&1
