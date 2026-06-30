from __future__ import annotations
import time, logging, datetime
from .battery import Battery
from .player import Player
from .notifier import Notifier

log = logging.getLogger(__name__)

class Monitor:
    def __init__(self, cfg):
        self.cfg = cfg
        self.battery = Battery()
        self.player = Player(cfg.music_files, cfg.volume, cfg.annoying)
        self.notifier = Notifier()
    def run(self) -> None:
        log.info("Monitoring started.")
        try:
            while True:
                # Enforce Quiet Hours
                current_hour = datetime.datetime.now().hour
                q_start, q_end = self.cfg.quiet_hours[0], self.cfg.quiet_hours[1]
                
                is_quiet = (current_hour >= q_start or current_hour < q_end) if q_start > q_end else (q_start <= current_hour < q_end)
                
                if is_quiet:
                    if self.player.playing:
                        self.player.stop()
                    time.sleep(self.cfg.poll_interval)
                    continue

                info = self.battery.read()
                
                in_target = (self.cfg.min_percentage <= info.percentage <= self.cfg.max_percentage)

                if info.charging and in_target and not self.player.playing:
                    if self.player.play():
                        self.notifier.send("Battery target reached", f"{info.percentage}% reached.")
                elif (not info.charging or info.percentage < self.cfg.min_percentage) and self.player.playing:
                    self.player.stop()
                    self.notifier.send("Stopped", "Conditions no longer met.")

                time.sleep(self.cfg.poll_interval)
        except KeyboardInterrupt:
            log.info("Interrupted; cleaning up.")
            self.player.stop()
