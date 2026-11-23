"""Word-by-word captions drawn with Pillow and laid over the video by ffmpeg (no libass needed: this ffmpeg has none).

The browser preview (web/src/lib/captions.ts + CaptionLayer) mirrors this file: same chunking, same state timeline,
same font metrics. Change them together. Word times are seconds on the video's own timeline."""
import re
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

FONT_DIR = Path(__file__).parent / "fonts"
FONTS = {
    "montserrat": ("Montserrat.ttf", "ExtraBold"),
    "poppins": ("Poppins-Bold.ttf", None),
    "gabarito": ("Gabarito.ttf", "ExtraBold"),
}
SWEAR_STEMS = ("sik", "amk", "amına", "amina", "orospu", "piç", "yarrak", "göt", "got", "ibne", "mına")
DEFAULT_STYLE = {"font": "montserrat", "size": 0.075, "ypos": 0.62, "chunk": 3, "color": "#FFFFFF", "active": "#FFDD00",
                 "stroke": 1.0, "upper": True, "mask": False, "sync": -0.08}
OW, OH = 1080, 1920


def clean_style(s: dict | None) -> dict:
    """Validate/clamp a style coming from the browser; unknown keys are dropped, missing ones get the defaults."""
    s = {**DEFAULT_STYLE, **(s or {})}
    if s["font"] not in FONTS:
        raise ValueError(f"Bilinmeyen font: {s['font']}")
    hexre = re.compile(r"^#[0-9a-fA-F]{6}$")
    for k in ("color", "active"):
        if not hexre.match(str(s[k])):
            raise ValueError(f"Geçersiz renk: {s[k]}")
    return {"font": s["font"], "size": min(0.16, max(0.03, float(s["size"]))), "ypos": min(0.95, max(0.02, float(s["ypos"]))),
            "chunk": int(min(6, max(1, int(s["chunk"])))), "color": str(s["color"]), "active": str(s["active"]),
            "stroke": min(3.0, max(0.0, float(s["stroke"]))), "upper": bool(s["upper"]), "mask": bool(s["mask"]),
            "sync": min(1.0, max(-1.0, float(s["sync"])))}


def clean_words(words, limit: int = 1500) -> list[dict]:
    out = []
    for w in (words or [])[:limit]:
        text = str(w.get("word", "")).strip()[:40]
        if not text:
            continue
        s = max(0.0, float(w["start"]))
        e = max(s + 0.02, float(w["end"]))
        out.append({"word": text, "start": round(s, 3), "end": round(e, 3)})
    out.sort(key=lambda w: w["start"])
    return out


def tr_lower(s: str) -> str:
    return s.replace("İ", "i").replace("I", "ı").lower()


def tr_upper(s: str) -> str:
    return s.replace("i", "İ").replace("ı", "I").upper()


def mask_word(w: str) -> str:
    core = re.sub(r"[^\wçğıöşüÇĞİÖŞÜ]", "", w)
    if core and tr_lower(core).startswith(SWEAR_STEMS):
        i = w.find(core[0])
        return w[:i + 1] + "*" * (len(core) - 1) + w[i + len(core):]
    return w


def _rgba(hexcol: str):
    h = hexcol.lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), 255)


def _chunks(words, size):
    out, cur = [], []
    for w in words:
        cur.append(w)
        if len(cur) == size or w["word"].endswith((".", "?", "!", ",")):
            out.append(cur)
            cur = []
    if cur:
        out.append(cur)
    return out


def build_states(words, chunk: int, sync: float = 0.0):
    """-> [(start, end, active_index, chunk_words)], strictly sequential (no overlaps).

    Overlapping states used to shift every later caption: the concat timeline is the sum of durations, so an entry that
    starts before the previous one ended was placed late and the error accumulated. `sync` (seconds, positive = later)
    moves every caption in time."""
    raw = []
    for ch in _chunks(list(words), chunk):
        for i, w in enumerate(ch):
            end = ch[i + 1]["start"] if i + 1 < len(ch) else w["end"] + 0.15
            end = min(end, w["start"] + 1.5)
            raw.append([max(0.0, w["start"] + sync), max(0.0, max(end, w["start"] + 0.04) + sync), i, ch])
    raw.sort(key=lambda s: s[0])
    out, t = [], 0.0
    for k, (s, e, i, ch) in enumerate(raw):
        s = max(s, t)
        if k + 1 < len(raw):
            e = min(e, max(raw[k + 1][0], s + 0.04))   # never run into the next caption
        e = max(e, s + 0.04)
        out.append((s, e, i, ch))
        t = e
    return out


class Drawer:
    """Draws one caption state (a chunk of words, one highlighted) as a band image on the 1080-wide frame."""

    def __init__(self, W: int, H: int, st: dict, band: bool = True):
        self.W, self.H, self.st = W, H, st
        self.size = int(W * st["size"])
        self.ypos = int(H * st["ypos"])
        self.fname, self.var = FONTS[st["font"]]
        self.active, self.base = _rgba(st["active"]), _rgba(st["color"])
        self.f0 = self.font(self.size)
        self.y0, self.bh = 0, H
        if band:
            sp = max(2, round(self.size / 11 * float(st["stroke"])))
            self.y0 = max(0, (self.ypos - sp - 4) // 2 * 2)
            self.bh = min(H - self.y0, int(self.size * 1.7) + 2 * sp + 8) // 2 * 2

    def font(self, px):
        ft = ImageFont.truetype(str(FONT_DIR / self.fname), px)
        if self.var:
            try:
                ft.set_variation_by_name(self.var)
            except Exception:  # noqa: BLE001
                pass
        return ft

    def draw(self, ch, ai) -> Image.Image:
        st, W = self.st, self.W
        img = Image.new("RGBA", (W, self.bh), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        texts = [mask_word(w["word"]) if st["mask"] else w["word"] for w in ch]
        texts = [tr_upper(t) if st["upper"] else t for t in texts]
        f = self.f0
        sp = d.textlength(" ", font=f)
        total = sum(d.textlength(x, font=f) for x in texts) + sp * (len(texts) - 1)
        if total > W * 0.92:                       # long words: shrink this caption to fit the frame
            f = self.font(max(14, int(self.size * W * 0.92 / total)))
            sp = d.textlength(" ", font=f)
            total = sum(d.textlength(x, font=f) for x in texts) + sp * (len(texts) - 1)
        stroke = max(2, round(f.size / 11 * float(st["stroke"]))) if st["stroke"] > 0 else 0
        x = (W - total) / 2
        for i, tx in enumerate(texts):
            d.text((x, self.ypos - self.y0), tx, font=f, fill=self.active if i == ai else self.base,
                   stroke_width=stroke, stroke_fill=(0, 0, 0, 255))
            x += d.textlength(tx, font=f) + sp
        return img


def prepare(td: Path, words, style: dict, total: float, W: int = OW, H: int = OH):
    """Caption overlay for a W x H video of `total` seconds: writes the band PNG states and an ffmpeg concat list into
    `td`. `words` are already relative to the video start. Returns (list_path, y0): overlay at y = y0, or None."""
    st = clean_style(style)
    states = build_states(words, st["chunk"], st["sync"])
    if not states:
        return None
    drawer = Drawer(W, H, st)
    td = Path(td)
    Image.new("RGBA", (W, drawer.bh), (0, 0, 0, 0)).save(td / "blank.png")
    entries, t = [], 0.0

    def add(p, dur):
        entries.append(f"file '{p}'\nduration {dur:.3f}")

    for n, (s, e, ai, ch) in enumerate(states):
        if s >= total:
            break
        if s > t + 0.01:
            add(td / "blank.png", s - t)
        p = td / f"s{n:05d}.png"
        drawer.draw(ch, ai).save(p)
        add(p, e - s)
        t = e
    if total > t + 0.01:        # overlay=shortest=1 would otherwise cut the video at the last caption
        add(td / "blank.png", total - t)
    if not entries:
        return None
    (td / "list.txt").write_text("\n".join(entries + [entries[-1].split("\n")[0]]) + "\n")
    return td / "list.txt", drawer.y0


def sample(style: dict | None, text: str = "ÖRNEK ALTYAZI METNİ") -> Image.Image:
    """The style on a dark frame: used by tests and for eyeballing the font rendering."""
    st = clean_style(style)
    words = [{"word": t, "start": 0, "end": 1} for t in text.split()][:st["chunk"]]
    base = Image.new("RGBA", (OW, OH), (38, 42, 56, 255))
    dr = Drawer(OW, OH, st, band=False)
    return Image.alpha_composite(base, dr.draw(words, min(1, len(words) - 1))).convert("RGB")
