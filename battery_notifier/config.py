# battery_notifier/config.py
from __future__ import annotations
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional
import logging

log = logging.getLogger(__name__)
APP_DIR = Path(os.environ.get("BATTERY_NOTIFIER_HOME", Path.home() / ".config" / "battery-music-notifier"))

def sanitize_proxy_url(url: str) -> str:
    """Intelligently repairs common malformed proxy strings from end-users."""
    url = url.strip()
    if not url:
        return ""

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


@dataclass
class Config:
    music_files: List[str] = field(default_factory=list)
    min_percentage: int = 99
    max_percentage: int = 100
    volume: float = 0.8
    poll_interval: float = 3.0
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

    @classmethod
    def load(cls, path: Optional[Path] = None) -> "Config":
        import tomllib
        cfg = cls()
        path = path or (APP_DIR / "config.toml")
        if path.exists():
            with path.open("rb") as f:
                data = tomllib.load(f).get("battery_notifier", {})
            for k, v in data.items():
                if hasattr(cfg, k): 
                    setattr(cfg, k, v)
        
        # Smart Auto-Correction Layer: Clean the proxy string natively upon ingestion
        cfg.proxy_url = sanitize_proxy_url(cfg.proxy_url)
        return cfg