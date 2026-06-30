# battery_notifier/remote.py
from __future__ import annotations
import socket
import time
import logging
import threading
import urllib.request
import json
import smtplib
from email.message import EmailMessage
from .player import Player
from .battery import Battery

log = logging.getLogger(__name__)

class NotificationServer:
    """Runs on your laptop. Listens offline over TCP, handles online alerts asynchronously."""
    def __init__(self, cfg, host: str = "127.0.0.1", port: int = 8000):
        self.cfg = cfg
        self.host = host
        self.port = port
        self.player = Player(cfg.music_files, cfg.volume, cfg.annoying)
        self._stop_event = threading.Event()

    def run(self) -> None:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind((self.host, self.port))
            s.listen()
            s.settimeout(1.0)
            
            print(f"📡 Server listening on {self.host}:{self.port}... (Always Open)")
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
                            self.player.play()
                            
                            # lets add this Thread Isolation: Run web alerts in the background :)
                            threading.Thread(target=self._dispatch_web_alerts, daemon=True).start()
                            
                        elif data == "STOP":
                            log.info("Received remote command: STOP")
                            self.player.stop()
            except KeyboardInterrupt:
                print("\nShutting down server safely...")
            finally:
                self.player.stop()

    def _dispatch_web_alerts(self) -> None:
        """Asynchronously tests connectivity and shoots out web notifications safely."""
        # 1. Establish/Verify Internet Connection
        has_internet = False
        for attempt in range(3):
            try:
                # Fast connection test to Cloudflare DNS without blocking
                with socket.create_connection(("1.1.1.1", 53), timeout=3):
                    has_internet = True
                    break
            except OSError:
                log.warning("Network link unavailable. Retrying connection check... (%d/3)", attempt + 1)
                time.sleep(2)
                
        if not has_internet:
            log.error("Could not establish web connection. Web notifications skipped.")
            return

        # 2. Fire Telegram Webhook
        if self.cfg.telegram_token and self.cfg.telegram_chat_id:
            try:
                url = f"https://api.telegram.org/bot{self.cfg.telegram_token}/sendMessage"
                payload = json.dumps({
                    "chat_id": self.cfg.telegram_chat_id,
                    "text": "🔋 Battery Target Reached! Your charging device is ready."
                }).encode('utf-8')
                
                req = urllib.request.Request(
                    url, data=payload, 
                    headers={'Content-Type': 'application/json'}, 
                    method='POST'
                )
                with urllib.request.urlopen(req, timeout=5) as response:
                    if response.status == 200:
                        log.info("Telegram notification successfully routed.")
            except Exception as e:
                log.error("Failed to transmit Telegram alert: %s", e)

        # 3. Fire Email Notification via SMTP
        if self.cfg.email_sender and self.cfg.email_receiver and self.cfg.email_password:
            try:
                msg = EmailMessage()
                msg.set_content("🔋 Battery Target Reached! Your charging device is ready.")
                msg["Subject"] = "Battery Music Notifier Alert"
                msg["From"] = self.cfg.email_sender
                msg["To"] = self.cfg.email_receiver
                
                with smtplib.SMTP(self.cfg.email_smtp_server, self.cfg.email_smtp_port, timeout=5) as server:
                    server.starttls()
                    server.login(self.cfg.email_sender, self.cfg.email_password)
                    server.send_message(msg)
                    log.info("Email alert dispatched successfully.")
            except Exception as e:
                log.error("Failed to distribute Email alert: %s", e)


class RemoteMonitor:
    """Runs inside Termux on your phone. Monitors local battery and pings the laptop."""
    def __init__(self, cfg, host: str = "127.0.0.1", port: int = 8000):
        self.cfg = cfg
        self.host = host
        self.port = port
        self.battery = Battery()
        self._was_playing = False

    def _send_signal(self, command: str) -> bool:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(2.0)
                s.connect((self.host, self.port))
                s.sendall(command.encode('utf-8'))
            return True
        except Exception as e:
            log.warning("Could not reach laptop server on command %s: %s", command, e)
            return False

    def run(self) -> None:
        print(f"🔋 Client monitor running on phone. Telemetry targeted to {self.host}:{self.port}")
        try:
            while True:
                info = self.battery.read()
                in_target = (self.cfg.min_percentage <= info.percentage <= self.cfg.max_percentage)

                if info.charging and in_target and not self._was_playing:
                    if self._send_signal("START"):
                        self._was_playing = True
                elif (not info.charging or info.percentage < self.cfg.min_percentage) and self._was_playing:
                    if self._send_signal("STOP"):
                        self._was_playing = False

                time.sleep(self.cfg.poll_interval)
        except KeyboardInterrupt:
            print("\nExiting phone monitor loop...")
            self._send_signal("STOP")