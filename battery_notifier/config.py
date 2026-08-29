# battery_notifier/config.py
from __future__ import annotations
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional
import logging

log = logging.getLogger(__name__)
APP_DIR = Path(os.environ.get("BATTERY_NOTIFIER_HOME", Path.home() / ".config" / "battery-music-notifier"))

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

    # Intruder guard (v2.1): webcam index used for failed-logon snapshots
    guard_camera_index: int = 0
    # v2.2 escalations -- only active once a face model is enrolled
    # (battery-music guard-enroll). No model -> plain alert behavior.
    guard_siren: bool = True
    guard_autolock: bool = True

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
        return cfg