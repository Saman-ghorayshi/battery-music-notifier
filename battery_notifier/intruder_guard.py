# battery_notifier/intruder_guard.py
"""Intruder Guard (v2.1, experimental): webcam snapshot on failed logon.

While armed, watches the Windows security log for Event 4625 (a failed
sign-in attempt). On a new failure it grabs a single webcam frame, uploads
it through the relay and fires THIEF_ALERT, so the paired phone rings and
can pull the photo with GET /api/snapshot/{id}.

Two things it needs on Windows to actually see anything:
  - an elevated terminal: only admin processes may read the Security log
  - opencv-python-headless for the camera grab (extra: pip install -e ".[guard]")

Everything degrades gracefully -- no admin, no camera or no relay just logs
a warning and keeps watching.
"""
from __future__ import annotations
import calendar
import logging
import os
import re
import subprocess
import threading
import time
from collections import deque
from datetime import datetime

log = logging.getLogger(__name__)

# How often to look for new failed sign-ins
CHECK_INTERVAL = 5.0
# One photo per intrusion; retries within the cooldown stay silent
COOLDOWN_SECONDS = 90
# Hard cap so a prankster hammering the lock screen can't fill the bucket
HOURLY_BUDGET = 5
SNAPSHOT_MAX_WIDTH = 640
JPEG_QUALITY = 70

# wevtutil prints UTC, so the parse goes through calendar.timegm to avoid
# local-timezone surprises on the timestamp comparison.
_SYSTEM_TIME_RE = re.compile(r'SystemTime="([^"]+)"')


def last_failed_logon() -> float | None:
    """Epoch time of the newest failed Windows sign-in, or None."""
    if os.name != "nt":
        return None
    cmd = [
        "wevtutil", "qe", "Security",
        "/q:*[System[(EventID=4625)]]",
        "/c:1", "/rd:true", "/f:xml",
    ]
    create_no_window = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        r = subprocess.run(
            cmd, capture_output=True, text=True, timeout=10,
            creationflags=create_no_window,
        )
    except Exception as e:
        log.debug("wevtutil unavailable: %s", e)
        return None
    if r.returncode != 0:
        # By far the most common cause: not elevated, Security log is off limits
        log.debug("wevtutil failed (%s): %s", r.returncode, (r.stderr or "").strip()[:120])
        return None
    m = _SYSTEM_TIME_RE.search(r.stdout or "")
    if not m:
        return None
    try:
        dt = datetime.strptime(m.group(1)[:19], "%Y-%m-%dT%H:%M:%S")
    except ValueError:
        return None
    return float(calendar.timegm(dt.timetuple()))


def grab_snapshot(camera_index: int = 0) -> bytes | None:
    """One downscaled JPEG frame from the webcam; None if no camera or cv2."""
    try:
        import cv2
    except ImportError:
        log.warning(
            "opencv not installed - camera capture disabled. "
            "Install with: pip install battery-music-notifier[guard]"
        )
        return None
    cam = cv2.VideoCapture(camera_index)
    try:
        ok, frame = cam.read()
    finally:
        cam.release()
    if not ok or frame is None:
        log.warning("Camera %s returned no frame", camera_index)
        return None
    h, w = frame.shape[:2]
    if w > SNAPSHOT_MAX_WIDTH:
        scale = SNAPSHOT_MAX_WIDTH / w
        frame = cv2.resize(frame, (SNAPSHOT_MAX_WIDTH, int(h * scale)))
    ok, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), JPEG_QUALITY])
    if not ok:
        return None
    return bytes(buf)


class IntruderGuard:
    """Watches for failed logons while armed; one snapshot per intrusion."""

    def __init__(self, config, worker_client=None):
        self.cfg = config
        self.worker = worker_client
        self.camera_index = getattr(config, "guard_camera_index", 0) or 0
        self._stop_event = threading.Event()
        self._armed = False
        # Events older than this are history, not intrusions; set at arm time
        self._last_seen_event = 0.0
        self._uploads: deque = deque()  # upload timestamps, hourly budget

    def arm(self, verbose: bool = True) -> None:
        """Block and watch until disarm(). Run from a thread inside the GUI."""
        latest = last_failed_logon()
        if latest is None and os.name == "nt" and verbose:
            print("  [WARN] Can't read the Security log. Run this terminal as")
            print("         administrator or failed logons stay invisible.")
        # Baseline = newest existing event, so old failures don't re-fire
        self._last_seen_event = latest or time.time()
        self._stop_event.clear()
        self._armed = True

        if verbose:
            print("  Intruder Guard ARMED (failed logon -> webcam snapshot -> phone)")
            print("  Press Ctrl+C to disarm.\n")
        while not self._stop_event.is_set():
            try:
                self._check_once()
            except Exception as e:
                log.error("Intruder guard loop error: %s", e)
            time.sleep(CHECK_INTERVAL)
        self._armed = False

    def _check_once(self) -> None:
        event_ts = last_failed_logon()
        if not event_ts or event_ts <= self._last_seen_event:
            return
        self._last_seen_event = event_ts
        now = time.time()
        if not self._should_upload(now):
            log.info("Intrusion detected but suppressed (cooldown/budget)")
            return
        image = grab_snapshot(self.camera_index)
        if not image:
            return
        snap_id = self.worker.upload_snapshot(image) if self.worker else None
        if self.worker:
            self.worker.send_alert(
                alert_type="THIEF_ALERT", battery_pct=-1, is_charging=False,
                snapshot_id=snap_id,
            )
        log.info("Intruder snapshot sent (snap_id=%s)", snap_id)

    def _should_upload(self, ts: float) -> bool:
        if self._uploads and ts - self._uploads[-1] < COOLDOWN_SECONDS:
            return False
        while self._uploads and ts - self._uploads[0] > 3600:
            self._uploads.popleft()
        if len(self._uploads) >= HOURLY_BUDGET:
            return False
        self._uploads.append(ts)
        return True

    @property
    def is_armed(self) -> bool:
        return self._armed

    def disarm(self) -> None:
        """Stop watching. Safe to call from another thread."""
        self._stop_event.set()


if __name__ == "__main__":
    # python -m battery_notifier.intruder_guard
    from .config import Config
    from .connection import detect_environment
    from .worker_client import WorkerClient

    cfg = Config()
    env = detect_environment()
    print("=" * 50)
    print("  Intruder Guard")
    print("=" * 50)
    print(f"  Environment: {env.platform_name}")

    worker = None
    if cfg.worker_url:
        worker = WorkerClient(cfg.worker_url, cfg.worker_token, cfg)
        if not cfg.worker_token:
            print("  No worker token in config. Registering...")
            token = worker.register(device_name=env.platform_name, platform=env.platform_name)
            if token:
                print(f"  Registered! Token: {token[:8]}...")
                cfg.worker_token = token
            else:
                print("  [WARN] Registration failed. Snapshots won't reach the relay.")
                worker = None
    else:
        print("  [WARN] No worker_url configured. Run 'battery-music init' first.")

    try:
        IntruderGuard(cfg, worker_client=worker).arm()
    except KeyboardInterrupt:
        pass
