from __future__ import annotations
import platform, subprocess, re, logging
from dataclasses import dataclass

log = logging.getLogger(__name__)

@dataclass
class BatteryInfo:
    percentage: int
    charging: bool

class Battery:
    """Cross-platform battery reader."""
    def __init__(self) -> None:
        self.system = platform.system()

    def read(self) -> BatteryInfo:
        if self.system == "Windows":
            return self._windows()
        if self.system == "Darwin":
            return self._macos()
        if self.system == "Linux":
            return self._linux()
        raise RuntimeError(f"Unsupported OS: {self.system}")

    def _windows(self) -> BatteryInfo:
        import wmi
        b = wmi.WMI().Win32_Battery()[0]
        return BatteryInfo(b.EstimatedChargeRemaining, b.BatteryStatus == 2)

    def _macos(self) -> BatteryInfo:
        out = subprocess.check_output(["pmset", "-g", "batt"], text=True)
        pct = int(re.search(r"(\d+)%", out).group(1))
        return BatteryInfo(pct, "AC Power" in out)

    def _linux(self) -> BatteryInfo:
        out = subprocess.check_output(["acpi", "-b"], text=True)
        pct = int(re.search(r"(\d+)%", out).group(1))
        return BatteryInfo(pct, "Charging" in out)
