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
            if not shutil.which("termux-battery-status"):
                raise RuntimeError(
                    " Termux telemetry binary missing.\n"
                    " FIX: Run 'pkg install termux-api' inside Termux, "
                    "and ensure the 'Termux:API' add-on app is installed on your Android device."
                )
            try:
                result = subprocess.run(["termux-battery-status"], capture_output=True, text=True, check=True)
                data = json.loads(result.stdout)
                is_charging = data.get("status") in ("CHARGING", "FULL")
                return BatteryInfo(percentage=int(data.get("percentage", 0)), charging=is_charging)
            except Exception as e:
                raise RuntimeError(
                    f" Termux API call failed.\n"
                    f" FIX: Make sure the 'Termux:API' Android app has background permissions enabled.\n"
                    f"Details: {e}"
                )

        # Desktop fallback
        batt = psutil.sensors_battery()
        if batt is None:
            raise RuntimeError("No battery telemetry detected on this system hardware.")
        return BatteryInfo(percentage=int(batt.percent), charging=batt.power_plugged)