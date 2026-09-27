# battery_notifier/qrpair.py
"""QR pairing payload + rendering.

The laptop renders BMN1|<relay_url>|<6-digit-code>; the phone's Scan-QR
screen decodes it, fills both fields, and pairs without typing anything.
One versioned prefix (BMN1) so future formats can coexist: an unknown
prefix is ignored, never mis-parsed.
"""
from __future__ import annotations
import logging
import os

log = logging.getLogger(__name__)

PREFIX = "BMN1"


def build_pair_payload(worker_url: str, code: str) -> str:
    url = (worker_url or "").strip().rstrip("/")
    code = (code or "").strip()
    if not url or not code:
        raise ValueError("worker_url and code are required")
    return f"{PREFIX}|{url}|{code}"


def parse_pair_payload(text: str) -> tuple[str, str] | None:
    """(worker_url, code) from a BMN1 payload, or None for anything else."""
    if not text:
        return None
    parts = text.strip().split("|")
    if len(parts) != 3 or parts[0] != PREFIX:
        return None
    url, code = parts[1].strip(), parts[2].strip()
    if not url.startswith(("http://", "https://")) or not code.isdigit():
        return None
    return url, code


def ascii_qr(payload: str) -> str:
    """Unicode block QR for the terminal (falls back to empty on error)."""
    try:
        import qrcode
        qr = qrcode.QRCode(border=1)
        qr.add_data(payload)
        qr.make(fit=True)
        return qr.print_ascii(invert=True) or ""
    except Exception as e:
        return f"(terminal QR unavailable: {e})"


def show_qr_window(payload: str, ttl_seconds: int = 300,
                   linked_event=None) -> None:
    """Topmost window with a large scannable QR. Blocks the calling thread
    until closed, the pairing code's TTL expires, or -- the smart part --
    `linked_event` fires: the laptop watches the relay and closes the QR
    the moment a device actually pairs."""
    if os.name != "nt":
        return
    try:
        import qrcode
        import tkinter as tk
    except Exception as e:
        log.warning("QR window unavailable: %s", e)
        return

    img = qrcode.make(payload).resize((420, 420))

    try:
        root = tk.Tk()
    except Exception as e:
        log.warning("QR window could not open: %s", e)
        return
    root.title("Pair with Battery Music Notifier")
    root.attributes("-topmost", True)
    root.configure(bg="white")

    from PIL import ImageTk
    photo = ImageTk.PhotoImage(img)
    tk.Label(root, image=photo, bg="white").pack(padx=20, pady=(20, 8))
    tk.Label(root, text="Scan with Battery Music Notifier -> Pair screen -> Scan QR",
             font=("Segoe UI", 11), bg="white").pack(padx=20, pady=(0, 4))
    countdown = tk.Label(root, bg="white", fg="#666",
                         font=("Segoe UI", 10))
    countdown.pack(pady=(0, 16))

    remaining = {"t": ttl_seconds}

    def tick() -> None:
        if not root.winfo_exists():
            return
        if linked_event is not None and linked_event.is_set():
            countdown.config(text="✓ Device paired! You can close this.",
                             fg="#2e7d32", font=("Segoe UI", 12, "bold"))
            root.after(2500, lambda: root.destroy() if root.winfo_exists() else None)
            return
        if remaining["t"] > 0:
            m, sec = divmod(remaining["t"], 60)
            countdown.config(text=f"code expires in {m:02d}:{sec:02d}")
            remaining["t"] -= 1
            root.after(1000, tick)
        else:
            try:
                root.destroy()
            except Exception:
                pass

    tick()
    root.mainloop()
