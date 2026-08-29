"""Tests for intruder_guard.py and the snapshot client methods."""
import base64
import calendar
import sys
from unittest.mock import MagicMock, patch

import pytest

from battery_notifier.config import Config


@pytest.fixture
def mock_config():
    cfg = Config()
    cfg.worker_url = "https://test-worker.example.com"
    cfg.worker_token = "test_token_12345678abcdef"
    cfg.guard_camera_index = 0
    return cfg


FAKE_EVT_XML = (
    '<Event xmlns="http://schemas.microsoft.com/win/2004/08/events/event">'
    "<System>"
    '<TimeCreated SystemTime="2026-08-29T10:00:00.123456700Z"/>'
    "</System></Event>"
)


# ---------------------------------------------------------------------------
# last_failed_logon: wevtutil parsing
# ---------------------------------------------------------------------------

@patch("battery_notifier.intruder_guard.os")
@patch("battery_notifier.intruder_guard.subprocess")
def test_last_failed_logon_parses_wevtutil(mock_subprocess, mock_os):
    """Parses the newest 4625 event time out of wevtutil XML output."""
    from battery_notifier.intruder_guard import last_failed_logon

    mock_os.name = "nt"
    mock_subprocess.run.return_value = MagicMock(returncode=0, stdout=FAKE_EVT_XML, stderr="")
    mock_subprocess.CREATE_NO_WINDOW = 0

    ts = last_failed_logon()
    assert ts == calendar.timegm((2026, 8, 29, 10, 0, 0))


@patch("battery_notifier.intruder_guard.os")
@patch("battery_notifier.intruder_guard.subprocess")
def test_last_failed_logon_denied_without_admin(mock_subprocess, mock_os):
    """Non-zero exit (Access denied without elevation) means no signal, not a crash."""
    from battery_notifier.intruder_guard import last_failed_logon

    mock_os.name = "nt"
    mock_subprocess.run.return_value = MagicMock(returncode=5, stdout="", stderr="Access is denied.")
    mock_subprocess.CREATE_NO_WINDOW = 0

    assert last_failed_logon() is None


@patch("battery_notifier.intruder_guard.os")
@patch("battery_notifier.intruder_guard.subprocess")
def test_last_failed_logon_skipped_off_windows(mock_subprocess, mock_os):
    """On non-Windows the watcher has nothing to read and never spawns wevtutil."""
    from battery_notifier.intruder_guard import last_failed_logon

    mock_os.name = "posix"
    assert last_failed_logon() is None
    mock_subprocess.run.assert_not_called()


# ---------------------------------------------------------------------------
# grab_snapshot
# ---------------------------------------------------------------------------

def test_grab_snapshot_without_cv2():
    """Missing opencv degrades to None instead of raising."""
    with patch.dict(sys.modules, {"cv2": None}):
        from battery_notifier.intruder_guard import grab_snapshot
        assert grab_snapshot() is None


# ---------------------------------------------------------------------------
# IntruderGuard: cooldown, budget, check-once flow
# ---------------------------------------------------------------------------

def test_should_upload_cooldown_and_budget(mock_config):
    """One upload per cooldown window, hard-capped per rolling hour."""
    from battery_notifier.intruder_guard import IntruderGuard, COOLDOWN_SECONDS, HOURLY_BUDGET

    g = IntruderGuard(mock_config, worker_client=MagicMock())
    t0 = 1_000_000.0
    step = COOLDOWN_SECONDS + 1

    assert g._should_upload(t0) is True
    assert g._should_upload(t0 + 10) is False                      # inside cooldown
    assert g._should_upload(t0 + step) is True

    # Fill the rest of the hourly budget
    for i in range(HOURLY_BUDGET - 2):
        assert g._should_upload(t0 + (i + 2) * step) is True
    assert len(g._uploads) == HOURLY_BUDGET
    assert g._should_upload(t0 + (HOURLY_BUDGET + 1) * step) is False  # budget spent

    # An hour later the budget resets
    assert g._should_upload(t0 + 3700) is True


@patch("battery_notifier.intruder_guard.snapshot_from_frame")
@patch("battery_notifier.intruder_guard.grab_frame")
@patch("battery_notifier.intruder_guard.last_failed_logon")
def test_check_once_uploads_and_alerts(mock_last, mock_grab, mock_snap, mock_config):
    """A new failed logon becomes: snapshot -> upload -> THIEF_ALERT with snap id."""
    from battery_notifier.intruder_guard import IntruderGuard

    worker = MagicMock()
    worker.upload_snapshot.return_value = 42
    g = IntruderGuard(mock_config, worker_client=worker)
    g._last_seen_event = 100.0

    mock_last.return_value = 200.0
    mock_grab.return_value = "frame"
    mock_snap.return_value = b"\xff\xd8\xfffakejpeg"

    g._check_once()

    mock_grab.assert_called_once_with(0)
    worker.upload_snapshot.assert_called_once_with(b"\xff\xd8\xfffakejpeg")
    worker.send_alert.assert_called_once_with(
        alert_type="THIEF_ALERT", battery_pct=-1, is_charging=False, snapshot_id=42,
    )


@patch("battery_notifier.intruder_guard.grab_frame")
@patch("battery_notifier.intruder_guard.last_failed_logon")
def test_check_once_ignores_old_events(mock_last, mock_grab, mock_config):
    """Events at or before the baseline are history, not intrusions."""
    from battery_notifier.intruder_guard import IntruderGuard

    worker = MagicMock()
    g = IntruderGuard(mock_config, worker_client=worker)
    g._last_seen_event = 300.0

    mock_last.return_value = 300.0
    g._check_once()
    mock_last.return_value = 100.0
    g._check_once()

    mock_grab.assert_not_called()
    worker.upload_snapshot.assert_not_called()
    worker.send_alert.assert_not_called()


@patch("battery_notifier.intruder_guard.grab_frame")
@patch("battery_notifier.intruder_guard.last_failed_logon")
def test_check_once_survives_camera_failure(mock_last, mock_grab, mock_config):
    """No camera frame: the alert still goes out (photo-less), and the
    guard keeps its baseline so the same event never re-fires."""
    from battery_notifier.intruder_guard import IntruderGuard

    worker = MagicMock()
    g = IntruderGuard(mock_config, worker_client=worker)
    g._last_seen_event = 100.0

    mock_last.return_value = 200.0
    mock_grab.return_value = None

    g._check_once()
    worker.upload_snapshot.assert_not_called()
    worker.send_alert.assert_called_once_with(
        alert_type="THIEF_ALERT", battery_pct=-1, is_charging=False, snapshot_id=None,
    )
    assert g._last_seen_event == 200.0


# ---------------------------------------------------------------------------
# WorkerClient snapshot methods
# ---------------------------------------------------------------------------

@patch("battery_notifier.worker_client.requests")
def test_upload_snapshot_sends_base64(mock_requests, mock_config):
    """upload_snapshot base64-encodes the frame and returns snap_id."""
    from battery_notifier.worker_client import WorkerClient

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"ok": True, "snap_id": 7, "bytes": 10}
    mock_requests.post.return_value = mock_resp

    wc = WorkerClient("https://test.example.com", token="t" * 24, config=mock_config)
    assert wc.upload_snapshot(b"\xff\xd8\xffabc") == 7

    _, kwargs = mock_requests.post.call_args
    assert kwargs["json"]["image"] == base64.b64encode(b"\xff\xd8\xffabc").decode("ascii")


@patch("battery_notifier.worker_client.requests")
def test_upload_snapshot_failure(mock_requests, mock_config):
    """Worker rejection maps to None."""
    from battery_notifier.worker_client import WorkerClient

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"ok": False, "error": "unsupported_format"}
    mock_requests.post.return_value = mock_resp

    wc = WorkerClient("https://test.example.com", token="t" * 24, config=mock_config)
    assert wc.upload_snapshot(b"not-an-image") is None


@patch("battery_notifier.worker_client.requests")
def test_get_snapshot_returns_bytes(mock_requests, mock_config):
    from battery_notifier.worker_client import WorkerClient

    mock_resp = MagicMock(status_code=200, content=b"\xff\xd8\xffjpg")
    mock_requests.get.return_value = mock_resp

    wc = WorkerClient("https://test.example.com", token="t" * 24, config=mock_config)
    assert wc.get_snapshot(7) == b"\xff\xd8\xffjpg"


@patch("battery_notifier.worker_client.requests")
def test_get_snapshot_404_returns_none(mock_requests, mock_config):
    from battery_notifier.worker_client import WorkerClient

    mock_resp = MagicMock(status_code=404)
    mock_requests.get.return_value = mock_resp

    wc = WorkerClient("https://test.example.com", token="t" * 24, config=mock_config)
    assert wc.get_snapshot(999) is None


@patch("battery_notifier.worker_client.requests")
def test_send_alert_includes_snapshot_id(mock_requests, mock_config):
    """snapshot_id rides along in the alert payload only when set."""
    from battery_notifier.worker_client import WorkerClient

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"ok": True, "alert_type": "THIEF_ALERT"}
    mock_requests.post.return_value = mock_resp

    wc = WorkerClient("https://test.example.com", token="t" * 24, config=mock_config)

    wc.send_alert(alert_type="THIEF_ALERT", snapshot_id=42)
    _, kwargs = mock_requests.post.call_args
    assert kwargs["json"]["snapshot_id"] == 42

    wc.send_alert(alert_type="THIEF_ALERT")
    _, kwargs = mock_requests.post.call_args
    assert "snapshot_id" not in kwargs["json"]


# ---------------------------------------------------------------------------
# v2.2: face verdict drives lock + siren escalation
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_worker():
    w = MagicMock()
    w.upload_snapshot.return_value = 7
    return w


@patch("battery_notifier.intruder_guard.grab_frame")
@patch("battery_notifier.intruder_guard.last_failed_logon")
def test_owner_face_stands_down(mock_last, mock_grab, mock_config, mock_worker):
    """Owner's face -> silent: no lock, no siren, no upload, no alert."""
    from battery_notifier.intruder_guard import IntruderGuard

    player = MagicMock()
    lock = MagicMock()
    g = IntruderGuard(mock_config, worker_client=mock_worker, player=player,
                      face_verdict=lambda frame: "owner")
    g._last_seen_event = 100.0
    mock_last.return_value = 200.0
    mock_grab.return_value = "frame"

    with patch("battery_notifier.intruder_guard.lock_workstation", lock):
        g._check_once()

    lock.assert_not_called()
    player.play.assert_not_called()
    mock_worker.upload_snapshot.assert_not_called()
    mock_worker.send_alert.assert_not_called()


@patch("battery_notifier.intruder_guard.snapshot_from_frame")
@patch("battery_notifier.intruder_guard.grab_frame")
@patch("battery_notifier.intruder_guard.last_failed_logon")
def test_unknown_face_locks_and_sirens(mock_last, mock_grab, mock_snap, mock_config, mock_worker):
    """Unknown face -> instant lock + siren; stands down when the owner
    clears the alert from the phone (worker poll shows alert cleared)."""
    from battery_notifier.intruder_guard import IntruderGuard

    player = MagicMock()
    lock = MagicMock(return_value=True)
    mock_worker.poll.return_value = {"ok": True, "alert_active": 0}  # cleared remotely
    g = IntruderGuard(mock_config, worker_client=mock_worker, player=player,
                      face_verdict=lambda frame: "unknown")
    g._last_seen_event = 100.0
    mock_last.return_value = 200.0
    mock_grab.return_value = "frame"
    mock_snap.return_value = b"\xff\xd8\xfffakejpeg"

    with patch("battery_notifier.intruder_guard.lock_workstation", lock), \
         patch("battery_notifier.intruder_guard.SIREN_POLL_SECONDS", 0.01):
        g._check_once()

    lock.assert_called_once()
    player.play.assert_called_once()
    player.stop.assert_called_once()  # remote stand-down
    mock_worker.send_alert.assert_called_once_with(
        alert_type="THIEF_ALERT", battery_pct=-1, is_charging=False, snapshot_id=7,
    )


@patch("battery_notifier.intruder_guard.snapshot_from_frame")
@patch("battery_notifier.intruder_guard.grab_frame")
@patch("battery_notifier.intruder_guard.last_failed_logon")
def test_siren_survives_transient_poll_errors(mock_last, mock_grab, mock_snap, mock_config, mock_worker):
    """A failed poll during the siren must not stand down early."""
    from battery_notifier.intruder_guard import IntruderGuard

    player = MagicMock()
    mock_worker.poll.side_effect = [{"ok": False, "error": "timeout"},
                                    {"ok": True, "alert_active": 0}]
    g = IntruderGuard(mock_config, worker_client=mock_worker, player=player,
                      face_verdict=lambda frame: "unknown")
    g._last_seen_event = 100.0
    mock_last.return_value = 200.0
    mock_grab.return_value = "frame"
    mock_snap.return_value = b"\xff\xd8\xfffakejpeg"

    with patch("battery_notifier.intruder_guard.lock_workstation", MagicMock()), \
         patch("battery_notifier.intruder_guard.SIREN_POLL_SECONDS", 0.01):
        g._check_once()

    assert mock_worker.poll.call_count == 2  # first error ignored, second cleared
    player.stop.assert_called_once()


@patch("battery_notifier.intruder_guard.snapshot_from_frame")
@patch("battery_notifier.intruder_guard.grab_frame")
@patch("battery_notifier.intruder_guard.last_failed_logon")
def test_no_model_keeps_legacy_quiet_behavior(mock_last, mock_grab, mock_snap, mock_config, mock_worker):
    """No face model -> v2.1 behavior: alert + snapshot, never lock/siren."""
    from battery_notifier.intruder_guard import IntruderGuard

    player = MagicMock()
    lock = MagicMock()
    g = IntruderGuard(mock_config, worker_client=mock_worker, player=player,
                      face_verdict=None)
    g._last_seen_event = 100.0
    mock_last.return_value = 200.0
    mock_grab.return_value = "frame"
    mock_snap.return_value = b"\xff\xd8\xfffakejpeg"

    with patch("battery_notifier.intruder_guard.lock_workstation", lock):
        g._check_once()

    lock.assert_not_called()
    player.play.assert_not_called()
    mock_worker.upload_snapshot.assert_called_once()
    mock_worker.send_alert.assert_called_once()


@patch("battery_notifier.intruder_guard.snapshot_from_frame")
@patch("battery_notifier.intruder_guard.grab_frame")
@patch("battery_notifier.intruder_guard.last_failed_logon")
def test_broken_face_check_fails_toward_locking(mock_last, mock_grab, mock_snap, mock_config, mock_worker):
    """A crashing recognizer must not silently ignore the intrusion."""
    from battery_notifier.intruder_guard import IntruderGuard

    lock = MagicMock(return_value=True)

    def boom(frame):
        raise RuntimeError("model exploded")

    g = IntruderGuard(mock_config, worker_client=mock_worker, player=None,
                      face_verdict=boom)
    g._last_seen_event = 100.0
    mock_last.return_value = 200.0
    mock_grab.return_value = "frame"
    mock_snap.return_value = b"\xff\xd8\xfffakejpeg"

    with patch("battery_notifier.intruder_guard.lock_workstation", lock):
        g._check_once()

    lock.assert_called_once()
    mock_worker.send_alert.assert_called_once()


@patch("battery_notifier.intruder_guard.subprocess")
@patch("battery_notifier.intruder_guard.os")
def test_lock_workstation_runs_rundll32(mock_os, mock_subprocess):
    from battery_notifier.intruder_guard import lock_workstation

    mock_os.name = "nt"
    mock_subprocess.CREATE_NO_WINDOW = 0
    assert lock_workstation() is True
    cmd = mock_subprocess.run.call_args[0][0]
    assert cmd == ["rundll32.exe", "user32.dll,LockWorkStation"]


@patch("battery_notifier.intruder_guard.os")
def test_lock_workstation_noop_off_windows(mock_os):
    from battery_notifier.intruder_guard import lock_workstation

    mock_os.name = "posix"
    assert lock_workstation() is False


@patch("battery_notifier.intruder_guard.grab_frame")
@patch("battery_notifier.intruder_guard.last_failed_logon")
def test_no_camera_still_alerts_without_photo(mock_last, mock_grab, mock_config, mock_worker):
    """Covered/disconnected camera: no snapshot is possible, but the
    intrusion alert still goes out -- silence would be the worse failure."""
    from battery_notifier.intruder_guard import IntruderGuard

    lock = MagicMock()
    g = IntruderGuard(mock_config, worker_client=mock_worker, player=None,
                      face_verdict=lambda f: "unknown")
    g._last_seen_event = 100.0
    mock_last.return_value = 200.0
    mock_grab.return_value = None

    with patch("battery_notifier.intruder_guard.lock_workstation", lock):
        g._check_once()

    lock.assert_not_called()  # no frame -> no verdict evidence
    mock_worker.upload_snapshot.assert_not_called()
    mock_worker.send_alert.assert_called_once_with(
        alert_type="THIEF_ALERT", battery_pct=-1, is_charging=False, snapshot_id=None,
    )
