"""Original-contribution overlays burned into a clip: live chat reactions (the messages viewers actually sent at that
moment) and a context banner (what the clip is about) in the first seconds; plus the viewer's own voice commentary
mixed over the original sound (which is ducked while the voice speaks)."""
import colorsys
import json
import re
import tempfile
import zlib
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from . import youtube
from .captions import FONT_DIR, FONTS, probe_duration
from .log import run_ok

SHOW = 4.5          # seconds a chat message stays visible
GAP = 0.9           # minimum seconds between two shown messages
LINES = 4           # at most this many visible at once
BANNER_S = 3.0


# ---------------------------------------------------------------- chat
def load_chat(jd: Path, duration: float) -> list:
    """All cached chat messages of a project as [{"t","u","c"}] (Kick crawl log or YouTube replay), sorted."""
    jd = Path(jd)
    f = jd / youtube.CHAT_FILE
    if f.exists():
        return youtube.parse_chat(f, duration)
    log = jd / "chat.log.jsonl"
    msgs, seen = [], set()
    if log.exists():
        for line in log.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                for mid, t, u, c in json.loads(line)["m"]:
                    if mid not in seen:
                        seen.add(mid)
                        msgs.append({"t": t, "u": u, "c": c})
            except (ValueError, KeyError):
                continue
    msgs.sort(key=lambda x: x["t"])
    return msgs


def clean_text(c: str) -> str:
    """Kick emotes arrive as [emote:ID:NAME]; show them as :NAME:."""
    return re.sub(r"\[emote:\d+:([^\]]+)\]", r":\1:", c).strip()


def pick(msgs: list, start: float, end: float, limit: int = 40) -> list:
    """Chat shown over [start, end]: [(t_rel, user, text)]. Skips bot commands and long messages, drops repeats
    seen within 4 s, keeps at least GAP seconds between messages."""
    out, last_t, recent = [], -99.0, {}
    for m in msgs:
        if not start <= m["t"] <= end:
            continue
        text = clean_text(m["c"])
        if not text or text.startswith("!") or len(text) > 70:
            continue
        key = text.lower()
        if m["t"] - recent.get(key, -99) < 4.0:
            continue
        recent[key] = m["t"]
        if m["t"] - last_t < GAP:
            continue
        last_t = m["t"]
        out.append((m["t"] - start, m["u"], text))
        if len(out) >= limit:
            break
    return out


def visible_states(items: list, length: float) -> list:
    """[(t0, t1, [items visible])] with at most LINES newest visible; boundaries wherever the set changes."""
    cuts = sorted({0.0, length, *[min(length, t) for t, *_ in items], *[min(length, t + SHOW) for t, *_ in items]})
    states = []
    for a, b in zip(cuts, cuts[1:]):
        if b - a < 0.03:
            continue
        vis = [it for it in items if it[0] <= a + 1e-6 and a < it[0] + SHOW][-LINES:]
        states.append((a, b, vis))
    return states


# ---------------------------------------------------------------- drawing
def _font(px: int, weight: str = "Bold"):
    name, _ = FONTS["montserrat"]
    f = ImageFont.truetype(str(FONT_DIR / name), px)
    try:
        f.set_variation_by_name(weight)
    except Exception:  # noqa: BLE001
        pass
    return f


def _user_color(u: str):
    h = (zlib.crc32(u.encode()) % 360) / 360
    r, g, b = colorsys.hls_to_rgb(h, 0.68, 0.75)
    return int(r * 255), int(g * 255), int(b * 255), 255


def draw_chat(W: int, H: int, vis: list) -> Image.Image:
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    if not vis:
        return img
    d = ImageDraw.Draw(img)
    fs = max(18, int(W * (0.034 if H > W else 0.022)))
    f = _font(fs)
    x, y, pad = int(W * 0.04), int(H * 0.08), int(fs * 0.45)
    for _, u, text in vis:
        name = u[:18] + ": "
        wn, wt = d.textlength(name, font=f), d.textlength(text, font=f)
        maxw = W * 0.92
        if wn + wt + 2 * pad > maxw:                               # shrink the text rather than overflow
            while text and wn + d.textlength(text + "…", font=f) + 2 * pad > maxw:
                text = text[:-1]
            text += "…"
            wt = d.textlength(text, font=f)
        d.rounded_rectangle([x, y, x + wn + wt + 2 * pad, y + fs + 2 * pad], radius=fs * 0.4, fill=(0, 0, 0, 150))
        d.text((x + pad, y + pad), name, font=f, fill=_user_color(u))
        d.text((x + pad + wn, y + pad), text, font=f, fill=(255, 255, 255, 255))
        y += fs + 2 * pad + int(fs * 0.25)
    return img


def draw_banner(W: int, H: int, text: str) -> Image.Image:
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    fs = max(22, int(W * (0.05 if H > W else 0.032)))
    f = _font(fs, "ExtraBold")
    words, lines, cur = text.split(), [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if d.textlength(t, font=f) > W * 0.8 and cur:
            lines.append(cur)
            cur = w
        else:
            cur = t
    lines = (lines + [cur])[:3]
    lh = int(fs * 1.25)
    bw = max(d.textlength(l, font=f) for l in lines) + fs
    bh = lh * len(lines) + fs * 0.6
    x0, y0 = (W - bw) / 2, H * 0.04
    d.rounded_rectangle([x0, y0, x0 + bw, y0 + bh], radius=fs * 0.5, fill=(255, 221, 0, 235))
    for k, l in enumerate(lines):
        d.text((W / 2, y0 + fs * 0.3 + k * lh), l, font=f, fill=(20, 20, 20, 255), anchor="ma")
    return img


# ---------------------------------------------------------------- burn
def burn(video: Path, states: list, out: Path, W: int, H: int) -> Path:
    """states: [(t0, t1, RGBA image or None)] covering 0..length; overlays them on the video."""
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        Image.new("RGBA", (W, H), (0, 0, 0, 0)).save(td / "blank.png")
        entries, t = [], 0.0
        for n, (a, b, im) in enumerate(states):
            if a > t + 0.01:
                entries.append(f"file '{td / 'blank.png'}'\nduration {a - t:.3f}")
            p = td / "blank.png"
            if im is not None:
                p = td / f"s{n:05d}.png"
                im.save(p)
            entries.append(f"file '{p}'\nduration {b - a:.3f}")
            t = b
        total = probe_duration(video)
        if total > t + 0.01:        # overlay=shortest=1 would otherwise cut the video where the overlay ends
            entries.append(f"file '{td / 'blank.png'}'\nduration {total - t:.3f}")
        entries.append(entries[-1].split("\n")[0])
        (td / "list.txt").write_text("\n".join(entries) + "\n")
        out.parent.mkdir(parents=True, exist_ok=True)
        run_ok(["ffmpeg", "-y", "-v", "error", "-i", str(video), "-f", "concat", "-safe", "0", "-i", str(td / "list.txt"),
                "-filter_complex", "[1:v]fps=30,format=rgba[o];[0:v][o]overlay=shortest=1:format=auto",
                "-c:v", "libx264", "-crf", "20", "-pix_fmt", "yuv420p", "-c:a", "copy", str(out)], "bindirme basma", timeout=900)
    return out


def apply(jd: Path, m: dict, rec: dict, video: Path, out: Path) -> Path:
    """Chat reactions and/or the banner over `video`. Raises ValueError when there is nothing to show."""
    from .captions import probe_size
    W, H = probe_size(video)
    length = rec["end"] - rec["start"]
    chat = []
    if rec.get("reactions"):
        chat = pick(load_chat(jd, m["duration"]), rec["start"], rec["end"])
    banner = (rec.get("banner") or "").strip()
    cuts = sorted({0.0, length, *([min(length, BANNER_S)] if banner else [])} |
                  {c for a, b, _ in visible_states(chat, length) for c in (a, b)})
    bimg = draw_banner(W, H, banner) if banner else None
    cache, states = {}, []
    for a, b in zip(cuts, cuts[1:]):
        if b - a < 0.03:
            continue
        vis = tuple(it for it in chat if it[0] <= a + 1e-6 and a < it[0] + SHOW)[-LINES:]
        show_b = bool(banner) and a < BANNER_S
        if not vis and not show_b:
            continue
        if vis not in cache:
            cache[vis] = draw_chat(W, H, list(vis))
        im = cache[vis]
        if show_b:
            im = Image.alpha_composite(im, bimg)
        states.append((a, b, im))
    if not states:
        raise ValueError("Gösterilecek sohbet mesajı/başlık yok.")
    return burn(video, states, out, W, H)


# ---------------------------------------------------------------- voice commentary
def mix_voice(video: Path, voice: Path, out: Path, duck: bool = True) -> Path:
    """Put the recorded voice over the clip; the original sound drops while the voice speaks (sidechain ducking)."""
    graph = ("[1:a]volume=1.4,aformat=sample_rates=48000:channel_layouts=stereo,apad,asplit[v1][v2];"
             "[0:a]aformat=sample_rates=48000:channel_layouts=stereo[g];"
             + ("[g][v1]sidechaincompress=threshold=0.02:ratio=12:attack=15:release=350[d];" if duck else "[g]anull[d];[v1]anullsink;")
             + "[d][v2]amix=inputs=2:duration=first:normalize=0[a]")
    out.parent.mkdir(parents=True, exist_ok=True)
    run_ok(["ffmpeg", "-y", "-v", "error", "-i", str(video), "-i", str(voice), "-filter_complex", graph,
            "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-shortest", str(out)], "yorum karıştırma", timeout=300)
    return out
