"""9:16 layouts. The stream layout (game + webcam + chat panel) varies per streamer, so instead of
guessing with face tracking, each clip gets an editable layout:
  none  - keep the original 16:9
  blur  - whole frame centred over a blurred copy (always works)
  crop  - one 9:16 window (x, y, zoom) into the frame
  stack - two windows stacked (e.g. game on top, webcam below), each 1080x960
Cell coordinates are normalised (0-1) centres; zoom >= 1."""
import subprocess
from pathlib import Path

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


def render(src: Path, layout: dict, out: Path, W: int, H: int) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(src), "-filter_complex",
                    filter_graph(layout, W, H), "-map", "[v]", "-map", "0:a?", "-c:v", "libx264", "-crf", "20",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", str(out)], check=True)
    return out
