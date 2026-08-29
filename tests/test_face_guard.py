"""Tests for face_guard.py model persistence (DPAPI at rest on Windows)."""
import os
from unittest.mock import MagicMock

import pytest

from battery_notifier import face_guard


class FakeRecognizer:
    """Stands in for cv2.face.LBPHFaceRecognizer: write() dumps fake yml."""

    def __init__(self, payload=b"fake-yml-opencv-data"):
        self.payload = payload
        self.read_from = None

    def write(self, path):
        with open(path, "wb") as f:
            f.write(self.payload)

    def read(self, path):
        self.read_from = path
        with open(path, "rb") as f:
            if not f.read().startswith(self.payload):
                raise ValueError("bad model")


def test_dpapi_roundtrip():
    """Real DPAPI: what the current Windows user encrypts, it decrypts."""
    if os.name != "nt":
        pytest.skip("DPAPI is Windows-only")
    secret = b"lbph-model-bytes-123"
    assert face_guard._dpapi_unprotect(face_guard._dpapi_protect(secret)) == secret


def test_dpapi_blob_is_not_plaintext():
    if os.name != "nt":
        pytest.skip("DPAPI is Windows-only")
    secret = b"sensitive-face-data" * 10
    blob = face_guard._dpapi_protect(secret)
    assert secret not in blob


def test_save_model_writes_encrypted_magic(tmp_path):
    """The on-disk model carries the magic header, not the raw yml."""
    if os.name != "nt":
        pytest.skip("encryption path is Windows-only")
    out = tmp_path / "face_model.yml"
    face_guard.save_model(FakeRecognizer(), out)

    raw = out.read_bytes()
    assert raw.startswith(face_guard.MODEL_MAGIC)
    assert b"fake-yml-opencv-data" not in raw  # payload is encrypted


def test_load_model_bytes_roundtrip(tmp_path):
    if os.name != "nt":
        pytest.skip("encryption path is Windows-only")
    out = tmp_path / "face_model.yml"
    face_guard.save_model(FakeRecognizer(b"my-model-bytes"), out)
    assert face_guard.load_model_bytes(out) == b"my-model-bytes"


def test_legacy_plaintext_model_still_loads(tmp_path):
    """Pre-2.2.1 plaintext models keep working (re-encrypted next enroll)."""
    p = tmp_path / "face_model.yml"
    p.write_bytes(b"old-plaintext-yml")
    assert face_guard.load_model_bytes(p) == b"old-plaintext-yml"


def test_load_model_bytes_missing(tmp_path):
    assert face_guard.load_model_bytes(tmp_path / "nope.yml") is None


def test_save_and_read_temp_file_is_cleaned(tmp_path):
    """The decrypted temp file must not survive load_verdict's read."""
    if os.name != "nt":
        pytest.skip("encryption path is Windows-only")
    out = tmp_path / "face_model.yml"
    face_guard.save_model(FakeRecognizer(), out)
    assert not list(tmp_path.glob("*.tmp"))


# ---------------------------------------------------------------------------
# v2.2.2: camera diagnostics classification + encrypted sample archive
# ---------------------------------------------------------------------------

def test_classify_pnp_disabled():
    """Problem code 22 = CM_PROB_DISABLED (Fn camera key / Device Manager)."""
    txt = '[{"Status":"Error","Problem":22}]'
    assert face_guard.classify_pnp_output(txt) == "disabled"


def test_classify_pnp_driver_error():
    txt = '[{"Status":"Error","Problem":0}]'
    assert face_guard.classify_pnp_output(txt) == "error"


def test_classify_pnp_missing():
    assert face_guard.classify_pnp_output("") == "missing"
    assert face_guard.classify_pnp_output(None) == "missing"


def test_classify_pnp_healthy():
    txt = '[{"Status":"OK","Problem":0}]'
    assert face_guard.classify_pnp_output(txt) == "ok"


def test_archive_roundtrip_encrypted(tmp_path):
    """Samples persist encrypted and come back identical."""
    if os.name != "nt":
        pytest.skip("encryption path is Windows-only")
    p = tmp_path / "face_samples.bin"
    face_guard._save_archive([b"s1", b"s2"], p)
    raw = p.read_bytes()
    assert raw.startswith(face_guard.ARCHIVE_MAGIC)
    assert b"s1" not in raw  # encrypted at rest
    assert face_guard._load_archive(p) == [b"s1", b"s2"]


def test_archive_missing(tmp_path):
    assert face_guard._load_archive(tmp_path / "nope.bin") == []
