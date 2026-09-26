# battery_notifier/guardlock.py
"""Single-instance + alarm-source locks for the long-running listeners.

Two PID files under APP_DIR:

  relay.lock  -- the relay listener (`battery-music relay`) holds it for its
                 whole life. A second relay instance finds a live PID and
                 exits instead of double-polling / double-screaming.
  thief.lock  -- ThiefCatcher (`battery-music arm`) holds it while armed.
                 The relay listener reads it every poll: when a local
                 ThiefCatcher is the alarm source the relay must stay silent
                 for THIEF episodes (BATTERY episodes always play).

A lock whose PID is no longer running is STALE and may be taken over, so a
crashed process never wedges the next start.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

log = logging.getLogger(__name__)

LOCK_RELAY = "relay.lock"
LOCK_THIEF = "thief.lock"
LOCK_GUARD = "guard.lock"  # kept here for reference; managed by cli._acquire_guard_lock


def _pid_alive(pid: int) -> bool:
    """True if `pid` is a live process on this machine."""
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    if pid == os.getpid():
        return True
    try:
        import psutil

        return bool(psutil.pid_exists(pid))
    except Exception:
        # psutil missing/unusable: fall back to OS primitives.
        if os.name == "nt":
            try:
                import ctypes

                PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
                k32 = ctypes.windll.kernel32
                handle = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
                if handle:
                    k32.CloseHandle(handle)
                    return True
                return False
            except Exception:
                return False
        try:
            os.kill(pid, 0)  # signal 0 = existence probe
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            return True  # exists, but owned by someone else
        except OSError:
            return False


def lock_path(app_dir: Path | str, name: str) -> Path:
    return Path(app_dir) / name


def _read_pid(path: Path) -> int | None:
    """PID stored in the lock file, or None if unparsable."""
    try:
        return int(path.read_text(encoding="utf-8", errors="ignore").strip())
    except Exception:
        return None


def is_locked(app_dir: Path | str, name: str) -> bool:
    """True if a live process currently holds the named lock."""
    path = lock_path(app_dir, name)
    if not path.exists():
        return False
    pid = _read_pid(path)
    if pid is None:
        return False
    return _pid_alive(pid)


def acquire(app_dir: Path | str, name: str) -> Path | None:
    """Create/take over the named lock for this process.

    Returns the lock Path on success, or None when a live process already
    holds it. Stale locks (PID dead / unparsable) are taken over.
    Raises on filesystem errors -- callers decide whether that is fatal.
    """
    path = lock_path(app_dir, name)
    if path.exists():
        pid = _read_pid(path)
        if pid is not None and _pid_alive(pid):
            return None  # live holder -- busy
        log.info("Removing stale lock %s (pid %r is not running)", path, pid)
        try:
            path.unlink()
        except FileNotFoundError:
            pass
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(os.getpid()), encoding="utf-8")
    return path


def release(path: Path | str | None) -> None:
    """Remove a lock we own. Never raises; never deletes a foreign lock
    (a fresh lock left by another process after ours went stale)."""
    if not path:
        return
    try:
        path = Path(path)
        if not path.exists():
            return
        pid = _read_pid(path)
        if pid is None or pid == os.getpid():
            path.unlink()
        else:
            log.info("Not removing %s: now held by pid %s", path, pid)
    except Exception as e:  # lock cleanup must never crash the owner
        log.warning("Lock release failed for %r: %s", path, e)
