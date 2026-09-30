#!/usr/bin/env python3
"""Generate the Android launcher icon set for Battery Music Notifier.

Brand: dark-navy rounded square, white alarm bell with the purple accent,
charging-green spark -- same family as the Windows .ico and the app themes.

Writes (idempotent):
  app/src/main/res/mipmap-anydpi-v26/ic_launcher.xml + ic_launcher_round.xml
  app/src/main/res/values/ic_launcher_background.xml
  app/src/main/res/mipmap-{mdpi..xxxhdpi}/ic_launcher.png          (legacy)
  app/src/main/res/mipmap-{mdpi..xxxhdpi}/ic_launcher_round.png    (legacy)
  app/src/main/res/mipmap-{mdpi..xxxhdpi}/ic_launcher_foreground.png (adaptive)

Usage:  python tools/make_android_icon.py
"""
from pathlib import Path

from PIL import Image, ImageDraw

RES = Path(__file__).resolve().parent.parent / "android" / "app" / "src" / "main" / "res"

NAVY = (19, 17, 24, 255)        # #131118 -- the dark theme background
NAVY_EDGE = (42, 38, 54, 255)   # subtle rim
PURPLE = (185, 166, 255, 255)   # #B9A6FF -- dark-theme accent
PURPLE_DEEP = (72, 60, 130, 255)
WHITE = (255, 255, 255, 255)
GREEN = (0, 212, 120, 255)      # charging spark

DENSITIES = {  # launcher icon sizes in px
    "mdpi": 48, "hdpi": 72, "xhdpi": 96, "xxhdpi": 144, "xxxhdpi": 192,
}
FG = 432  # adaptive foreground canvas (108dp @ xxxhdpi)


def rounded_bg(size: int, radius_ratio: float = 0.22) -> Image.Image:
    """Dark navy rounded square with a soft purple rim glow."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    r = int(size * radius_ratio)
    d.rounded_rectangle([0, 0, size - 1, size - 1], radius=r, fill=NAVY,
                        outline=NAVY_EDGE, width=max(1, size // 64))
    # subtle purple glow, top-left
    glow = int(size * 0.5)
    gl = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    gd = ImageDraw.Draw(gl)
    gd.ellipse([-size * 0.2, -size * 0.2, glow, glow], fill=(72, 60, 130, 70))
    img = Image.alpha_composite(img, gl)
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, size - 1, size - 1], radius=r,
                        outline=(90, 80, 120, 90), width=max(1, size // 96))
    return img


def draw_glyph(img: Image.Image, scale: float = 1.0) -> None:
    """Alarm bell + music note + green spark, drawn on a 100-unit grid
    centered in the image (safe-zone aware for adaptive icons)."""
    d = ImageDraw.Draw(img)
    W = img.size[0]
    u = W / 100.0 * scale
    cx = W / 2

    def box(x0, y0, x1, y1):
        return [cx + (x0 - 50) * u, (y0) * u, cx + (x1 - 50) * u, (y1) * u]

    def pt(x, y):
        return (cx + (x - 50) * u, (y) * u)

    # bell body: dome + skirt
    d.pieslice(box(28, 22, 72, 66), 180, 360, fill=WHITE)
    d.rounded_rectangle(box(28, 44, 72, 62), radius=int(4 * u), fill=WHITE)
    # bell lip
    d.rounded_rectangle(box(24, 60, 76, 68), radius=int(4 * u), fill=WHITE)
    # clapper
    d.ellipse(box(44, 68, 56, 78), fill=PURPLE)
    # music note (purple), upper-right of the bell
    d.ellipse(box(64, 30, 76, 40), fill=PURPLE)
    d.rounded_rectangle(box(71, 18, 75, 37), radius=int(1.5 * u), fill=WHITE)
    # flag
    d.polygon([pt(75, 18), pt(84, 24), pt(75, 30)], fill=WHITE)
    # charging spark (green), lower-left
    d.polygon([pt(30, 62), pt(38, 62), pt(32, 76),
               pt(40, 68), pt(34, 76)], fill=GREEN)


def legacy(size: int) -> Image.Image:
    img = rounded_bg(size)
    draw_glyph(img, scale=1.0)
    return img


def foreground() -> Image.Image:
    """Adaptive foreground: glyph in the middle 66/108 safe zone."""
    img = Image.new("RGBA", (FG, FG), (0, 0, 0, 0))
    draw_glyph(img, scale=0.62)  # shrink into the safe zone
    return img


def background() -> Image.Image:
    img = Image.new("RGBA", (FG, FG), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, FG, FG], fill=NAVY)
    gl = Image.new("RGBA", (FG, FG), (0, 0, 0, 0))
    gd = ImageDraw.Draw(gl)
    gd.ellipse([-FG * 0.25, -FG * 0.25, FG * 0.75, FG * 0.75], fill=(72, 60, 130, 90))
    return Image.alpha_composite(img, gl)


def main() -> None:
    anydpi = RES / "mipmap-anydpi-v26"
    anydpi.mkdir(parents=True, exist_ok=True)
    (anydpi / "ic_launcher.xml").write_text(
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<adaptive-icon xmlns:android="http://schemas.android.com/apk/res/android">\n'
        '    <background android:drawable="@mipmap/ic_launcher_background"/>\n'
        '    <foreground android:drawable="@mipmap/ic_launcher_foreground"/>\n'
        "</adaptive-icon>\n", encoding="utf-8")
    (anydpi / "ic_launcher_round.xml").write_text(
        (anydpi / "ic_launcher.xml").read_text(encoding="utf-8"), encoding="utf-8")
    (RES / "mipmap-anydpi-v26" / "ic_launcher_background.xml").unlink(missing_ok=True)

    bg = background()
    fg = foreground()
    for dpi, size in DENSITIES.items():
        d = RES / f"mipmap-{dpi}"
        d.mkdir(parents=True, exist_ok=True)
        legacy(size).save(d / "ic_launcher.png")
        # round legacy: same art, circular mask
        rimg = legacy(size)
        mask = Image.new("L", (size, size), 0)
        md = ImageDraw.Draw(mask)
        md.ellipse([0, 0, size, size], fill=255)
        rimg.putalpha(mask)
        rimg.save(d / "ic_launcher_round.png")
        bg.resize((size, size), Image.LANCZOS).save(d / "ic_launcher_background.png")
        fg.resize((size, size), Image.LANCZOS).save(d / "ic_launcher_foreground.png")
    print(f"Android launcher icons written to {RES}")


if __name__ == "__main__":
    main()
