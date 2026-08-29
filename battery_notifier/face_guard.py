# battery_notifier/face_guard.py
"""Owner-vs-intruder face check for the Intruder Guard (v2.2).

Enroll once from your own webcam (guard-enroll), then every guard trigger
runs the captured frame through an LBPH recognizer trained on your face:

  owner    -> stand down silently (you just mistyped your password)
  unknown  -> lock the workstation, siren, snapshot, alert
  no_face  -> treated as unknown. A covered webcam must fail toward locking,
              never toward ignoring.

The face model lives in the app config dir and never leaves the laptop --
only the snapshot JPEG goes to the relay. Needs opencv-contrib (the plain
opencv package has no cv2.face): pip install battery-music-notifier[guard]
"""
from __future__ import annotations
import logging
import os
from pathlib import Path

log = logging.getLogger(__name__)

# LBPH confidence: lower = better match. 70 is a forgiving close-range
# threshold; tuned to fail toward "unknown" (see module docstring).
OWNER_CONFIDENCE_MAX = 70.0
ENROLL_FRAMES = 20
FACE_SIZE = 200


def model_path() -> Path:
    from .config import APP_DIR
    return Path(APP_DIR) / "face_model.yml"


def _cascade():
    import cv2
    return cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")


def _detect_faces(frame):
    """Grayscale face boxes, (x, y, w, h), or an empty list."""
    import cv2
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    return _cascade().detectMultiScale(gray, scaleFactor=1.2, minNeighbors=5,
                                       minSize=(60, 60))


def enroll(camera_index: int = 0, out_path: Path = None, frames: int = ENROLL_FRAMES) -> Path:
    """Capture `frames` of whoever is looking at the camera and train LBPH.

    Run this sitting at the laptop, normal lighting, glasses as usual.
    Overwrites any previous model.
    """
    import cv2
    from cv2 import face  # opencv-contrib only

    out_path = out_path or model_path()
    cam = cv2.VideoCapture(camera_index)
    samples, labels = [], []
    try:
        while len(samples) < frames:
            ok, frame = cam.read()
            if not ok or frame is None:
                raise RuntimeError("camera returned no frame")
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

    recognizer = face.LBPHFaceRecognizer_create()
    recognizer.train(samples, labels)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    recognizer.write(str(out_path))
    print(f"  face model saved: {out_path}")
    return out_path


def load_verdict(model_path: Path = None):
    """Return verdict(frame) -> 'owner' | 'unknown' | 'no_face', or None.

    None means no usable face check (no model, or opencv-contrib missing) --
    callers must fall back to today's plain-alert behavior, never to locking.
    """
    import cv2
    try:
        from cv2 import face
    except ImportError:
        log.warning("opencv-contrib not installed -- face check disabled "
                    "(install with: pip install battery-music-notifier[guard])")
        return None
    model_path = model_path or model_path()
    if not os.path.exists(model_path):
        return None

    recognizer = face.LBPHFaceRecognizer_create()
    try:
        recognizer.read(str(model_path))
    except cv2.error as e:
        log.error("face model unreadable: %s", e)
        return None

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
