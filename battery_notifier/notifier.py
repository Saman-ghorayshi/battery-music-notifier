from __future__ import annotations
import platform, logging, smtplib
from email.mime.text import MIMEText
import requests

log = logging.getLogger(__name__)

class Notifier:
    def __init__(self, cfg=None):
        self.cfg = cfg
        self.system = platform.system()
        self._impl = self._init_impl()

    def _init_impl(self):
        try:
            if self.system == "Windows":
                from win10toast import ToastNotifier
                return ToastNotifier()
            if self.system == "Darwin":
                import pync
                return pync
            if self.system == "Linux":
                import notify2
                notify2.init("battery-music-notifier")
                return notify2
        except Exception as e:
            log.warning("Notification backend unavailable: %s", e)
        return None

    def send(self, title: str, message: str) -> None:
        # 1. OS-level notification
        try:
            if self.system == "Windows" and self._impl:
                self._impl.show_toast(title, message, duration=5, threaded=True)
            elif self.system == "Darwin" and self._impl:
                self._impl.notify(title, message)
            elif self.system == "Linux" and self._impl:
                n = self._impl.Notification(title, message)
                n.show()
        except Exception as e:
            log.warning("OS notification failed: %s", e)

        # 2. Telegram
        self._send_telegram(title, message)
        # 3. Email
        self._send_email(title, message)

    def _send_telegram(self, title: str, message: str) -> None:
        if not self.cfg or not self.cfg.telegram_token or not self.cfg.telegram_chat_id:
            return
        proxies = {"http": self.cfg.proxy_url, "https": self.cfg.proxy_url} if self.cfg.proxy_url else None
        try:
            url = f"https://api.telegram.org/bot{self.cfg.telegram_token}/sendMessage"
            payload = {"chat_id": self.cfg.telegram_chat_id, "text": f"{title}: {message}"}
            requests.post(url, json=payload, proxies=proxies, timeout=5)
            log.info("Telegram notification sent.")
        except Exception as e:
            log.warning("Telegram notification failed: %s", e)

    def _send_email(self, title: str, message: str) -> None:
        if not self.cfg or not self.cfg.email_sender or not self.cfg.email_password or not self.cfg.email_receiver:
            return
        try:
            msg = MIMEText(f"{title}: {message}")
            msg["Subject"] = title
            msg["From"] = self.cfg.email_sender
            msg["To"] = self.cfg.email_receiver
            with smtplib.SMTP(self.cfg.email_smtp_server, self.cfg.email_smtp_port, timeout=10) as server:
                server.starttls()
                server.login(self.cfg.email_sender, self.cfg.email_password)
                server.send_message(msg)
            log.info("Email notification sent.")
        except Exception as e:
            log.warning("Email notification failed: %s", e)