"""Cross-platform auto-start configuration."""
from __future__ import annotations
import os, platform, logging
from pathlib import Path

log = logging.getLogger(__name__)

APP_NAME = "Battery Music Notifier"


def _is_windows() -> bool:
    return platform.system() == "Windows"


def _get_startup_path() -> Path:
    """Return the platform-specific startup file path."""
    if _is_windows():
        # Windows: shell:startup folder
        startup = Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
        return startup / "battery-music-notifier.vbs"
    else:
        # Linux/macOS: XDG autostart
        autostart = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "autostart"
        return autostart / "battery-music-notifier.desktop"


def enable_autostart() -> bool:
    """Enable auto-start on boot. Returns True on success."""
    try:
        path = _get_startup_path()
        path.parent.mkdir(parents=True, exist_ok=True)

        if _is_windows():
            # VBS script — runs hidden, no command window popup
            exe = _find_exe()
            if not exe:
                log.error("Could not find battery-music executable for autostart.")
                return False
            # Use pythonw to avoid console window, fallback to python
            pythonw = Path(exe).parent / "pythonw.exe"
            python = pythonw if pythonw.exists() else exe
            path.write_text(
                f'Set ws = CreateObject("WScript.Shell")\n'
                f'ws.Run """{python}"" -m battery_notifier run", 0, False\n',
                encoding="utf-8",
            )
        else:
            # .desktop file for Linux/macOS
            exe = _find_exe() or "battery-music"
            path.write_text(
                f"[Desktop Entry]\n"
                f"Type=Application\n"
                f"Name={APP_NAME}\n"
                f"Exec={exe} run\n"
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
