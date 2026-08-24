# battery_notifier/gui/services.py
"""Background services for the desktop GUI.

Every long-running piece (relay listener, socket server, thief catcher,
worker heartbeat) runs as a daemon thread -- the same pattern proven in the
integration harnesses. State flows through a StatusBus: a plain dict guarded
by a Lock that the UI polls via a JS timer (simplest, no push channel needed).

This module is import-safe WITHOUT pywebview/pystray installed.
"""
from __future__ import annotations

import copy
import logging
import threading
import time

from ..battery import Battery
from ..config import Config
from ..connection import get_effective_proxy
from ..player import Player

log = logging.getLogger(__name__)

RELAY_POLL_INTERVAL = 2.0  # seconds between worker polls (matches cli relay)
HEARTBEAT_INTERVAL = 30.0  # seconds between worker /health checks


class StatusBus:
    """Thread-safe state store: dict + Lock. The UI polls snapshots."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._state: dict = {
            "battery_pct": -1,
            "charging": False,
            "thief": {"armed": False, "alert_active": False, "mode": "both"},
            "relay": {"running": False, "error": "", "last_alert": ""},
            "serve": {"running": False, "error": ""},
            "heartbeat": {"ok": None, "checked_at": 0.0},
        }

    def update(self, section: str | None = None, **kwargs) -> None:
        with self._lock:
            if section:
                self._state.setdefault(section, {}).update(kwargs)
            else:
                self._state.update(kwargs)

    def snapshot(self) -> dict:
        with self._lock:
            return copy.deepcopy(self._state)


class RelayService(threading.Thread):
    """Polls the worker and plays the alarm when an alert is active.

    Mirrors the proven `battery-music relay` loop from cli.py, including
    auto re-register on unauthorized (safe cutover for hashed tokens).
    """

    def __init__(self, cfg: Config, bus: StatusBus, worker=None, player: Player | None = None):
        super().__init__(name="relay-service", daemon=True)
        self.cfg = cfg
        self.bus = bus
        self.player = player
        self._worker = worker
        self._stop_event = threading.Event()
        self._last_alert_active = False
        self._consecutive_errors = 0

    def stop(self) -> None:
        self._stop_event.set()

    # -- internals ---------------------------------------------------------

    def _make_worker(self):
        from ..worker_client import WorkerClient
        return WorkerClient(self.cfg.worker_url, self.cfg.worker_token, self.cfg)

    def _save_token(self, token: str) -> None:
        self.cfg.worker_token = token
        try:
            from ..cli import _save_worker_token
            _save_worker_token(token)
        except Exception as e:
            log.warning("Could not persist worker token: %s", e)

    def run(self) -> None:
        if not self.cfg.worker_url:
            self.bus.update("relay", running=False, error="no worker_url configured")
            return

        worker = self._worker or self._make_worker()
        if not self.cfg.worker_token:
            env_name = "desktop"
            token = worker.register(device_name=env_name, platform="GUI")
            if token:
                self._save_token(token)
                worker.token = token
            else:
                self.bus.update("relay", running=False, error="registration failed")
                return

        self.bus.update("relay", running=True, error="")
        while not self._stop_event.is_set():
            try:
                resp = worker.poll()
                self._consecutive_errors = 0
                error = resp.get("error", "") if not resp.get("ok") else ""
                if error == "unauthorized":
                    log.info("Worker rejected token, re-registering")
                    token = worker.register(device_name="desktop", platform="GUI")
                    if token:
                        self._save_token(token)
                        worker.token = token
                    else:
                        self.bus.update("relay", error="re-registration failed")
                elif error == "banned":
                    self.bus.update("relay", error="device banned by admin")
                    break
                elif resp.get("ok"):
                    self.bus.update("relay", error="")
                    alert_active = bool(resp.get("alert_active"))
                    alert_type = resp.get("alert_type", "")
                    if alert_active and not self._last_alert_active:
                        self.bus.update("relay", last_alert=f"{alert_type} @ {time.strftime('%H:%M:%S')}")
                        if alert_type == "THIEF_ALERT" and self.player:
                            self.player.play()
                    elif not alert_active and self._last_alert_active:
                        if self.player:
                            self.player.stop()
                    self._last_alert_active = alert_active
            except Exception as e:
                self._consecutive_errors += 1
                if self._consecutive_errors <= 3:
                    self.bus.update("relay", error=str(e))
                log.error("Relay poll error (%d): %s", self._consecutive_errors, e)
            self._stop_event.wait(RELAY_POLL_INTERVAL)

        if self.player:
            try:
                self.player.stop()
            except Exception:
                pass
        self.bus.update("relay", running=False)


class ServeService(threading.Thread):
    """Runs NotificationServer (socket listener) inside a daemon thread."""

    def __init__(self, cfg: Config, bus: StatusBus):
        super().__init__(name="serve-service", daemon=True)
        self.cfg = cfg
        self.bus = bus
        self.server = None

    def stop(self) -> None:
        if self.server:
            self.server.stop()

    def run(self) -> None:
        from ..remote import NotificationServer
        try:
            self.server = NotificationServer(self.cfg, "auto", 8000)
            self.bus.update("serve", running=True, error="")
            self.server.run()
        except Exception as e:
            log.exception("Serve service crashed")
            self.bus.update("serve", running=False, error=str(e))
        finally:
            self.bus.update("serve", running=False)


class ThiefService:
    """Arms/disarms a ThiefCatcher on its own thread."""

    def __init__(self, cfg: Config, bus: StatusBus):
        self.cfg = cfg
        self.bus = bus
        self.catcher = None
        self._thread: threading.Thread | None = None

    def arm(self, mode: str = "both", force: bool = False) -> dict:
        if self.is_alive():
            return {"ok": False, "error": "already armed"}
        from ..thief_catcher import ThiefCatcher

        worker = None
        if mode in ("relay", "both") and self.cfg.worker_url:
            from ..worker_client import WorkerClient
            worker = WorkerClient(self.cfg.worker_url, self.cfg.worker_token, self.cfg)

        alarm_files = self.cfg.alarm_files or self.cfg.music_files
        player = Player(alarm_files, self.cfg.volume, annoying=True) if alarm_files else None
        self.catcher = ThiefCatcher(
            self.cfg, player=player, worker_client=worker, local_port=8000,
        )
        self._thread = threading.Thread(
            target=self._run_catcher, args=(self.catcher, mode, force),
            name="thief-service", daemon=True,
        )
        self._thread.start()
        self.bus.update("thief", armed=True, alert_active=False, mode=mode)
        return {"ok": True}

    def _run_catcher(self, catcher, mode: str, force: bool) -> None:
        try:
            catcher.arm(mode=mode, verbose=False, force=force)
        except Exception as e:
            log.exception("Thief catcher crashed")
        finally:
            self.bus.update("thief", armed=getattr(catcher, "_armed", False),
                            alert_active=False)

    def disarm(self) -> dict:
        if self.catcher:
            try:
                self.catcher.disarm()
            except Exception as e:
                log.warning("Disarm error: %s", e)
        if self._thread:
            self._thread.join(timeout=5)
        self.bus.update("thief", armed=False, alert_active=False)
        return {"ok": True}

    def is_alive(self) -> bool:
        return bool(self._thread and self._thread.is_alive())


class HeartbeatService(threading.Thread):
    """Periodic GET {worker}/health so the UI has a live heartbeat dot."""

    def __init__(self, cfg: Config, bus: StatusBus):
        super().__init__(name="heartbeat-service", daemon=True)
        self.cfg = cfg
        self.bus = bus
        self._stop_event = threading.Event()

    def stop(self) -> None:
        self._stop_event.set()

    def run(self) -> None:
        proxy = get_effective_proxy(self.cfg)
        proxies = {"http": proxy, "https": proxy} if proxy else None
        while not self._stop_event.wait(HEARTBEAT_INTERVAL):
            if not self.cfg.worker_url:
                continue
            ok = False
            try:
                import requests
                r = requests.get(f"{self.cfg.worker_url.rstrip('/')}/health",
                                 proxies=proxies, timeout=5)
                ok = r.status_code == 200
            except Exception as e:
                log.debug("Heartbeat failed: %s", e)
            self.bus.update("heartbeat", ok=ok, checked_at=time.time())


class ServiceManager:
    """Owns config + every background service; the single object the JS
    bridge talks to."""

    def __init__(self, config_path=None):
        self.cfg = Config.load(config_path)
        self.config_path = config_path
        self.bus = StatusBus()
        self.relay: RelayService | None = None
        self.serve: ServeService | None = None
        self.thief = ThiefService(self.cfg, self.bus)
        self.heartbeat = HeartbeatService(self.cfg, self.bus)
        self.heartbeat.start()
        self._battery = Battery()

    # -- state -------------------------------------------------------------

    def reload_config(self, path=None) -> None:
        self.cfg = Config.load(path or self.config_path)
        self.thief.cfg = self.cfg

    def get_state(self) -> dict:
        state = self.bus.snapshot()
        try:
            info = self._battery.read()
            state["battery_pct"] = info.percentage
            state["charging"] = bool(info.charging)
        except Exception as e:
            log.debug("Battery read failed: %s", e)
        return state

    # -- relay -------------------------------------------------------------

    def start_relay(self) -> dict:
        if self.relay and self.relay.is_alive():
            return {"ok": False, "error": "already running"}
        if not self.cfg.worker_url:
            return {"ok": False, "error": "no worker_url configured"}
        player = None
        alarm_files = self.cfg.alarm_files or self.cfg.music_files
        if alarm_files:
            player = Player(alarm_files, self.cfg.volume, annoying=True)
        self.relay = RelayService(self.cfg, self.bus, player=player)
        self.relay.start()
        return {"ok": True}

    def stop_relay(self) -> dict:
        if not (self.relay and self.relay.is_alive()):
            return {"ok": False, "error": "not running"}
        self.relay.stop()
        self.relay.join(timeout=10)
        return {"ok": True}

    # -- serve (local socket) ---------------------------------------------

    def start_serve(self) -> dict:
        if self.serve and self.serve.is_alive():
            return {"ok": False, "error": "already running"}
        self.serve = ServeService(self.cfg, self.bus)
        self.serve.start()
        # give the bind a moment to fail loudly if port is taken
        self.serve.join(timeout=0.3)
        err = self.bus.snapshot()["serve"].get("error", "")
        return {"ok": not err, "error": err}

    def stop_serve(self) -> dict:
        if not (self.serve and self.serve.is_alive()):
            return {"ok": False, "error": "not running"}
        self.serve.stop()
        self.serve.join(timeout=5)
        return {"ok": True}

    # -- thief catcher -----------------------------------------------------

    def arm_thief(self, mode: str = "both", force: bool = False) -> dict:
        result = self.thief.arm(mode=mode, force=force)
        return result

    def disarm_thief(self) -> dict:
        return self.thief.disarm()

    # -- shutdown ----------------------------------------------------------

    def shutdown_all(self) -> None:
        try:
            self.heartbeat.stop()
        except Exception:
            pass
        try:
            self.disarm_thief()
        except Exception:
            pass
        try:
            self.stop_relay()
        except Exception:
            pass
        try:
            self.stop_serve()
        except Exception:
            pass
