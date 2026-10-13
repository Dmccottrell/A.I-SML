"""make_logos.py - writes the Emvryx logo files (E + glowing ring) in design/logo/ and web/icon.svg.

    python design/logo/make_logos.py

The mark is an E whose middle arm runs into a glowing ring (the model's core). The five models share it and
differ in colour and in how much the ring has grown: Ember (a small coal), Flare (a ring), Equinox (ring with
four ticks), Solstice (ring with eight rays), Apogee (ring with two halos). Small sizes (favicon, app icon)
use `small`: a bolder E and a solid dot.
"""
import math
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
CX, CY = 46, 32


def rays(c, r1, r2, n, w=2):
    return "".join(f'<path d="M{CX + r1 * math.cos(a):.1f} {CY + r1 * math.sin(a):.1f} L{CX + r2 * math.cos(a):.1f} '
                   f'{CY + r2 * math.sin(a):.1f}" stroke="{c}" stroke-width="{w}" stroke-linecap="round"/>'
                   for a in (i * 2 * math.pi / n for i in range(n)))


def mark(kind, main, accent, light=None, anim=False):
    """The inside of the 64 x 64 mark. `light` is the pale ring colour (defaults to the accent)."""
    light = light or accent
    pulse = lambda v: f'<animate attributeName="r" values="{v}" dur="1.6s" repeatCount="indefinite"/>' if anim else ""
    glow = {"ember": 9, "apogee": 15}.get(kind, 12)
    out = f'<circle cx="{CX}" cy="{CY}" r="{glow}" fill="{accent}" fill-opacity="0.16"/>'
    out += (f'<path d="M17 16 H41 M17 48 H41 M17 16 V48" stroke="{main}" stroke-width="6" stroke-linecap="round" '
            f'stroke-linejoin="round"/><path d="M17 32 H{36 if kind == "ember" else 37}" stroke="{accent}" stroke-width="6" '
            f'stroke-linecap="round"/>')
    if kind == "ember":
        out += f'<circle cx="{CX - 1}" cy="{CY}" r="3.4" fill="{accent}">{pulse("2.6;4.4;2.6")}</circle>'
    elif kind == "apogee":
        out += (f'<circle cx="{CX}" cy="{CY}" r="4.5" stroke="{light}" stroke-width="2.5">{pulse("4;6;4")}</circle>'
                f'<circle cx="{CX}" cy="{CY}" r="8.5" stroke="{accent}" stroke-width="1.6" stroke-opacity="0.7"/>'
                f'<circle cx="{CX}" cy="{CY}" r="12" stroke="{accent}" stroke-width="1.2" stroke-opacity="0.4"/>')
    else:
        ring = f'<circle cx="{CX}" cy="{CY}" r="5.5" stroke="{light if kind == "solstice" else accent}" stroke-width="3">{pulse("4.5;7;4.5")}</circle>'
        dot = f'<circle cx="{CX}" cy="{CY}" r="1.8" fill="{accent if kind != "flare" else light}"/>'
        out += ring + dot
        if kind == "equinox":
            out += rays(main, 8.5, 11, 4)
        elif kind == "solstice":
            out += rays(accent, 8.5, 11.5, 8)
    return out


def small(main, accent):
    """Favicon / app icon: bolder E, solid dot, no glow or fine detail."""
    return (f'<path d="M15 15 H42 M15 49 H42 M15 15 V49" stroke="{main}" stroke-width="8" stroke-linecap="round" stroke-linejoin="round"/>'
            f'<path d="M15 32 H34" stroke="{accent}" stroke-width="8" stroke-linecap="round"/>'
            f'<circle cx="49" cy="32" r="6.5" fill="{accent}"/>')


def file(inner, bg):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" width="256" height="256" fill="none">\n'
            f'<rect width="64" height="64" rx="14" fill="{bg}"/>\n{inner}\n</svg>\n')


def write(path, text):
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def main():
    dark, pale = "#07080D", "#EEF0F6"
    write(os.path.join(HERE, "emvryx-mark-dark.svg"), file(mark("main", pale, "#8B5CF6", "#C4B5FD"), dark))
    write(os.path.join(HERE, "emvryx-mark-light.svg"), file(mark("main", "#0D0F1A", "#7C3AED", "#8B5CF6"), "#F7F8FC"))
    models = {"ember": (pale, "#FFB05A", None), "flare": (pale, "#FF4B1F", "#FFF3E6"), "equinox": (pale, pale, None),
              "solstice": (pale, "#F2A60C", "#FFE7A0"), "apogee": ("#A8D1F5", "#A8D1F5", "#F4F9FF")}
    for name, (m, a, l) in models.items():
        write(os.path.join(HERE, f"{name}.svg"), file(mark(name, m, a, l), dark))
    write(os.path.join(ROOT, "web", "icon.svg"), file(small(pale, "#F5A524"), dark))       # the chat app keeps its amber icon (the website's violet one is emvryx-icon-small.svg)
    write(os.path.join(HERE, "emvryx-icon-small.svg"), file(small(pale, "#8B5CF6"), dark))
    return ["emvryx-mark-dark", "emvryx-mark-light", *models, "web/icon.svg", "emvryx-icon-small"]


if __name__ == "__main__":
    print("wrote:", ", ".join(main()))
