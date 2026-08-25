#!/usr/bin/env python3
"""Generate the brand multi-resolution Windows icon.

Draws the same battery glyph the tray uses (dark body #1a1a2e, slate outline
#30475e, charge-fill #00d478) at every size Windows wants, into
battery_notifier/assets/icon.ico. Idempotent: safe to re-run any time the
design changes.

Usage:  python tools/make_icon.py
"""
from pathlib import Path

from PIL import Image, ImageDraw

SIZES = [256, 128, 64, 48, 32, 16]
OUT = Path(__file__).resolve().parent.parent / "battery_notifier" / "assets" / "icon.ico"

BODY = (26, 26, 46, 255)       # #1a1a2e
OUTLINE = (48, 71, 94, 255)    # #30475e
FILL = (0, 212, 120, 255)      # charging green


def draw_at(size: int) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    s = size / 64.0  # everything below is authored on a 64px grid

    def box(*xy):
        return [v * s for v in xy]

    def rrect(*xy, radius, **kw):
        d.rounded_rectangle(box(*xy), radius=max(1, radius * s), **kw)

    # battery body + terminal nub
    rrect(4, 14, 52, 54, radius=8, fill=BODY, outline=OUTLINE, width=3)
    rrect(53, 26, 60, 42, radius=3, fill=OUTLINE)

    # charge fill: ~70% like the tray icon
    h = max(2 * s, int((48 - 18 - 4) * 0.70))
    d.rectangle(box(10, 50 - h, 46, 48), fill=FILL)

    return img


def main():
    images = [draw_at(s) for s in SIZES]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    images[0].save(OUT, format="ICO",
                   sizes=[(s, s) for s in SIZES],
                   append_images=images[1:])
    print(f"wrote {OUT} ({OUT.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
