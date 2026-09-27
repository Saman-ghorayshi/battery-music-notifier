# battery_notifier/player.py
from __future__ import annotations
import os
import random
import threading
import logging

log = logging.getLogger(__name__)

class Player:
    def __init__(self, files, volume: float = 0.8, annoying: bool = False,
                 output_mode: str = "auto"):
        self.files = [str(os.path.expanduser(f)) for f in files]
        self.volume = max(0.0, min(1.0, volume))
        self.annoying = annoying
        # v2.6: which output the alarm uses. 'auto' forces built-in speakers
        # and refuses Bluetooth/headphones -- the owner's AirPods in another
        # room must never silence a scream meant for the whole room.
        self.output_mode = output_mode or "auto"
        self._thread = None
        self._stop = threading.Event()
        self._playing = False

    def _pick_output_device(self):
        """Index of the sounddevice output to play the alarm through, or
        None for the system default. See alarm_output docs in config.py."""
        import re
        import sounddevice as sd
        try:
            outputs = [d for d in sd.query_devices() if d["max_output_channels"] > 0]
        except Exception:
            return None
        mode = (self.output_mode or "auto").strip()
        if mode.lower() == "default":
            return None
        if mode.lower() != "auto":
            named = [d for d in outputs if mode.lower() in str(d["name"]).lower()]
            return named[0]["index"] if named else None
        speaker_re = re.compile(r"speaker|loudspeaker", re.I)
        remote_re = re.compile(r"airpod|bluetooth|headphone|headset|earbud|hands-?free|hdmi|spdif|digital output", re.I)
        builtin = [d for d in outputs
                   if speaker_re.search(str(d["name"])) and not remote_re.search(str(d["name"]))]
        if builtin:
            return builtin[0]["index"]
        # No explicit 'speaker' name: any local output that is not remote.
        nonremote = [d for d in outputs if not remote_re.search(str(d["name"]))]
        return nonremote[0]["index"] if nonremote else None

    @property
    def playing(self) -> bool:
        return self._playing

    def play(self) -> bool:
        if not self.files:
            return False
        # Stop any existing playback before starting a new one
        if self._playing:
            self.stop()
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, args=(self.files,), daemon=True)
        self._thread.start()
        self._playing = True
        return True

    def _loop(self, files):
        import time
        try:
            first = random.choice(files)

            # Try sounddevice/soundfile first (desktop platforms)
            sd = None
            sf = None
            try:
                import sounddevice as sd
                import soundfile as sf
            except ImportError:
                pass

            if sd is not None and sf is not None:
                try:
                    device_index = self._pick_output_device()
                    if device_index is not None:
                        log.info("Alarm output: device %s (%r) -- built-in speakers forced",
                                 device_index, str(sd.query_devices()[device_index]["name"]))
                    else:
                        log.info("Alarm output: system default")
                    data, sr = sf.read(first, dtype="float32")
                    while not self._stop.is_set():
                        duration = len(data) / sr
                        start_time = time.time()
                        sd.play(data * self.volume, sr, device=device_index)

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
                    # Runtime failure (audio device, format) — fall through to CLI player
                    log.warning("sounddevice playback failed (%s), falling back to CLI player", e)
                    sd = None

            # CLI player fallback (Termux, or desktop where sounddevice failed)
            if sd is None:
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
                    log.error("Audio engine failure: sounddevice missing and no system CLI player found.")
                    return

                is_termux = player_cmd[0] == "termux-media-player"

                while not self._stop.is_set():
                    current_track = random.choice(files)

                    if is_termux:
                        # termux-media-player is async: it starts a background
                        # service and exits immediately. Poll player state instead
                        # of process state, otherwise the loop breaks instantly.
                        subprocess.run(
                            player_cmd + [current_track],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                            timeout=15,
                        )
                        while not self._stop.is_set():
                            info = subprocess.run(
                                ["termux-media-player", "info"],
                                capture_output=True, text=True,
                                timeout=5,
                            )
                            if "playing" not in info.stdout.lower():
                                break
                            time.sleep(0.5)
                        if self._stop.is_set():
                            subprocess.run(["termux-media-player", "stop"], stdout=subprocess.DEVNULL, timeout=5)
                            break
                        if not self.annoying:
                            subprocess.run(["termux-media-player", "stop"], stdout=subprocess.DEVNULL, timeout=5)
                            break
                    else:
                        # Standard CLI players: process blocks until track finishes
                        proc = subprocess.Popen(
                            player_cmd + [current_track],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                        )
                        while proc.poll() is None and not self._stop.is_set():
                            time.sleep(0.1)
                        if self._stop.is_set():
                            proc.terminate()
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
        
        # Bug #8 Fix: Explicitly kill termux media player
        import shutil
        if shutil.which("termux-media-player"):
            try:
                import subprocess
                subprocess.run(["termux-media-player", "stop"],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2)
            except Exception: pass
            
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)
        self._playing = False