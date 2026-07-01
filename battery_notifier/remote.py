from __future__ import annotations
import socket
import threading
import time
import logging
import requests
from .player import Player
from .adb_helper import auto_setup_usb_bridge

log = logging.getLogger(__name__)

# Dedicated UDP Port for wireless auto-discovery beacons
DISCOVERY_UDP_PORT = 8002
BEACON_MESSAGE = b"BATTERY_MUSIC_BEACON_V1"


class RemoteMonitor:
    def __init__(self, host: str, port: int, config):
        self.host = host
        self.port = port
        self.cfg = config
        self._stop_event = threading.Event()
        
        # Import dynamically to prevent any chance of circular import chains
        from .battery import Battery
        self.battery = Battery()
        self.resolved_host = None

    def run(self) -> None:
        print("📡 Remote Monitor Client active.")
        print(f"🔋 Thresholds -> Min Alert: {self.cfg.min_percentage}%, Max Alert: {self.cfg.max_percentage}%")
        print("Press Ctrl+C to terminate the monitoring loop.\n")
        
        is_playing = False
        
        # Step 1: Pre-resolve host once if we are using wireless Auto-Discovery
        if not self.host or self.host.lower() == "auto":
            self.resolved_host = discover_server_ip(timeout=4.0)
            if self.resolved_host:
                print(f"🎯 Auto-connected to discovered server at: {self.resolved_host}:{self.port}")
            else:
                self.resolved_host = "127.0.0.1"
                print(f"🔄 No server discovered yet. Operating with local fallback: {self.resolved_host}:{self.port}")
        else:
            self.resolved_host = self.host
            print(f"🎯 Target server manually set to: {self.resolved_host}:{self.port}")

        # Step 2: Main client polling loop
        while not self._stop_event.is_set():
            try:
                info = self.battery.read()
                pct = info.percentage
                charging = info.charging
                
                # Symmetrical detection conditions
                should_alert = False
                if charging and pct >= self.cfg.max_percentage:
                    should_alert = True
                elif not charging and pct <= self.cfg.min_percentage:
                    should_alert = True
                    
                if should_alert:
                    if not is_playing:
                        print(f"🚨 Battery status alert: {pct}% (Charging: {charging}). Sending wake command...")
                        
                        # Trigger dynamic re-discovery if previous connection attempt was dropped
                        if (not self.host or self.host.lower() == "auto") and not self.resolved_host:
                            self.resolved_host = discover_server_ip(timeout=3.0) or "127.0.0.1"
                        
                        success = send_notification(self.resolved_host, self.port, "START")
                        if success:
                            is_playing = True
                            print("✅ Alert successfully accepted by server.")
                        else:
                            print("⚠️ Server failed to respond. Resetting search credentials...")
                            if not self.host or self.host.lower() == "auto":
                                self.resolved_host = None  # Force rediscovery on next tick
                else:
                    if is_playing:
                        print(f"💚 Battery status normalized: {pct}% (Charging: {charging}). Sending stop command...")
                        success = send_notification(self.resolved_host, self.port, "STOP")
                        if success:
                            is_playing = False
                            print("✅ Server successfully silenced.")
                            
            except KeyboardInterrupt:
                print("\nShutting down monitor client...")
                break
            except Exception as e:
                log.error("Error encountered in client tracking loop: %s", e)
                print(f"⚠️ Local tracking exception: {e}")
                
            time.sleep(self.cfg.poll_interval)


class NotificationServer:
    def __init__(self, host: str = "0.0.0.0", port: int = 8000, config = None):
        self.host = host
        self.port = port
        self.cfg = config
        self.player = Player(config.music_files, config.volume, config.annoying) if config else None
        self._stop_event = threading.Event()
        self._beacon_thread = None

    def _run_udp_beacon(self) -> None:
        """Periodically broadcasts UDP packets so clients can auto-discover this laptop's IP."""
        log.info("Starting UDP discovery beacon broadcasts...")
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            while not self._stop_event.is_set():
                try:
                    s.sendto(BEACON_MESSAGE, ("255.255.255.255", DISCOVERY_UDP_PORT))
                except Exception as e:
                    log.debug("UDP beacon broadcast failed: %s", e)
                time.sleep(2.0)

    def _dispatch_web_alerts(self) -> None:
        """Asynchronously triggers external web hooks (Telegram, SMTP) in a separate thread."""
        if not self.cfg:
            return

        # Telegram Dispatch Hook
        if self.cfg.telegram_token and self.cfg.telegram_chat_id:
            proxies = {"http": self.cfg.proxy_url, "https": self.cfg.proxy_url} if self.cfg.proxy_url else None
            try:
                url = f"https://api.telegram.org/bot{self.cfg.telegram_token}/sendMessage"
                payload = {"chat_id": self.cfg.telegram_chat_id, "text": "🔋 Alert: Laptop battery threshold crossed!"}
                requests.post(url, json=payload, proxies=proxies, timeout=5)
                log.info("Telegram notification sent successfully.")
            except Exception as e:
                log.error("Failed to dispatch Telegram notification: %s", e)

    def run(self) -> None:
        # Automatically set up the USB ADB bridge if a device is connected
        print("🔗 Initializing automatic USB ADB Bridge check...")
        auto_setup_usb_bridge(mode="reverse", port=self.port, max_retries=3)

        # Start the UDP Auto-Discovery Beacon thread
        self._beacon_thread = threading.Thread(target=self._run_udp_beacon, daemon=True)
        self._beacon_thread.start()

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind((self.host, self.port))
            except Exception as e:
                print(f"❌ Error binding server to {self.host}:{self.port}. Details: {e}")
                return
                
            s.listen()
            s.settimeout(1.0)
            
            print(f"\n📡 Server listening on {self.host}:{self.port}... (Always Open)")
            print("✨ Wireless auto-discovery is active! Phones can connect automatically.")
            log.info("Remote socket server initialization successful.")

            try:
                while not self._stop_event.is_set():
                    try:
                        conn, addr = s.accept()
                    except socket.timeout:
                        continue
                    
                    with conn:
                        data = conn.recv(1024).decode('utf-8').strip()
                        if data == "START":
                            log.info("Received remote command: START")
                            if self.player:
                                self.player.play()
                            # Run web alerts in the background thread
                            threading.Thread(target=self._dispatch_web_alerts, daemon=True).start()
                            
                        elif data == "STOP":
                            log.info("Received remote command: STOP")
                            if self.player:
                                self.player.stop()
            except KeyboardInterrupt:
                print("\nShutting down server safely...")
            finally:
                self._stop_event.set()
                if self.player:
                    self.player.stop()


def discover_server_ip(timeout: float = 5.0) -> str | None:
    """Listens for the UDP beacon broadcast from the laptop to auto-detect its IP address."""
    print("🔍 Searching wireless network for your laptop... (Auto-Discovery Active)")
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("", DISCOVERY_UDP_PORT))
        except Exception as e:
            log.debug("Failed to bind to UDP discovery port: %s", e)
            return None

        s.settimeout(timeout)
        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                data, addr = s.recvfrom(1024)
                if data == BEACON_MESSAGE:
                    detected_ip = addr[0]
                    print(f"✅ Auto-detected laptop IP: {detected_ip}!")
                    return detected_ip
            except socket.timeout:
                break
            except Exception:
                pass
    print("⚠️ Auto-discovery timed out. No active laptop found on your Wi-Fi/Hotspot subnet.")
    return None


def send_notification(host: str, port: int, command: str) -> bool:
    """Sends a control command (START/STOP) to the laptop server, with optional auto-discovery."""
    target_host = host

    # If the host is empty or set to "auto", invoke the wireless discovery helper
    if not host or host.lower() == "auto":
        discovered = discover_server_ip(timeout=4.0)
        if discovered:
            target_host = discovered
        else:
            # Fall back to localhost if discovery fails
            target_host = "127.0.0.1"
            print(f"🔄 Falling back to default host: {target_host}")

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(3.0)
            s.connect((target_host, port))
            s.sendall(command.encode('utf-8'))
            return True
    except Exception as e:
        log.error("Failed to connect to notifier server at %s:%d: %s", target_host, port, e)
        print(f"❌ Connection failed to {target_host}:{port}. Is the laptop server running?")
        return False