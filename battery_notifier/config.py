# battery_notifier/config.py
from __future__ import annotations
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional
import logging

log = logging.getLogger(__name__)
APP_DIR = Path(os.environ.get("BATTERY_NOTIFIER_HOME", Path.home() / ".config" / "battery-music-notifier"))

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
    
    # ✨ New Web Hook Parameters
    telegram_token: str = ""
    telegram_chat_id: str = ""
    email_smtp_server: str = "smtp.gmail.com"
    email_smtp_port: int = 587
    email_sender: str = ""
    email_password: str = ""
    email_receiver: str = ""

    @classmethod
    def load(cls, path: Optional[Path] = None) -> "Config":
        import tomllib
        cfg = cls()
        path = path or (APP_DIR / "config.toml")
        if path.exists():
            with path.open("rb") as f:
                data = tomllib.load(f).get("battery_notifier", {})
            for k, v in data.items():
                if hasattr(cfg, k): setattr(cfg, k, v)
        return cfg