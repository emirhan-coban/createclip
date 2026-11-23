"""Fonts shared by the text layers (the browser draws the same files from /fonts/*.ttf)."""
from pathlib import Path

FONT_DIR = Path(__file__).parent / "fonts"
FONTS = {
    "montserrat": ("Montserrat.ttf", "ExtraBold"),
    "poppins": ("Poppins-Bold.ttf", None),
    "gabarito": ("Gabarito.ttf", "ExtraBold"),
}


def rgba(hexcol: str):
    h = hexcol.lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), 255)
