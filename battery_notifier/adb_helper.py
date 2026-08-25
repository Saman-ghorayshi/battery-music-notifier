from __future__ import annotations
import os
import shutil
import subprocess
import time
import logging
from pathlib import Path

log = logging.getLogger(__name__)

def find_adb_executable() -> str | None:
    """Search system PATH and common platform installations for the adb binary."""
    # 1. Search system PATH
    adb_path = shutil.which("adb")
    if adb_path:
        return adb_path

    # 2. Check common platform-specific default directories
    home = Path.expanduser(Path("~"))
    potential_paths = []

    if os.name == "nt":  # Windows
        localappdata = Path(os.environ.get("LOCALAPPDATA", home / "AppData" / "Local"))
        potential_paths.extend([
            localappdata / "Android" / "Sdk" / "platform-tools" / "adb.exe",
            Path("C:/Program Files/Android/Android Studio/bin/adb.exe"),
            Path("C:/Android/platform-tools/adb.exe"),
            Path("C:/platform-tools/adb.exe"),
        ])
    else:  # macOS / Linux
        potential_paths.extend([
            home / "Library" / "Android" / "sdk" / "platform-tools" / "adb",
            Path("/usr/bin/adb"),
            Path("/usr/local/bin/adb"),
            Path("/opt/android-sdk/platform-tools/adb"),
        ])

    for path in potential_paths:
        if path.exists():
            return str(path)

    return None


def auto_setup_usb_bridge(mode: str = "reverse", port: int = 8000, max_retries: int = 15) -> bool:
    """
    Scans for an authorized USB device and automatically configures
    the requested ADB tunnel (reverse or forward).
    """
    adb = find_adb_executable()
    if not adb:
        log.warning("ADB executable not found. Automatic USB tunneling skipped.")
        print("  Tip: Install Android Platform Tools (ADB) or add it to your system PATH for auto-connection.")
        return False

    print("  Listening for USB device connection... Please plug in your phone.")
    
    # Force start the local adb server (bounded: adb start-server can hang
    # indefinitely when the adb server itself is wedged)
    try:
        from .proc_safe import bounded_run, run_ok
        run_ok([adb, "start-server"], timeout=10)
    except Exception:
        pass

    for attempt in range(1, max_retries + 1):
        try:
            # Check for authorized devices
            out = bounded_run([adb, "devices"], timeout=10)
            lines = out.strip().split("\n")[1:] if out else []  # Skip header line
            
            devices = []
            unauthorized_found = False
            
            for line in lines:
                if not line.strip():
                    continue
                parts = line.split()
                if len(parts) >= 2:
                    serial, status = parts[0], parts[1]
                    if status == "device":
                        devices.append(serial)
                    elif status == "unauthorized":
                        unauthorized_found = True

            if devices:
                target_device = devices[0]
                print(f"  Found authorized USB device: {target_device}")
                
                # Apply the requested bridge
                if mode == "reverse":
                    cmd = [adb, "-s", target_device, "reverse", f"tcp:{port}", f"tcp:{port}"]
                    action_name = "Reverse Port Tunnel"
                else:
                    cmd = [adb, "-s", target_device, "forward", f"tcp:{port}", f"tcp:{port}"]
                    action_name = "Forward Port Tunnel"

                if not run_ok(cmd, timeout=15):
                    raise RuntimeError(f"{action_name} command failed")
                print(f"  {action_name} successfully set up over USB on port {port}!")
                log.info("ADB Auto-Bridge %s set up successfully.", mode)
                return True
                
            if unauthorized_found:
                print(f"  [WARN] Device detected but UNAUTHORIZED! Please unlock your phone and tap 'Allow USB Debugging'. [Attempt {attempt}/{max_retries}]")
            else:
                print(f"  Waiting for phone to connect via USB... [Attempt {attempt}/{max_retries}]")

        except Exception as e:
            log.debug("ADB check failed during attempt %d: %s", attempt, e)

        time.sleep(2)

    print("  [ERROR] Auto-connection timed out. Please plug in your phone, turn on USB Debugging, and try again.")
    return False
