# battery_notifier/gui/bridge.py
"""JS<->Python API exposed to the web UI via pywebview's js_api.

Every method is callable from JS as pywebview.api.<name>(...args) and must
return JSON-serializable data. Heavy/optional deps (qrcode, PIL, webview)
are imported lazily inside methods so headless unit tests can import Bridge.
"""
from __future__ import annotations

import base64
import io
import logging
import re
import time
from contextlib import redirect_stdout
from pathlib import Path

from ..config import APP_DIR, Config

log = logging.getLogger(__name__)

LOG_FILE = APP_DIR / "gui.log"
_MASK = "__SET__"  # sentinel: field configured, value not echoed back


class Bridge:
    def __init__(self, manager, config_path: Path | None = None):
        self.manager = manager
        self.config_path = Path(config_path) if config_path else (APP_DIR / "config.toml")

    # ------------------------------------------------------------------ state

    def get_state(self) -> dict:
        return self.manager.get_state()

    # --------------------------------------------------------------- controls

    def arm_thief(self, force: bool = False, mode: str | None = None) -> dict:
        mode = mode or getattr(self.manager.cfg, "_thief_mode", "both")
        return self.manager.arm_thief(mode=mode, force=force)

    def disarm_thief(self) -> dict:
        return self.manager.disarm_thief()

    def start_relay(self) -> dict:
        return self.manager.start_relay()

    def stop_relay(self) -> dict:
        return self.manager.stop_relay()

    def start_serve(self) -> dict:
        return self.manager.start_serve()

    def stop_serve(self) -> dict:
        return self.manager.stop_serve()

    def set_autostart(self, enabled: bool) -> dict:
        from ..autostart import enable_autostart, disable_autostart
        ok = enable_autostart() if enabled else disable_autostart()
        return {"ok": ok}

    # ---------------------------------------------------------------- pairing

    def pair_generate(self) -> dict:
        cfg = self.manager.cfg
        if not cfg.worker_url:
            return {"ok": False, "error": "no worker_url configured"}
        from ..worker_client import WorkerClient

        worker = WorkerClient(cfg.worker_url, cfg.worker_token, cfg)
        if not cfg.worker_token:
            token = worker.register(device_name="desktop", platform="GUI")
            if not token:
                return {"ok": False, "error": "registration failed"}
            cfg.worker_token = token
            try:
                from ..cli import _save_worker_token
                _save_worker_token(token)
            except Exception as e:
                log.warning("Token persist failed: %s", e)

        resp = worker._post("/api/pair/generate", {})
        if not resp.get("ok"):
            return {"ok": False, "error": resp.get("error", "pairing failed")}

        code = str(resp["code"])
        try:
            qr_data_url = self._code_qr(code)
        except Exception as e:
            log.warning("QR generation failed: %s", e)
            qr_data_url = ""
        return {"ok": True, "code": code, "expires_in": resp.get("expires_in", 300),
                "qr": qr_data_url}

    @staticmethod
    def _code_qr(code: str) -> str:
        import qrcode
        img = qrcode.make(code, box_size=6, border=2)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()

    # --------------------------------------------------------------- settings

    _FIELDS = {
        # payload key -> (type, config attribute)
        "min_percentage": (int, None), "max_percentage": (int, None),
        "volume": (float, None), "poll_interval": (float, None),
        "annoying": (bool, None),
        "quiet_hours": (list, None),
        "proxy_url": (str, None),
        "worker_url": (str, None), "admin_key": (str, None),
        "telegram_token": (str, None), "telegram_chat_id": (str, None),
        "email_smtp_server": (str, None), "email_smtp_port": (int, None),
        "email_sender": (str, None), "email_password": (str, None),
        "email_receiver": (str, None),
        "music_files": (list, None), "alarm_files": (list, None),
        "socket_secret": (str, None),
    }

    def get_settings(self) -> dict:
        """Current config as a plain dict. Secrets are masked with __SET__
        so the browser never sees them; saving the mask keeps them intact."""
        cfg = self.manager.cfg
        out: dict = {}
        for key, (typ, _attr) in self._FIELDS.items():
            val = getattr(cfg, key)
            out[key] = val
        for secret in ("telegram_token", "email_password", "admin_key", "socket_secret"):
            if out.get(secret):
                out[secret] = _MASK
        out["autostart"] = self._autostart_enabled()
        return {"ok": True, "settings": out}

    def save_settings(self, data: dict) -> dict:
        """Write settings to config.toml preserving comments (tomlkit),
        then hot-reload the live config."""
        import tomlkit

        path = self.config_path
        old_cfg = self.manager.cfg
        if path.exists():
            doc = tomlkit.parse(path.read_text(encoding="utf-8"))
        else:
            doc = tomlkit.document()
        table = doc.get("battery_notifier")
        if table is None:
            table = tomlkit.table()
            doc["battery_notifier"] = table

        for key, (typ, _attr) in self._FIELDS.items():
            if key not in data:
                continue
            val = data[key]
            if typ is int:
                val = int(float(val))
            elif typ is float:
                val = float(val)
            elif typ is bool:
                val = bool(val)
            elif typ is list:
                if key in ("music_files", "alarm_files"):
                    val = [str(v) for v in (val or [])]
                else:
                    val = list(val or [])
            else:
                # keep existing secret when the UI echoes the mask back
                if key in ("telegram_token", "email_password", "admin_key", "socket_secret") \
                        and val == _MASK:
                    val = getattr(old_cfg, key, "")
                val = "" if val is None else str(val)
            table[key] = val
            setattr(old_cfg, key, val)  # hot-apply to the running instance

        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(tomlkit.dumps(doc), encoding="utf-8")
        log.info("Settings saved to %s", path)
        return {"ok": True}

    @staticmethod
    def _autostart_enabled() -> bool:
        try:
            from ..autostart import is_autostart_enabled
            return is_autostart_enabled()
        except Exception:
            return False

    # ------------------------------------------------------------ file dialog

    def pick_files(self, kind: str = "music") -> dict:
        """Native multi-select file dialog. kind: music|alarm."""
        import webview
        window = webview.windows[0] if webview.windows else None
        if window is None:
            return {"ok": False, "files": []}
        file_types = ("Audio Files (*.wav;*.mp3;*.flac;*.ogg)", "All files (*.*)")
        result = window.create_file_dialog(
            webview.OPEN_DIALOG, allow_multiple=True, file_types=file_types,
        )
        files = list(result or [])
        return {"ok": True, "files": files}

    # ------------------------------------------------------------ diagnostics

    def run_diagnostics(self) -> dict:
        """Run doctor capturing stdout; split into per-check cards."""
        from ..diagnostics import run_doctor

        buf = io.StringIO()
        ok = False
        try:
            with redirect_stdout(buf):
                ok = run_doctor(self.manager.cfg)
        except Exception as e:
            buf.write(f"\n [x] Diagnostics crashed: {e}")
        text = buf.getvalue()
        sections: list[dict] = []
        current: dict | None = None
        header = re.compile(r"^ \[(\d+)\]\s+(.*)$")
        for line in text.splitlines():
            m = header.match(line)
            if m:
                current = {"title": f"[{m.group(1)}] {m.group(2)}", "body": "", "ok": True}
                sections.append(current)
            elif current is not None:
                body = current["body"] + line + "\n"
                lowered = body.lower()
                current["ok"] = not any(
                    bad in lowered for bad in ("fail", "unreachable", "missing",
                                               "malformed", "blocked", "error", "warn"))
                current["body"] = body
        return {"ok": ok, "sections": sections, "raw": text}

    # ------------------------------------------------------------------- logs

    def get_logs(self, lines: int = 200) -> dict:
        try:
            if not LOG_FILE.exists():
                return {"ok": True, "text": "(no log output yet)"}
            content = LOG_FILE.read_text(encoding="utf-8", errors="replace").splitlines()
            return {"ok": True, "text": "\n".join(content[-int(lines):])}
        except Exception as e:
            return {"ok": False, "text": f"(log read failed: {e})"}

    @staticmethod
    def setup_logging(verbose: bool = False) -> None:
        """Route app logs into gui.log so the Logs tab has content."""
        from logging.handlers import RotatingFileHandler
        level = logging.DEBUG if verbose else logging.INFO
        fmt = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(LOG_FILE, maxBytes=1 << 20, backupCount=2,
                                      encoding="utf-8")
        logging.basicConfig(level=level, format=fmt,
                            handlers=[logging.StreamHandler(), handler])
