# 🎵 Battery Music Notifier

> Cross-platform Python app that plays your favorite tune when your battery reaches the charge level you want. Lightweight, configurable, and easy to install.

## ✨ Features
- 🔋 Cross-platform battery detection (WMI / `pmset` / ACPI)
- 🎛️ TOML config + Interactive Setup Wizard
- 🔔 Native desktop notifications
- 📢 **Annoying mode** (`--annoying`) — loop forever, ignore quiet hours
- 🌙 Quiet hours (default 22:00–08:00)

## 🚀 Quick start

```bash
# Install
pipx install battery-music-notifier

# Run the interactive setup wizard!
battery-music init

# Start monitoring
battery-music run

# Or override everything inline:
battery-music run -m ~/Music/song1.wav --min 80 --max 100 --volume 0.6

# Make me mad:
battery-music run --annoying
```

## 🏗️ Architecture
- `battery.py` — OS-specific readers behind one `Battery.read()` interface
- `player.py` — threaded, stoppable, volume-aware player
- `notifier.py` — native notifications with graceful fallback
- `monitor.py` — the loop, with quiet hours + annoying mode
- `cli.py` — argparse subcommands and interactive wizard

## 🧪 Development
```bash
git clone https://github.com/you/battery-music-notifier
cd battery-music-notifier
pip install -e ".[dev]"
pytest
```

## 📝 License
MIT
