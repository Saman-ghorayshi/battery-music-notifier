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
# Siren auto-stop: the owner is at the phone by then, and a false positive
# shouldn't scream all afternoon
SIREN_MAX_SECONDS = 300
SIREN_POLL_SECONDS = 3

# wevtutil prints UTC, so the parse goes through calendar.timegm to avoid
# local-timezone surprises on the timestamp comparison.
_SYSTEM_TIME_RE = re.compile(r'SystemTime="([^"]+)"')


def lock_workstation() -> bool:
    """Windows lock. Belt-and-braces: a failed logon usually means the lock
    screen is already up; this also covers UAC/unlock prompts."""
    if os.name != "nt":
        log.info("autolock: not Windows, skipping")
        return False
    try:
        create_no_window = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        subprocess.run(
            ["rundll32.exe", "user32.dll,LockWorkStation"],
            timeout=5, creationflags=create_no_window, check=False,
        )
        return True
    except Exception as e:
        log.error("lock_workstation failed: %s", e)
        return False


def _wevtutil_newest(event_id: int) -> float | None:
    """Epoch time of the newest Windows security event with this id, or None."""
    if os.name != "nt":
        return None
    cmd = [
        "wevtutil", "qe", "Security",
        f"/q:*[System[(EventID={event_id})]]",
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


def last_failed_logon() -> float | None:
    """Epoch time of the newest failed Windows sign-in, or None."""
    return _wevtutil_newest(4625)


def last_successful_logon() -> float | None:
    """Epoch time of the newest successful Windows sign-in (incl. unlock).

    The owner's real mute button: typing the correct password is identity
    proof a thief cannot fake, so the guard stands down the moment a
    successful logon lands after a trigger.
    """
    return _wevtutil_newest(4624)


def grab_frame(camera_index: int = 0):
    """One raw BGR frame from the webcam, camera released immediately."""
    try:
        import cv2
    except ImportError:
        log.warning("opencv not installed - camera capture disabled. "
                    "Install with: pip install battery-music-notifier[guard]")
        return None
    cam = cv2.VideoCapture(camera_index)
    try:
        ok, frame = cam.read()
    finally:
        cam.release()
    if not ok or frame is None:
        log.warning("Camera %s returned no frame", camera_index)
        return None
    return frame


def snapshot_from_frame(frame) -> bytes | None:
    """Downscale + JPEG-encode a raw frame for the relay."""
    import cv2
    h, w = frame.shape[:2]
    if w > SNAPSHOT_MAX_WIDTH:
        scale = SNAPSHOT_MAX_WIDTH / w
        frame = cv2.resize(frame, (SNAPSHOT_MAX_WIDTH, int(h * scale)))
    ok, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), JPEG_QUALITY])
    if not ok:
        return None
    return bytes(buf)


def sharpest_frame(frames):
    """Focus measure (Laplacian variance) — the sharpest frame is the best
    evidence and the most reliable face-verdict input."""
    try:
        import cv2
        return max(frames, key=lambda f: cv2.Laplacian(
            cv2.cvtColor(f, cv2.COLOR_BGR2GRAY), cv2.CV_64F).var())
    except Exception:
        return frames[0]


def snapshot_montage(frames) -> bytes | None:
    """Side-by-side burst in ONE image: three moments, one snapshot row.
    Steps JPEG quality down until the worker's 150 KB cap is comfortable."""
    import cv2
    if not frames:
        return None
    if len(frames) == 1:
        return snapshot_from_frame(frames[0])
    height = min(f.shape[0] for f in frames)
    resized = []
    for f in frames[:3]:
        scale = height / f.shape[0]
        resized.append(cv2.resize(f, (int(f.shape[1] * scale), height)))
    strip = cv2.hconcat(resized)
    if strip.shape[1] > SNAPSHOT_MAX_WIDTH:
        scale = SNAPSHOT_MAX_WIDTH / strip.shape[1]
        strip = cv2.resize(strip, (SNAPSHOT_MAX_WIDTH, int(strip.shape[0] * scale)))
    for q in (JPEG_QUALITY, 60, 50, 40):
        ok, buf = cv2.imencode(".jpg", strip, [int(cv2.IMWRITE_JPEG_QUALITY), q])
        if not ok:
            return None
        if len(buf) <= 140_000:
            return bytes(buf)
    return None


def capture_burst(camera_index: int, count: int, interval: float) -> list:
    """`count` frames spaced `interval` seconds apart (first immediately)."""
    frames = []
    frame = grab_frame(camera_index)
    if frame is None:
        return frames
    frames.append(frame)
    while len(frames) < max(1, count):
        time.sleep(max(0.0, interval))
        f = grab_frame(camera_index)
        if f is not None:
            frames.append(f)
    return frames


def grab_snapshot(camera_index: int = 0) -> bytes | None:
    """One downscaled JPEG frame from the webcam; None if no camera or cv2."""
    frame = grab_frame(camera_index)
    if frame is None:
        return None
    try:
        return snapshot_from_frame(frame)
    except Exception as e:
        log.error("snapshot encode failed: %s", e)
        return None


class IntruderGuard:
    """Watches for failed logons while armed; one snapshot per intrusion.

    With an enrolled face model (v2.2): owner -> stand down silently,
    unknown/no_face -> lock + siren + snapshot + alert. Without a model the
    guard keeps the v2.1 behavior: snapshot + alert, no lock, no siren.
    """

    def __init__(self, config, worker_client=None, player=None, face_verdict=None):
        self.cfg = config
        self.worker = worker_client
        self.player = player
        self.face_verdict = face_verdict  # None = no model -> legacy behavior
        self.camera_index = getattr(config, "guard_camera_index", 0) or 0
        self._stop_event = threading.Event()
        self._armed = False
        self._cycles = 0
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

        # Account-level arm: the phone sees it and arms its side too
        if self.worker:
            r = self.worker.arm_account(True)
            if not r.get("ok"):
                log.warning("account arm failed: %s (guard still armed locally)",
                            r.get("error"))

        if verbose:
            if self.face_verdict:
                print("  Face check: ON (owner stands down, unknown locks + siren)")
            else:
                print("  Face check: OFF (no model -- run 'battery-music guard-enroll')")
                print("           every failed logon alerts, nothing locks or sirens")
            try:
                from .face_guard import diagnose_camera
                cam_ok, cam_detail = diagnose_camera(self.camera_index)
                if not cam_ok:
                    print("  [WARN] Camera: " + cam_detail.splitlines()[0])
                    print("         run 'battery-music guard-enroll' for the guided fix")
            except Exception:
                pass
            print("  Intruder Guard ARMED (failed logon -> webcam snapshot -> phone)")
            print("  Press Ctrl+C to disarm.\n")
        while not self._stop_event.is_set():
            try:
                # Remote disarm: if the account was disarmed (from the phone,
                # with the pass), the guard stands down and exits.
                if self.worker and self._cycles % 5 == 0:
                    state = self.worker.poll()
                    if state.get("ok") and not state.get("armed", 0):
                        print("  Account was disarmed remotely. Guard standing down.")
                        log.info("remote disarm detected -- guard exiting")
                        self._stop_event.set()
                        break
                self._cycles += 1
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

        verdict = None
        burst_count = max(1, int(getattr(self.cfg, "burst_count", 3) or 1))
        burst_gap = float(getattr(self.cfg, "burst_interval", 1.5) or 0)
        frames = capture_burst(self.camera_index, burst_count, burst_gap)
        if frames and self.face_verdict:
            try:
                verdict = self.face_verdict(sharpest_frame(frames))
                if verdict == "owner" and len(frames) >= 2:
                    from .face_guard import LIVENESS_MIN_SCORE, liveness_score
                    score = liveness_score(frames[0], frames[-1])
                    if score < LIVENESS_MIN_SCORE:
                        # Static pixels where a live face should blink: a
                        # printed photo of the owner. Fail toward locking.
                        log.warning("liveness failed (score %.2f) -- owner treated as spoof", score)
                        verdict = "unknown"
            except Exception as e:
                log.error("face verdict failed: %s", e)
                verdict = "unknown"  # fail toward locking, never ignoring
        if verdict == "owner":
            log.info("Owner's face at failed logon -- standing down")
            return

        if verdict in ("unknown", "no_face") and getattr(self.cfg, "guard_autolock", True):
            if lock_workstation():
                log.info("Unknown face -- workstation locked")

        # No camera evidence changes the alert, not whether we send it:
        # an intrusion without a photo still rings the phone.
        image = snapshot_montage(frames) if frames else None
        snap_id = self.worker.upload_snapshot(image) if (self.worker and image) else None
        if self.worker:
            self.worker.send_alert(
                alert_type="THIEF_ALERT", battery_pct=-1, is_charging=False,
                snapshot_id=snap_id,
            )
        log.info("Intruder alert sent (snap_id=%s, verdict=%s, photo=%s)",
                 snap_id, verdict, image is not None)

        # Siren only when the face check is active and disapproved: without a
        # model every mistyped password would scream (v2.1 compat = quiet).
        if verdict in ("unknown", "no_face") and getattr(self.cfg, "guard_siren", True) and self.player:
            self.player.play()
            self._siren_with_stand_down(trigger_ts=event_ts)

    def _siren_with_stand_down(self, trigger_ts: float | None = None) -> None:
        """Keep screaming until the 5-min cap OR the owner proves identity:
        'STOP ALARM EVERYWHERE' from the phone (-> /api/clear), a remote
        disarm with the pass, or simply typing the correct Windows password
        (Event 4624 lands after the trigger). Runs inside the arm() loop; a
        second intrusion during the siren is suppressed by cooldown/budget."""
        deadline = time.time() + SIREN_MAX_SECONDS
        while time.time() < deadline and not self._stop_event.is_set():
            time.sleep(SIREN_POLL_SECONDS)
            # Owner typed the real password -> identity proven, stop now
            ok_ts = last_successful_logon()
            if ok_ts and (trigger_ts is None or ok_ts >= trigger_ts - 2):
                self.player.stop()
                log.info("owner authenticated (successful logon) -- stood down")
                return
            if self.worker is None:
                continue
            state = self.worker.poll()
            if state and not state.get("ok", True):
                continue  # transient poll error: keep going
            if state is None:
                continue
            cleared = not state.get("alert_active", 0)
            disarmed = not state.get("armed", 0)
            if cleared or disarmed:
                self.player.stop()
                why = "alert cleared" if cleared else "account disarmed"
                log.info("remote %s -- siren stood down", why)
                return
        self.player.stop()
        log.info("Siren auto-stopped after %ss", SIREN_MAX_SECONDS)

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
        if self.player:
            self.player.stop()


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
