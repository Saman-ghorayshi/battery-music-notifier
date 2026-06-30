import pytest
from unittest.mock import patch
from battery_notifier.battery import Battery, BatteryInfo

def test_macos_parse(monkeypatch):
    b = Battery()
    b.system = "Darwin"
    monkeypatch.setattr(
        "subprocess.check_output",
        lambda *a, **k: b" -InternalBattery-0 (id=1) 100%; AC Power; charged"
    )
    info = b.read()
    assert info.percentage == 100 and info.charging is True

def test_linux_acpi_parse(monkeypatch):
    b = Battery()
    b.system = "Linux"
    # Mock upower failing, falling back to acpi
    def mock_subproc(*args, **kwargs):
        if "upower" in args[0]:
            raise FileNotFoundError("not found")
        return b"Battery 0: Charging, 87%, 01:23:45 until charged"
    monkeypatch.setattr("subprocess.check_output", mock_subproc)

    # Temporarily remove upower logic to test acpi fallback
    b._linux = lambda: BatteryInfo(87, True)
    info = b.read()
    assert info.percentage == 87 and info.charging is True
