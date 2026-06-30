import pytest
from typing import NamedTuple
from battery_notifier.battery import Battery
from battery_notifier.remote import NotificationServer, RemoteMonitor
from battery_notifier.config import Config
from battery_notifier.battery import BatteryInfo

# =====================================================================
# 1. LOCAL TELEMETRY TESTS
# =====================================================================

class MockBattery(NamedTuple):
    percent: float
    power_plugged: bool
    secsleft: int

def test_psutil_battery_reading(monkeypatch):
    """Verify local psutil battery abstraction reads data correctly."""
    monkeypatch.setattr(
        "psutil.sensors_battery",
        lambda: MockBattery(percent=85.0, power_plugged=True, secsleft=-2)
    )
    
    b = Battery()
    info = b.read()
    
    assert info.percentage == 85
    assert info.charging is True


# =====================================================================
# 2. DISTRIBUTED NETWORK & SOCKET TESTS
# =====================================================================

def test_remote_monitor_triggers_start_signal(mocker):
    """Verify that the client sends a 'START' signal when charging triggers match."""
    cfg = Config(min_percentage=90, max_percentage=100, poll_interval=0.01)
    monitor = RemoteMonitor(cfg)
    
    mocker.patch.object(monitor.battery, 'read', return_value=BatteryInfo(percentage=95, charging=True))
    mock_send = mocker.patch.object(monitor, '_send_signal', return_value=True)
    mocker.patch('time.sleep', side_effect=KeyboardInterrupt)

    try:
        monitor.run()
    except KeyboardInterrupt:
        pass 

    mock_send.assert_any_call("START")


def test_server_dispatches_web_alerts_safely(mocker):
    """Verify that the server async alert worker fires web hooks safely."""
    cfg = Config(
        telegram_token="12345:fake_token", 
        telegram_chat_id="67890",
        email_sender="sender@test.com",
        email_receiver="receiver@test.com",
        email_password="super_secret_password"
    )
    server = NotificationServer(cfg)
    
    mocker.patch('socket.create_connection')
    mock_urlopen = mocker.patch('urllib.request.urlopen')
    mock_smtp = mocker.patch('smtplib.SMTP')

    server._dispatch_web_alerts()

    mock_urlopen.assert_called_once()
    mock_smtp.assert_called_once()