import pytest
from typing import NamedTuple  
from battery_notifier.battery import Battery

# Mock structure mimicking psutil return values
class MockBattery(NamedTuple):
    percent: float
    power_plugged: bool
    secsleft: int

def test_psutil_battery_reading(monkeypatch):
    # Setup mock telemetry values: 85% charge, currently plugged in
    monkeypatch.setattr(
        "psutil.sensors_battery",
        lambda: MockBattery(percent=85.0, power_plugged=True, secsleft=-2)
    )
    
    b = Battery()
    info = b.read()
    
    assert info.percentage == 85
    assert info.charging is True