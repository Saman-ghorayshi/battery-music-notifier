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
        while not self._stop_event.is_set():
            try:
                info = self.battery.read()
                now_charging = info.charging

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
                log.error("Thief catcher loop error: %s", e)

            time.sleep(POLL_INTERVAL)

        self._disarm()

    def _trigger_alert(self, mode: str, battery_pct: int, verbose: bool = True) -> None:
        """Fire the alert through all configured channels."""
        if verbose:
            print(f"\n  !!! CHARGER UNPLUGGED !!! Battery: {battery_pct}%")
            print("  Triggering alarm...\n")

        # Local alarm: play sound on this device
        if mode in ("local", "both"):
            if self.player:
                self.player.play()
                if verbose:
                    print("  [LOCAL] Alarm playing on this device")

        # Telegram-only mode: send via bot description (no worker, no socket)
        if mode == "telegram":
            self._send_telegram_alert("THIEF_ALERT", verbose)
            return

        # Relay alarm: send to worker, laptop will pick it up
        if mode == "relay" and self.worker:
            success = self.worker.send_alert(
                alert_type="THIEF_ALERT",
                battery_pct=battery_pct,
                is_charging=False,
            )
            if verbose:
                if success:
                    print("  [RELAY] THIEF_ALERT sent to worker, laptop will alarm")
                else:
                    print("  [RELAY] Failed to send alert to worker")
            # Local socket fallback (relay-only mode, worker might be down)
            self._send_local_socket("THIEF_ALERT")

        elif mode == "both":
            if self.worker:
                success = self.worker.send_alert(
                    alert_type="THIEF_ALERT",
                    battery_pct=battery_pct,
                    is_charging=False,
                )
                if verbose:
                    if success:
                        print("  [RELAY] THIEF_ALERT sent to worker, laptop will alarm")
                    else:
                        print("  [RELAY] Failed to send alert to worker")
            else:
                if verbose:
                    print("  [RELAY] No worker configured, using local socket only")
            # Always try local socket in both mode (fallback if worker is down)
            self._send_local_socket("THIEF_ALERT")

        elif mode == "relay" and not self.worker:
            # Relay-only mode with no worker: local socket is the only channel
            self._send_local_socket("THIEF_ALERT")

    def _stop_alert(self, mode: str) -> None:
        """Stop the alarm."""
        if mode in ("local", "both"):
            if self.player:
                self.player.stop()

        if mode == "telegram":
            self._send_telegram_alert("THIEF_STOP", verbose=False)

        if mode in ("relay", "both") and self.worker:
            self.worker.clear_alert()

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
        """Send command via local socket as fallback."""
        try:
            from .connection import send_command_with_ack
            secret = getattr(self.cfg, 'socket_secret', '') if self.cfg else ''
            send_command_with_ack("127.0.0.1", self.local_port, command, timeout=2.0, secret=secret)
        except Exception as e:
            log.debug("Local socket send failed: %s", e)

    def _disarm(self) -> None:
        """Disarm and clean up."""
        # If alert was active, send stop through the same mode that triggered it.
        # _stop_alert handles player.stop(), worker.clear_alert(), and telegram stop.
        if self._alert_active:
            self._stop_alert(self._mode)
        else:
            # No active alert, just stop the player if it's playing
            if self.player:
                self.player.stop()
            if self.worker:
                self.worker.clear_alert()
        self._armed = False
        self._alert_active = False

    @property
    def is_armed(self) -> bool:
        return self._armed

    def disarm(self) -> None:
        """Public disarm method."""
        self._stop_event.set()
        self._disarm()
        print("  Thief Catcher DISARMED.")
