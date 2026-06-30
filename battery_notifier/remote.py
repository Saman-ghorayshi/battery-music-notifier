# battery_notifier/remote.py
from __future__ import annotations
import socket
import time
import logging
import threading
from .player import Player
from .battery import Battery

log = logging.getLogger(__name__)

class NotificationServer:
    """Runs on your laptop. Listens for triggers over an offline TCP socket connection."""
    def __init__(self, cfg, host: str = "127.0.0.1", port: int = 8000):
        self.cfg = cfg
        self.host = host
        self.port = port
        self.player = Player(cfg.music_files, cfg.volume, cfg.annoying)
        self._stop_event = threading.Event()

    def run(self) -> None:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            # Allow rapid port reuse on restarts
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind((self.host, self.port))
            s.listen()
            s.settimeout(1.0)
            
            print(f"📡 Server listening on {self.host}:{self.port}... (Press Ctrl+C to stop)")
            log.info("Remote socket server initialization successful.")

            try:
                while not self._stop_event.is_set():
                    try:
                        conn, addr = s.accept()
                    except socket.timeout:
                        continue  # Keep checking stop event
                    
                    with conn:
                        data = conn.recv(1024).decode('utf-8').strip()
                        if data == "START":
                            log.info("Received remote command: START")
                            self.player.play()
                        elif data == "STOP":
                            log.info("Received remote command: STOP")
                            self.player.stop()
            except KeyboardInterrupt:
                print("\nShutting down server safely...")
            finally:
                self.player.stop()


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
        print(f"🔋 Client monitor running on phone. Directing telemetry to {self.host}:{self.port}")
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