"""9:16 layouts. The stream layout (game + webcam + chat panel) varies per streamer, so instead of
guessing with face tracking, each clip gets an editable layout:
  none  - keep the original 16:9
  blur  - whole frame centred over a blurred copy (always works)
  crop  - one 9:16 window (x, y, zoom) into the frame
  stack - two windows stacked (e.g. game on top, webcam below), each 1080x960
Cell coordinates are normalised (0-1) centres; zoom >= 1."""
import subprocess
from pathlib import Path

from . import encode
from .log import run_ok

OUT_W, OUT_H = 1080, 1920
DEFAULT = {"mode": "none", "cells": []}


def default_cells(mode: str):
    if mode == "crop":
        return [{"x": 0.5, "y": 0.5, "zoom": 1.0}]
    if mode == "stack":
        return [{"x": 0.5, "y": 0.5, "zoom": 1.0}, {"x": 0.5, "y": 0.5, "zoom": 1.0}]
    return []


def crop_box(W: int, H: int, aspect: float, cell: dict):
    """Pixel crop (w, h, x, y) of an `aspect` (w/h) window centred at the cell, honouring zoom."""
    zoom = max(1.0, float(cell.get("zoom", 1.0)))
    h = H / zoom
    w = h * aspect
    if w > W:
        w = W
        h = w / aspect
    w, h = int(w) // 2 * 2, int(h) // 2 * 2
    x = min(max(cell.get("x", 0.5) * W - w / 2, 0), W - w)
    y = min(max(cell.get("y", 0.5) * H - h / 2, 0), H - h)
    return w, h, int(x), int(y)


def _cell_filter(label_in, label_out, W, H, aspect, cell, out_w, out_h):
    w, h, x, y = crop_box(W, H, aspect, cell)
    return f"[{label_in}]crop={w}:{h}:{x}:{y},scale={out_w}:{out_h}[{label_out}]"


def filter_graph(layout: dict, W: int, H: int) -> str:
    mode = layout.get("mode", "none")
    cells = layout.get("cells") or default_cells(mode)
    if mode == "blur":
        return ("[0:v]split[a][b];[a]scale=1080:1920:force_original_aspect_ratio=increase,"
                "crop=1080:1920,boxblur=40:5[bg];[b]scale=1080:-2[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2[v]")
    if mode == "crop":
        return _cell_filter("0:v", "v", W, H, OUT_W / OUT_H, cells[0], OUT_W, OUT_H)
    if mode == "stack":
        cell_h = OUT_H // 2
        return ("[0:v]split[a][b];" + _cell_filter("a", "t", W, H, OUT_W / cell_h, cells[0], OUT_W, cell_h) + ";"
                + _cell_filter("b", "u", W, H, OUT_W / cell_h, cells[1], OUT_W, cell_h) + ";[t][u]vstack[v]")
    raise ValueError(f"Bilinmeyen yerleşim: {mode}")


def timed_graph(layout: dict, W: int, H: int, out_label: str = "v") -> str:
    """filter_graph with the frame rate capped (OUT_FPS) before anything else; mode "none" is just the cap."""
    g = filter_graph(layout, W, H) if layout.get("mode", "none") != "none" else "[0:v]null[v]"
    g = g.replace("[0:v]", f"[0:v]{encode.fps_filter()}[f];[f]", 1)
    return g if out_label == "v" else g.replace("[v]", f"[{out_label}]")


def render(src: Path, layout: dict, out: Path, W: int, H: int) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    run_ok(["ffmpeg", "-y", "-v", "error", "-i", str(src), "-filter_complex",
            timed_graph(layout, W, H), "-map", "[v]", "-map", "0:a?", *encode.video_args(), "-c:a", "aac", str(out)],
           "9:16 yerleşim")
    return out


# ---------------------------------------------------------------- face finding (optional: needs opencv)
def detect_face(video: Path, samples: int = 16):
    """Streamer face box found by OpenCV's Haar cascade in evenly spaced frames: (cx, cy, face_h) normalised to the
    frame, median over the frames where a face was found. None when opencv is missing, no face turns up in at least
    3 frames, or the detections jump around (different things detected)."""
    try:
        import cv2
        import statistics
    except ImportError:
        return None
    cap = cv2.VideoCapture(str(video))
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    if n < 2:
        return None
    cascades = [cv2.CascadeClassifier(str(Path(cv2.data.haarcascades) / n))
                for n in ("haarcascade_frontalface_alt2.xml", "haarcascade_frontalface_default.xml")]
    hits = []
    for k in range(samples):
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(n * (k + 0.5) / samples))
        ok, fr = cap.read()
        if not ok:
            continue
        H, W = fr.shape[:2]
        g = cv2.equalizeHist(cv2.cvtColor(fr, cv2.COLOR_BGR2GRAY))
        faces = []
        for cas in cascades:
            faces = cas.detectMultiScale(g, scaleFactor=1.1, minNeighbors=5, minSize=(int(H * 0.06), int(H * 0.06)))
            if len(faces):
                break
        if len(faces):
            x, y, w, h = max(faces, key=lambda f: f[2] * f[3])
            hits.append((float((x + w / 2) / W), float((y + h / 2) / H), float(h / H)))
    cap.release()
    if len(hits) < 3:
        return None
    cx, cy, fh = (statistics.median(v[i] for v in hits) for i in range(3))
    hits = [v for v in hits if abs(v[0] - cx) <= 0.08 and abs(v[1] - cy) <= 0.08]    # ignore stray detections
    if len(hits) < 3:
        return None
    cx, cy, fh = (statistics.median(v[i] for v in hits) for i in range(3))
    return cx, cy, fh


def auto_layout(video: Path):
    """stack layout: game on top, the face (zoomed) below. None when no stable face is found."""
    f = detect_face(video)
    if not f:
        return None
    cx, cy, fh = f
    zoom = min(4.0, max(1.5, 1 / (3.2 * fh)))
    return {"mode": "stack", "cells": [{"x": 0.5, "y": 0.5, "zoom": 1.0}, {"x": round(cx, 3), "y": round(cy, 3), "zoom": round(zoom, 2)}]}
