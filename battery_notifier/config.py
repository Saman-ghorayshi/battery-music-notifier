# battery_notifier/config.py
from __future__ import annotations
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional
import logging

log = logging.getLogger(__name__)
APP_DIR = Path(os.environ.get("BATTERY_NOTIFIER_HOME", Path.home() / ".config" / "battery-music-notifier"))

# ---------------------------------------------------------------------------
# Secret storage (worker_token / admin_key)
#
# On Windows these are stored DPAPI-encrypted as "dpapi:<base64>" -- DPAPI
# (CryptProtectData) ties the blob to the Windows user account, so a stolen
# config.toml alone does not yield the relay token. No pip dependencies.
# On other platforms the values stay plaintext and the file is chmod 0600.
# ---------------------------------------------------------------------------
_DPAPI_PREFIX = "dpapi:"
_CRYPTPROTECT_UI_FORBIDDEN = 0x1

# Fields whose values are secrets and get encrypted on save / decrypted on load
SECRET_FIELDS = ("worker_token", "admin_key", "alarm_pin")


def _dpapi_protect(data: bytes) -> bytes:
    import ctypes

    # pbData MUST be c_void_p, never c_char_p: reading a c_char_p field
    # auto-converts to a Python bytes COPY, and LocalFree-ing that copy
    # frees CPython's own allocator memory (heap corruption 0xc0000374).
    class _BLOB(ctypes.Structure):
        _fields_ = [("cbData", ctypes.c_ulong), ("pbData", ctypes.c_void_p)]

    buf = ctypes.create_string_buffer(data, len(data))
    blob_in = _BLOB(len(data), ctypes.cast(buf, ctypes.c_void_p))
    blob_out = _BLOB()
    ok = ctypes.windll.crypt32.CryptProtectData(
        ctypes.byref(blob_in), None, None, None, None,
        _CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(blob_out),
    )
    if not ok:
        raise OSError(f"CryptProtectData failed (GetLastError={ctypes.GetLastError()})")
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(ctypes.c_void_p(blob_out.pbData))


def _dpapi_unprotect(data: bytes) -> bytes:
    import ctypes

    # Same c_void_p rule as _dpapi_protect (see the comment there).
    class _BLOB(ctypes.Structure):
        _fields_ = [("cbData", ctypes.c_ulong), ("pbData", ctypes.c_void_p)]

    buf = ctypes.create_string_buffer(data, len(data))
    blob_in = _BLOB(len(data), ctypes.cast(buf, ctypes.c_void_p))
    blob_out = _BLOB()
    ok = ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(blob_in), None, None, None, None,
        _CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(blob_out),
    )
    if not ok:
        raise OSError(f"CryptUnprotectData failed (GetLastError={ctypes.GetLastError()})")
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(ctypes.c_void_p(blob_out.pbData))


def encrypt_secret(value: str) -> str:
    """Return a storage-safe string for a secret.

    Windows: "dpapi:<base64>" (already-encrypted values pass through).
    Other OSes: the value unchanged (plaintext, file is chmod'ed 0600).
    Failure falls back to plaintext rather than losing the secret.
    """
    if not value:
        return value
    if value.startswith(_DPAPI_PREFIX):
        return value  # already encrypted
    if os.name != "nt":
        return value
    try:
        import base64

        raw = _dpapi_protect(value.encode("utf-8"))
        return _DPAPI_PREFIX + base64.b64encode(raw).decode("ascii")
    except Exception as e:
        log.warning("Could not DPAPI-encrypt secret (%s); storing plaintext", e)
        return value


def decrypt_secret(value: str) -> str:
    """Inverse of encrypt_secret. Values without the dpapi: prefix pass
    through unchanged. Undecryptable values (other machine/user/platform)
    return "" -- better an unusable token than ciphertext sent as a token."""
    if not value or not value.startswith(_DPAPI_PREFIX):
        return value
    if os.name != "nt":
        log.warning("DPAPI secret cannot be decrypted on this platform")
        return ""
    try:
        import base64

        raw = _dpapi_unprotect(base64.b64decode(value[len(_DPAPI_PREFIX):]))
        return raw.decode("utf-8")
    except Exception as e:
        log.warning("Could not DPAPI-decrypt secret (%s)", e)
        return ""


def harden_config_perms(path: Path) -> None:
    """Best-effort 0600 on POSIX so plaintext secrets are not world-readable.
    No-op on Windows (DPAPI protects the values instead)."""
    if os.name == "nt":
        return
    try:
        os.chmod(path, 0o600)
    except Exception as e:
        log.warning("Could not chmod 600 %s: %s", path, e)

# Default hosted worker URL (users can override or self-host)
DEFAULT_WORKER_URL = "https://battery-relay.sthidontknow.workers.dev"

# Bundled default alarm sound
DEFAULT_ALARM_FILE = str(Path(__file__).parent / "assets" / "default_alarm.wav")

def sanitize_proxy_url(url: str) -> str:
    """Intelligently repairs common malformed proxy strings from end-users."""
    url = url.strip()
    if not url:
        return ""

    # Opt-out keywords (C5 fix): force a direct connection and disable
    # auto-detection so a local proxy can never hijack traffic.
    if url.lower() in ("direct", "off", "none"):
        return "direct"

    # Case A: User typed just a raw port number (e.g., "10808" or "7890")
    if url.isdigit():
        port = int(url)
        proto = "http" if port in (10809, 7890) else "socks5"
        return f"{proto}://127.0.0.1:{port}"

    # Case B: User separated protocol with a space (e.g., "socks 10808" or "socks5 12334")
    if " " in url:
        parts = url.split(None, 1)
        proto = "socks5" if "socks" in parts[0].lower() else "http"
        remainder = parts[1].strip()
        if remainder.isdigit():
            return f"{proto}://127.0.0.1:{remainder}"
        return f"{proto}://{remainder}"

    # Case C: User explicitly typed an incomplete or outdated protocol (e.g., "socks://...")
    if "://" in url:
        proto, remainder = url.split("://", 1)
        if proto.lower() in ("socks", "socks5"):
            return f"socks5://{remainder}"
        return f"{proto.lower()}://{remainder}"

    # Case D: User supplied a host string without any protocol flag (e.g., "127.0.0.1:10808")
    if ":" in url:
        try:
            port = int(url.split(":")[-1])
            if port in (10809, 7890):
                return f"http://{url}"
        except ValueError:
            pass
        return f"socks5://{url}"

    return url


def _resolve_annotation(ann):
    """Resolve a string annotation to a real type. E.g. 'float' -> float."""
    if ann is None:
        return None
    if isinstance(ann, type):
        return ann
    if isinstance(ann, str):
        # builtins
        builtins_map = {"int": int, "float": float, "str": str, "bool": bool, "list": list, "dict": dict}
        if ann in builtins_map:
            return builtins_map[ann]
        # Optional[...] is Union[...] when stringified
        if ann.startswith("Optional["):
            inner = ann[9:-1]
            return _resolve_annotation(inner)
        # List[...] / list[...] (PEP 585 lowercase included)
        if ann.startswith(("List[", "list[")):
            return list
        # pathlib.Path (incl. Optional[Path])
        if ann == "Path":
            return Path
    return ann


@dataclass
class Config:
    music_files: List[str] = field(default_factory=list)
    min_percentage: int = 20
    max_percentage: int = 100
    volume: float = 0.8
    poll_interval: float = 10.0  # CHANGED: 3.0 -> 10.0 to protect CF free tier
    annoying: bool = False
    quiet_hours: list[int] = field(default_factory=lambda: [22, 8])
    log_file: Optional[Path] = None
    
    # Web Hook Parameters
    telegram_token: str = ""
    telegram_chat_id: str = ""
    email_smtp_server: str = "smtp.gmail.com"
    email_smtp_port: int = 587
    email_sender: str = ""
    email_password: str = ""
    email_receiver: str = ""
    
    # Proxy Configuration Parameter
    proxy_url: str = ""
    
    # Worker relay settings (defaults to hosted worker, users can self-host)
    worker_url: str = DEFAULT_WORKER_URL
    worker_token: str = ""
    admin_key: str = ""
    
    # Thief catcher alarm sound (falls back to bundled default)
    alarm_files: List[str] = field(default_factory=lambda: [DEFAULT_ALARM_FILE])

    # Local socket shared secret (optional, prevents LAN attackers from sending STOP)
    socket_secret: str = ""
    # v2.6 mode toggles: which battery events play music at all.
    alert_at_full: bool = True   # music when the battery reaches max (charging)
    alert_at_low: bool = True    # music when the battery drops to min
    # v2.6 alarm hardening: the PIN the fullscreen gate asks for when the
    # thief alarm rings locally (owner types it to silence everything), and
    # which output the alarm plays through -- 'auto' forces built-in
    # speakers (never Bluetooth), 'default' trusts the OS, or any substring
    # of a device name to pin a specific output.
    alarm_pin: str = "6969"
    alarm_output: str = "auto"
    # v2.7 routing: where each alarm makes noise.
    #   both | phone | laptop | phone_then_laptop (escalate_minutes governs)
    route_thief: str = "both"
    route_battery: str = "both"
    escalate_minutes: int = 2

    # Intruder guard (v2.1): webcam index used for failed-logon snapshots
    guard_camera_index: int = 0
    # v2.2 escalations -- only active once a face model is enrolled
    # (battery-music guard-enroll). No model -> plain alert behavior.
    guard_siren: bool = True
    guard_autolock: bool = True
    # v2.4 photo burst: N frames spaced apart, shipped as one montage
    burst_count: int = 3
    burst_interval: float = 1.5
    # v2.4 quiet-hours auto-arm, e.g. "23:00-07:00" (empty = off)
    quiet_arm: str = ""
    quiet_auto_disarm: bool = False

    @classmethod
    def load(cls, path: Optional[Path] = None) -> "Config":
        cfg = cls()
        path = path or (APP_DIR / "config.toml")
        if path.exists():
            data = {}
            try:
                try:
                    import tomllib
                except ModuleNotFoundError:
                    import tomli as tomllib
                try:
                    with path.open("rb") as f:
                        data = tomllib.load(f).get("battery_notifier", {})
                except tomllib.TOMLDecodeError as e:
                    # A corrupted config must not crash every command with a raw
                    # traceback (e.g. unescaped Windows backslash paths in TOML).
                    print(f"  [WARN] Config file is invalid TOML: {path}")
                    print(f"         {e}")
                    print(f"         Fix it manually, delete it, or run 'battery-music init --force'.")
                    print(f"         Using default settings for now.\n")
                    data = {}
            except Exception as e:
                log.warning("Could not read config %s: %s", path, e)
                data = {}
            
            # Type-safe field assignment (Bug #6 Fix)
            type_hints = {f.name: f.type for f in cls.__dataclass_fields__.values()}
            for k, v in data.items():
                if not hasattr(cfg, k): continue
                expected = _resolve_annotation(type_hints.get(k))
                try:
                    if expected is float and isinstance(v, (int, float)): setattr(cfg, k, float(v))
                    elif expected is int and isinstance(v, (int, float)): setattr(cfg, k, int(v))
                    elif expected is bool and isinstance(v, bool): setattr(cfg, k, v)
                    elif expected is str and isinstance(v, str): setattr(cfg, k, v)
                    elif expected is list and isinstance(v, list): setattr(cfg, k, v)
                    elif expected is Optional[Path] and isinstance(v, str): setattr(cfg, k, Path(v))
                    else: log.warning("Config field '%s' has unexpected type %s, keeping default", k, type(v).__name__)
                except (ValueError, TypeError) as e:
                    log.warning("Config field '%s' value %r invalid (%s), keeping default", k, v, e)
        
        cfg.proxy_url = sanitize_proxy_url(cfg.proxy_url)

        # Secrets may be stored as "dpapi:<base64>"; decrypt transparently.
        for f in SECRET_FIELDS:
            val = getattr(cfg, f, "")
            if isinstance(val, str) and val.startswith(_DPAPI_PREFIX):
                setattr(cfg, f, decrypt_secret(val))

        # One-time, best-effort upgrade: plaintext secrets still in the file
        # get rewritten encrypted (Windows only; on other OSes the file is
        # chmod'ed instead). Never crashes a command over housekeeping.
        try:
            _upgrade_plaintext_secrets(path)
        except Exception as e:
            log.debug("Secret upgrade skipped: %s", e)

        return cfg


def _upgrade_plaintext_secrets(path: Path) -> None:
    """Rewrite plaintext worker_token/admin_key in config.toml as
    DPAPI-encrypted values (idempotent: a second load finds nothing to do)."""
    if os.name != "nt" or not path.exists():
        return
    import tomlkit

    doc = tomlkit.parse(path.read_text(encoding="utf-8"))
    table = doc.get("battery_notifier")
    if not isinstance(table, dict):
        return
    changed = False
    for f in SECRET_FIELDS:
        val = table.get(f)
        if isinstance(val, str) and val and not val.startswith(_DPAPI_PREFIX):
            table[f] = encrypt_secret(val)
            changed = True
    if changed:
        path.write_text(tomlkit.dumps(doc), encoding="utf-8")
        log.info("Upgraded plaintext secrets in %s to DPAPI-encrypted values", path)