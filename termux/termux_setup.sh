#!/data/data/com.termux/files/usr/bin/bash
# Battery Music Notifier -- Termux one-line installer
#
#   curl -sSL <raw-url>/termux/termux_setup.sh | bash
#
# Installs pkg deps + the app, writes a default config non-interactively,
# installs Termux:Widget home-screen buttons, and prints wake-lock hints.
set -euo pipefail

REPO_RAW="${BATTERY_REPO_RAW:-https://raw.githubusercontent.com/Saman-ghorayshi/battery-music-notifier/main}"

say() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }

say "Installing pkg dependencies"
pkg update -y >/dev/null 2>&1 || true
pkg install -y python git libsndfile termux-api

say "Installing battery-music-notifier"
pip install --upgrade pip
pip install "sounddevice soundfile" 2>/dev/null || true
pip install "git+${REPO_RAW%/termux/termux_setup.sh}" 2>/dev/null \
  || pip install "git+https://github.com/Saman-ghorayshi/battery-music-notifier.git"

say "Writing default config"
APP_DIR="$HOME/.config/battery-music-notifier"
mkdir -p "$APP_DIR"
if [ ! -f "$APP_DIR/config.toml" ]; then
  cat > "$APP_DIR/config.toml" <<'TOML'
[battery_notifier]
music_files = []
min_percentage = 20
max_percentage = 100
volume = 0.8
poll_interval = 10.0
annoying = false
quiet_hours = [22, 8]
proxy_url = ""
worker_url = ""
worker_token = ""
alarm_files = []
socket_secret = ""
TOML
  echo "  Config written. Run 'battery-music init' later to customize,"
  echo "  or edit $APP_DIR/config.toml directly."
else
  echo "  Existing config kept."
fi

say "Installing Termux:Widget home-screen buttons"
mkdir -p "$HOME/.shortcuts" "$HOME/.shortcuts/tasks"
curl -sSL "$REPO_RAW/termux/shortcuts/start-monitor.sh" -o "$HOME/.shortcuts/Start Monitor"
curl -sSL "$REPO_RAW/termux/shortcuts/arm-thief.sh"    -o "$HOME/.shortcuts/Arm Thief"
chmod +x "$HOME/.shortcuts/"*

say "Done!"
cat <<'EOF'

Next steps:
  1. Open Termux and run:      battery-music init     (choose relay defaults)
  2. IMPORTANT (Android kills background apps):
       termux-wake-lock
     or enable a Termux boot script / acquire wake-lock in your shortcut.
  3. Install "Termux:Widget" (F-Droid), then use its widget:
     "Start Monitor" and "Arm Thief" buttons appear on your home screen.
EOF