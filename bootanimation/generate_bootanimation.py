"""
Generate GridFront Detect Android boot animation.
800x1280 portrait, white background, GridFront 3x3 grid logo + text.
Part0: fade-in (30 frames, 1s)
Part1: breathing pulse loop (60 frames, 2s)
Output: bootanimation.zip (ZIP_STORED)
"""

import os
import math
import zipfile
from PIL import Image, ImageDraw, ImageFont

W, H = 800, 1280
BG = (0xF8, 0xF8, 0xF8)
FPS = 30

# Logo colors (left, center, right columns)
COL_LEFT = (0x4A, 0x84, 0xBF)
COL_CENTER = (0x3C, 0xAB, 0xD6)
COL_RIGHT = (0x90, 0xD2, 0xE8)

TEXT_DARK = (0x17, 0x17, 0x17)
TEXT_LIGHT = (0x73, 0x73, 0x73)

# Grid logo parameters
GRID_COLS = [COL_LEFT, COL_CENTER, COL_RIGHT]
GRID_ROWS = 3
SQUARE_SIZE = 52
SQUARE_GAP = 14
SQUARE_RADIUS = 12

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def lerp_color(bg, fg, alpha):
    """Blend fg over bg by alpha (0..1)."""
    return tuple(int(b + (f - b) * alpha) for b, f in zip(bg, fg))


def draw_rounded_rect(draw, xy, radius, fill):
    """Draw a rounded rectangle."""
    x0, y0, x1, y1 = xy
    draw.rounded_rectangle([x0, y0, x1, y1], radius=radius, fill=fill)


def get_font(size):
    """Try to load a clean sans-serif font, fall back to default."""
    font_paths = [
        "C:/Windows/Fonts/segoeui.ttf",
        "C:/Windows/Fonts/arial.ttf",
        "C:/Windows/Fonts/calibri.ttf",
    ]
    for fp in font_paths:
        if os.path.exists(fp):
            try:
                return ImageFont.truetype(fp, size)
            except Exception:
                continue
    return ImageFont.load_default()


def get_bold_font(size):
    """Try to load a bold sans-serif font."""
    font_paths = [
        "C:/Windows/Fonts/segoeuib.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
        "C:/Windows/Fonts/calibrib.ttf",
    ]
    for fp in font_paths:
        if os.path.exists(fp):
            try:
                return ImageFont.truetype(fp, size)
            except Exception:
                continue
    return get_font(size)


def draw_frame(alpha=1.0, scale=1.0):
    """
    Draw one frame of the boot animation.
    alpha: overall opacity (0..1) for fade-in
    scale: scale factor for breathing pulse (0.95..1.05 range)
    """
    img = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)

    # --- Grid Logo ---
    grid_w = GRID_ROWS * SQUARE_SIZE + (GRID_ROWS - 1) * SQUARE_GAP
    grid_h = grid_w  # 3x3 square grid
    # Position grid centered, slightly above vertical center
    logo_center_y = H * 0.42

    scaled_sq = int(SQUARE_SIZE * scale)
    scaled_gap = int(SQUARE_GAP * scale)
    scaled_grid_w = GRID_ROWS * scaled_sq + (GRID_ROWS - 1) * scaled_gap
    scaled_grid_h = scaled_grid_w

    grid_x0 = (W - scaled_grid_w) // 2
    grid_y0 = int(logo_center_y - scaled_grid_h // 2)

    for row in range(GRID_ROWS):
        for col in range(GRID_ROWS):
            base_color = GRID_COLS[col]
            color = lerp_color(BG, base_color, alpha)
            x = grid_x0 + col * (scaled_sq + scaled_gap)
            y = grid_y0 + row * (scaled_sq + scaled_gap)
            r = int(SQUARE_RADIUS * scale)
            draw_rounded_rect(draw, (x, y, x + scaled_sq, y + scaled_sq), r, color)

    # --- Text ---
    font_gf = get_bold_font(int(48 * scale))
    font_detect = get_font(int(36 * scale))

    gf_color = lerp_color(BG, TEXT_DARK, alpha)
    det_color = lerp_color(BG, TEXT_LIGHT, alpha)

    # "GridFront" text
    text_y = grid_y0 + scaled_grid_h + int(36 * scale)
    gf_text = "GridFront"
    gf_bbox = draw.textbbox((0, 0), gf_text, font=font_gf)
    gf_w = gf_bbox[2] - gf_bbox[0]
    gf_x = (W - gf_w) // 2
    draw.text((gf_x, text_y), gf_text, fill=gf_color, font=font_gf)

    # "Detect" text below
    det_y = text_y + (gf_bbox[3] - gf_bbox[1]) + int(8 * scale)
    det_text = "Detect"
    det_bbox = draw.textbbox((0, 0), det_text, font=font_detect)
    det_w = det_bbox[2] - det_bbox[0]
    det_x = (W - det_w) // 2
    draw.text((det_x, det_y), det_text, fill=det_color, font=font_detect)

    return img


def ease_in_out(t):
    """Smooth ease-in-out curve."""
    return t * t * (3.0 - 2.0 * t)


def generate():
    part0_dir = os.path.join(BASE_DIR, "part0")
    part1_dir = os.path.join(BASE_DIR, "part1")
    os.makedirs(part0_dir, exist_ok=True)
    os.makedirs(part1_dir, exist_ok=True)

    # Part 0: Fade in (30 frames)
    num_fade = 30
    print(f"Generating part0 ({num_fade} frames)...")
    for i in range(num_fade):
        t = i / (num_fade - 1)
        alpha = ease_in_out(t)
        img = draw_frame(alpha=alpha, scale=1.0)
        img.save(os.path.join(part0_dir, f"{i:05d}.png"), "PNG")

    # Part 1: Breathing pulse loop (60 frames)
    num_pulse = 60
    print(f"Generating part1 ({num_pulse} frames)...")
    for i in range(num_pulse):
        t = i / num_pulse  # 0..1 over the loop
        # Sine-based breathing: scale oscillates between 0.97 and 1.03
        breath = math.sin(t * 2 * math.pi)
        scale = 1.0 + 0.03 * breath
        # Also subtle alpha pulse between 0.85 and 1.0
        alpha = 0.925 + 0.075 * breath
        img = draw_frame(alpha=alpha, scale=scale)
        img.save(os.path.join(part1_dir, f"{i:05d}.png"), "PNG")

    # desc.txt
    desc_path = os.path.join(BASE_DIR, "desc.txt")
    with open(desc_path, "w", newline="\n") as f:
        f.write(f"{W} {H} {FPS}\n")
        f.write("p 1 0 part0\n")
        f.write("p 0 0 part1\n")
    print("Wrote desc.txt")

    # Package as bootanimation.zip (ZIP_STORED — critical for Android)
    zip_path = os.path.join(BASE_DIR, "bootanimation.zip")
    print(f"Creating {zip_path}...")
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_STORED) as zf:
        zf.write(desc_path, "desc.txt")
        for folder in ["part0", "part1"]:
            folder_path = os.path.join(BASE_DIR, folder)
            files = sorted(os.listdir(folder_path))
            for fname in files:
                fpath = os.path.join(folder_path, fname)
                zf.write(fpath, f"{folder}/{fname}")

    zip_size = os.path.getsize(zip_path)
    print(f"Done! bootanimation.zip = {zip_size / 1024 / 1024:.1f} MB")


if __name__ == "__main__":
    generate()
