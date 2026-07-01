import pytest
import socket
from unittest.mock import MagicMock, patch
from battery_notifier.config import Config
from battery_notifier.remote import (
    RemoteMonitor,
    NotificationServer,
    send_notification,
    discover_server_ip,
    BEACON_MESSAGE
)

@pytest.fixture
def mock_config():
    """Generates a standard test configuration profile with mock boundaries."""
    cfg = Config()
    cfg.music_files = ["test_track.mp3"]
    cfg.min_percentage = 20
    cfg.max_percentage = 80
    cfg.volume = 0.5
    cfg.annoying = False
    cfg.poll_interval = 0.1
    return cfg

def test_notification_server_initialization(mock_config):
    """Verify that NotificationServer constructor arguments map perfectly to prevent AttributeError."""
    server = NotificationServer(mock_config, "0.0.0.0", 8000)
    assert server.cfg == mock_config
    assert server.host == "0.0.0.0"
    assert server.port == 8000
    assert server.player is not None

def test_remote_monitor_initialization(mock_config):
    """Verify that RemoteMonitor constructor arguments match NotificationServer's schema mapping."""
    monitor = RemoteMonitor(mock_config, "127.0.0.1", 8000)
    assert monitor.cfg == mock_config
    assert monitor.host == "127.0.0.1"
    assert monitor.port == 8000
    assert monitor.resolved_host is None

@patch("socket.socket")
def test_send_notification_success(mock_socket_class):
    """Test that send_notification successfully establishes a connection and writes commands."""
    mock_socket_instance = MagicMock()
    mock_socket_class.return_value.__enter__.return_value = mock_socket_instance

    success = send_notification("127.0.0.1", 8000, "START")
    
    assert success is True
    mock_socket_instance.connect.assert_called_with(("127.0.0.1", 8000))
    mock_socket_instance.sendall.assert_called_with(b"START")

@patch("socket.socket")
def test_send_notification_failure(mock_socket_class):
    """Verify send_notification fails gracefully and safely returns False on connection errors."""
    mock_socket_instance = MagicMock()
    mock_socket_instance.connect.side_effect = socket.error("Connection Refused")
    mock_socket_class.return_value.__enter__.return_value = mock_socket_instance

    success = send_notification("127.0.0.1", 8000, "START")
    assert success is False

@patch("socket.socket")
def test_discover_server_ip_success(mock_socket_class):
    """Verify UDP auto-discovery correctly captures the broadcast sender's IP."""
    mock_socket_instance = MagicMock()
    mock_socket_instance.recvfrom.return_value = (BEACON_MESSAGE, ("192.168.1.15", 8002))
    mock_socket_class.return_value.__enter__.return_value = mock_socket_instance

    detected_ip = discover_server_ip(timeout=1.0)
    assert detected_ip == "192.168.1.15"

@patch("socket.socket")
def test_discover_server_ip_timeout(mock_socket_class):
    """Verify auto-discovery handles network timeouts smoothly and returns None."""
    mock_socket_instance = MagicMock()
    mock_socket_instance.recvfrom.side_effect = socket.timeout
    mock_socket_class.return_value.__enter__.return_value = mock_socket_instance

    detected_ip = discover_server_ip(timeout=0.1)
    assert detected_ip is None

@patch("time.sleep")
@patch("battery_notifier.battery.Battery.read")
@patch("battery_notifier.remote.send_notification")
def test_remote_monitor_loop_symmetrical_charging_alert(mock_send, mock_read, mock_sleep, mock_config):
    """Verify that the client triggers a START signal when battery is charging and crosses max threshold."""
    from battery_notifier.battery import BatteryInfo
    
    # Mock battery reading: 85% and charging (exceeds max_percentage=80)
    mock_read.return_value = BatteryInfo(percentage=85, charging=True)
    mock_send.return_value = True

    monitor = RemoteMonitor(mock_config, "127.0.0.1", 8000)
    monitor.resolved_host = "127.0.0.1"

    # When the loop finishes its first pass and calls time.sleep, we flip the stop switch
    mock_sleep.side_effect = lambda x: monitor._stop_event.set()

    monitor.run()

    # Verify the tracking loop detected the boundary breach and sent the alert
    mock_send.assert_called_with("127.0.0.1", 8000, "START")

@patch("time.sleep")
@patch("battery_notifier.battery.Battery.read")
@patch("battery_notifier.remote.send_notification")
def test_remote_monitor_loop_symmetrical_discharging_alert(mock_send, mock_read, mock_sleep, mock_config):
    """Verify that the client triggers a START signal when battery is discharging and drops under min threshold."""
    from battery_notifier.battery import BatteryInfo
    
    # Mock battery reading: 15% and discharging (below min_percentage=20)
    mock_read.return_value = BatteryInfo(percentage=15, charging=False)
    mock_send.return_value = True

    monitor = RemoteMonitor(mock_config, "127.0.0.1", 8000)
    monitor.resolved_host = "127.0.0.1"

    mock_sleep.side_effect = lambda x: monitor._stop_event.set()

    monitor.run()

    mock_send.assert_called_with("127.0.0.1", 8000, "START")

@patch("time.sleep")
@patch("battery_notifier.battery.Battery.read")
@patch("battery_notifier.remote.send_notification")
def test_remote_monitor_loop_no_alert_when_safe(mock_send, mock_read, mock_sleep, mock_config):
    """Verify that no signals are sent when battery levels reside safely within thresholds."""
    from battery_notifier.battery import BatteryInfo
    
    # Safe range: 50% battery
    mock_read.return_value = BatteryInfo(percentage=50, charging=True)

    monitor = RemoteMonitor(mock_config, "127.0.0.1", 8000)
    monitor.resolved_host = "127.0.0.1"

    mock_sleep.side_effect = lambda x: monitor._stop_event.set()

    monitor.run()

    # Ensure no network signals were dispatched
    mock_send.assert_not_called()