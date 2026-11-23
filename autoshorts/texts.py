"""Text layers (titles, labels, emoji) drawn with Pillow and overlaid by ffmpeg for a time range.

The browser preview (web/src/lib/texts.ts) mirrors this file: same wrapping, same block geometry, same baselines.
Change them together. Times are seconds from the CLIP's start (not the source's), so a title stays at the start of the
clip when the cut is trimmed. Emoji: single code points via Apple Color Emoji (macOS); ZWJ sequences are not composed."""
import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .fonts import FONT_DIR, FONTS, rgba as _rgba

OW, OH = 1080, 1920
EMOJI_FONT = "/System/Library/Fonts/Apple Color Emoji.ttc"
EMOJI_RE = re.compile("([\U0001F300-\U0001FAFF⌀-⏿☀-➿⬀-⯿])")
LINE = 1.25          # line height, in font sizes
BASE = 1.0           # baseline distance from the top of a line, in font sizes
EMOJI_ADV = 1.2      # an emoji takes this many font sizes of width
EMOJI_PX = 1.15      # and is drawn this big
MAX_W = 0.88         # wrap at this fraction of the frame width
DEFAULT = {"id": "t", "text": "Metni yaz", "start": 0.0, "end": 3.0, "x": 0.5, "y": 0.2, "size": 0.07, "font": "montserrat",
           "color": "#FFFFFF", "stroke": 1.0, "bg": {"on": False, "color": "#000000", "opacity": 0.55}}


def clean_layers(layers) -> list[dict]:
    """Validate/clamp the text layers coming from the browser."""
    hexre = re.compile(r"^#[0-9a-fA-F]{6}$")
    out = []
    for i, l in enumerate((layers or [])[:12]):
        l = {**DEFAULT, **l}
        if l["font"] not in FONTS:
            raise ValueError(f"Bilinmeyen font: {l['font']}")
        bg = {**DEFAULT["bg"], **(l.get("bg") or {})}
        for c in (l["color"], bg["color"]):
            if not hexre.match(str(c)):
                raise ValueError(f"Geçersiz renk: {c}")
        text = str(l["text"]).replace("‍", "").replace("\r", "")[:200]
        s = max(0.0, float(l["start"]))
        e = max(s + 0.1, float(l["end"]))
        out.append({"id": str(l.get("id") or f"t{i}")[:24], "text": text, "start": round(s, 2), "end": round(e, 2),
                    "x": min(1.0, max(0.0, float(l["x"]))), "y": min(1.0, max(0.0, float(l["y"]))),
                    "size": min(0.2, max(0.02, float(l["size"]))), "font": l["font"], "color": str(l["color"]),
                    "stroke": min(3.0, max(0.0, float(l["stroke"]))),
                    "bg": {"on": bool(bg["on"]), "color": str(bg["color"]), "opacity": min(1.0, max(0.0, float(bg["opacity"])))}})
    return out


def runs(s: str) -> list[tuple[bool, str]]:
    """Split a word into text runs and single-emoji runs (variation selectors dropped)."""
    out = []
    for part in EMOJI_RE.split(s.replace("️", "")):
        if not part:
            continue
        out.append((bool(EMOJI_RE.fullmatch(part)), part))
    return out


class Renderer:
    def __init__(self, layer: dict):
        self.l = layer
        self.px = int(OW * layer["size"])
        name, var = FONTS[layer["font"]]
        self.font = ImageFont.truetype(str(FONT_DIR / name), self.px)
        if var:
            try:
                self.font.set_variation_by_name(var)
            except Exception:  # noqa: BLE001
                pass
        self.sp = self.font.getlength(" ")
        self.adv = self.px * EMOJI_ADV

    def run_w(self, is_emoji: bool, t: str) -> float:
        return self.adv if is_emoji else self.font.getlength(t)

    def word_w(self, w: str) -> float:
        return sum(self.run_w(e, t) for e, t in runs(w))

    def wrap(self) -> list[list[str]]:
        """Greedy word wrap; explicit newlines kept."""
        lines = []
        for raw in self.l["text"].split("\n"):
            cur, cw = [], 0.0
            for w in raw.split(" "):
                if w == "":
                    continue
                ww = self.word_w(w)
                add = ww if not cur else self.sp + ww
                if cur and cw + add > OW * MAX_W:
                    lines.append(cur)
                    cur, cw = [w], ww
                else:
                    cur.append(w)
                    cw += add
            lines.append(cur)
        return lines

    def geometry(self):
        """Lines with widths, plus the layer's box on the 1080x1920 canvas."""
        lines = self.wrap()
        widths = [sum(self.word_w(w) for w in ln) + self.sp * max(0, len(ln) - 1) for ln in lines]
        block_w = max(widths + [1.0])
        lh = self.px * LINE
        block_h = lh * len(lines)
        stroke = self.stroke_px()
        padx, pady = (self.px * 0.4, self.px * 0.22) if self.l["bg"]["on"] else (0.0, 0.0)
        pad_x, pad_y = padx + stroke + 2, pady + stroke + 2
        w, h = block_w + 2 * pad_x, block_h + 2 * pad_y
        cx, cy = self.l["x"] * OW, self.l["y"] * OH
        return {"lines": lines, "widths": widths, "lh": lh, "pad": (pad_x, pad_y), "size": (w, h),
                "origin": (cx - w / 2, cy - h / 2), "block": (block_w, block_h), "padbg": (padx, pady)}

    def stroke_px(self) -> int:
        return max(2, round(self.px / 11 * self.l["stroke"])) if self.l["stroke"] > 0 else 0

    def render(self) -> tuple[Image.Image, int, int]:
        g = self.geometry()
        W, H = int(g["size"][0]) + 1, int(g["size"][1]) + 1
        img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        l = self.l
        pad_x, pad_y = g["pad"]
        if l["bg"]["on"]:
            r, gcol, b, _ = _rgba(l["bg"]["color"])
            bx, by = g["padbg"]
            d.rounded_rectangle((pad_x - bx, pad_y - by, pad_x + g["block"][0] + bx, pad_y + g["block"][1] + by),
                                radius=self.px * 0.35, fill=(r, gcol, b, int(255 * l["bg"]["opacity"])))
        stroke = self.stroke_px()
        color = _rgba(l["color"])
        emoji_font = None
        for i, ln in enumerate(g["lines"]):
            x = pad_x + (g["block"][0] - g["widths"][i]) / 2
            base = pad_y + i * g["lh"] + self.px * BASE
            for wi, w in enumerate(ln):
                for is_emoji, t in runs(w):
                    if is_emoji:
                        if emoji_font is None:
                            try:
                                emoji_font = ImageFont.truetype(EMOJI_FONT, 160)
                            except OSError:
                                emoji_font = False
                        if emoji_font:
                            e = Image.new("RGBA", (200, 200), (0, 0, 0, 0))
                            ImageDraw.Draw(e).text((10, 10), t, font=emoji_font, embedded_color=True)
                            box = e.getbbox()
                            if box:
                                size = int(self.px * EMOJI_PX)
                                e = e.crop((10, 10, 170, 170)).resize((size, size), Image.LANCZOS)
                                img.alpha_composite(e, (int(x + (self.adv - size) / 2), int(base - size * 0.85)))
                        x += self.adv
                    else:
                        d.text((x, base), t, font=self.font, fill=color, anchor="ls", stroke_width=stroke, stroke_fill=(0, 0, 0, 255))
                        x += self.font.getlength(t)
                if wi + 1 < len(ln):
                    x += self.sp
        return img, int(g["origin"][0]), int(g["origin"][1])


def render_layers(td: Path, layers: list[dict], length: float) -> list[tuple[Path, int, int, float, float]]:
    """PNG per visible layer: [(png, x, y, start, end)] with the time range clamped to the clip."""
    out = []
    for n, l in enumerate(clean_layers(layers)):
        s, e = l["start"], min(l["end"], length)
        if s >= length or e <= s or not l["text"].strip():
            continue
        img, x, y = Renderer(l).render()
        p = Path(td) / f"text{n}.png"
        img.save(p)
        out.append((p, x, y, s, e))
    return out
