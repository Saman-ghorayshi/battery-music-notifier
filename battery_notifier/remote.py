# battery_notifier/remote.py
from __future__ import annotations
import socket
import threading
import time
import logging
import requests
from .player import Player
from .adb_helper import auto_setup_usb_bridge
from .connection import (
    detect_environment,
    smart_find_server,
    smart_bind_server,
    send_command_with_ack,
    ping_server,
    save_cached_host,
    load_cached_host,
    get_effective_proxy,
    ACK_PREFIX,
    BEACON_MESSAGE,
    DISCOVERY_UDP_PORT,
)

log = logging.getLogger(__name__)


class RemoteMonitor:
    """Client-side monitor: reads battery, sends commands to laptop server."""

    def __init__(self, config, host: str, port: int, conn_mode: str = "auto"):
        self.cfg = config
        self.host = host
        self.port = port
        self.conn_mode = conn_mode
        self._stop_event = threading.Event()
        self.resolved_host = None
        self.env = detect_environment()

        # Auto-apply proxy if none configured
        self.effective_proxy = get_effective_proxy(config)
        if self.effective_proxy and (not config or not config.proxy_url):
            if config:
                config.proxy_url = self.effective_proxy
                log.info("Auto-applied detected proxy: %s", self.effective_proxy)

        from .battery import Battery
        self.battery = Battery()

    def _resolve_host(self, verbose: bool = True) -> str | None:
        """Figure out where the server is using all available methods."""
        # Manual host specified
        if self.host and self.host.lower() != "auto":
            if ping_server(self.host, self.port, timeout=2.0):
                return self.host
            if verbose:
                print(f"  Specified host {self.host} did not respond to PING")
            return None

        # Auto-discovery
        if verbose:
            print("  Auto-discovering server...")
        found = smart_find_server(self.port, verbose=verbose)
        return found

    def _has_internet(self) -> bool:
        """Check if cloud internet (Telegram API) is reachable, using proxy if available."""
        proxies = {"http": self.effective_proxy, "https": self.effective_proxy} if self.effective_proxy else None
        try:
            r = requests.get("https://api.telegram.org", proxies=proxies, timeout=3.0, stream=True)
            r.close()
            return True
        except requests.RequestException:
            return False

    def _dispatch_client_web_alerts(self, command: str = "START") -> bool:
        """Send cloud alerts directly from mobile client when local network fails.

        Uses the bot description trick (setMyDescription), which only needs
        a bot token -- no chat_id required. The laptop polls the description.
        """
        if not self.cfg:
            return False
        proxies = {"http": self.effective_proxy, "https": self.effective_proxy} if self.effective_proxy else None

        if self.cfg.telegram_token:
            try:
                url = f"https://api.telegram.org/bot{self.cfg.telegram_token}/setMyDescription"
                payload = {"description": command}
                r = requests.post(url, json=payload, proxies=proxies, timeout=5)
                r.raise_for_status()
                resp = r.json()
                if resp.get("ok"):
                    print(f"  [Cloud] Telegram command dispatched: {command}")
                    log.info("Client fallback Telegram command sent: %s", command)
                    return True
                else:
                    log.error("Telegram API returned ok=false: %s", resp.get("description", "unknown"))
                    return False
            except Exception as e:
                log.error("Cloud fallback failed: %s", e)
                return False
        return False

    def _print_env_status(self) -> None:
        """Print environment status at startup."""
        print(f"  Remote Monitor Client active on {self.env.platform_name}")
        print(f"  Local IP: {self.env.local_ip or 'unknown'}, Subnet: {self.env.subnet or 'none'}")

        if self.conn_mode != "auto":
            print(f"  Connection mode: {self.conn_mode}")

        if self.env.is_vpn:
            print(f"  [VPN] Active: {self.env.vpn_name}")
            print("  [VPN] Local network discovery (UDP, subnet scan) will be skipped.")
            print("  [VPN] USB tunnel or Telegram cloud fallback will be used instead.")

        if self.effective_proxy:
            if self.cfg and self.cfg.proxy_url:
                print(f"  Proxy: {self.effective_proxy} (from config)")
            else:
                print(f"  Proxy: {self.effective_proxy} (auto-detected)")
        else:
            print("  Proxy: none (direct connection)")

        print(f"  Battery thresholds -> Min: {self.cfg.min_percentage}%, Max: {self.cfg.max_percentage}%")
        print("  Press Ctrl+C to stop.\n")

    def run(self) -> None:
        self._print_env_status()
        
        # ADB Forward Fix: If desktop is client and phone is server, setup forward bridge
        use_local = self.conn_mode in ("auto", "local")
        if use_local and (self.env.is_windows or self.env.is_macos or self.env.is_linux):
            print("  [Desktop Client] Checking for USB ADB bridge to phone...")
            auto_setup_usb_bridge(mode="forward", port=self.port, max_retries=3)
            
        # In telegram mode, skip local discovery entirely
        if self.conn_mode == "telegram":
            print("  Telegram-only mode: skipping local server discovery.")
            if not self.cfg.telegram_token:
                print("  [ERROR] Telegram mode requires telegram_token in config.")
                print("  Run 'battery-music init' and enter a Telegram bot token.")
                return
            print("  Cloud fallback will be used for all alerts.\n")
        else:
            # Initial connection establishment (auto and local modes)
            print("  Establishing connection to laptop server...")
            self.resolved_host = self._resolve_host(verbose=True)

            if self.resolved_host:
                print(f"  CONNECTED to server at {self.resolved_host}:{self.port}\n")
            else:
                print("  Could not find laptop server via any local method.")
                if self.env.is_vpn:
                    print("  [VPN] VPN blocks local discovery. Options:")
                    print("    - Connect via USB cable (battery-music client --host 127.0.0.1)")
                    if self.conn_mode == "auto":
                        print("    - Use Telegram cloud fallback (will activate automatically if internet works)")
                elif self.env.is_termux:
                    print("  Tips for Termux:")
                    print("    - Make sure laptop is running: battery-music serve")
                    print("    - Or use USB: battery-music serve  +  battery-music client --host 127.0.0.1")
                    if self.conn_mode == "auto":
                        print("    - Cloud fallback (Telegram) will be used if internet is available")
                else:
                    print("  Tips:")
                    print("    - Make sure server is running: battery-music serve")
                    print("    - Or use: battery-music start  (auto-detects role)")
                    if self.conn_mode == "local":
                        print("    - Local-only mode: Telegram fallback disabled.")
                print()

        is_playing = False
        connection_lost_count = 0
        max_reconnect_attempts = 3

        while not self._stop_event.is_set():
            try:
                info = self.battery.read()
                pct = info.percentage
                charging = info.charging

                should_alert = False
                if charging and pct >= self.cfg.max_percentage:
                    should_alert = True
                elif not charging and pct <= self.cfg.min_percentage:
                    should_alert = True

                if should_alert and not is_playing:
                    print(f"  Battery alert: {pct}% (charging={charging})")

                    # Re-resolve if we lost connection
                    if not self.resolved_host:
                        print("  Re-attempting discovery...")
                        self.resolved_host = self._resolve_host(verbose=False)

                    if self.resolved_host:
                        success = send_command_with_ack(
                            self.resolved_host, self.port, "START",
                            secret=getattr(self.cfg, 'socket_secret', ''),
                        )
                        if success:
                            is_playing = True
                            connection_lost_count = 0
                            print(f"  [OK] Laptop acknowledged START at {self.resolved_host}")
                        else:
                            connection_lost_count += 1
                            print(f"  [FAIL] Laptop did not acknowledge (attempt {connection_lost_count}/{max_reconnect_attempts})")
                            if connection_lost_count >= max_reconnect_attempts:
                                print("  Switching to cloud fallback...")
                                self.resolved_host = None
                    else:
                        # Cloud fallback (auto mode only; local mode stays local)
                        if self.conn_mode == "local":
                            print("  [WARN] Local-only mode: no server and no Telegram fallback.")
                        elif self._has_internet():
                            print("  Routing through Telegram cloud fallback...")
                            sent = self._dispatch_client_web_alerts()
                            if sent:
                                is_playing = True
                                # Reset counter so re-discovered connections get
                                # a clean slate instead of instant-thrashing back
                                # to cloud on the first failed ACK
                                connection_lost_count = 0
                            else:
                                print("  [WARN] Cloud fallback send failed, will retry next cycle")
                        else:
                            print("  [CRITICAL] No local server and no internet - cannot alert!")

                elif not should_alert and is_playing:
                    print(f"  Battery normalized: {pct}% (charging={charging})")
                    if self.resolved_host:
                        success = send_command_with_ack(
                            self.resolved_host, self.port, "STOP",
                            secret=getattr(self.cfg, 'socket_secret', ''),
                        )
                        if success:
                            print(f"  [OK] Laptop acknowledged STOP")
                        else:
                            print(f"  [WARN] Laptop did not acknowledge STOP, resetting state")
                    else:
                        # Cloud fallback: send STOP via Telegram (auto mode only)
                        if self.conn_mode != "local" and self._has_internet():
                            print("  Routing STOP through Telegram cloud fallback...")
                            self._dispatch_client_web_alerts("STOP")
                    is_playing = False

            except KeyboardInterrupt:
                print("\n  Shutting down client...")
                break
            except Exception as e:
                log.error("Client loop error: %s", e)
                print(f"  [WARN] Error: {e}")

            time.sleep(self.cfg.poll_interval)


class NotificationServer:
    """Server-side: listens for client commands, plays music, sends ACKs."""

    def __init__(self, config, host: str = "auto", port: int = 8000, conn_mode: str = "auto"):
        self.cfg = config
        self.host = host
        self.port = port
        self.conn_mode = conn_mode
        self.player = Player(config.music_files, config.volume, config.annoying) if config else None
        self._stop_event = threading.Event()
        self._beacon_thread = None
        self._telegram_thread = None
        self.env = detect_environment()

        # Auto-apply proxy if none configured
        self.effective_proxy = get_effective_proxy(config)
        if self.effective_proxy and (not config or not config.proxy_url):
            if config:
                config.proxy_url = self.effective_proxy
                log.info("Auto-applied detected proxy: %s", self.effective_proxy)

    def _run_udp_beacon(self) -> None:
        """Broadcast UDP beacon so clients can auto-discover this server."""
        log.info("UDP beacon broadcasts active")
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            while not self._stop_event.is_set():
                try:
                    s.sendto(BEACON_MESSAGE, ("255.255.255.255", DISCOVERY_UDP_PORT))
                except Exception as e:
                    log.debug("Beacon broadcast failed: %s", e)
                time.sleep(2.0)

    def _poll_telegram(self) -> None:
        """Poll Telegram Bot Description for START/STOP commands from phone."""
        log.info("Telegram polling active")
        proxies = {"http": self.effective_proxy, "https": self.effective_proxy} if self.effective_proxy else None
        base_url = f"https://api.telegram.org/bot{self.cfg.telegram_token}"
        last_cmd = ""

        while not self._stop_event.is_set():
            if not self.cfg.telegram_token:
                time.sleep(5)
                continue
            try:
                r = requests.get(f"{base_url}/getMyDescription", proxies=proxies, timeout=5)
                if r.status_code == 200 and r.json().get("ok"):
                    desc = r.json().get("result", {}).get("description", "").upper().strip()
                    if desc != last_cmd:
                        if desc in ("START", "THIEF_ALERT"):  # Bug #5 Fix: exact match
                            log.info("Telegram command: %s", desc)
                            if self.player: self.player.play()
                            threading.Thread(target=self._dispatch_web_alerts, daemon=True).start()
                            try:
                                cr = requests.post(f"{base_url}/setMyDescription", json={"description": ""}, proxies=proxies, timeout=5)
                                cr.raise_for_status()
                            except Exception as e:
                                log.warning("Failed to clear Telegram description: %s", e)
                            last_cmd = ""
                        elif desc in ("STOP", "THIEF_STOP"):  # Bug #5 Fix: exact match
                            log.info("Telegram command: %s", desc)
                            if self.player: self.player.stop()
                            try:
                                cr = requests.post(f"{base_url}/setMyDescription", json={"description": ""}, proxies=proxies, timeout=5)
                                cr.raise_for_status()
                            except Exception as e:
                                log.warning("Failed to clear Telegram description: %s", e)
                            last_cmd = ""
                        else:
                            last_cmd = desc
            except Exception:
                pass
            time.sleep(2)

    def _dispatch_web_alerts(self) -> None:
        """Send external notifications (Telegram, Email) in a separate thread."""
        if not self.cfg:
            return
        proxies = {"http": self.effective_proxy, "https": self.effective_proxy} if self.effective_proxy else None

        # Telegram
        if self.cfg.telegram_token and self.cfg.telegram_chat_id:
            try:
                url = f"https://api.telegram.org/bot{self.cfg.telegram_token}/sendMessage"
                payload = {"chat_id": self.cfg.telegram_chat_id, "text": "Battery alert: threshold crossed!"}
                r = requests.post(url, json=payload, proxies=proxies, timeout=5)
                if r.status_code == 200 and r.json().get("ok"):
                    log.info("Telegram notification sent.")
                else:
                    log.warning("Telegram send failed: HTTP %s, response: %s", r.status_code, r.text[:200])
            except Exception as e:
                log.error("Telegram notification failed: %s", e)

        # Email
        if self.cfg.email_sender and self.cfg.email_password and self.cfg.email_receiver:
            smtp_server = None
            try:
                import smtplib
                from email.mime.text import MIMEText
                msg = MIMEText("Battery alert: threshold crossed!")
                msg["Subject"] = "Battery Music Notifier Alert"
                msg["From"] = self.cfg.email_sender
                msg["To"] = self.cfg.email_receiver
                if self.cfg.email_smtp_port == 465:
                    smtp_server = smtplib.SMTP_SSL(self.cfg.email_smtp_server, self.cfg.email_smtp_port, timeout=10)
                else:
                    smtp_server = smtplib.SMTP(self.cfg.email_smtp_server, self.cfg.email_smtp_port, timeout=10)
                    smtp_server.starttls()
                smtp_server.login(self.cfg.email_sender, self.cfg.email_password)
                smtp_server.send_message(msg)
                log.info("Email notification sent.")
            except Exception as e:
                log.error("Email notification failed: %s", e)
            finally:
                if smtp_server is not None:
                    try:
                        smtp_server.quit()
                    except Exception:
                        try:
                            smtp_server.close()
                        except Exception:
                            pass

    def _handle_client(self, conn: socket.socket, addr: tuple) -> None:
        """Handle a single client connection with ACK protocol."""
        try:
            conn.settimeout(2.0)  # Prevent infinite blocking on empty connections
            data = conn.recv(1024).decode("utf-8").strip()
            if not data:
                return

            # PING/PONG health check (no auth needed for discovery)
            if data == "PING":
                conn.sendall(b"PONG")
                log.debug("PING from %s answered", addr[0])
                return

            # Shared-secret authentication for commands
            # If socket_secret is configured, commands must be prefixed with the secret:
            # Format: "SECRET:START" or "SECRET:THIEF_ALERT"
            # If no secret is configured, commands are accepted as-is (backward compatible)
            secret = getattr(self.cfg, 'socket_secret', '') if self.cfg else ''
            if secret:
                # Bug #18 Fix: Use startswith to handle colons in secret
                if data.startswith(secret + ":"):
                    data = data[len(secret) + 1:]
                else:
                    log.warning("Unauthorized command from %s (bad or missing secret)", addr[0])
                    conn.sendall(b"ERR:UNAUTHORIZED")
                    return

            # START/STOP/THIEF_ALERT/THIEF_STOP commands
            # THIEF_ALERT and THIEF_STOP are mapped to play/stop for the alarm
            if data in ("START", "STOP", "THIEF_ALERT", "THIEF_STOP"):
                log.info("Command %s from %s", data, addr[0])
                print(f"  [{time.strftime('%H:%M:%S')}] {data} from {addr[0]}")

                if data in ("START", "THIEF_ALERT"):
                    if self.player: self.player.play()
                    threading.Thread(target=self._dispatch_web_alerts, daemon=True).start()
                elif data in ("STOP", "THIEF_STOP"):
                    if self.player: self.player.stop()

                # Send ACK confirmation back to client
                ack = f"{ACK_PREFIX}{data}"
                conn.sendall(ack.encode("utf-8"))
                log.info("ACK sent for %s", data)
            else:
                log.debug("Unknown command from %s: %s", addr[0], data)
                conn.sendall(b"ERR:UNKNOWN_CMD")
        except Exception as e:
            log.error("Client handler error: %s", e)

    def _print_env_status(self) -> None:
        """Print environment status at startup."""
        print(f"  Notification Server on {self.env.platform_name}")
        print(f"  Local IP: {self.env.local_ip or 'unknown'}, Subnet: {self.env.subnet or 'none'}")

        if self.env.is_vpn:
            print(f"  [VPN] Active: {self.env.vpn_name}")
            print("  [VPN] UDP beacon may not reach clients behind the VPN tunnel.")

        if self.effective_proxy:
            if self.cfg and self.cfg.proxy_url:
                print(f"  Proxy: {self.effective_proxy} (from config)")
            else:
                print(f"  Proxy: {self.effective_proxy} (auto-detected)")
        else:
            print("  Proxy: none (direct connection)")

    def run(self) -> None:
        self._print_env_status()

        use_local = self.conn_mode in ("auto", "local")
        use_telegram = self.conn_mode in ("auto", "telegram")

        if self.conn_mode != "auto":
            print(f"  Connection mode: {self.conn_mode}")

        # USB bridge setup (local modes only)
        if use_local:
            print("  Checking for USB ADB bridge...")
            auto_setup_usb_bridge(mode="reverse", port=self.port, max_retries=3)

            # UDP beacon for auto-discovery
            self._beacon_thread = threading.Thread(target=self._run_udp_beacon, daemon=True)
            self._beacon_thread.start()
            print("  UDP beacon active (port 8002)")

        # Telegram cloud polling
        if use_telegram and self.cfg.telegram_token:
            print("  Telegram cloud polling active")
            self._telegram_thread = threading.Thread(target=self._poll_telegram, daemon=True)
            self._telegram_thread.start()
        elif use_telegram and not self.cfg.telegram_token:
            print("  [ERROR] Telegram mode selected but no telegram_token configured.")
            print("  Run 'battery-music init' and enter a Telegram bot token.")
            return

        # Socket binding (local modes only)
        if use_local:
            # Smart bind: try 0.0.0.0 first, fallback 127.0.0.1
            s = smart_bind_server(self.host, self.port)
            if not s:
                print(f"  [ERROR] Cannot bind to {self.host}:{self.port}")
                print("  Try a different port: battery-music serve --port 8001")
                return

            bound_host = s.getsockname()[0]
            if bound_host == "0.0.0.0":
                display = self.env.local_ip or "0.0.0.0"
                print(f"  Listening on {display}:{self.port} (all interfaces)")
                if self.env.local_ip:
                    print(f"  Phone can connect to: {self.env.local_ip}:{self.port}")
            else:
                print(f"  Listening on {bound_host}:{self.port}")
            print("  Waiting for client connections...\n")
        else:
            # Telegram-only mode: no socket, just poll Telegram
            print("  Telegram-only mode: no local socket. Polling bot description...")
            print("  Waiting for Telegram commands...\n")
            s = None

        try:
            if s is not None:
                while not self._stop_event.is_set():
                    try:
                        conn, addr = s.accept()
                    except socket.timeout:
                        continue
                    with conn:
                        self._handle_client(conn, addr)
            else:
                # Telegram-only: just sleep and let the polling thread work
                while not self._stop_event.is_set():
                    time.sleep(1)
        except KeyboardInterrupt:
            print("\n  Shutting down server...")
        finally:
            self._stop_event.set()
            if s is not None:
                s.close()
            if self.player:
                self.player.stop()


# ---------------------------------------------------------------------------
# Backwards-compatible standalone functions (used by tests + old callers)
# ---------------------------------------------------------------------------

def discover_server_ip(timeout: float = 5.0) -> str | None:
    """Listen for UDP beacon from server. Kept for backward compatibility."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
            except (AttributeError, OSError):
                pass
            s.bind(("", DISCOVERY_UDP_PORT))
            s.settimeout(timeout)
            start = time.time()
            while time.time() - start < timeout:
                try:
                    data, addr = s.recvfrom(1024)
                    if data == BEACON_MESSAGE:
                        return addr[0]
                except socket.timeout:
                    break
                except Exception:
                    pass
    except Exception as e:
        log.debug("Discovery failed: %s", e)
    return None


def send_notification(host: str, port: int, command: str, secret: str = "") -> bool:
    """Send command to server. Uses ACK protocol if server supports it."""
    return send_command_with_ack(host, port, command, timeout=5.0, secret=secret)
