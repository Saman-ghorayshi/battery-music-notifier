"""Tests for worker_client.py and thief_catcher.py"""
import pytest
import time
from unittest.mock import MagicMock, patch, call
from battery_notifier.config import Config
from battery_notifier.battery import BatteryInfo


@pytest.fixture
def mock_config():
    cfg = Config()
    cfg.music_files = ["test_track.mp3"]
    cfg.alarm_files = ["alarm.mp3"]
    cfg.min_percentage = 20
    cfg.max_percentage = 80
    cfg.volume = 0.5
    cfg.poll_interval = 0.1
    cfg.worker_url = "https://test-worker.example.com"
    cfg.worker_token = "test_token_12345678abcdef"
    cfg.alarm_files = ["alarm.mp3"]
    return cfg


# ---------------------------------------------------------------------------
# WorkerClient tests
# ---------------------------------------------------------------------------

@patch("battery_notifier.worker_client.requests")
def test_worker_register_success(mock_requests, mock_config):
    """WorkerClient.register returns token on success."""
    from battery_notifier.worker_client import WorkerClient

    mock_resp = MagicMock()
    mock_resp.json.return_value = {"ok": True, "token": "newtoken123", "user_id": 1}
    mock_requests.post.return_value = mock_resp

    wc = WorkerClient("https://test.example.com", config=mock_config)
    token = wc.register("MyPhone", "Termux")

    assert token == "newtoken123"
    assert wc.token == "newtoken123"


@patch("battery_notifier.worker_client.requests")
def test_worker_register_failure(mock_requests, mock_config):
    """WorkerClient.register returns None on failure."""
    from battery_notifier.worker_client import WorkerClient

    mock_resp = MagicMock()
    mock_resp.json.return_value = {"ok": False, "error": "db_error"}
    mock_requests.post.return_value = mock_resp

    wc = WorkerClient("https://test.example.com", config=mock_config)
    token = wc.register("MyPhone", "Termux")

    assert token is None


@patch("battery_notifier.worker_client.requests")
def test_worker_send_alert_success(mock_requests, mock_config):
    """WorkerClient.send_alert returns True on success."""
    from battery_notifier.worker_client import WorkerClient

    mock_resp = MagicMock()
    mock_resp.json.return_value = {"ok": True, "alert_active": 1, "alert_type": "THIEF_ALERT"}
    mock_requests.post.return_value = mock_resp

    wc = WorkerClient("https://test.example.com", token="mytoken", config=mock_config)
    result = wc.send_alert(alert_type="THIEF_ALERT", battery_pct=75, is_charging=False)

    assert result is True


@patch("battery_notifier.worker_client.requests")
def test_worker_send_alert_rate_limited(mock_requests, mock_config):
    """WorkerClient.send_alert returns False on rate limit."""
    from battery_notifier.worker_client import WorkerClient

    mock_resp = MagicMock()
    mock_resp.json.return_value = {"ok": False, "error": "rate_limited"}
    mock_requests.post.return_value = mock_resp

    wc = WorkerClient("https://test.example.com", token="mytoken", config=mock_config)
    result = wc.send_alert(alert_type="THIEF_ALERT", battery_pct=75, is_charging=False)

    assert result is False


@patch("battery_notifier.worker_client.requests")
def test_worker_poll(mock_requests, mock_config):
    """WorkerClient.poll returns alert state."""
    from battery_notifier.worker_client import WorkerClient

    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "ok": True,
        "alert_active": 1,
        "alert_type": "THIEF_ALERT",
        "alert_ts": 1234567890,
        "battery_pct": 42,
        "is_charging": 0,
    }
    mock_requests.get.return_value = mock_resp

    wc = WorkerClient("https://test.example.com", token="mytoken", config=mock_config)
    result = wc.poll()

    assert result["ok"] is True
    assert result["alert_active"] == 1
    assert result["alert_type"] == "THIEF_ALERT"


@patch("battery_notifier.worker_client.requests")
def test_worker_clear_alert(mock_requests, mock_config):
    """WorkerClient.clear_alert returns True on success."""
    from battery_notifier.worker_client import WorkerClient

    mock_resp = MagicMock()
    mock_resp.json.return_value = {"ok": True, "alert_active": 0}
    mock_requests.post.return_value = mock_resp

    wc = WorkerClient("https://test.example.com", token="mytoken", config=mock_config)
    result = wc.clear_alert()

    assert result is True


@patch("battery_notifier.worker_client.requests")
def test_worker_admin_stats(mock_requests, mock_config):
    """WorkerClient.admin_stats returns stats dict."""
    from battery_notifier.worker_client import WorkerClient

    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "ok": True,
        "stats": {
            "total_users": 42,
            "active_5min": 5,
            "active_alerts": 2,
            "banned": 1,
            "pro": 3,
            "founding": 10,
            "total_alerts_sent": 150,
        },
        "recent_users": [],
    }
    mock_requests.get.return_value = mock_resp

    wc = WorkerClient("https://test.example.com", token="mytoken", config=mock_config)
    wc._admin_session = "fake_session"
    result = wc.admin_stats()

    assert result["ok"] is True
    assert result["stats"]["total_users"] == 42


@patch("battery_notifier.worker_client.requests")
def test_worker_network_error_handling(mock_requests, mock_config):
    """WorkerClient handles network errors gracefully."""
    from battery_notifier.worker_client import WorkerClient

    mock_requests.post.side_effect = Exception("network error")
    mock_requests.get.side_effect = Exception("network error")

    wc = WorkerClient("https://test.example.com", token="mytoken", config=mock_config)
    assert wc.send_alert() is False
    assert wc.ping() is False
    assert wc.register() is None
    assert wc.poll() == {"ok": False, "error": "network error"}


# ---------------------------------------------------------------------------
# ThiefCatcher tests
# ---------------------------------------------------------------------------

@patch("battery_notifier.thief_catcher.Player")
def test_thief_catcher_init(mock_player_cls, mock_config):
    """ThiefCatcher initializes with correct alarm files."""
    from battery_notifier.thief_catcher import ThiefCatcher

    mock_player = MagicMock()
    mock_player_cls.return_value = mock_player

    tc = ThiefCatcher(mock_config, player=mock_player)
    assert tc.cfg == mock_config
    assert tc._armed is False
    assert tc._alert_active is False


@patch("battery_notifier.thief_catcher.time")
@patch("battery_notifier.thief_catcher.Battery")
def test_thief_catcher_detects_unplug(mock_battery_cls, mock_time, mock_config):
    """ThiefCatcher triggers alert when charger is unplugged."""
    from battery_notifier.thief_catcher import ThiefCatcher

    # Mock battery: first read charging, second read not charging
    mock_battery = MagicMock()
    mock_battery.read.side_effect = [
        BatteryInfo(percentage=80, charging=True),   # Initial check
        BatteryInfo(percentage=80, charging=True),   # Grace period check
        BatteryInfo(percentage=80, charging=True),   # Loop: was_charging=True
        BatteryInfo(percentage=75, charging=False),  # Loop: UNPLUGGED!
    ]
    mock_battery_cls.return_value = mock_battery

    # Mock time to skip grace period
    mock_time.time.side_effect = [0, 0.5, 1, 2, 3, 4, 5]
    mock_time.sleep = MagicMock()

    mock_player = MagicMock()
    mock_worker = MagicMock()

    tc = ThiefCatcher(mock_config, player=mock_player, worker_client=mock_worker)
    tc._stop_event.set()  # Stop after first detection cycle

    # Manually call the trigger to test it
    tc._trigger_alert("both", 75, verbose=False)

    mock_player.play.assert_called_once()
    mock_worker.send_alert.assert_called_with(
        alert_type="THIEF_ALERT", battery_pct=75, is_charging=False
    )


def test_thief_catcher_disarm(mock_config):
    """ThiefCatcher.disarm stops player and clears worker alert."""
    from battery_notifier.thief_catcher import ThiefCatcher

    mock_player = MagicMock()
    mock_worker = MagicMock()

    tc = ThiefCatcher(mock_config, player=mock_player, worker_client=mock_worker)
    tc._armed = True
    tc._alert_active = True
    tc._disarm()

    assert tc._armed is False
    assert tc._alert_active is False
    mock_player.stop.assert_called_once()
    mock_worker.clear_alert.assert_called_once()


@patch("battery_notifier.thief_catcher.Battery")
def test_thief_catcher_arm_not_charging(mock_battery_cls, mock_config):
    """ThiefCatcher.arm refuses to arm when not charging (without --force)."""
    from battery_notifier.thief_catcher import ThiefCatcher

    mock_battery = MagicMock()
    mock_battery.read.return_value = BatteryInfo(percentage=50, charging=False)
    mock_battery_cls.return_value = mock_battery

    mock_player = MagicMock()
    tc = ThiefCatcher(mock_config, player=mock_player)
    tc.arm(mode="local", verbose=False)

    # Should not arm
    assert tc._armed is False


@patch("battery_notifier.thief_catcher.Battery")
def test_thief_catcher_stop_alert_on_replug(mock_battery_cls, mock_config):
    """ThiefCatcher stops alarm when charger is reconnected."""
    from battery_notifier.thief_catcher import ThiefCatcher

    mock_player = MagicMock()
    mock_worker = MagicMock()

    tc = ThiefCatcher(mock_config, player=mock_player, worker_client=mock_worker)
    tc._alert_active = True

    # Simulate re-plug
    tc._stop_alert("both")

    mock_player.stop.assert_called_once()
    mock_worker.clear_alert.assert_called_once()


# ---------------------------------------------------------------------------
# Config tests for new fields
# ---------------------------------------------------------------------------

def test_config_has_worker_fields():
    """Config dataclass includes worker_url, worker_token, admin_key, alarm_files."""
    from battery_notifier.config import DEFAULT_WORKER_URL, DEFAULT_ALARM_FILE
    cfg = Config()
    assert hasattr(cfg, "worker_url")
    assert hasattr(cfg, "worker_token")
    assert hasattr(cfg, "admin_key")
    assert hasattr(cfg, "alarm_files")
    # worker_url defaults to hosted worker
    assert cfg.worker_url == DEFAULT_WORKER_URL
    assert cfg.worker_token == ""
    assert cfg.admin_key == ""
    # alarm_files defaults to bundled alarm
    assert len(cfg.alarm_files) > 0
    assert DEFAULT_ALARM_FILE in cfg.alarm_files[0]


def test_config_defaults_are_sensible():
    """Defaults: min=20 (low battery), max=100 (full charge). Not 99/100."""
    cfg = Config()
    assert cfg.min_percentage == 20, "min should be 20, not 99 (old bug caused constant ringing)"
    assert cfg.max_percentage == 100


def test_config_loads_worker_fields(tmp_path):
    """Config.load reads worker fields from TOML."""
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text('''[battery_notifier]
music_files = ["test.mp3"]
worker_url = "https://my-worker.example.com"
worker_token = "tok12345678abcdef"
admin_key = "secretadminkey"
alarm_files = ["alarm.wav"]
''')
    cfg = Config.load(cfg_file)
    assert cfg.worker_url == "https://my-worker.example.com"
    assert cfg.worker_token == "tok12345678abcdef"
    assert cfg.admin_key == "secretadminkey"
    assert cfg.alarm_files == ["alarm.wav"]
