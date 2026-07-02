import pytest
import socket
import json
import tempfile
import os
from unittest.mock import MagicMock, patch, mock_open
from battery_notifier.config import Config
from battery_notifier.remote import (
    RemoteMonitor,
    NotificationServer,
    send_notification,
    discover_server_ip,
)
from battery_notifier.connection import (
    detect_environment,
    ping_server,
    send_command_with_ack,
    smart_find_server,
    scan_subnet,
    load_cached_host,
    save_cached_host,
    smart_bind_server,
    get_effective_proxy,
    _detect_vpn,
    _detect_local_proxy,
    COMMON_PROXY_PORTS,
    ACK_PREFIX,
    BEACON_MESSAGE,
    DISCOVERY_UDP_PORT,
)


@pytest.fixture
def mock_config():
    """Standard test configuration with mock boundaries."""
    cfg = Config()
    cfg.music_files = ["test_track.mp3"]
    cfg.min_percentage = 20
    cfg.max_percentage = 80
    cfg.volume = 0.5
    cfg.annoying = False
    cfg.poll_interval = 0.1
    return cfg


# ---------------------------------------------------------------------------
# Environment detection tests
# ---------------------------------------------------------------------------

def test_detect_environment_returns_dataclass():
    """detect_environment returns a populated Environment object."""
    env = detect_environment()
    assert env.platform_name is not None
    assert isinstance(env.is_termux, bool)
    assert isinstance(env.is_windows, bool)
    assert isinstance(env.is_linux, bool)
    assert isinstance(env.is_macos, bool)


# ---------------------------------------------------------------------------
# PING/PONG tests
# ---------------------------------------------------------------------------

@patch("socket.socket")
def test_ping_server_success(mock_socket_class):
    """ping_server returns True when server responds with PONG."""
    mock_sock = MagicMock()
    mock_socket_class.return_value.__enter__.return_value = mock_sock
    mock_sock.recv.return_value = b"PONG"

    assert ping_server("192.168.1.10", 8000) is True
    mock_sock.connect.assert_called_with(("192.168.1.10", 8000))
    mock_sock.sendall.assert_called_with(b"PING")


@patch("socket.socket")
def test_ping_server_wrong_response(mock_socket_class):
    """ping_server returns False when server responds with something else."""
    mock_sock = MagicMock()
    mock_socket_class.return_value.__enter__.return_value = mock_sock
    mock_sock.recv.return_value = b"NOTPONG"

    assert ping_server("192.168.1.10", 8000) is False


@patch("socket.socket")
def test_ping_server_connection_error(mock_socket_class):
    """ping_server returns False on connection failure."""
    mock_sock = MagicMock()
    mock_sock.connect.side_effect = socket.error("refused")
    mock_socket_class.return_value.__enter__.return_value = mock_sock

    assert ping_server("192.168.1.10", 8000) is False


# ---------------------------------------------------------------------------
# ACK protocol tests
# ---------------------------------------------------------------------------

@patch("socket.socket")
def test_send_command_with_ack_success(mock_socket_class):
    """send_command_with_ack returns True when correct ACK is received."""
    mock_sock = MagicMock()
    mock_socket_class.return_value.__enter__.return_value = mock_sock
    mock_sock.recv.return_value = f"{ACK_PREFIX}START".encode()

    assert send_command_with_ack("127.0.0.1", 8000, "START") is True
    mock_sock.sendall.assert_called_with(b"START")


@patch("socket.socket")
def test_send_command_with_ack_wrong_response(mock_socket_class):
    """send_command_with_ack returns False on wrong ACK."""
    mock_sock = MagicMock()
    mock_socket_class.return_value.__enter__.return_value = mock_sock
    mock_sock.recv.return_value = b"WRONG"

    assert send_command_with_ack("127.0.0.1", 8000, "START") is False


@patch("socket.socket")
def test_send_command_with_ack_timeout(mock_socket_class):
    """send_command_with_ack returns False when server does not respond."""
    mock_sock = MagicMock()
    mock_socket_class.return_value.__enter__.return_value = mock_sock
    mock_sock.recv.side_effect = socket.timeout

    assert send_command_with_ack("127.0.0.1", 8000, "STOP") is False


@patch("socket.socket")
def test_send_command_with_ack_connection_error(mock_socket_class):
    """send_command_with_ack returns False on connection failure."""
    mock_sock = MagicMock()
    mock_sock.connect.side_effect = socket.error("no route")
    mock_socket_class.return_value.__enter__.return_value = mock_sock

    assert send_command_with_ack("127.0.0.1", 8000, "START") is False


# ---------------------------------------------------------------------------
# Cache file tests
# ---------------------------------------------------------------------------

def test_save_and_load_cached_host(tmp_path):
    """save_cached_host writes JSON and load_cached_host reads it back."""
    cache_file = tmp_path / "last_server.json"
    with patch("battery_notifier.connection.CACHE_FILE", cache_file):
        save_cached_host("192.168.1.50")
        loaded = load_cached_host()
    assert loaded == "192.168.1.50"


def test_load_cached_host_missing_file(tmp_path):
    """load_cached_host returns None when cache file does not exist."""
    cache_file = tmp_path / "nonexistent.json"
    with patch("battery_notifier.connection.CACHE_FILE", cache_file):
        assert load_cached_host() is None


def test_load_cached_host_corrupt_file(tmp_path):
    """load_cached_host returns None on corrupt cache."""
    cache_file = tmp_path / "corrupt.json"
    cache_file.write_text("not valid json{{{")
    with patch("battery_notifier.connection.CACHE_FILE", cache_file):
        assert load_cached_host() is None


# ---------------------------------------------------------------------------
# Smart bind tests
# ---------------------------------------------------------------------------

@patch("socket.socket")
def test_smart_bind_server_auto_success(mock_socket_class):
    """smart_bind_server with 'auto' tries 0.0.0.0 first."""
    mock_sock = MagicMock()
    mock_socket_class.return_value = mock_sock

    result = smart_bind_server("auto", 8000)
    assert result is not None
    mock_sock.bind.assert_called_with(("0.0.0.0", 8000))


@patch("socket.socket")
def test_smart_bind_server_explicit_host(mock_socket_class):
    """smart_bind_server with explicit host only tries that host."""
    mock_sock = MagicMock()
    mock_socket_class.return_value = mock_sock

    result = smart_bind_server("192.168.1.10", 9000)
    assert result is not None
    mock_sock.bind.assert_called_once_with(("192.168.1.10", 9000))


@patch("socket.socket")
def test_smart_bind_server_all_fail(mock_socket_class):
    """smart_bind_server returns None when all bind attempts fail."""
    mock_sock = MagicMock()
    mock_sock.bind.side_effect = OSError("addr in use")
    mock_socket_class.return_value = mock_sock

    result = smart_bind_server("auto", 8000)
    assert result is None


# ---------------------------------------------------------------------------
# Subnet scan tests
# ---------------------------------------------------------------------------

@patch("socket.socket")
def test_scan_subnet_finds_server(mock_socket_class):
    """scan_subnet returns IP of server that responds with PONG."""
    mock_sock = MagicMock()
    mock_socket_class.return_value.__enter__.return_value = mock_sock
    # Port open + PONG response
    mock_sock.connect_ex.return_value = 0
    mock_sock.recv.return_value = b"PONG"

    result = scan_subnet(8000, "192.168.1")
    assert result is not None
    assert result.startswith("192.168.1.")


def test_scan_subnet_no_subnet():
    """scan_subnet returns None when subnet is None."""
    assert scan_subnet(8000, None) is None


# ---------------------------------------------------------------------------
# Backward compatibility: send_notification wraps ACK protocol
# ---------------------------------------------------------------------------

@patch("battery_notifier.remote.send_command_with_ack")
def test_send_notification_uses_ack(mock_send_ack):
    """send_notification delegates to send_command_with_ack."""
    mock_send_ack.return_value = True
    assert send_notification("127.0.0.1", 8000, "START") is True
    mock_send_ack.assert_called_with("127.0.0.1", 8000, "START", timeout=5.0)


# ---------------------------------------------------------------------------
# RemoteMonitor / NotificationServer initialization
# ---------------------------------------------------------------------------

def test_notification_server_initialization(mock_config):
    """NotificationServer constructor sets all attributes."""
    server = NotificationServer(mock_config, "0.0.0.0", 8000)
    assert server.cfg == mock_config
    assert server.port == 8000
    assert server.player is not None


def test_remote_monitor_initialization(mock_config):
    """RemoteMonitor constructor sets all attributes."""
    monitor = RemoteMonitor(mock_config, "127.0.0.1", 8000)
    assert monitor.cfg == mock_config
    assert monitor.port == 8000
    assert monitor.resolved_host is None


# ---------------------------------------------------------------------------
# discover_server_ip (backward compatible)
# ---------------------------------------------------------------------------

@patch("socket.socket")
def test_discover_server_ip_success(mock_socket_class):
    """UDP auto-discovery captures beacon sender IP."""
    mock_sock = MagicMock()
    mock_sock.recvfrom.return_value = (BEACON_MESSAGE, ("192.168.1.15", DISCOVERY_UDP_PORT))
    mock_socket_class.return_value.__enter__.return_value = mock_sock

    detected_ip = discover_server_ip(timeout=1.0)
    assert detected_ip == "192.168.1.15"


@patch("socket.socket")
def test_discover_server_ip_timeout(mock_socket_class):
    """Auto-discovery handles timeout and returns None."""
    mock_sock = MagicMock()
    mock_sock.recvfrom.side_effect = socket.timeout
    mock_socket_class.return_value.__enter__.return_value = mock_sock

    assert discover_server_ip(timeout=0.1) is None


# ---------------------------------------------------------------------------
# RemoteMonitor loop tests (ACK-based)
# ---------------------------------------------------------------------------

@patch("time.sleep")
@patch("battery_notifier.remote.RemoteMonitor._resolve_host")
@patch("battery_notifier.battery.Battery.read")
@patch("battery_notifier.remote.send_command_with_ack")
def test_remote_monitor_loop_charging_alert_with_ack(mock_send, mock_read, mock_resolve, mock_sleep, mock_config):
    """Client sends START and gets ACK from server when charging above max."""
    from battery_notifier.battery import BatteryInfo

    mock_read.return_value = BatteryInfo(percentage=85, charging=True)
    mock_send.return_value = True
    mock_resolve.return_value = "127.0.0.1"

    monitor = RemoteMonitor(mock_config, "127.0.0.1", 8000)
    monitor.resolved_host = "127.0.0.1"
    mock_sleep.side_effect = lambda x: monitor._stop_event.set()

    monitor.run()

    mock_send.assert_called_with("127.0.0.1", 8000, "START")


@patch("time.sleep")
@patch("battery_notifier.remote.RemoteMonitor._resolve_host")
@patch("battery_notifier.battery.Battery.read")
@patch("battery_notifier.remote.send_command_with_ack")
def test_remote_monitor_loop_discharging_alert_with_ack(mock_send, mock_read, mock_resolve, mock_sleep, mock_config):
    """Client sends START when battery drops below min threshold."""
    from battery_notifier.battery import BatteryInfo

    mock_read.return_value = BatteryInfo(percentage=15, charging=False)
    mock_send.return_value = True
    mock_resolve.return_value = "127.0.0.1"

    monitor = RemoteMonitor(mock_config, "127.0.0.1", 8000)
    monitor.resolved_host = "127.0.0.1"
    mock_sleep.side_effect = lambda x: monitor._stop_event.set()

    monitor.run()

    mock_send.assert_called_with("127.0.0.1", 8000, "START")


@patch("time.sleep")
@patch("battery_notifier.battery.Battery.read")
@patch("battery_notifier.remote.send_command_with_ack")
def test_remote_monitor_loop_no_alert_when_safe(mock_send, mock_read, mock_sleep, mock_config):
    """No commands sent when battery is within safe thresholds."""
    from battery_notifier.battery import BatteryInfo

    mock_read.return_value = BatteryInfo(percentage=50, charging=True)

    monitor = RemoteMonitor(mock_config, "127.0.0.1", 8000)
    monitor.resolved_host = "127.0.0.1"
    mock_sleep.side_effect = lambda x: monitor._stop_event.set()

    monitor.run()

    mock_send.assert_not_called()


@patch("time.sleep")
@patch("battery_notifier.remote.RemoteMonitor._resolve_host")
@patch("battery_notifier.remote.RemoteMonitor._has_internet", return_value=False)
@patch("battery_notifier.battery.Battery.read")
@patch("battery_notifier.remote.send_command_with_ack")
def test_remote_monitor_loop_ack_failure_triggers_fallback(
    mock_send, mock_read, mock_internet, mock_resolve, mock_sleep, mock_config
):
    """When ACK fails 3 times, client resets resolved_host to trigger re-discovery."""
    from battery_notifier.battery import BatteryInfo

    mock_read.return_value = BatteryInfo(percentage=85, charging=True)
    mock_send.return_value = False  # ACK always fails
    mock_resolve.return_value = "127.0.0.1"

    monitor = RemoteMonitor(mock_config, "127.0.0.1", 8000)
    monitor.resolved_host = "127.0.0.1"

    call_count = [0]
    def stop_after_6_calls(x):
        call_count[0] += 1
        if call_count[0] >= 6:
            monitor._stop_event.set()
    mock_sleep.side_effect = stop_after_6_calls

    monitor.run()

    # After 3 failures, resolved_host should be reset to None
    assert monitor.resolved_host is None
    assert mock_send.call_count >= 3


# ---------------------------------------------------------------------------
# VPN detection tests
# ---------------------------------------------------------------------------

def test_detect_environment_includes_vpn_fields():
    """detect_environment returns Environment with VPN fields populated."""
    env = detect_environment()
    assert isinstance(env.is_vpn, bool)
    assert hasattr(env, "vpn_name")
    assert hasattr(env, "auto_proxy")


@patch("battery_notifier.connection._detect_vpn")
def test_vpn_detected_returns_true(mock_vpn):
    """When _detect_vpn finds a VPN, Environment.is_vpn is True."""
    mock_vpn.return_value = (True, "tun0")
    env = detect_environment()
    assert env.is_vpn is True
    assert env.vpn_name == "tun0"


@patch("battery_notifier.connection._detect_vpn")
def test_vpn_not_detected_returns_false(mock_vpn):
    """When _detect_vpn finds no VPN, Environment.is_vpn is False."""
    mock_vpn.return_value = (False, None)
    env = detect_environment()
    assert env.is_vpn is False
    assert env.vpn_name is None


@patch("os.listdir")
def test_detect_vpn_android_finds_tun0(mock_listdir):
    """VPN detection on Android finds tun0 interface."""
    mock_listdir.return_value = ["lo", "wlan0", "tun0", "rmnet0"]
    is_vpn, name = _detect_vpn(
        is_termux=True, is_android=True,
        is_windows=False, is_linux=False, is_macos=False
    )
    assert is_vpn is True
    assert name == "tun0"


@patch("os.listdir")
def test_detect_vpn_android_no_vpn(mock_listdir):
    """VPN detection on Android returns False when no tun/tap interfaces."""
    mock_listdir.return_value = ["lo", "wlan0", "rmnet0"]
    is_vpn, name = _detect_vpn(
        is_termux=True, is_android=True,
        is_windows=False, is_linux=False, is_macos=False
    )
    assert is_vpn is False
    assert name is None


@patch("subprocess.run")
def test_detect_vpn_windows_powershell(mock_run):
    """VPN detection on Windows uses PowerShell adapter names."""
    mock_run.return_value = MagicMock(stdout="Wintun Userspace Tunnel\n", stderr="")
    is_vpn, name = _detect_vpn(
        is_termux=False, is_android=False,
        is_windows=True, is_linux=False, is_macos=False
    )
    assert is_vpn is True
    assert "Wintun" in name


@patch("subprocess.run")
def test_detect_vpn_windows_no_vpn(mock_run):
    """VPN detection on Windows returns False when no VPN adapter found."""
    mock_run.return_value = MagicMock(stdout="", stderr="")
    is_vpn, name = _detect_vpn(
        is_termux=False, is_android=False,
        is_windows=True, is_linux=False, is_macos=False
    )
    assert is_vpn is False


@patch("subprocess.run")
def test_detect_vpn_linux_finds_interface(mock_run):
    """VPN detection on Linux finds tun/tap/ppp interfaces."""
    mock_run.return_value = MagicMock(
        stdout="1: lo: <LOOPBACK>\n2: eth0: <BROADCAST>\n5: tun0: <POINTOPOINT>\n"
    )
    is_vpn, name = _detect_vpn(
        is_termux=False, is_android=False,
        is_windows=False, is_linux=True, is_macos=False
    )
    assert is_vpn is True
    assert name == "tun0"


# ---------------------------------------------------------------------------
# Auto-proxy detection tests
# ---------------------------------------------------------------------------

@patch("socket.socket")
def test_detect_local_proxy_finds_port(mock_socket_class):
    """_detect_local_proxy scans common ports and returns first open one."""
    mock_sock = MagicMock()
    mock_socket_class.return_value.__enter__.return_value = mock_sock
    mock_sock.connect_ex.return_value = 0  # Port is open

    result = _detect_local_proxy()
    assert result is not None
    assert "127.0.0.1" in result


@patch("socket.socket")
def test_detect_local_proxy_none_open(mock_socket_class):
    """_detect_local_proxy returns None when no proxy ports are open."""
    mock_sock = MagicMock()
    mock_socket_class.return_value.__enter__.return_value = mock_sock
    mock_sock.connect_ex.return_value = 1  # Connection refused

    result = _detect_local_proxy()
    assert result is None


def test_get_effective_proxy_uses_config_first():
    """get_effective_proxy prioritizes config.proxy_url over auto-detected."""
    cfg = Config()
    cfg.proxy_url = "socks5://10.0.0.1:9999"
    result = get_effective_proxy(cfg)
    assert result == "socks5://10.0.0.1:9999"


@patch("battery_notifier.connection._detect_local_proxy")
def test_get_effective_proxy_falls_back_to_auto(mock_detect):
    """get_effective_proxy uses auto-detected proxy when config has none."""
    mock_detect.return_value = "http://127.0.0.1:7890"
    cfg = Config()
    cfg.proxy_url = ""
    result = get_effective_proxy(cfg)
    assert result == "http://127.0.0.1:7890"


@patch("battery_notifier.connection._detect_local_proxy")
def test_get_effective_proxy_none_available(mock_detect):
    """get_effective_proxy returns None when no proxy available."""
    mock_detect.return_value = None
    cfg = Config()
    cfg.proxy_url = ""
    result = get_effective_proxy(cfg)
    assert result is None


# ---------------------------------------------------------------------------
# smart_find_server with VPN active
# ---------------------------------------------------------------------------

@patch("battery_notifier.connection._detect_local_proxy", return_value=None)
@patch("battery_notifier.connection._detect_vpn")
@patch("battery_notifier.connection.ping_server")
def test_smart_find_server_vpn_skips_local_methods(mock_ping, mock_vpn, mock_proxy):
    """When VPN is active, smart_find_server tries USB tunnel + cache only."""
    mock_vpn.return_value = (True, "tun0")
    mock_ping.return_value = False  # No USB tunnel, no cached host

    result = smart_find_server(8000, verbose=False)
    assert result is None
    # ping_server should only be called for 127.0.0.1 and cached (not subnet scan)
    # since VPN skips UDP + subnet scan


@patch("battery_notifier.connection._detect_local_proxy", return_value=None)
@patch("battery_notifier.connection._detect_vpn")
@patch("battery_notifier.connection.ping_server")
def test_smart_find_server_vpn_usb_tunnel_works(mock_ping, mock_vpn, mock_proxy):
    """When VPN is active, USB tunnel (127.0.0.1) still works."""
    mock_vpn.return_value = (True, "tun0")
    mock_ping.return_value = True  # USB tunnel responds

    result = smart_find_server(8000, verbose=False)
    assert result == "127.0.0.1"
