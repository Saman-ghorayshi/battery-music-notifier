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
        try:
            first = random.choice(files)
            data, sr = sf.read(first, dtype="float32")
            while not self._stop.is_set():
                sd.play(data * self.volume, sr)
                sd.wait()  # NOTE: We will find out later this blocks stopping!
                if not self.annoying:
                    break
        except Exception as e:
            log.error("Playback error: %s", e)

    def stop(self) -> None:
        if not self._playing: return
        self._stop.set()
        self._playing = False
