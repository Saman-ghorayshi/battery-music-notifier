# battery_notifier/face_guard.py
"""Owner-vs-intruder face check for the Intruder Guard (v2.2).

Enroll once from your own webcam (guard-enroll), then every guard trigger
runs the captured frame through an LBPH recognizer trained on your face:

  owner    -> stand down silently (you just mistyped your password)
  unknown  -> lock the workstation, siren, snapshot, alert
  no_face  -> treated as unknown. A covered webcam must fail toward locking,
              never toward ignoring.

The face model is DPAPI-encrypted (Windows CurrentUser scope) before it
hits disk: only the same Windows user on the same machine can decrypt it --
copying the file to a USB stick or another account yields useless bytes.
In memory only. It never leaves the laptop -- only the snapshot JPEG goes
to the relay. Needs opencv-contrib (the plain opencv package has no
cv2.face): pip install battery-music-notifier[guard]
"""
from __future__ import annotations
import logging
import os
import pickle
import subprocess
from pathlib import Path

log = logging.getLogger(__name__)

# LBPH confidence: lower = better match. 70 is a forgiving close-range
# threshold; tuned to fail toward "unknown" (see module docstring).
OWNER_CONFIDENCE_MAX = 70.0
ENROLL_FRAMES = 20
FACE_SIZE = 200
MAX_ARCHIVE_SAMPLES = 80  # per-look enroll sessions accumulate, newest win

# v2.2.1: encrypted model files carry this magic; plaintext files (pre-2.2.1
# enrollments) still load, and get re-encrypted on the next enroll.
MODEL_MAGIC = b"BMF1:"
ARCHIVE_MAGIC = b"BMS1:"

# Enrollment walks the user through looks so one session already spans
# lighting/angle/expression variance; big appearance changes (beard off)
# just mean running enroll again -- new samples append, nothing is lost.
ENROLL_PHASES = [
    ("look straight at the camera", 8),
    ("turn your head slightly left, then right", 6),
    ("smile, then go back to neutral", 6),
]


class CameraUnavailable(RuntimeError):
    """Camera present but unusable; .args[0] carries the guided fix."""


def model_path() -> Path:
    from .config import APP_DIR
    return Path(APP_DIR) / "face_model.yml"


def archive_path() -> Path:
    from .config import APP_DIR
    return Path(APP_DIR) / "face_samples.bin"


# ---- Camera diagnostics: why is there no frame, and what should the user do?

def classify_pnp_output(txt: str) -> str:
    """'ok' | 'disabled' | 'error' | 'missing' from Get-PnpDevice JSON."""
    txt = (txt or "").strip()
    if not txt:
        return "missing"
    import re
    if re.search(r'"Problem"\s*:\s*22\b', txt):  # CM_PROB_DISABLED
        return "disabled"
    if re.search(r'"Status"\s*:\s*"Error"', txt):
        return "error"
    return "ok"


def _camera_device_status() -> str:
    if os.name != "nt":
        return "unknown"
    try:
        create_no_window = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-PnpDevice -Class Camera,Image | Select-Object -First 5 "
             "Status,Problem | ConvertTo-Json -Compress"],
            capture_output=True, text=True, timeout=25,
            creationflags=create_no_window,
        )
    except Exception as e:
        log.debug("Get-PnpDevice failed: %s", e)
        return "unknown"
    return classify_pnp_output(r.stdout)


def diagnose_camera(camera_index: int = 0):
    """(ok, detail). On failure detail names the cause and the exact fix."""
    try:
        import cv2
    except ImportError:
        return False, ("opencv missing: pip install battery-music-notifier[guard]")
    cam = cv2.VideoCapture(camera_index)
    try:
        ok, frame = cam.read()
    finally:
        cam.release()
    if ok and frame is not None:
        return True, "camera works"

    hw = _camera_device_status()
    if hw == "disabled":
        return False, (
            "Your camera is DISABLED in Windows. Fix: Device Manager > Cameras > "
            "right-click > Enable device -- or press your laptop's Fn camera key."
        )
    if hw == "missing":
        return False, (
            "No camera hardware detected. If this laptop has one, reinstall its "
            "driver (Device Manager > Action > Scan for hardware changes)."
        )
    if hw == "error":
        return False, (
            "The camera driver reports an error. Reinstall it via Device Manager."
        )
    # Hardware looks alive -> privacy toggle or another app is holding it
    return False, (
        "Camera exists but frames are blocked. Fix in order:\n"
        "  1. Physical privacy shutter or camera kill switch on the laptop\n"
        "  2. Windows camera privacy: 'Let desktop apps access your camera' "
        "must be ON (python is a desktop app) -- battery-music guard-enroll "
        "opens this settings page for you\n"
        "  3. Close apps that may be holding the camera (Zoom/Teams/browser)\n"
        "  4. Antivirus webcam protection can block python.exe -- allow it there"
    )


def open_camera_privacy_settings() -> bool:
    """Pop the exact Windows settings page that governs desktop app cameras."""
    if os.name != "nt":
        return False
    try:
        os.startfile("ms-settings:privacy-webcam")  # noqa: S606 -- by design
        return True
    except Exception as e:
        log.debug("could not open camera settings: %s", e)
        return False


# ---- Encrypted sample archive: enroll sessions add up instead of resetting

def _load_archive(path: Path = None) -> list:
    p = path or archive_path()
    if not p.exists():
        return []
    raw = p.read_bytes()
    if raw.startswith(ARCHIVE_MAGIC):
        if os.name != "nt":
            log.error("encrypted face archive on non-Windows -- cannot read")
            return []
        try:
            raw = _dpapi_unprotect(raw[len(ARCHIVE_MAGIC):])
        except OSError as e:
            log.error("face archive decrypt failed: %s", e)
            return []
    try:
        return pickle.loads(raw)
    except Exception as e:
        log.error("face archive unreadable: %s", e)
        return []


def _save_archive(samples: list, path: Path = None) -> None:
    p = path or archive_path()
    payload = pickle.dumps(samples)
    p.parent.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        p.write_bytes(ARCHIVE_MAGIC + _dpapi_protect(payload))
    else:
        p.write_bytes(payload)


# ---- DPAPI (CurrentUser) -- zero dependencies, Windows-only ----------------
# pbData MUST be c_void_p, not c_char_p: DPAPI blobs contain NUL bytes and a
# c_char_p field converts pointer->str on access (truncates + corrupts heap).

def _dpapi_protect(data: bytes) -> bytes:
    import ctypes

    class BLOB(ctypes.Structure):
        _fields_ = [("cbData", ctypes.c_uint), ("pbData", ctypes.c_void_p)]

    buf = ctypes.create_string_buffer(data, len(data))
    bin_ = BLOB(len(data), ctypes.cast(buf, ctypes.c_void_p))
    out = BLOB()
    if not ctypes.windll.crypt32.CryptProtectData(
        ctypes.byref(bin_), None, None, None, None, 0, ctypes.byref(out)
    ):
        raise OSError("CryptProtectData failed")
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(ctypes.c_void_p(out.pbData))


def _dpapi_unprotect(data: bytes) -> bytes:
    import ctypes

    class BLOB(ctypes.Structure):
        _fields_ = [("cbData", ctypes.c_uint), ("pbData", ctypes.c_void_p)]

    buf = ctypes.create_string_buffer(data, len(data))
    bin_ = BLOB(len(data), ctypes.cast(buf, ctypes.c_void_p))
    out = BLOB()
    if not ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(bin_), None, None, None, None, 0, ctypes.byref(out)
    ):
        raise OSError("CryptUnprotectData failed -- different user or machine?")
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(ctypes.c_void_p(out.pbData))


def _cascade():
    import cv2
    return cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")


def _detect_faces(frame):
    """Grayscale face boxes, (x, y, w, h), or an empty list."""
    import cv2
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    return _cascade().detectMultiScale(gray, scaleFactor=1.2, minNeighbors=5,
                                       minSize=(60, 60))


def save_model(recognizer, out_path: Path) -> Path:
    """Train-agnostic persist: recognizer writes yml, we encrypt it at rest."""
    out_path = Path(out_path)
    tmp = out_path.with_suffix(".yml.tmp")
    recognizer.write(str(tmp))
    try:
        raw = tmp.read_bytes()
    finally:
        tmp.unlink(missing_ok=True)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        out_path.write_bytes(MODEL_MAGIC + _dpapi_protect(raw))
    else:
        # Face guard is a Windows feature; dev/CI fallback stays plaintext.
        log.warning("non-Windows: face model stored WITHOUT encryption")
        out_path.write_bytes(raw)
    return out_path


def load_model_bytes(path: Path = None) -> bytes | None:
    """Model bytes, decrypted if needed; None if missing. Legacy plaintext
    files (no magic) load as-is and get re-encrypted on next enroll."""
    path = path or model_path()
    if not path.exists():
        return None
    raw = path.read_bytes()
    if raw.startswith(MODEL_MAGIC):
        if os.name != "nt":
            log.error("encrypted face model found on non-Windows -- cannot decrypt")
            return None
        try:
            return _dpapi_unprotect(raw[len(MODEL_MAGIC):])
        except OSError as e:
            log.error("face model decrypt failed: %s", e)
            return None
    return raw


def enroll(camera_index: int = 0, out_path: Path = None, frames: int = ENROLL_FRAMES) -> Path:
    """Capture `frames` across guided looks (straight / turned / smiling),
    merge with any previously enrolled samples, retrain, save encrypted.

    Run it sitting at the laptop in normal lighting. After a big look change
    (beard off, new haircut) just run it again: new samples add to the old
    ones, so the model knows both looks. Nothing is uploaded anywhere.
    """
    import cv2
    from cv2 import face  # opencv-contrib only

    out_path = out_path or model_path()
    cam = cv2.VideoCapture(camera_index)
    samples, labels = [], []
    # Cumulative frame targets per phase, last phase absorbs any remainder
    targets, done = [], 0
    for _, count in ENROLL_PHASES[:-1]:
        done += count
        targets.append(done)
    try:
        phase_i = -1
        while len(samples) < frames:
            target = targets[phase_i] if 0 <= phase_i < len(targets) else frames
            if len(samples) >= target and phase_i < len(ENROLL_PHASES) - 1:
                phase_i += 1
                print(f"\n  [{len(samples) + 1}/{frames}] {ENROLL_PHASES[phase_i][0]} ...")
            ok, frame = cam.read()
            if not ok or frame is None:
                raise CameraUnavailable("camera stopped returning frames mid-enroll")
            faces = _detect_faces(frame)
            if len(faces) != 1:
                continue  # want exactly one face per sample
            x, y, w, h = faces[0]
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            sample = cv2.resize(gray[y:y + h, x:x + w], (FACE_SIZE, FACE_SIZE))
            samples.append(sample)
            labels.append(0)  # label 0 is always the owner
            print(f"\r  captured {len(samples)}/{frames}", end="", flush=True)
    finally:
        cam.release()
    print()

    # Merge with previous sessions so looks accumulate instead of resetting
    merged = list(_load_archive()) + samples
    merged = merged[-MAX_ARCHIVE_SAMPLES:]  # newest looks win if over cap
    recognizer = face.LBPHFaceRecognizer_create()
    recognizer.train(merged, [0] * len(merged))
    save_model(recognizer, out_path)
    _save_archive(merged)
    print(f"  face model saved (encrypted): {out_path} "
          f"({len(merged)} samples total)")
    return out_path


def load_verdict(model_path: Path = None):
    """Return verdict(frame) -> 'owner' | 'unknown' | 'no_face', or None.

    None means no usable face check (no model, unreadable model, or
    opencv-contrib missing) -- callers must fall back to today's plain-alert
    behavior, never to locking.
    """
    import cv2
    try:
        from cv2 import face
    except ImportError:
        log.warning("opencv-contrib not installed -- face check disabled "
                    "(install with: pip install battery-music-notifier[guard])")
        return None
    model_path = model_path or model_path()
    model_bytes = load_model_bytes(model_path)
    if model_bytes is None:
        return None

    # LBPH's read() only takes a path, so decrypt to a short-lived temp file
    # in the same directory and shred it right after.
    tmp = Path(model_path).with_suffix(".yml.tmp")
    try:
        tmp.write_bytes(model_bytes)
        recognizer = face.LBPHFaceRecognizer_create()
        recognizer.read(str(tmp))
    except (cv2.error, OSError) as e:
        log.error("face model unreadable: %s", e)
        return None
    finally:
        tmp.unlink(missing_ok=True)

    def verdict(frame) -> str:
        faces = _detect_faces(frame)
        if len(faces) == 0:
            return "no_face"
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        best = None
        for (x, y, w, h) in faces:
            sample = cv2.resize(gray[y:y + h, x:x + w], (FACE_SIZE, FACE_SIZE))
            _, confidence = recognizer.predict(sample)
            best = confidence if best is None else min(best, confidence)
        return "owner" if best <= OWNER_CONFIDENCE_MAX else "unknown"

    return verdict
