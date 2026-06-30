from __future__ import annotations
import psutil
from dataclasses import dataclass

@dataclass
class BatteryInfo:
    percentage: int
    charging: bool

class Battery:
    """Robust cross-platform battery reader using native OS APIs via psutil."""
    def read(self) -> BatteryInfo:
        batt = psutil.sensors_battery()
        if batt is None:
            raise RuntimeError("No battery detected on this system hardware.")
        
        return BatteryInfo(percentage=int(batt.percent), charging=batt.power_plugged)