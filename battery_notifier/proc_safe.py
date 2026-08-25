# battery_notifier/proc_safe.py
"""Bounded subprocess helpers that survive wedged child trees.

subprocess.run(timeout=...) cannot reap children that spawned their own
kids -- those inherit our pipes, so communicate() waits for EOF forever.
We kill the entire tree instead (taskkill /T /F on Windows, process group
on posix).
"""
from __future__ import annotations

import logging
import os
import signal
import subprocess

log = logging.getLogger(__name__)

#: Set by the last call that had to tree-kill a hung child.
last_timed_out = False


def _kill_tree(p: subprocess.Popen) -> None:
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(p.pid), "/T", "/F"],
                           capture_output=True, timeout=10)
        else:
            os.killpg(os.getpgid(p.pid), signal.SIGKILL)
    except Exception:
        pass


def bounded_run(args, timeout: float = 10.0) -> str:
    """Run args, return stdout ('' on failure/timeout). Tree-kills on hang."""
    global last_timed_out
    last_timed_out = False
    p = subprocess.Popen(args, stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE, text=True)
    try:
        out, _ = p.communicate(timeout=timeout)
        return out or ""
    except subprocess.TimeoutExpired:
        last_timed_out = True
        log.warning("subprocess timed out after %.0fs: %s", timeout, args[0])
        _kill_tree(p)
        return ""


def run_ok(args, timeout: float = 10.0) -> bool:
    """Run args, return True on exit code 0. Tree-kills on hang."""
    global last_timed_out
    last_timed_out = False
    p = subprocess.Popen(args, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL)
    try:
        ok = p.wait(timeout=timeout) == 0
        return ok
    except subprocess.TimeoutExpired:
        last_timed_out = True
        log.warning("subprocess timed out after %.0fs: %s", timeout, args[0])
        _kill_tree(p)
        return False
