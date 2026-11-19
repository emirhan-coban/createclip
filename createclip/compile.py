"""Compilation: "Günün en iyi N anı" - intro card, a countdown card before each clip, the clips, and a credits text
(source stream + timestamp of every clip). Everything is normalised to one size/fps so the parts concatenate."""
import time
from pathlib import Path

from PIL import Image, ImageDraw

from . import captions, dupes, review
from .log import run_ok
from .overlay import _font

CARD_S = 1.6


def card(W: int, H: int, lines: list, big: int = 0) -> Image.Image:
    img = Image.new("RGB", (W, H), (18, 18, 24))
    d = ImageDraw.Draw(img)
    fs = max(28, int(W * (0.07 if H > W else 0.045)))
    y = H / 2 - len(lines) * fs * 0.7
    for k, (txt, accent) in enumerate(lines):
        f = _font(int(fs * (1.6 if k == 0 and big else 1)), "ExtraBold")
        words, cur, wrapped = txt.split(), "", []
        for w in words:
            t = (cur + " " + w).strip()
            if d.textlength(t, font=f) > W * 0.86 and cur:
                wrapped.append(cur)
                cur = w
            else:
                cur = t
        for l in wrapped + [cur]:
            d.text((W / 2, y), l, font=f, fill=(255, 221, 0) if accent else (240, 240, 240), anchor="ma")
            y += fs * 1.3
        y += fs * 0.3
    return img


def _card_video(td: Path, name: str, lines, W, H, big=0) -> Path:
    png, out = td / f"{name}.png", td / f"{name}.mp4"
    card(W, H, lines, big).save(png)
    run_ok(["ffmpeg", "-y", "-v", "error", "-loop", "1", "-t", str(CARD_S), "-i", str(png), "-f", "lavfi", "-t", str(CARD_S),
            "-i", "anullsrc=r=48000:cl=stereo", "-r", "30", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
            "-shortest", str(out)], "kart")
    return out


def _norm(src: Path, out: Path, W: int, H: int) -> Path:
    run_ok(["ffmpeg", "-y", "-v", "error", "-i", str(src), "-vf",
            f"scale={W}:{H}:force_original_aspect_ratio=decrease,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2,fps=30,format=yuv420p",
            "-af", "aresample=48000,aformat=channel_layouts=stereo", "-c:v", "libx264", "-crf", "20", "-preset", "veryfast",
            "-c:a", "aac", "-ar", "48000", str(out)], "parça düzenleme", timeout=600)
    return out


def pick_rows(root: Path, n: int = 5, status: str = "approved") -> list:
    rows = review.inbox(root, status)
    for r in rows:
        r["text"] = review.clip_text_of(root, r)
    dupes.mark(rows)
    rows = [r for r in rows if not r["dup_of"]]
    rows.sort(key=lambda r: -r["score"])
    return rows[:n]


def build(root: Path, n: int = 5, status: str = "approved", title: str | None = None) -> dict:
    import tempfile
    root = Path(root)
    rows = pick_rows(root, n, status)
    if len(rows) < 2:
        raise ValueError(f"Derleme için en az 2 klip gerekli ('{status}' durumunda {len(rows)} var).")
    paths = [root / "output" / r["video"].removeprefix("/files/") for r in rows]
    W, H = captions.probe_size(paths[0])
    W, H = (1080, 1920) if H > W else (1920, 1080)
    title = title or f"Günün en iyi {len(rows)} anı"
    out_dir = root / "ready" / "derleme"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y-%m-%d_%H%M")
    out = out_dir / f"{stamp}_en-iyi-{len(rows)}.mp4"
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        parts = [_card_video(td, "intro", [(title, True), (time.strftime("%d.%m.%Y"), False)], W, H, big=1)]
        for k, (r, p) in enumerate(zip(rows, paths)):             # countdown: best clip last
            rank = len(rows) - k
            parts.append(_card_video(td, f"c{k}", [(f"#{rank}", True), (r["title"], False)], W, H, big=1))
            parts.append(_norm(p, td / f"p{k}.mp4", W, H))
        listing = td / "list.txt"
        listing.write_text("".join(f"file '{p}'\n" for p in parts))
        run_ok(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(listing), "-c", "copy", str(out)],
               "derleme birleştirme", timeout=600)
    credits = [title, ""]
    for k, r in enumerate(rows):
        credits.append(f"#{len(rows) - k} {r['title']} — {r['slug']} · {r['source_title']} · {review._stamp(r['start'])}")
    out.with_suffix(".txt").write_text("\n".join(credits) + "\n")
    return {"path": str(out), "clips": len(rows), "credits": str(out.with_suffix(".txt"))}
