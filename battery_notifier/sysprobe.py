# battery_notifier/sysprobe.py
"""Wedge-proof system probes.

platform.system() queries WMI on Windows, and WMI occasionally hangs
system-wide (Hyper-V/WSL churn is a common trigger -- we hit it live).
Every platform lookup in the package goes through safe_system() so a
wedged WMI service degrades to a sane guess instead of freezing the app.
"""
from __future__ import annotations

import logging
import os
import threading

import platform as _platform_mod

log = logging.getLogger(__name__)

_cache = None
wmi_wedged = False  #: True once platform.system() had to be timed out


def safe_system(timeout: float = 4.0) -> str:
    """platform.system() in a daemon thread with a hard timeout."""
    global _cache, wmi_wedged
    if _cache is not None:
        return _cache

    result: dict = {}

    def _call():
        try:
            result["v"] = _platform_mod.system()
        except Exception:
            pass

    t = threading.Thread(target=_call, daemon=True)
    t.start()
    t.join(timeout=timeout)

    if "v" not in result:
        # WMI wedged: os.name is instant and always available
        wmi_wedged = True
        result["v"] = "Windows" if os.name == "nt" else (
            "Java" if os.name == "java" else "Linux")
        log.warning("platform.system() timed out after %.0fs; assuming %s",
                    timeout, result["v"])

    _cache = result["v"]
    return result["v"]
