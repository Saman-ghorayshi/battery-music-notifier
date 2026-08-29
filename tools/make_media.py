# tools/make_media.py
"""Generates the README media: 3 animated demo GIFs (Pillow) + 2 animated
SVGs (hand-written, written separately). Re-run after changing the script:

    python tools/make_media.py

Everything lands in docs/assets/. Frames are drawn on GitHub-dark panels so
they look intentional on both themes.
"""
from PIL import Image, ImageDraw, ImageFont
import os

OUT = os.path.join(os.path.dirname(__file__), "..", "docs", "assets")
os.makedirs(OUT, exist_ok=True)

W, H = 800, 420
BG = "#0d1117"
PANEL = "#161b22"
PANEL_EDGE = "#30363d"
TEXT = "#e6edf3"
MUTED = "#8b949e"
BLUE = "#58a6ff"
GREEN = "#3fb950"
RED = "#f85149"
AMBER = "#d29922"
PURPLE = "#bc8cff"

FONT_DIR = "C:/Windows/Fonts/"


def font(name, size):
    return ImageFont.truetype(FONT_DIR + name, size)


def ease(t):
    """ease-out cubic"""
    t = min(max(t, 0.0), 1.0)
    return 1 - (1 - t) ** 3


def rr(d, box, r, fill=None, outline=None, width=1):
    d.rounded_rectangle(box, radius=r, fill=fill, outline=outline, width=width)


def text_c(d, xy, s, f, fill):
    l, t, r, b = d.textbbox((0, 0), s, font=f)
    d.text((xy[0] - (r - l) / 2, xy[1] - (b - t) / 2), s, font=f, fill=fill)


def laptop(d, x, y, w=190, h=118, screen=PANEL, edge=PANEL_EDGE, tint=None):
    """Laptop glyph, top-left at (x, y). Returns screen rect."""
    d.rounded_rectangle([x, y, x + w, y + h], radius=8, fill=screen, outline=tint or edge, width=2)
    d.rounded_rectangle([x - 12, y + h, x + w + 12, y + h + 14], radius=5, fill="#21262d", outline=edge)
    return [x, y, x + w, y + h]


def phone(d, x, y, w=92, h=180, tint=None):
    """Phone glyph. Returns screen rect."""
    d.rounded_rectangle([x, y, x + w, y + h], radius=14, fill=PANEL, outline=tint or PANEL_EDGE, width=2)
    d.rounded_rectangle([x + w / 2 - 14, y + 6, x + w / 2 + 14, y + 12], radius=3, fill="#21262d")
    return [x, y, x + w, y + h]


def cloud(d, cx, cy, tint=None):
    """Cloudflare-ish cloud glyph centered at cx, cy."""
    col = tint or "#f0883e"
    d.ellipse([cx - 62, cy - 22, cx - 14, cy + 14], fill=col)
    d.ellipse([cx - 34, cy - 34, cx + 30, cy + 16], fill=col)
    d.ellipse([cx + 12, cy - 24, cx + 60, cy + 14], fill=col)
    d.rounded_rectangle([cx - 58, cy - 2, cx + 58, cy + 14], radius=8, fill=col)


def waves(d, cx, cy, t, color, max_r=90, n=3):
    """Expanding siren arcs; t in [0,1) drives the phase."""
    for i in range(n):
        phase = (t * n + i / n) % 1.0
        r = 18 + phase * max_r
        alpha = int(255 * (1 - phase) * 0.9)
        col = color + f"{alpha:02x}"
        d.arc([cx - r, cy - r, cx + r, cy + r], 200, 340, fill=col, width=4)


def chip(d, x, y, s, f, fg, bg, pad=10):
    l, t, r, b = d.textbbox((0, 0), s, font=f)
    w, h = r - l + pad * 2, b - t + pad
    d.rounded_rectangle([x, y, x + w, y + h], radius=9, fill=bg)
    d.text((x + pad, y + pad / 2 - 1), s, font=f, fill=fg)
    return [x, y, x + w, y + h]


def base():
    im = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(im)
    d.text((20, H - 26), "battery-music-notifier", font=font("consolab.ttf", 15), fill="#30363d")
    return im, d


def overlay(base_im):
    return Image.new("RGBA", base_im.size, (0, 0, 0, 0))


def title(d, s, sub=None):
    text_c(d, (W / 2, 34), s, font("arialbd.ttf", 26), TEXT)
    if sub:
        text_c(d, (W / 2, 66), sub, font("segoeui.ttf", 16), MUTED)


def save_gif(frames, name, duration=100):
    pal = frames[0].quantize(colors=256)
    q = [f.quantize(palette=pal, dither=Image.NONE).convert("RGB") for f in frames]
    # rebuild palette-locked P frames for flicker-free playback
    out = []
    for f in q:
        out.append(f.quantize(palette=pal, dither=Image.NONE))
    out[0].save(
        os.path.join(OUT, name), save_all=True, append_images=out[1:],
        duration=duration, loop=0, optimize=True, disposal=2,
    )
    print("wrote", name, f"({len(frames)} frames)")


# ---------------------------------------------------------------------------
# GIF 1 - phone theft: arm -> unplug -> both scream -> stop everywhere
# ---------------------------------------------------------------------------

def gif_thief():
    N = 30
    frames = []
    fx = 460  # charger contact x on laptop side
    for i in range(N):
        im, d = base()
        title(d, "Thief Catcher", "charger pull -> both devices scream")

        # charger cable: laptop side fixed, phone side fixed, plug state
        unplug_t = ease((i - 7) / 3) if i >= 7 else 0
        # laptop (left), phone (right), cloud (top center)
        lscr = laptop(d, 60, 150, tint=RED if 12 <= i < 26 else None)
        pscr = phone(d, 640, 120, tint=RED if 10 <= i < 26 else None)
        cloud(d, W / 2, 120, tint=BLUE if 12 <= i < 24 else "#f0883e")

        # cable from laptop right edge to phone left edge
        y1, y2 = 200, 240
        x1, x2 = 262, 628
        if unplug_t == 0:
            d.line([x1, y1, x2, y2], fill="#6e7681", width=5)
            d.ellipse([x2 - 8, y2 - 8, x2 + 8, y2 + 8], fill="#6e7681")
        else:
            d.line([x1, y1, x1 + 60, y1 + 20], fill="#6e7681", width=5)
            # falling plug piece
            py = y2 + unplug_t * 90
            d.ellipse([x2 - 26, py - 8, x2 - 10, py + 8], fill="#6e7681")
            d.line([x2 - 10, py, x2 + 10, py], fill="#8b949e", width=5)

        # states
        f26 = font("arialbd.ttf", 22)
        if i < 7:
            chip(d, 648, 310, "ARMED", f26, "#0d1117", GREEN)
            text_c(d, (lscr[0] + 95, lscr[1] + 60), "watching", font("segoeui.ttf", 15), MUTED)
        elif i < 10:
            chip(d, 636, 310, "UNPLUGGED!", f26, "#0d1117", AMBER)
        elif i < 26:
            t = (i - 10) / 16
            waves(d, 705, 300, t, RED)
            waves(d, 150, 290, t, RED)
            chip(d, 630, 380, "THIEF_ALERT", font("consolab.ttf", 18), "#0d1117", RED)
            chip(d, 40, 380, "SIREN", font("arialbd.ttf", 18), "#0d1117", RED)
            # alert dot cloud path: phone -> cloud -> laptop
            if 11 <= i <= 17:
                tt = ease((i - 11) / 6)
                if tt < 0.5:
                    dot_x = 640 - tt * 2 * (640 - W / 2)
                    dot_y = 210 - tt * 2 * (210 - 150)
                else:
                    tt = (tt - 0.5) * 2
                    dot_x = W / 2 + tt * (262 - W / 2)
                    dot_y = 150 + tt * (200 - 150)
                d.ellipse([dot_x - 8, dot_y - 8, dot_x + 8, dot_y + 8], fill=RED)
            text_c(d, (W / 2, 120), "relay", font("segoeui.ttf", 14), "#0d1117")
        else:
            t = ease((i - 26) / 4)
            chip(d, 630, 380, "STOP EVERYWHERE", font("arialbd.ttf", 16), "#0d1117", GREEN)
            text_c(d, (lscr[0] + 95, lscr[1] + 60), "cleared", font("segoeui.ttf", 15), GREEN)
            text_c(d, (686, lscr[1] + 230), "cleared", font("segoeui.ttf", 15), GREEN)

        # phone screen content
        f_sm = font("segoeui.ttf", 14)
        d.text((652, 136), "Battery 87%", font=f_sm, fill=TEXT)
        if i < 7:
            d.text((652, 158), "charging", font=f_sm, fill=GREEN)
        elif i < 26:
            d.text((652, 158), "ON BATTERY", font=f_sm, fill=RED)

        # laptop screen content
        d.text((80, 162), "Battery Music", font=font("segoeui.ttf", 15), fill=TEXT)
        if 12 <= i < 26:
            d.text((80, 186), "ALERT: THIEF_ALERT", font=font("consolab.ttf", 13), fill=RED)
        elif i >= 26:
            d.text((80, 186), "alert cleared", font=font("segoeui.ttf", 13), fill=GREEN)
        else:
            d.text((80, 186), "relay listener ready", font=font("segoeui.ttf", 13), fill=MUTED)

        frames.append(im)
    save_gif(frames, "demo_thief.gif")


# ---------------------------------------------------------------------------
# GIF 2 - intruder guard: failed logon -> face -> lock+siren -> photo to phone
# ---------------------------------------------------------------------------

def gif_intruder():
    N = 34
    frames = []
    for i in range(N):
        im, d = base()
        title(d, "Intruder Guard", "failed logon -> face verdict -> lock, siren, photo")

        lscr = laptop(d, 90, 140, w=210, h=130, tint=RED if 15 <= i < 28 else None)
        pscr = phone(d, 645, 130, tint=BLUE if 22 <= i < 30 else None)
        cloud(d, W / 2, 112, tint=PURPLE if 20 <= i < 28 else "#f0883e")

        f_sm = font("segoeui.ttf", 14)
        fc = font("consolab.ttf", 13)

        if i < 6:
            # lock screen with password dots
            text_c(d, (195, 165), "Locked", font("arialbd.ttf", 18), TEXT)
            dots = "." * (2 + (i % 4))
            text_c(d, (195, 200), "password " + dots, fc, MUTED)
        elif i < 10:
            # failed logon shake + red
            off = 0 if i % 2 == 0 else 5
            text_c(d, (195 + off, 165), "Locked", font("arialbd.ttf", 18), RED)
            text_c(d, (195, 200), "Event 4625 - FAILED", fc, RED)
            chip(d, 120, 300, "failed logon detected", font("arialbd.ttf", 15), "#0d1117", AMBER)
        elif i < 17:
            # camera check
            if i == 10:
                ov = overlay(im); ImageDraw.Draw(ov).rectangle([0, 0, W, H], fill=(255, 255, 255, 70))
                im = Image.alpha_composite(im.convert("RGBA"), ov).convert("RGB")
                d = ImageDraw.Draw(im)
            text_c(d, (195, 165), "Face check", font("arialbd.ttf", 17), TEXT)
            # face oval + scanning brackets
            cx, cy = 195, 215
            d.ellipse([cx - 26, cy - 30, cx + 26, cy + 30], outline=BLUE, width=3)
            for k, (bx, by) in enumerate([(-36, -40), (26, -40), (-36, 22), (26, 22)]):
                sx = 1 if k in (1, 3) else -1
                sy = 1 if k in (2, 3) else -1
                d.line([cx + bx, cy + by, cx + bx + 14 * sx, cy + by], fill=BLUE, width=3)
                d.line([cx + bx, cy + by, cx + bx, cy + by + 14 * sy], fill=BLUE, width=3)
            if i >= 14:
                chip(d, 130, 300, "verdict: UNKNOWN", font("arialbd.ttf", 15), "#0d1117", RED)
            else:
                chip(d, 150, 300, "scanning...", font("arialbd.ttf", 15), "#0d1117", BLUE)
        elif i < 28:
            text_c(d, (195, 165), "LOCKED", font("arialbd.ttf", 24), RED)
            waves(d, 195, 220, (i - 15) / 13, RED, max_r=110)
            chip(d, 130, 300, "LOCKED + SIREN", font("arialbd.ttf", 15), "#0d1117", RED)
            # snapshot flies laptop -> cloud -> phone
            if 20 <= i <= 26:
                tt = ease((i - 20) / 6)
                if tt < 0.5:
                    px = 300 + tt * 2 * (W / 2 - 320)
                    py = 200 - tt * 2 * (200 - 130)
                else:
                    tt = (tt - 0.5) * 2
                    px = W / 2 + tt * (645 - W / 2)
                    py = 130 + tt * (190 - 130)
                d.rounded_rectangle([px - 22, py - 16, px + 22, py + 16], radius=4, fill=TEXT)
                d.polygon([px - 22, py + 16, px + 2, py - 6, px + 22, py + 16], fill="#58a6ff")
        else:
            text_c(d, (195, 165), "LOCKED", font("arialbd.ttf", 20), MUTED)
            chip(d, 120, 300, "standing down / capped", font("segoeui.ttf", 14), TEXT, PANEL)

        # phone side: receives photo
        if i < 20:
            d.text((660, 146), "watching", font=f_sm, fill=MUTED)
        else:
            d.text((660, 146), "THIEF_ALERT", font=font("consolab.ttf", 13), fill=RED)
            # tiny photo thumbnail
            d.rounded_rectangle([652, 170, 726, 214], radius=6, fill=TEXT)
            d.polygon([652, 214, 678, 188, 700, 214], fill=BLUE)
            d.ellipse([706, 176, 718, 188], fill=AMBER)
            d.text((652, 222), "from your laptop", font=font("segoeui.ttf", 11), fill=MUTED)

        if 20 <= i < 28:
            text_c(d, (W / 2, 112), "photo", font("segoeui.ttf", 14), "#0d1117")
        frames.append(im)
    save_gif(frames, "demo_intruder.gif")


# ---------------------------------------------------------------------------
# GIF 3 - pairing + test alert
# ---------------------------------------------------------------------------

def gif_pair():
    N = 26
    frames = []
    code = "4 8 2 9 1 3"
    for i in range(N):
        im, d = base()
        title(d, "Pair in 30 seconds", "one code, one account, every device")

        lscr = laptop(d, 90, 150, w=210, h=130, tint=GREEN if 15 <= i < 21 else None)
        pscr = phone(d, 645, 130, tint=GREEN if 15 <= i < 21 else None)
        cloud(d, W / 2, 112)

        if i < 15:
            text_c(d, (195, 172), "Pairing Code", font("segoeui.ttf", 15), MUTED)
            text_c(d, (195, 205), code, font("consolab.ttf", 30), GREEN)
            chip(d, 120, 300, "battery-music pair", font("consolab.ttf", 14), TEXT, PANEL)
        else:
            text_c(d, (195, 172), "Paired", font("arialbd.ttf", 20), GREEN)
            text_c(d, (195, 205), "account linked", font("segoeui.ttf", 14), MUTED)
            chip(d, 130, 300, "same account = same alarm", font("segoeui.ttf", 14), TEXT, PANEL)

        # phone: digits fill in
        typed = min(6, max(0, (i - 4) * 1))
        digits = code.split()
        shown = " ".join(digits[:typed])
        f_sm = font("segoeui.ttf", 14)
        d.text((660, 146), "Enter code", font=f_sm, fill=MUTED)
        d.rounded_rectangle([644, 172, 734, 204], radius=8, fill="#0d1117", outline=PANEL_EDGE)
        text_c(d, (689, 188), shown, font("consolab.ttf", 14), BLUE)
        if i >= 15:
            text_c(d, (689, 224), "PAIRED", font("arialbd.ttf", 16), GREEN)
        if i >= 20:
            # test alert dot phone -> cloud -> laptop
            tt = ease((i - 20) / 5)
            if tt < 0.5:
                px = 640 - tt * 2 * (640 - W / 2)
                py = 210 - tt * 2 * (210 - 130)
            else:
                tt = (tt - 0.5) * 2
                px = W / 2 + tt * (300 - W / 2)
                py = 130 + tt * (190 - 130)
            d.ellipse([px - 7, py - 7, px + 7, py + 7], fill=GREEN)
            chip(d, 630, 250, "SEND TEST ALERT", font("arialbd.ttf", 12), "#0d1117", GREEN)
        if i >= 23:
            waves(d, 195, 220, (i - 23) / 3, GREEN, max_r=70)
            text_c(d, (195, 250), "rings!", font("arialbd.ttf", 15), GREEN)
        frames.append(im)
    save_gif(frames, "demo_pair.gif")


if __name__ == "__main__":
    gif_thief()
    gif_intruder()
    gif_pair()
    print("done ->", os.path.abspath(OUT))
