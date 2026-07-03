"""Cross-platform auto-start configuration."""
from __future__ import annotations
import os, platform, logging
from pathlib import Path

log = logging.getLogger(__name__)

APP_NAME = "Battery Music Notifier"


def _is_windows() -> bool:
    return platform.system() == "Windows"


def _is_macos() -> bool:
    return platform.system() == "Darwin"


def _get_startup_path() -> Path:
    """Return the platform-specific startup file path."""
    if _is_windows():
        # Windows: shell:startup folder
        startup = Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
        return startup / "battery-music-notifier.vbs"
    elif _is_macos():
        # macOS: LaunchAgent plist in ~/Library/LaunchAgents/
        return Path.home() / "Library" / "LaunchAgents" / "com.battery-music-notifier.plist"
    else:
        # Linux: XDG autostart
        autostart = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "autostart"
        return autostart / "battery-music-notifier.desktop"


def enable_autostart() -> bool:
    """Enable auto-start on boot. Returns True on success."""
    try:
        path = _get_startup_path()
        path.parent.mkdir(parents=True, exist_ok=True)

        if _is_windows():
            # VBS script — runs hidden, no command window popup
            import sys
            exe = _find_exe()
            if not exe:
                log.error("Could not find battery-music executable for autostart.")
                return False
            # Check if running as a frozen PyInstaller app
            if getattr(sys, 'frozen', False):
                cmd = f'"{exe}" run'
            else:
                # Use pythonw to avoid console window, fallback to python
                pythonw = Path(exe).parent / "pythonw.exe"
                python = pythonw if pythonw.exists() else exe
                cmd = f'"{python}" -m battery_notifier run'
            path.write_text(
                f'Set ws = CreateObject("WScript.Shell")\n'
                f'ws.Run "{cmd}", 0, False\n',
                encoding="utf-8",
            )
        elif _is_macos():
            # macOS: LaunchAgent plist
            import sys
            exe = _find_exe()
            if not exe:
                log.error("Could not find battery-music executable for autostart.")
                return False
            if getattr(sys, 'frozen', False):
                program_args = f"<string>{exe}</string><string>run</string>"
            else:
                program_args = f"<string>{exe}</string><string>-m</string><string>battery_notifier</string><string>run</string>"
            path.write_text(
                f'<?xml version="1.0" encoding="UTF-8"?>\n'
                f'<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
                f'"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
                f'<plist version="1.0">\n'
                f'<dict>\n'
                f'  <key>Label</key>\n'
                f'  <string>com.battery-music-notifier</string>\n'
                f'  <key>ProgramArguments</key>\n'
                f'  <array>\n'
                f'    {program_args}\n'
                f'  </array>\n'
                f'  <key>RunAtLoad</key>\n'
                f'  <true/>\n'
                f'  <key>KeepAlive</key>\n'
                f'  <false/>\n'
                f'</dict>\n'
                f'</plist>\n',
                encoding="utf-8",
            )
        else:
            # Linux: .desktop file
            import sys
            exe = _find_exe() or "battery-music"
            # Add -m flag for non-frozen Python (frozen PyInstaller exe takes "run" directly)
            if getattr(sys, 'frozen', False):
                exec_line = f"Exec={exe} run"
            else:
                exec_line = f'Exec={exe} -m battery_notifier run'
            path.write_text(
                f"[Desktop Entry]\n"
                f"Type=Application\n"
                f"Name={APP_NAME}\n"
                f"{exec_line}\n"
                f"Comment=Play music when battery reaches target\n"
                f"Terminal=false\n"
                f"StartupNotify=false\n",
                encoding="utf-8",
            )
        log.info("Autostart enabled: %s", path)
        return True
    except Exception as e:
        log.error("Failed to enable autostart: %s", e)
        return False


def disable_autostart() -> bool:
    """Disable auto-start on boot. Returns True on success."""
    try:
        path = _get_startup_path()
        if path.exists():
            path.unlink()
            log.info("Autostart disabled: %s", path)
        return True
    except Exception as e:
        log.error("Failed to disable autostart: %s", e)
        return False


def is_autostart_enabled() -> bool:
    """Check if auto-start is currently enabled."""
    return _get_startup_path().exists()


def _find_exe() -> str | None:
    """Find the python executable path."""
    import sys
    return sys.executable
