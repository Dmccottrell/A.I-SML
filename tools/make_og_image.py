"""
make_og_image.py - Makes design/og.png, the 1200 x 630 picture that shows when a link to the website is shared (chat apps, social posts).

Run it again only when the wording or the look changes, then run `python tools/build_site.py` and commit `design/og.png` and `site/og.png`:

    python tools/make_og_image.py

Needs Pillow (`pip install pillow`, already needed for pictures). It draws the Emvryx mark (an E whose middle arm runs into a glowing ring) and two lines of text.
"""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401
from PIL import Image, ImageDraw, ImageFont

W, H = 1200, 630
BG, TEXT, MUTED, AMBER, CORE = (7, 8, 13), (238, 240, 246), (154, 163, 188), (139, 92, 246), (196, 181, 253)
FONTS = ["DejaVuSans-Bold.ttf", "LiberationSans-Bold.ttf", "NotoSans-Bold.ttf", "arialbd.ttf", "Arial Bold.ttf"]


def font(size, bold=True):
    for name in FONTS if bold else [f.replace("-Bold", "").replace("bd", "") for f in FONTS]:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def make(path):
    img = Image.new("RGB", (W, H), BG)
    glow = Image.new("RGB", (W, H), BG)
    gd = ImageDraw.Draw(glow)
    gd.ellipse([-300, -420, 900, 480], fill=(24, 16, 46))
    img = Image.blend(img, glow, 0.9)
    d = ImageDraw.Draw(img)
    # the mark, drawn on a 64 x 64 grid scaled up
    k, ox, oy = 7.2, 80, 120
    px = lambda x, y: (ox + x * k, oy + y * k)
    for pts in (((17, 16), (41, 16)), ((17, 48), (41, 48)), ((17, 16), (17, 48))):
        d.line([px(*pts[0]), px(*pts[1])], fill=TEXT, width=int(6 * k), joint="curve")
        for p in pts:
            x, y = px(*p)
            d.ellipse([x - 3 * k, y - 3 * k, x + 3 * k, y + 3 * k], fill=TEXT)
    d.line([px(17, 32), px(37, 32)], fill=AMBER, width=int(6 * k))
    x, y = px(17, 32)
    d.ellipse([x - 3 * k, y - 3 * k, x + 3 * k, y + 3 * k], fill=AMBER)
    cx, cy = px(46, 32)
    d.ellipse([cx - 12 * k, cy - 12 * k, cx + 12 * k, cy + 12 * k], fill=(44, 30, 84))
    d.ellipse([cx - 5.5 * k, cy - 5.5 * k, cx + 5.5 * k, cy + 5.5 * k], outline=CORE, width=int(3 * k))
    d.ellipse([cx - 1.8 * k, cy - 1.8 * k, cx + 1.8 * k, cy + 1.8 * k], fill=AMBER)
    d.text((600, 190), "Emvryx", font=font(120), fill=TEXT)
    for i, line in enumerate(("A family of five AI models.", "Shows its sources.", "Says \"I don't know\".")):
        d.text((602, 330 + i * 56), line, font=font(38, False), fill=MUTED)
    d.text((602, 540), "emvryx.app", font=font(34), fill=AMBER)
    img.save(path, "PNG", optimize=True)


if __name__ == "__main__":
    out = os.path.join(emvryx_paths.ROOT, "design", "og.png")
    make(out)
    print("wrote", out)
