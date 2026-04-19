"""GridFront Detect boot animation — unified boot experience on black.

Design:
  Black background. Official horizontal GridFront logo (9-square grid +
  "GridFront" wordmark) centered. Thin progress bar below. First frame of
  part0 equals the logo-partition image so bootlogo -> bootanim is seamless.

Layout (800x1280 portrait):
  Logo centered at ~42% vertical, scaled to ~65% width.
  Progress bar at ~68% vertical, 55% width.

Parts:
  part0: 20 frames @ 30fps — fade-in from black (0.67s)
  part1: 240 frames @ 30fps — static logo + progress bar sweep (8s, loops)
"""

import os
import zipfile
from PIL import Image, ImageDraw, ImageFont

W, H = 800, 1280
BG = (0, 0, 0)
FPS = 30

COL_CENTER = (0x3C, 0xAB, 0xD6)
TEXT_WHITE = (0xFF, 0xFF, 0xFF)
TEXT_DIM = (0x8A, 0x8A, 0x8A)
BAR_TRACK = (0x2A, 0x2F, 0x34)
BAR_FILL = COL_CENTER

LOGO_SRC = r"G:/Shared drives/GridFront Internal/Branding/Gridfront_Logo.png"
LOGO_WIDTH = int(W * 0.78)
LOGO_CENTER_Y = int(H * 0.42)

BAR_Y = int(H * 0.68)
BAR_W = int(W * 0.55)
BAR_H = 6
BAR_RADIUS = 3
BAR_X = (W - BAR_W) // 2

STATUS_TEXT = "Starting GridFront Detect"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def get_font(size, bold=False):
    paths = (
        ["C:/Windows/Fonts/segoeuib.ttf", "C:/Windows/Fonts/arialbd.ttf"]
        if bold
        else ["C:/Windows/Fonts/segoeui.ttf", "C:/Windows/Fonts/arial.ttf"]
    )
    for fp in paths:
        if os.path.exists(fp):
            try:
                return ImageFont.truetype(fp, size)
            except Exception:
                continue
    return ImageFont.load_default()


def load_logo_white_text():
    """Load the brand logo and swap the dark-navy wordmark for white.

    The official PNG has transparent bg, blue grid squares, and dark-navy
    "GridFront" text. On a black canvas the navy is invisible — recolor
    any dark pixels (luminance < 0.35) to white while preserving blues
    and alpha.
    """
    src = Image.open(LOGO_SRC).convert("RGBA")
    pixels = src.load()
    for y in range(src.height):
        for x in range(src.width):
            r, g, b, a = pixels[x, y]
            if a == 0:
                continue
            # Perceptual luminance; navy text is ~0.15, light blue squares ~0.7
            lum = (0.299 * r + 0.587 * g + 0.114 * b) / 255.0
            if lum < 0.35:
                pixels[x, y] = (255, 255, 255, a)
    scale = LOGO_WIDTH / src.width
    new_size = (LOGO_WIDTH, int(src.height * scale))
    return src.resize(new_size, Image.LANCZOS)


LOGO_RECOLORED = load_logo_white_text()


def apply_alpha(img, alpha):
    if alpha >= 1.0:
        return img
    base = Image.new("RGBA", img.size, (0, 0, 0, 0))
    return Image.blend(base, img, alpha)


def draw_logo(canvas, alpha=1.0):
    logo = apply_alpha(LOGO_RECOLORED, alpha)
    x = (W - logo.width) // 2
    y = LOGO_CENTER_Y - logo.height // 2
    canvas.alpha_composite(logo, (x, y))


def draw_progress_bar(canvas, progress, alpha=1.0):
    overlay = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    a = int(255 * alpha)
    track_c = BAR_TRACK + (a,)
    fill_c = BAR_FILL + (a,)

    draw.rounded_rectangle(
        [BAR_X, BAR_Y, BAR_X + BAR_W, BAR_Y + BAR_H],
        radius=BAR_RADIUS,
        fill=track_c,
    )
    fill_w = max(BAR_H, int(BAR_W * progress)) if progress > 0 else 0
    if fill_w > 0:
        draw.rounded_rectangle(
            [BAR_X, BAR_Y, BAR_X + fill_w, BAR_Y + BAR_H],
            radius=BAR_RADIUS,
            fill=fill_c,
        )

    font_status = get_font(22)
    status_c = TEXT_DIM + (a,)
    bb = draw.textbbox((0, 0), STATUS_TEXT, font=font_status)
    tx = (W - (bb[2] - bb[0])) // 2
    ty = BAR_Y + BAR_H + 24
    draw.text((tx, ty), STATUS_TEXT, fill=status_c, font=font_status)

    canvas.alpha_composite(overlay)


def draw_frame(alpha=1.0, progress=0.0):
    canvas = Image.new("RGBA", (W, H), BG + (255,))
    draw_logo(canvas, alpha=alpha)
    draw_progress_bar(canvas, progress=progress, alpha=alpha)
    return canvas.convert("RGB")


def ease_in_out(t):
    return t * t * (3.0 - 2.0 * t)


def generate():
    part0_dir = os.path.join(BASE_DIR, "part0")
    part1_dir = os.path.join(BASE_DIR, "part1")

    for d in (part0_dir, part1_dir):
        if os.path.isdir(d):
            for f in os.listdir(d):
                if f.endswith(".png"):
                    os.remove(os.path.join(d, f))
        os.makedirs(d, exist_ok=True)

    num_fade = 20
    print(f"part0: {num_fade} frames (fade-in)")
    for i in range(num_fade):
        t = i / (num_fade - 1)
        alpha = ease_in_out(t)
        draw_frame(alpha=alpha, progress=0.0).save(
            os.path.join(part0_dir, f"{i:05d}.png"), "PNG"
        )

    num_loop = 240
    print(f"part1: {num_loop} frames (progress sweep)")
    for i in range(num_loop):
        p = i / (num_loop - 1)
        p_eased = ease_in_out(p)
        draw_frame(alpha=1.0, progress=p_eased).save(
            os.path.join(part1_dir, f"{i:05d}.png"), "PNG"
        )

    final = draw_frame(alpha=1.0, progress=0.0)
    final.save(os.path.join(BASE_DIR, "bootlogo.png"), "PNG")
    print("saved bootlogo.png (logo-partition source image)")

    desc_path = os.path.join(BASE_DIR, "desc.txt")
    with open(desc_path, "w", newline="\n") as f:
        f.write(f"{W} {H} {FPS}\n")
        f.write("p 1 0 part0\n")
        f.write("p 0 0 part1\n")

    zip_path = os.path.join(BASE_DIR, "bootanimation.zip")
    print(f"packing {zip_path}...")
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_STORED) as zf:
        zf.write(desc_path, "desc.txt")
        for folder in ("part0", "part1"):
            for fname in sorted(os.listdir(os.path.join(BASE_DIR, folder))):
                zf.write(
                    os.path.join(BASE_DIR, folder, fname), f"{folder}/{fname}"
                )

    size = os.path.getsize(zip_path)
    print(f"done — {size / 1024 / 1024:.2f} MB")


if __name__ == "__main__":
    generate()
