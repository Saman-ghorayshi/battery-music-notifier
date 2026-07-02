# battery_notifier/worker_client.py
"""HTTP relay client for the Cloudflare Worker backend.
Handles registration, sending alerts, polling for alerts, and admin actions."""
from __future__ import annotations
import json
import time
import logging
import requests
from typing import Optional
from .connection import get_effective_proxy

log = logging.getLogger(__name__)

# Poll interval for laptop to check worker for alerts
POLL_INTERVAL = 2.0
REQUEST_TIMEOUT = 8


class WorkerClient:
    """Talks to the Cloudflare Worker relay."""

    def __init__(self, worker_url: str, token: str = "", config=None):
        self.base_url = worker_url.rstrip("/")
        self.token = token
        self.config = config
        self._proxy = get_effective_proxy(config)
        self._proxies = {"http": self._proxy, "https": self._proxy} if self._proxy else None

    def _headers(self) -> dict:
        h = {"Content-Type": "application/json"}
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        return h

    def _post(self, path: str, payload: dict) -> dict:
        try:
            r = requests.post(
                f"{self.base_url}{path}",
                json=payload,
                headers=self._headers(),
                proxies=self._proxies,
                timeout=REQUEST_TIMEOUT,
            )
            return r.json()
        except Exception as e:
            log.error("Worker POST %s failed: %s", path, e)
            return {"ok": False, "error": str(e)}

    def _get(self, path: str) -> dict:
        try:
            r = requests.get(
                f"{self.base_url}{path}",
                headers=self._headers(),
                proxies=self._proxies,
                timeout=REQUEST_TIMEOUT,
            )
            return r.json()
        except Exception as e:
            log.error("Worker GET %s failed: %s", path, e)
            return {"ok": False, "error": str(e)}

    # ---- Public API ----

    def register(self, device_name: str = "", platform: str = "") -> Optional[str]:
        """Register a new device, returns token or None."""
        resp = self._post("/api/register", {"device_name": device_name, "platform": platform})
        if resp.get("ok"):
            self.token = resp["token"]
            log.info("Registered with worker, token: %s", self.token[:8] + "...")
            return self.token
        log.error("Registration failed: %s", resp.get("error"))
        return None

    def ping(self) -> bool:
        """Send keep-alive."""
        resp = self._post("/api/ping", {})
        return resp.get("ok", False)

    def send_alert(
        self, alert_type: str = "BATTERY",
        battery_pct: int = -1, is_charging: bool = False,
    ) -> bool:
        """Send an alert through the worker relay."""
        resp = self._post("/api/alert", {
            "alert_type": alert_type,
            "battery_pct": battery_pct,
            "is_charging": is_charging,
        })
        if resp.get("ok"):
            log.info("Alert sent: type=%s", alert_type)
            return True
        if resp.get("error") == "rate_limited":
            log.warning("Rate limited by worker")
        else:
            log.error("Alert failed: %s", resp.get("error"))
        return False

    def clear_alert(self) -> bool:
        """Clear the active alert."""
        resp = self._post("/api/clear", {})
        return resp.get("ok", False)

    def poll(self) -> dict:
        """Poll for alert state (laptop checks if phone sent alert)."""
        return self._get("/api/poll")

    # ---- Admin API ----

    def admin_login(self, admin_key: str) -> Optional[str]:
        """Login as admin, returns session key."""
        resp = self._post("/admin/login", {"admin_key": admin_key})
        if resp.get("ok"):
            self._admin_session = resp["session_key"]
            return resp["session_key"]
        return None

    def admin_stats(self) -> dict:
        """Get user stats."""
        headers = self._headers()
        if hasattr(self, "_admin_session"):
            headers["Authorization"] = f"Bearer {self._admin_session}"
        try:
            r = requests.get(
                f"{self.base_url}/admin/stats",
                headers=headers,
                proxies=self._proxies,
                timeout=REQUEST_TIMEOUT,
            )
            return r.json()
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def admin_ban(self, user_id: int) -> bool:
        headers = self._headers()
        if hasattr(self, "_admin_session"):
            headers["Authorization"] = f"Bearer {self._admin_session}"
        try:
            r = requests.post(
                f"{self.base_url}/admin/ban",
                json={"user_id": user_id},
                headers=headers,
                proxies=self._proxies,
                timeout=REQUEST_TIMEOUT,
            )
            return r.json().get("ok", False)
        except Exception:
            return False

    def admin_broadcast(self, alert_type: str = "TEST") -> bool:
        headers = self._headers()
        if hasattr(self, "_admin_session"):
            headers["Authorization"] = f"Bearer {self._admin_session}"
        try:
            r = requests.post(
                f"{self.base_url}/admin/broadcast",
                json={"alert_type": alert_type},
                headers=headers,
                proxies=self._proxies,
                timeout=REQUEST_TIMEOUT,
            )
            return r.json().get("ok", False)
        except Exception:
            return False

    def admin_clear_all(self) -> bool:
        headers = self._headers()
        if hasattr(self, "_admin_session"):
            headers["Authorization"] = f"Bearer {self._admin_session}"
        try:
            r = requests.post(
                f"{self.base_url}/admin/clear-all",
                json={},
                headers=headers,
                proxies=self._proxies,
                timeout=REQUEST_TIMEOUT,
            )
            return r.json().get("ok", False)
        except Exception:
            return False
