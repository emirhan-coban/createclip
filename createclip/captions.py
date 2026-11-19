"""Burn word-by-word captions with Pillow + ffmpeg overlay (works without libass)."""
import re
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .log import run_ok

FONT_DIR = Path(__file__).parent / "fonts"
FONTS = {
    "montserrat": ("Montserrat.ttf", "ExtraBold"),
    "poppins": ("Poppins-Bold.ttf", None),
    "gabarito": ("Gabarito.ttf", "ExtraBold"),
}
SWEAR_STEMS = ("sik", "amk", "amına", "amina", "orospu", "piç", "yarrak", "göt", "got", "ibne", "mına")
DEFAULT_STYLE = {"font": "montserrat", "size": None, "ypos": None, "chunk": 3,
                 "active": "#FFDD00", "color": "#FFFFFF", "mask": False, "sync": -0.08,
                 "stroke": 1.0, "upper": True}


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


def probe_size(video: Path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
         "-of", "csv=p=0", str(video)], capture_output=True, text=True, check=True).stdout.strip()
    w, h = out.split(",")
    return int(w), int(h)


def probe_duration(video: Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=duration",
                          "-of", "csv=p=0", str(video)], capture_output=True, text=True, check=True).stdout.strip()
    try:
        return float(out)
    except ValueError:
        return float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                                     str(video)], capture_output=True, text=True, check=True).stdout.strip())


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

    Overlapping states used to shift every later caption: the concat timeline is the sum of durations,
    so an entry that starts before the previous one ended was placed late and the error accumulated.
    `sync` (seconds, positive = later) moves every caption in time."""
    raw = []
    for ch in _chunks([w for w in words if "start" in w], chunk):
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


class _Drawer:
    """Draws one caption state (a chunk of words with one highlighted) on a transparent W x H image."""

    def __init__(self, W, H, st):
        if st["font"] not in FONTS:
            raise ValueError(f"Bilinmeyen font: {st['font']}")
        self.W, self.H, self.st = W, H, st
        portrait = H > W
        self.size = int(W * (st["size"] or (0.075 if portrait else 0.052)))
        self.ypos = int(H * (st["ypos"] if st["ypos"] is not None else (0.62 if portrait else 0.72)))
        self.fname, self.var = FONTS[st["font"]]
        self.active, self.base = _rgba(st["active"]), _rgba(st["color"])
        self.f0 = self.font(self.size)

    def font(self, px):
        ft = ImageFont.truetype(str(FONT_DIR / self.fname), px)
        if self.var:
            try:
                ft.set_variation_by_name(self.var)
            except Exception:  # noqa: BLE001
                pass
        return ft

    def draw(self, ch, ai):
        st, W = self.st, self.W
        img = Image.new("RGBA", (W, self.H), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        texts = [mask_word(w["word"]) if st["mask"] else w["word"] for w in ch]
        texts = [tr_upper(t) if st.get("upper", True) else t for t in texts]
        f = self.f0
        sp = d.textlength(" ", font=f)
        total = sum(d.textlength(x, font=f) for x in texts) + sp * (len(texts) - 1)
        if total > W * 0.92:                       # long words: shrink this caption to fit the frame
            f = self.font(max(14, int(self.size * W * 0.92 / total)))
            sp = d.textlength(" ", font=f)
            total = sum(d.textlength(x, font=f) for x in texts) + sp * (len(texts) - 1)
        stroke = max(2, round(f.size / 11 * float(st.get("stroke", 1.0))))
        x = (W - total) / 2
        for i, tx in enumerate(texts):
            d.text((x, self.ypos), tx, font=f, fill=self.active if i == ai else self.base,
                   stroke_width=stroke, stroke_fill=(0, 0, 0, 255))
            x += d.textlength(tx, font=f) + sp
        return img


def preview(style: dict | None, W: int, H: int, text: str, frame: Image.Image | None = None) -> Image.Image:
    """Sample caption over a frame (or a dark gradient) - what the style looks like before producing anything."""
    st = {**DEFAULT_STYLE, **(style or {})}
    words = [{"word": t, "start": 0, "end": 1} for t in text.split()] or [{"word": "ÖRNEK", "start": 0, "end": 1}]
    ch = words[:max(1, int(st["chunk"]))]
    base = (frame.convert("RGBA").resize((W, H)) if frame else
            Image.new("RGBA", (W, H), (38, 42, 56, 255)))
    return Image.alpha_composite(base, _Drawer(W, H, st).draw(ch, min(1, len(ch) - 1))).convert("RGB")


def render(video: Path, words, out: Path, style: dict | None = None):
    st = {**DEFAULT_STYLE, **(style or {})}
    W, H = probe_size(video)
    drawer = _Drawer(W, H, st)
    states = build_states(words, int(st["chunk"]), float(st.get("sync") or 0.0))
    if not states:
        raise RuntimeError("Altyazı için kelime bulunamadı.")

    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        Image.new("RGBA", (W, H), (0, 0, 0, 0)).save(td / "blank.png")
        entries, t = [], 0.0

        def add(p, dur):
            entries.append(f"file '{p}'\nduration {dur:.3f}")

        for n, (s, e, ai, ch) in enumerate(states):
            if s > t + 0.01:
                add(td / "blank.png", s - t)
            p = td / f"s{n:05d}.png"
            drawer.draw(ch, ai).save(p)
            add(p, e - s)
            t = e
        total = probe_duration(video)
        if total > t + 0.01:        # overlay=shortest=1 would otherwise cut the video at the last caption
            add(td / "blank.png", total - t)
        (td / "list.txt").write_text("\n".join(entries + [entries[-1].split("\n")[0]]) + "\n")
        out.parent.mkdir(parents=True, exist_ok=True)
        run_ok(["ffmpeg", "-y", "-v", "error", "-i", str(video), "-f", "concat", "-safe", "0",
                "-i", str(td / "list.txt"), "-filter_complex",
                "[1:v]fps=30,format=rgba[o];[0:v][o]overlay=shortest=1:format=auto",
                "-c:v", "libx264", "-crf", "20", "-pix_fmt", "yuv420p", "-c:a", "aac", str(out)], "altyazı basma")
    return out
