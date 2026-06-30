# battery_notifier/player.py
from __future__ import annotations
import os
import random
import threading
import logging

log = logging.getLogger(__name__)

class Player:
    def __init__(self, files, volume: float = 0.8, annoying: bool = False):
        self.files = [str(os.path.expanduser(f)) for f in files]
        self.volume = max(0.0, min(1.0, volume))
        self.annoying = annoying
        self._thread = None
        self._stop = threading.Event()
        self._playing = False

    @property
    def playing(self) -> bool:
        return self._playing

    def play(self) -> bool:
        if not self.files:
            return False
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, args=(self.files,), daemon=True)
        self._thread.start()
        self._playing = True
        return True

    def _loop(self, files):
        import time
        try:
            first = random.choice(files)
            
            try:
                import sounddevice as sd
                import soundfile as sf
                
                data, sr = sf.read(first, dtype="float32")
                while not self._stop.is_set():
                    duration = len(data) / sr
                    start_time = time.time()
                    sd.play(data * self.volume, sr)
                    
                    while time.time() - start_time < duration and not self._stop.is_set():
                        time.sleep(0.1)
                        
                    if self._stop.is_set():
                        sd.stop()
                        break
                    if not self.annoying:
                        break
                        
                    nxt = random.choice(files)
                    if nxt != first:
                        data, sr = sf.read(nxt, dtype="float32")
                        
            except (ImportError, Exception):
                import shutil
                import subprocess
                
                player_cmd = None
                if shutil.which("termux-media-player"):
                    player_cmd = ["termux-media-player", "play"]
                elif shutil.which("mpv"):
                    player_cmd = ["mpv", "--no-video"]
                elif shutil.which("ffplay"):
                    player_cmd = ["ffplay", "-nodisp", "-autoexit"]
                elif shutil.which("play"):
                    player_cmd = ["play", "-q"]

                if not player_cmd:
                    log.error(" Audio engine failure: sounddevice missing and no system CLI player found.")
                    return

                while not self._stop.is_set():
                    current_track = random.choice(files)
                    proc = subprocess.Popen(
                        player_cmd + [current_track], 
                        stdout=subprocess.DEVNULL, 
                        stderr=subprocess.DEVNULL
                    )
                    
                    while proc.poll() is None and not self._stop.is_set():
                        time.sleep(0.1)
                        
                    if self._stop.is_set():
                        proc.terminate()
                        try:
                            if player_cmd[0] == "termux-media-player":
                                subprocess.run(["termux-media-player", "stop"], stdout=subprocess.DEVNULL)
                        except Exception:
                            pass
                        break
                        
                    if not self.annoying:
                        break
                        
        except Exception as e:
            log.error("Playback loop error: %s", e)

    def stop(self) -> None:
        if not self._playing: return
        self._stop.set()
        try:
            import sounddevice as sd
            sd.stop()
        except Exception: pass
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)
        self._playing = False