from __future__ import annotations
import platform, logging
log = logging.getLogger(__name__)

class Notifier:
    def __init__(self):
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
        try:
            if self.system == "Windows" and self._impl:
                self._impl.show_toast(title, message, duration=5, threaded=True)
            elif self.system == "Darwin" and self._impl:
                self._impl.notify(title, message)
            elif self.system == "Linux" and self._impl:
                n = self._impl.Notification(title, message)
                n.show()
        except Exception as e:
            log.warning("Notification failed: %s", e)
