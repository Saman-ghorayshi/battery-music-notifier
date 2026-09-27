# battery_notifier/worker_client.py
"""HTTP relay client for the Cloudflare Worker backend.
Handles registration, sending alerts, polling for alerts, and admin actions."""
from __future__ import annotations
import base64
import json
import time
import logging
import requests
from requests.exceptions import Timeout, ConnectionError as ReqConnError
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
        # v2.6.2: "direct" must mean DIRECT. requests with proxies=None
        # silently inherits the Windows system proxy (v2rayN), so the direct
        # route was never direct. An EXPLICIT empty dict overrides env.
        self._direct_proxies = {"http": None, "https": None}
        self._direct_requested = bool(config and getattr(config, "proxy_url", "") == "direct")
        if self._direct_requested:
            self._proxies = self._direct_proxies
        # Route fallback: on a connection failure, retry once on the alternate
        # route (direct <-> local proxy) and stick to whichever worked -- the
        # middlebox resets TLS per fingerprint, not per route, so either can
        # be the one that gets the alert through tonight.
        self._alt_proxies = ({"http": None, "https": None}
                             if self._proxy else
                             {"http": "socks5h://127.0.0.1:10808", "https": "socks5h://127.0.0.1:10808"})
        # v2.6 route fallback: censorship middleboxes reset TLS selectively
        # (python-requests blocked direct one hour, the proxy the next).
        # A failed CONNECTION now retries once on the alternate route and
        # sticks to whichever worked -- the alert must get through.
        self._alt_proxies = None if self._proxies else {"http": "socks5h://127.0.0.1:10808", "https": "socks5h://127.0.0.1:10808"}

    def _headers(self) -> dict:
        h = {"Content-Type": "application/json"}
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        return h

    def _request_with_fallback(self, method: str, path: str, payload: dict | None) -> dict:
        """One attempt on the primary route; on a connection failure, one
        retry on the alternate route (direct <-> local proxy)."""
        import socks  # noqa: F401  (PySocks: makes socks5h proxies available)

        routes = [self._proxies, self._alt_proxies]
        last_err: Exception | None = None
        for proxies in routes:
            try:
                if method == "POST":
                    r = requests.post(
                        f"{self.base_url}{path}", json=payload,
                        headers=self._headers(), proxies=proxies, timeout=REQUEST_TIMEOUT,
                    )
                else:
                    r = requests.get(
                        f"{self.base_url}{path}", headers=self._headers(),
                        proxies=proxies, timeout=REQUEST_TIMEOUT,
                    )
                if proxies is not None and proxies is not self._proxies:
                    # The alternate route worked: make it primary.
                    log.warning("Primary route failed; switched to the alternate route")
                    self._proxies, self._alt_proxies = proxies, self._proxies
                if r.status_code >= 400:
                    try: return r.json()
                    except ValueError: return {"ok": False, "error": f"HTTP {r.status_code}: {r.text[:200]}"}
                return r.json()
            except Timeout as e:
                last_err = e
            except ReqConnError as e:
                last_err = e
            except Exception as e:
                last_err = e
        return {"ok": False, "error": f"connection_failed: {last_err}"}

    def _post(self, path: str, payload: dict) -> dict:
        return self._request_with_fallback("POST", path, payload)

    def _get(self, path: str) -> dict:
        return self._request_with_fallback("GET", path, None)

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
        snapshot_id: Optional[int] = None,
    ) -> bool:
        """Send an alert through the worker relay."""
        payload = {
            "alert_type": alert_type,
            "battery_pct": battery_pct,
            "is_charging": is_charging,
        }
        if snapshot_id:
            payload["snapshot_id"] = snapshot_id
        resp = self._post("/api/alert", payload)
        if resp.get("ok"):
            log.info("Alert sent: type=%s", alert_type)
            return True
        if resp.get("error") == "rate_limited":
            log.warning("Rate limited by worker")
        elif resp.get("error") == "banned":
            log.error("Device is banned by admin — contact admin to resolve")
        else:
            log.error("Alert failed: %s", resp.get("error"))
        return False

    def clear_alert(self, gate_pin: str = None) -> bool:
        """Clear the active alert. Returns False if the worker refused or the
        call failed (e.g. 403 origin_cannot_clear: the device that raised a
        THIEF_ALERT is not allowed to clear it -- a thief re-plugging must not
        silence the fleet). Callers only need to tolerate a False return.

        gate_pin: the alarm PIN typed into the fullscreen gate. The relay
        checks its hash before honoring an origin clear -- the person at the
        keyboard proving they know the PIN is exactly who may silence it."""
        payload = {}
        if gate_pin:
            payload["gate_pin"] = gate_pin
        resp = self._post("/api/clear", payload)
        if resp.get("ok"):
            return True
        error = resp.get("error", "unknown")
        if error == "origin_cannot_clear":
            log.warning(
                "Worker refused THIEF-clear (origin_cannot_clear): "
                "disarm with pass/key instead. This is by design."
            )
        else:
            log.warning("clear_alert failed: %s", error)
        return False

    def poll(self) -> dict:
        """Poll for alert state (laptop checks if phone sent alert)."""
        return self._get("/api/poll")

    # ---- Account arm/disarm (v2.3) ----

    def set_pass_code(self, pass_code: str, current_pass_code: str = None) -> dict:
        """Set (first time) or change the account disarm pass. Raw response."""
        payload = {"pass_code": pass_code}
        if current_pass_code:
            payload["current_pass_code"] = current_pass_code
        return self._post("/api/pass/setup", payload)

    def arm_account(self, armed: bool, pass_code: str = None, key_sig: str = None) -> dict:
        """Arm/disarm the whole account. Disarming needs EITHER the pass OR
        a valid device-key signature over a fresh challenge. Raw response."""
        payload = {"armed": bool(armed)}
        if pass_code:
            payload["pass_code"] = pass_code
        if key_sig:
            payload["key_sig"] = key_sig
        return self._post("/api/arm", payload)

    def set_disarm_key(self, public_key_b64: str, pass_code: str = None) -> dict:
        """Upload the device's SPKI public key for biometric disarm."""
        payload = {"public_key": public_key_b64}
        if pass_code:
            payload["pass_code"] = pass_code
        return self._post("/api/key/setup", payload)

    def arm_challenge(self) -> dict:
        """Fresh one-time challenge for the device-key disarm signature."""
        return self._get("/api/arm/challenge")

    # ---- Intruder snapshots (v2.1) ----

    def upload_snapshot(self, image: bytes) -> Optional[int]:
        """Upload a JPEG/PNG snapshot, returns its snap_id (or None)."""
        b64 = base64.b64encode(image).decode("ascii")
        resp = self._post("/api/snapshot", {"image": b64})
        if resp.get("ok"):
            return resp.get("snap_id")
        log.error("Snapshot upload failed: %s", resp.get("error"))
        return None

    def get_snapshot(self, snap_id: int) -> Optional[bytes]:
        """Fetch a snapshot by id (must belong to this account)."""
        try:
            r = requests.get(
                f"{self.base_url}/api/snapshot/{snap_id}", headers=self._headers(),
                proxies=self._proxies, timeout=REQUEST_TIMEOUT,
            )
            if r.status_code == 200:
                return r.content
            log.error("Snapshot fetch failed: HTTP %s", r.status_code)
        except Exception as e:
            log.error("Snapshot fetch failed: %s", e)
        return None

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

    def admin_unban(self, user_id: int) -> bool:
        """Unban a user."""
        headers = self._headers()
        if hasattr(self, "_admin_session"):
            headers["Authorization"] = f"Bearer {self._admin_session}"
        try:
            r = requests.post(
                f"{self.base_url}/admin/unban",
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
