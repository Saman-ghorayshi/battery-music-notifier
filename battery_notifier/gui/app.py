# battery_notifier/gui/app.py
"""Desktop GUI entry point.

Architecture:
  - pywebview window (EdgeChromium on Windows) hosting the vanilla-JS SPA
    bundled in gui/web/ -- no build step, fully offline.
  - pystray tray icon with dynamic menu; closing the window hides it to the
    tray, Quit tears everything down.
  - Single-instance enforced by binding a local port.
Cold start target: < 3 s (all service threads are lazy except heartbeat).
"""
from __future__ import annotations

import logging
import socket
import sys
import threading
import time
from pathlib import Path

WEB_DIR = Path(__file__).parent / "web"
SINGLE_INSTANCE_PORT = 8599


def _acquire_single_instance() -> socket.socket | None:
    """Bind a local port as an app-level mutex. None => already running."""
    try:
        lock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        lock.bind(("127.0.0.1", SINGLE_INSTANCE_PORT))
        lock.listen(1)
        return lock
    except OSError:
        return None


def _draw_tray_icon(pct: int, charging: bool):
    from PIL import Image, ImageDraw

    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    body = (26, 26, 46, 255)          # matches UI #1a1a2e
    outline = (48, 71, 94, 255)       # #30475e
    fill = (0, 212, 120, 255) if charging else (0, 212, 255, 255)  # green/cyan

    d.rounded_rectangle([4, 14, 52, 54], radius=8, fill=body, outline=outline, width=3)
    d.rounded_rectangle([53, 26, 60, 42], radius=3, fill=outline)   # terminal nub

    pct = max(0, min(100, int(pct)))
    if pct > 0:
        # >=2px tall so rounded_rectangle never gets y1 < y0 on near-empty batteries
        h = max(2, int((40 - 18) * pct / 100))
        d.rectangle([10, 50 - h, 46, 48], fill=fill)
    return img


def _build_tray(manager, bridge, open_window, quit_app):
    import pystray
    from PIL import Image

    state = {"pct": -1, "charging": False}

    def menu_items(item=None):
        thief_armed = manager.thief.is_alive()
        relay_on = bool(manager.relay and manager.relay.is_alive())
        yield pystray.MenuItem("Open", lambda *_: open_window(), default=True)
        yield pystray.Menu.SEPARATOR
        yield pystray.MenuItem(
            ("Disarm Thief" if thief_armed else "Arm Thief"),
            lambda *_: (
                manager.disarm_thief() if thief_armed else manager.arm_thief(force=True)
            ),
        )
        yield pystray.MenuItem(
            ("Stop Relay" if relay_on else "Start Relay"),
            lambda *_: manager.stop_relay() if relay_on else manager.start_relay(),
        )
        yield pystray.Menu.SEPARATOR
        yield pystray.MenuItem("Quit", lambda *_: quit_app())

    icon = pystray.Icon(
        "battery-music-notifier",
        _draw_tray_icon(state["pct"], state["charging"]),
        title="Battery Music Notifier",
        menu=pystray.Menu(lambda *a, **k: list(menu_items(*a, **k))),
    )

    def _refresher():
        while True:
            try:
                snap = manager.get_state()
                pct, charging = snap.get("battery_pct", -1), snap.get("charging", False)
                label = f"{pct}%" if pct >= 0 else "?"
                icon.title = f"Battery {label}{' ⚡' if charging else ''}"
                if (pct, charging) != (state["pct"], state["charging"]):
                    state.update(pct=pct, charging=charging)
                    icon.icon = _draw_tray_icon(pct, charging)
            except Exception as e:
                logging.getLogger(__name__).debug("tray refresh: %s", e)
            time.sleep(20)

    threading.Thread(target=_refresher, name="tray-refresh", daemon=True).start()
    return icon


def main(verbose: bool = False) -> int:
    lock = _acquire_single_instance()
    if lock is None:
        print("Battery Music Notifier GUI is already running (tray icon).")
        return 1

    import webview

    from .bridge import Bridge
    from .services import ServiceManager

    Bridge.setup_logging(verbose)
    log = logging.getLogger(__name__)

    manager = ServiceManager()
    bridge = Bridge(manager)
    quitting = threading.Event()

    def open_window():
        window = webview.windows[0] if webview.windows else None
        if window is not None:
            window.show()
            return
        create_window()

    def create_window():
        w = webview.create_window(
            "Battery Music Notifier",
            WEB_DIR.joinpath("index.html").as_uri(),
            js_api=bridge,
            width=1000, height=700, min_size=(820, 560),
            background_color="#12121f",
        )

        def _on_closing():
            if not quitting.is_set():
                w.hide()  # minimize to tray instead of exiting
                return False  # veto close
            return True

        w.events.closing += _on_closing
        return w

    def quit_app():
        quitting.set()
        try:
            manager.shutdown_all()
        finally:
            if webview.windows:
                try:
                    webview.windows[0].destroy()
                except Exception:
                    pass

    tray = _build_tray(manager, bridge, open_window, quit_app)
    threading.Thread(target=tray.run, daemon=True).start()

    create_window()
    try:
        webview.start(debug=verbose)  # blocks until Quit destroys the window
    except Exception as e:
        log.exception("GUI loop failed: %s", e)
        return 2
    finally:
        manager.shutdown_all()
        tray.stop()
    return 0


if __name__ == "__main__":
    if __package__:
        # Launched properly: python -m battery_notifier.gui.app, entry point,
        # or a frozen exe that preserved package context.
        sys.exit(main())
    # Plain-script launch (`python app.py`): no package context, so the
    # relative imports inside main() would fail. Re-enter through the
    # package instead -- every module then imports with its real name.
    import os
    _root = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
    if _root not in sys.path:
        sys.path.insert(0, _root)
    from battery_notifier.gui.app import main as _packaged_main
    sys.exit(_packaged_main())
