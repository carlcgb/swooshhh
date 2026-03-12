"""Generate swooshhh.ico to match the tray icon (for the .exe). Same design as make_tray_icon in swooshhh.py."""
from PIL import Image, ImageDraw

W, H = 64, 64
BG = (45, 55, 72)
BLUE = (99, 179, 237)

img = Image.new("RGBA", (W, H), color=(*BG, 255))
draw = ImageDraw.Draw(img)
draw.rectangle([8, 8, 56, 56], outline=BLUE, width=2)
draw.rectangle([0, 24, 12, 40], fill=BLUE)
del draw

# Single 256x256 frame for reliable embedding in Windows exe
img_large = img.resize((256, 256), Image.LANCZOS)
img_large.save("swooshhh.ico", format="ICO", sizes=[(256, 256)])
