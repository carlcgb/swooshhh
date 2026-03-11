"""Generate swooshhh.ico (same design as tray: square with blue indicator) for PyInstaller --icon."""
import sys

# Match tray icon: dark gray background, blue outline square, blue bar on left
BG_RGB = (45, 55, 72)
BLUE_RGB = (99, 179, 237)

def draw_icon(size):
    """Draw the square-with-indicator icon at given size (same look as tray)."""
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (size, size), color=BG_RGB)
    draw = ImageDraw.Draw(img)
    # Scale from 64x64 design: inner rect [8,8,56,56], bar [0,24,12,40], outline width 2
    s = size / 64.0
    pad = max(1, int(8 * s))
    w = max(1, int(2 * s))  # outline width
    draw.rectangle([pad, pad, size - pad, size - pad], outline=BLUE_RGB, width=w)
    bar_t = int(24 * s)
    bar_r = int(12 * s)
    bar_b = int(40 * s)
    if bar_r > 0 and bar_b > bar_t:
        draw.rectangle([0, bar_t, bar_r, bar_b], fill=BLUE_RGB)
    return img

def main():
    ico = "swooshhh.ico"
    try:
        from PIL import Image
        base = draw_icon(256)
        base.save(ico, format="ICO", sizes=[(256, 256), (48, 48), (32, 32), (16, 16)])
        print(f"Created {ico} (square + indicator)")
        return 0
    except Exception as e:
        print(f"Failed: {e}", file=sys.stderr)
        return 1

if __name__ == "__main__":
    sys.exit(main())
