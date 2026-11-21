"""Single-pass final render: cut-clip -> 9:16 layout + word-by-word captions in ONE ffmpeg encode.
(The old chain encoded the same minute three times: trim, layout, captions.)"""
import tempfile
from pathlib import Path

from . import captions, encode, layout as layoutmod
from .log import run_ok


def graph(lay: dict, W: int, H: int, y0: int | None) -> str:
    """Filter graph: layout (fps-capped) and, when `y0` is given, the caption overlay (input 1) at y0."""
    if y0 is None:
        return layoutmod.timed_graph(lay, W, H)
    g = layoutmod.timed_graph(lay, W, H, out_label="lay")
    return f"{g};[1:v]{encode.fps_filter()},format=rgba[o];[lay][o]overlay=0:{y0}:shortest=1:format=auto[v]"


def final(src: Path, out: Path, lay: dict, words, style: dict | None) -> Path:
    W, H = captions.probe_size(src)
    out_w, out_h = (layoutmod.OUT_W, layoutmod.OUT_H) if lay.get("mode", "none") != "none" else (W, H)
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as td:
        lst, y0 = captions.prepare(Path(td), out_w, out_h, words, style, captions.probe_duration(src))
        run_ok(["ffmpeg", "-y", "-v", "error", "-i", str(src), "-f", "concat", "-safe", "0", "-i", str(lst),
                "-filter_complex", graph(lay, W, H, y0), "-map", "[v]", "-map", "0:a?",
                *encode.video_args(), "-c:a", "aac", str(out)], "dikey + altyazı")
    return out
