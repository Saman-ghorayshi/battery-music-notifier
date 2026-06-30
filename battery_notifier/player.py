from __future__ import annotations
import os, random, threading, logging
import sounddevice as sd
import soundfile as sf

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
            data, sr = sf.read(first, dtype="float32")
            while not self._stop.is_set():
                duration = len(data) / sr
                start_time = time.time()
                sd.play(data * self.volume, sr)
                
                # Active wait loop checking for stops
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
        except Exception as e:
            log.error("Playback error: %s", e)

    def stop(self) -> None:
        if not self._playing: return
        self._stop.set()
        try:
            sd.stop()  # Cleanly stop audio playback
        except Exception: pass
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)
        self._playing = False