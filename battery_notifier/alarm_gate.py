# battery_notifier/alarm_gate.py
"""Fullscreen PIN gate for a ringing alarm.

A thief's first instinct after hearing the siren is to close whatever
window is screaming. This gate is a fullscreen, always-on-top window that
ignores Alt+F4 and the close button, and keeps the alarm semantics intact:
only the correct PIN lets the owner silence it. The PIN lives in
config.toml (alarm_pin, default 6969) and is changeable in the GUI
settings. It is a deterrent, not cryptography -- the real backstops are
the dead-man switch and Telegram.

Runs its own Tk root on the calling thread; call from a daemon thread so
the alarm loop keeps playing underneath until the gate is satisfied.
"""
from __future__ import annotations
import logging
import os

log = logging.getLogger(__name__)


def face_check() -> str | None:
    """One webcam frame -> 'owner' | 'unknown' | 'no_face' | None.
    None = no enrolled model / no camera / no opencv-contrib: the caller
    falls back to the PIN without treating it as a stranger."""
    try:
        import cv2
        import numpy as np
        from .face_guard import load_verdict
        from .intruder_guard import grab_snapshot
        verdict = load_verdict()
        if verdict is None:
            return None
        shot = grab_snapshot(0)
        if not shot:
            return None
        frame = cv2.imdecode(np.frombuffer(shot, np.uint8), cv2.IMREAD_COLOR)
        if frame is None:
            return None
        return verdict(frame)
    except Exception as e:
        log.warning("face check failed: %s", e)
        return None


def show_pin_gate(pin: str, on_success=None, use_face: bool = True) -> bool:
    """Block until either a recognized owner face or the correct PIN.
    Returns True when the alarm may be silenced (face matched the enrolled
    owner, or the PIN was accepted), False when the gate could not be
    shown (non-Windows, no display, tkinter missing)."""
    if os.name != "nt":
        return False

    # Face-first: a recognized owner silences the alarm with no PIN at all.
    # A stranger (or nobody at the camera) gets the PIN prompt. No enrolled
    # model -> straight to the PIN, exactly like before this existed.
    if use_face:
        try:
            verdict = face_check()
            log.info("alarm gate face check: %s", verdict)
            if verdict == "owner":
                return True
        except Exception as e:
            log.warning("face check crashed: %s", e)
    try:
        import tkinter as tk
    except Exception as e:
        log.warning("PIN gate unavailable (tkinter missing): %s", e)
        return False

    result = {"ok": False}

    try:
        root = tk.Tk()
    except Exception as e:
        log.warning("PIN gate could not open a window: %s", e)
        return False

    root.title("ALARM -- PIN required")
    root.attributes("-fullscreen", True)
    root.attributes("-topmost", True)
    root.configure(bg="black")
    root.focus_force()  # the gate owns the keyboard from the first frame

    container = tk.Frame(root, bg="black")
    container.place(relx=0.5, rely=0.5, anchor="center")

    tk.Label(container, text="!! ALARM !!", font=("Segoe UI", 64, "bold"),
             fg="#ff3b30", bg="black").pack(pady=10)
    tk.Label(container, text="Enter PIN to stop the alarm",
             font=("Segoe UI", 20), fg="white", bg="black").pack(pady=10)

    entry = tk.Entry(container, font=("Segoe UI", 32), show="\u2022",
                     justify="center", width=10, bg="#1c1c1e", fg="white",
                     insertbackground="white", relief="flat")
    entry.pack(pady=10, ipady=8)
    entry.focus_set()

    msg = tk.Label(container, text="", font=("Segoe UI", 16),
                   fg="#ff9f0a", bg="black")
    msg.pack(pady=6)

    # The gate keeps LOOKING while it rings: walk back into frame, the
    # camera recognizes an enrolled owner, and the alarm silences with no
    # PIN at all. A stranger stays unrecognized -> the PIN stays required.
    face_state = {"last": None}

    def on_key(_event) -> None:
        # Any key anywhere refocuses the entry so a thief cannot tab away.
        entry.focus_set()

    def check(_event=None) -> None:
        if entry.get().strip() == str(pin):
            result["ok"] = True
            root.destroy()
        else:
            msg.config(text="WRONG PIN -- the alarm keeps playing")
            entry.delete(0, tk.END)

    def on_close() -> None:
        # Closing the gate is not silencing the alarm: refuse and refocus.
        msg.config(text="You cannot close this -- enter the PIN")
        root.after(50, lambda: root.attributes("-topmost", True))

    def face_tick() -> None:
        # Runs on the Tk event loop (scheduled via after), never inline:
        # destroying the root from here must unwind through mainloop, not
        # crash the remaining setup lines.
        if not root.winfo_exists():
            return
        try:
            verdict = face_check()
        except Exception:
            verdict = None
        if not root.winfo_exists():
            return
        if verdict != face_state["last"]:
            face_state["last"] = verdict
            if verdict == "no_face":
                msg.config(text="Looking for your face (recognized owners skip the PIN)...")
            elif verdict == "unknown":
                msg.config(text="Face not recognized -- enter the PIN")
        if verdict == "owner":
            result["ok"] = True
            root.destroy()
            return
        root.after(2000, face_tick)

    # ALL bindings first, THEN schedule the face loop on the event loop.
    entry.bind("<Return>", check)
    root.protocol("WM_DELETE_WINDOW", on_close)
    root.bind("<Key>", on_key)
    root.after(200, face_tick)

    # Thief evidence: whoever is standing at this laptop gets photographed
    # (burst + montage, same as the intruder guard) and the strip uploads
    # to the owner's account, next to the alert. Best-effort -- a dead
    # camera or offline relay must never break the gate.
    import threading as _th2

    def thief_evidence() -> None:
        try:
            from .intruder_guard import capture_burst, snapshot_montage
            from .config import Config as _Cfg
            from .worker_client import WorkerClient as _WC
            frames = capture_burst(0, count=4, interval=0.4)
            image = snapshot_montage(frames) if frames else None
            if image:
                _WC(_Cfg.load().worker_url, _Cfg.load().worker_token, _Cfg.load()).upload_snapshot(image)
                log.info("thief evidence uploaded (%d bytes)", len(image))
        except Exception as e:
            log.warning("thief evidence failed: %s", e)

    _th2.Thread(target=thief_evidence, name="thief-evidence", daemon=True).start()

    root.mainloop()

    if result["ok"] and on_success:
        try:
            on_success()
        except Exception:
            log.exception("PIN gate on_success callback failed")
    return result["ok"]


def spawn_gate(pin: str):
    """Start the gate as a detached PROCESS (a Tk window in a secondary
    thread of a console process never paints reliably on Windows). Returns
    the Popen handle, or None when a gate is already running -- one gate
    per machine, so the owner never types the PIN twice. Exit code 0 =
    PIN accepted (or a face was recognized); 1 = closed without either."""
    import subprocess
    import sys
    from . import guardlock
    from .config import APP_DIR
    try:
        if guardlock.acquire(APP_DIR, "gate.lock") is None:
            log.info("PIN gate already running -- not spawning a second one")
            return None
    except Exception as e:
        log.warning("gate.lock check failed: %s", e)
    exe = sys.executable
    if exe.lower().endswith("python.exe"):
        pythonw = exe[:-10] + "pythonw.exe"
        if os.path.exists(pythonw):
            exe = pythonw  # no console box behind the gate
    # NO DETACHED_PROCESS: a detached process has no visible desktop, and
    # the gate window would be INVISIBLE while the siren plays (seen live).
    # pythonw already has no console, so plain Popen shows the window.
    return subprocess.Popen([exe, "-m", "battery_notifier.alarm_gate", str(pin)])


if __name__ == "__main__":
    import sys as _sys
    _pin = _sys.argv[1] if len(_sys.argv) > 1 else "6969"
    _ok = show_pin_gate(_pin, use_face=True)
    _sys.exit(0 if _ok else 1)
