from __future__ import annotations
import os
import shutil
import subprocess
import json
import psutil
from dataclasses import dataclass

@dataclass
class BatteryInfo:
    percentage: int
    charging: bool

class Battery:
    """Robust cross-platform battery reader supporting Desktop OS and Android Termux."""
    def read(self) -> BatteryInfo:
        # Check if running inside Termux on Android
        if "TERMUX_VERSION" in os.environ or shutil.which("termux-battery-status"):
            try:
                result = subprocess.run(["termux-battery-status"], capture_output=True, text=True, check=True)
                data = json.loads(result.stdout)
                # 'status' returns 'CHARGING', 'DISCHARGING', 'FULL', etc.
                is_charging = data.get("status") in ("CHARGING", "FULL")
                return BatteryInfo(percentage=int(data.get("percentage", 0)), charging=is_charging)
            except Exception as e:
                raise RuntimeError(f"Termux API execution failed. Did you run 'pkg install termux-api'? Error: {e}")

        # Desktop fallback (Windows, macOS, Desktop Linux)
        batt = psutil.sensors_battery()
        if batt is None:
            raise RuntimeError("No battery telemetry detected on this system hardware.")
        return BatteryInfo(percentage=int(batt.percent), charging=batt.power_plugged)