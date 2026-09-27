# battery_notifier/thief_catcher.py
"""Thief Catcher: monitors charger unplug and triggers alerts.

When armed, watches for the transition: charging -> not charging.
If the charger is unplugged while armed, fires an alert immediately.
The alert goes through the worker relay, local socket, or Telegram bot.

Arming modes:
  - Local:    plays alarm sound on this device directly
  - Relay:    sends THIEF_ALERT to worker, laptop polls and plays alarm
  - Both:     does both simultaneously (default)
  - Telegram: sends THIEF_ALERT via Telegram bot description (cloud only)
"""
from __future__ import annotations
import ctypes
import platform
import re
import subprocess
import time
import logging
import threading
from .battery import Battery
from .connection import detect_environment, get_effective_proxy
from .player import Player

log = logging.getLogger(__name__)

# Grace period after arming before monitoring starts (avoids false triggers)
ARM_GRACE_SECONDS = 3
# How often to check battery state
POLL_INTERVAL = 1.0

# Windows lid-close action values (powercfg LIDACTION)
LID_DO_NOTHING = 0
ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001


class KeepAwake:
    """While armed, a sleeping laptop is a blind guard: idle-sleep freezes
    the watcher, and a thief closing the lid blackouts a screaming alarm.
    Two layers, both reverted on disarm:

      1. SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED) from a
         dedicated thread -- blocks idle sleep for as long as we run, and
         the OS clears it automatically if the process dies.
      2. Lid-close action set to "do nothing" (AC + DC), previous values
         remembered and restored on disarm.
    """

    def __init__(self) -> None:
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._old_lid: list[int] | None = None

    def acquire(self, verbose: bool = True) -> None:
        if platform.system() != "Windows":
            return
        self._stop.clear()

        def hold() -> None:
            k32 = ctypes.windll.kernel32
            k32.SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)
            while not self._stop.wait(30):
                # Re-assert periodically in case anything reset the state.
                k32.SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)
            k32.SetThreadExecutionState(ES_CONTINUOUS)

        self._thread = threading.Thread(target=hold, name="thief-keepawake", daemon=True)
        self._thread.start()
        self._old_lid = self._set_lid_action(LID_DO_NOTHING)
        if verbose and self._old_lid is not None:
            print("  Sleep guard: idle sleep blocked, lid close = do nothing (restored on disarm).")

    def release(self) -> None:
        if platform.system() != "Windows":
            return
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=3)
            self._thread = None
        if self._old_lid is not None:
            self._restore_lid_action(self._old_lid)
            self._old_lid = None

    @staticmethod
    def _lid_guids() -> tuple[str, str]:
        # SUB_BUTTONS \ LIDACTION
        return "4f971e89-eebd-4455-a8de-9e59040e7347", "5ca83367-6e45-459f-a27b-476b1d01c936"

    def _query_lid(self) -> list[int] | None:
        try:
            sub, setting = self._lid_guids()
            out = subprocess.run(
                ["powercfg", "/q", "SCHEME_CURRENT", sub, setting],
                capture_output=True, text=True, timeout=10,
            ).stdout
            values = re.findall(r"Index:\s*(0x[0-9a-fA-F]+)", out)
            if len(values) < 2:
                return None
            # Last two = Current AC, Current DC
            return [int(v, 16) for v in values[-2:]]
        except Exception as e:
            log.warning("Could not read lid-close action: %s", e)
            return None

    def _apply_lid(self, value: int) -> bool:
        try:
            sub, setting = self._lid_guids()
            ok = True
            for flag in ("/setacvalueindex", "/setdcvalueindex"):
                r = subprocess.run(
                    ["powercfg", flag, "SCHEME_CURRENT", sub, setting, str(value)],
                    capture_output=True, text=True, timeout=10,
                )
                ok = ok and r.returncode == 0
            # Make the modified scheme active so the change takes effect.
            subprocess.run(
                ["powercfg", "/setactive", "SCHEME_CURRENT"],
                capture_output=True, text=True, timeout=10,
            )
            return ok
        except Exception as e:
            log.warning("Could not change lid-close action: %s", e)
            return False

    def _set_lid_action(self, value: int) -> list[int] | None:
        old = self._query_lid()
        if old is None or (old[0] == value and old[1] == value):
            return None
        if self._apply_lid(value):
            return old
        return None

    def _restore_lid_action(self, old: list[int]) -> None:
        try:
            sub, setting = self._lid_guids()
            subprocess.run(
                ["powercfg", "/setacvalueindex", "SCHEME_CURRENT", sub, setting, str(old[0])],
                capture_output=True, text=True, timeout=10,
            )
            subprocess.run(
                ["powercfg", "/setdcvalueindex", "SCHEME_CURRENT", sub, setting, str(old[1])],
                capture_output=True, text=True, timeout=10,
            )
            subprocess.run(
                ["powercfg", "/setactive", "SCHEME_CURRENT"],
                capture_output=True, text=True, timeout=10,
            )
        except Exception as e:
            log.warning("Could not restore lid-close action: %s", e)


class ThiefCatcher:
    """Monitors charger state and alerts on unplug."""

    def __init__(self, config, player: Player = None, worker_client=None, local_port: int = 8000):
        self.cfg = config
        self.battery = Battery()
        self.player = player or Player(
            config.alarm_files or config.music_files,
            config.volume,
            annoying=True,  # Always loop alarm until disarmed
        )
        self.worker = worker_client
        self.local_port = local_port
        self.env = detect_environment()
        self.effective_proxy = get_effective_proxy(config)
        self._mode = "both"  # Remember mode for _disarm cleanup

        self._stop_event = threading.Event()
        self._armed = False
        self._alert_active = False
        self._keepawake = KeepAwake()
        self._thief_lock = None  # guardlock thief.lock, held while armed
        self._gate_proc = None   # fullscreen PIN gate process (thief only)

    def arm(self, mode: str = "both", verbose: bool = True, force: bool = False) -> None:
        """Start monitoring for charger unplug.

        Args:
            mode: 'local', 'relay', 'both', or 'telegram'
            verbose: print status messages
            force: arm even if device is not currently charging
        """
        # Read initial state
        info = self.battery.read()
        if not info.charging and not force:
            if verbose:
                print("  [WARN] Device is NOT charging right now!")
                print("  Plug in your charger first, then arm the thief catcher.")
                print("  Or run 'battery-music arm --force' to arm anyway (monitors for plug->unplug).")
            return

        if verbose:
            print(f"  Thief Catcher ARMED ({mode} mode)")
            print(f"  Battery: {info.percentage}%, charging: {info.charging}")
            print(f"  Grace period: {ARM_GRACE_SECONDS}s (plug stays connected)")
            print("  If charger is unplugged, alarm will trigger immediately.")
            print("  Press Ctrl+C to disarm.\n")

        self._armed = True
        self._alert_active = False
        self._mode = mode  # Remember mode for _disarm cleanup

        # Hold thief.lock for the whole armed period: the relay listener
        # reads it every poll and stays silent for THIEF episodes while we
        # are the alarm source (no overlapping sirens on one laptop).
        try:
            from . import guardlock
            from .config import APP_DIR
            self._thief_lock = guardlock.acquire(APP_DIR, guardlock.LOCK_THIEF)
            if self._thief_lock is None and verbose:
                print("  [WARN] Another ThiefCatcher holds thief.lock; arming anyway (relay will stay silent for THIEF alerts).")
        except Exception as e:
            log.warning("thief.lock acquire failed: %s", e)
            self._thief_lock = None

        self._keepawake.acquire(verbose)

        # Remember the state at arm time so we can detect unplug-during-grace
        was_charging_at_arm = info.charging

        # Grace period
        grace_end = time.time() + ARM_GRACE_SECONDS
        while time.time() < grace_end and not self._stop_event.is_set():
            time.sleep(0.5)

        if self._stop_event.is_set():
            self._disarm()
            return

        # Re-read battery AFTER grace period to get true initial state.
        try:
            info = self.battery.read()
            was_charging = info.charging
        except Exception as e:
            log.error("Battery read after grace period failed: %s", e)
            was_charging = True  # Assume still charging to avoid false alarm

        # Detect unplug during grace period: was charging at arm time,
        # but not charging after grace. The charger was pulled during
        # the grace window. Trigger immediately, don't wait for the loop.
        if was_charging_at_arm and not was_charging and not self._alert_active:
            if verbose:
                print("  [ALERT] Charger unplugged during grace period!")
            self._trigger_alert(mode, info.percentage, verbose)
            self._alert_active = True

        # Monitoring loop
        consecutive_read_failures = 0
        MAX_READ_FAILURES = 5

        while not self._stop_event.is_set():
            try:
                info = self.battery.read()
                now_charging = info.charging
                consecutive_read_failures = 0
                
                # Detect unplug: was charging, now not
                if was_charging and not now_charging and not self._alert_active:
                    self._trigger_alert(mode, info.percentage, verbose)
                    self._alert_active = True

                # Detect re-plug: was not charging, now charging
                elif not was_charging and now_charging and self._alert_active:
                    if verbose:
                        print("  Charger reconnected. Stopping alarm.")
                    self._stop_alert(mode)
                    self._alert_active = False

                was_charging = now_charging
                
            except KeyboardInterrupt:
                break
            except Exception as e:
                consecutive_read_failures += 1
                log.error("Thief catcher loop error (%d): %s", consecutive_read_failures, e)
                if consecutive_read_failures >= MAX_READ_FAILURES:
                    print(f"  [CRITICAL] Battery read failed {consecutive_read_failures} times!")
                    print("  Thief catcher is BLIND. Triggering failsafe alarm.")
                    if not self._alert_active:
                        self._trigger_alert(mode, -1, verbose=True)
                        self._alert_active = True
            
            time.sleep(POLL_INTERVAL)

        self._disarm()

    def _trigger_alert(self, mode: str, battery_pct: int, verbose: bool = True) -> None:
        if verbose:
            print(f"\n  !!! CHARGER UNPLUGGED !!! Battery: {battery_pct}%")

        # ALWAYS play locally, in every mode: this machine is the one being
        # carried away, so the stolen machine must scream even in relay mode
        # where the "official" alarm is expected from another device.
        if self.player: self.player.play()

        # Fullscreen PIN gate as its own PROCESS: the siren keeps playing
        # until an enrolled owner face is recognized (no PIN at all) or the
        # PIN is typed. A thief closing the window changes nothing.
        if self.cfg and getattr(self.cfg, "alarm_pin", ""):
            from .alarm_gate import spawn_gate
            self._gate_proc = spawn_gate(self.cfg.alarm_pin)
            if self._gate_proc is not None:
                gate_proc_ref = self._gate_proc
                gate_mode = mode
                gate_pin_ref = self.cfg.alarm_pin

                def gate_watch():
                    # Exit code 0 = the owner proved themselves (face or PIN):
                    # silence everything, with the PIN as the clear proof.
                    if gate_proc_ref.wait() == 0:
                        self._stop_alert(gate_mode, gate_pin=gate_pin_ref)

                threading.Thread(target=gate_watch, name="alarm-pin-gate-watch", daemon=True).start()

        if mode == "telegram":
            self._send_telegram_alert("THIEF_ALERT", verbose)
            return

        # Bug #2 Fix: Only send local socket if worker fails or doesn't exist
        worker_ok = False
        if mode in ("relay", "both") and self.worker:
            worker_ok = self.worker.send_alert(
                alert_type="THIEF_ALERT", battery_pct=battery_pct, is_charging=False,
            )
            if verbose:
                print("  [RELAY] sent" if worker_ok else "  [RELAY] failed")
        
        # Fallback to local socket ONLY if worker failed
        if not worker_ok:
            self._send_local_socket("THIEF_ALERT")

    def _stop_alert(self, mode: str, gate_pin: str = None) -> None:
        """Stop the alarm. gate_pin carries the alarm PIN typed into the
        fullscreen gate -- the relay requires it when the origin device
        clears its own THIEF alert (the thief has the token, not the PIN)."""
        # Local siren stops on every mode: _trigger_alert now plays locally
        # in every mode too, so there is always a local sound to stop.
        if self.player:
            self.player.stop()

        if mode == "telegram":
            self._send_telegram_alert("THIEF_STOP", verbose=False)

        if mode in ("relay", "both") and self.worker:
            try:
                ok = self.worker.clear_alert(gate_pin=gate_pin)
                if not ok:
                    # Expected with the new backend: the worker rejects
                    # THIEF-clear by the origin token (403 origin_cannot_clear)
                    # so a thief re-plugging cannot silence the fleet. Never
                    # crash, never retry-loop; the owner disarms with pass/key.
                    log.warning(
                        "Worker did not clear the relay alert "
                        "(likely 403 origin_cannot_clear); it stays active "
                        "until pass/key disarm."
                    )
            except Exception as e:
                log.warning("clear_alert call failed (%s); ignoring", e)

        if mode in ("relay", "both"):
            self._send_local_socket("THIEF_STOP")

    def _send_telegram_alert(self, command: str, verbose: bool = True) -> None:
        """Send alert command via Telegram bot description (cloud-only mode)."""
        if not self.cfg or not getattr(self.cfg, 'telegram_token', ''):
            if verbose:
                print("  [TELEGRAM] No telegram_token configured, cannot send cloud alert.")
            return
        try:
            import requests
            proxies = {"http": self.effective_proxy, "https": self.effective_proxy} if self.effective_proxy else None
            url = f"https://api.telegram.org/bot{self.cfg.telegram_token}/setMyDescription"
            r = requests.post(url, json={"description": command}, proxies=proxies, timeout=5)
            r.raise_for_status()
            if verbose:
                print(f"  [TELEGRAM] {command} sent via bot description")
        except Exception as e:
            log.error("Telegram alert send failed: %s", e)
            if verbose:
                print(f"  [TELEGRAM] Failed to send {command}: {e}")

    def _send_local_socket(self, command: str) -> None:
        """Send command via local socket. Tries discovered server, falls back to localhost."""
        from .connection import send_command_with_ack, ping_server, load_cached_host
        
        secret = getattr(self.cfg, 'socket_secret', '') if self.cfg else ''
        
        # Bug #3 Fix: Don't just hit 127.0.0.1, try the laptop's actual IP
        targets = []
        cached = load_cached_host()
        if cached: targets.append(cached)
        targets.append("127.0.0.1") 
        
        for host in targets:
            if ping_server(host, self.local_port, timeout=1.0):
                send_command_with_ack(host, self.local_port, command, timeout=2.0, secret=secret)
                return

    def _disarm(self) -> None:
        """Disarm and clean up."""
        self._keepawake.release()
        # Close the fullscreen PIN gate process if it is still waiting.
        proc = getattr(self, "_gate_proc", None)
        if proc is not None and proc.poll() is None:
            try: proc.terminate()
            except Exception: pass
            self._gate_proc = None
        # If alert was active, send stop through the same mode that triggered it.
        # _stop_alert handles player.stop(), worker.clear_alert(), and telegram stop.
        if self._alert_active:
            self._stop_alert(self._mode)
        else:
            # No active alert, just stop the player if it's playing
            if self.player:
                self.player.stop()
            if self.worker:
                try:
                    self.worker.clear_alert()
                except Exception as e:
                    log.warning("clear_alert during disarm failed (%s); ignoring", e)
        self._armed = False
        self._alert_active = False
        # Release thief.lock LAST: from now on the relay listener is free to
        # become the alarm source again.
        try:
            if self._thief_lock:
                from . import guardlock
                guardlock.release(self._thief_lock)
        except Exception as e:
            log.warning("thief.lock release failed: %s", e)
        finally:
            self._thief_lock = None

    @property
    def is_armed(self) -> bool:
        return self._armed

    def disarm(self) -> None:
        """Public disarm method."""
        self._stop_event.set()
        self._disarm()
        print("  Thief Catcher DISARMED.")
