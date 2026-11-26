"""Clip editor backend: source footage, timeline assets (filmstrip, waveform), the edit model and its ffmpeg render.

The edit is one JSON `project` (see default_project). The browser previews it with CSS using the same geometry as
`cell_rect`/`build_graph` below, so what you see is what ffmpeg exports. Times in a project are seconds in the SOURCE file;
the clip's position in the original stream is src_start + time."""
import json
import re
import shutil
import subprocess
import tempfile
from array import array
from pathlib import Path

from . import config, download, export, faces, power, render, store, texts
from .proc import Cancelled, log, run, run_ok

OW, OH = 1080, 1920
SPLIT_MIN, SPLIT_MAX = 0.25, 0.75


def stack_heights(split: float) -> tuple[int, int]:
    """Pixel heights of the top and bottom window of the two-window layout (even numbers; mirrored in layout.ts)."""
    top = int(OH * min(SPLIT_MAX, max(SPLIT_MIN, split))) // 2 * 2
    return top, OH - top


def editor_dir(clip_id: int) -> Path:
    d = config.data_dir() / "clips" / "editor" / str(clip_id)
    d.mkdir(parents=True, exist_ok=True)
    return d


# ---------------------------------------------------------------- the model
def default_project(clip: dict) -> dict:
    """The edit that reproduces the clip as it was first rendered (black bars, original cut)."""
    s0 = float(clip["src_start"] or 0)
    return {"version": 1,
            "trim": {"in": round(float(clip["start"]) - s0, 2), "out": round(float(clip["end"]) - s0, 2)},
            "layout": {"mode": "blur", "split": 0.5, "cells": [{"cx": 0.5, "cy": 0.5, "zoom": 1.0}, {"cx": 0.85, "cy": 0.8, "zoom": 3.0}]},
            "audio": {"volume": 1.0, "normalize": True},
            "texts": []}


def clean_project(p: dict, duration: float) -> dict:
    """Validate and clamp a project coming from the browser."""
    t = p.get("trim") or {}
    a = max(0.0, min(float(t.get("in", 0)), duration))
    b = max(0.0, min(float(t.get("out", duration)), duration))
    if b - a < 1.0:
        raise ValueError("Klip en az 1 saniye olmalı.")
    lay = p.get("layout") or {}
    mode = lay.get("mode", "blur")
    if mode not in ("blur", "crop", "stack"):
        raise ValueError("Bilinmeyen yerleşim.")
    cells = []
    for c in (lay.get("cells") or [{}, {}])[:2]:
        cells.append({"cx": min(1.0, max(0.0, float(c.get("cx", 0.5)))), "cy": min(1.0, max(0.0, float(c.get("cy", 0.5)))),
                      "zoom": min(8.0, max(1.0, float(c.get("zoom", 1.0))))})
    while len(cells) < 2:
        cells.append({"cx": 0.5, "cy": 0.5, "zoom": 1.0})
    au = p.get("audio") or {}
    split = round(min(SPLIT_MAX, max(SPLIT_MIN, float(lay.get("split", 0.5)))), 2)
    return {"version": 1, "trim": {"in": round(a, 2), "out": round(b, 2)}, "layout": {"mode": mode, "split": split, "cells": cells},
            "audio": {"volume": min(3.0, max(0.0, float(au.get("volume", 1.0)))), "normalize": bool(au.get("normalize", True))},
            "texts": texts.clean_layers(p.get("texts"))}


def cell_rect(W: float, H: float, cell: dict, aw: int, ah: int) -> tuple[float, float, float, float]:
    """The window (x, y, w, h) of the source frame that fills one cell of aspect aw:ah. Mirrored in web/src/lib/layout.ts."""
    zoom = max(1.0, float(cell.get("zoom", 1.0)))
    wh = H / zoom
    ww = wh * aw / ah
    if ww > W:
        ww, wh = W, W * ah / aw
    x0 = min(max(cell.get("cx", 0.5) * W - ww / 2, 0), W - ww)
    y0 = min(max(cell.get("cy", 0.5) * H - wh / 2, 0), H - wh)
    return x0, y0, ww, wh


def _even(v: float) -> int:
    return max(2, int(v) // 2 * 2)


def _crop(W, H, cell, aw, ah) -> str:
    x0, y0, ww, wh = cell_rect(W, H, cell, aw, ah)
    return f"crop={_even(ww)}:{_even(wh)}:{int(x0)}:{int(y0)}"


def build_graph(project: dict, W: int, H: int, out: str = "v") -> str:
    """ffmpeg filter_complex producing [out] (1080x1920, 30 fps) from input 0."""
    lay = project["layout"]
    mode, cells = lay["mode"], lay["cells"]
    if mode == "crop":
        return f"[0:v]fps=30,{_crop(W, H, cells[0], 9, 16)},scale={OW}:{OH}[{out}]"
    if mode == "stack":
        th, bh = stack_heights(lay.get("split", 0.5))
        return (f"[0:v]fps=30,split[a][b];[a]{_crop(W, H, cells[0], OW, th)},scale={OW}:{th}[t];"
                f"[b]{_crop(W, H, cells[1], OW, bh)},scale={OW}:{bh}[u];[t][u]vstack[{out}]")
    g = render.graph(OW, OH)
    return g[: g.rindex("[v]")] + f"[{out}]"


# ---------------------------------------------------------------- probing and timeline assets
def probe(path: Path) -> dict:
    p = run_ok(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,width,height:format=duration,start_time", "-of", "json", str(path)],
               "probe", timeout=60)
    d = json.loads(p.stdout)
    v = next((s for s in d["streams"] if s["codec_type"] == "video"), None)
    if not v:
        raise RuntimeError("Kaynak dosyada görüntü yok.")
    return {"width": int(v["width"]), "height": int(v["height"]), "duration": float(d["format"]["duration"]),
            "audio": any(s["codec_type"] == "audio" for s in d["streams"]), "start_time": float(d["format"].get("start_time") or 0)}


def normalize_source(path: Path, start_time: float) -> None:
    """Shift the file's timestamps so it starts at 0 (stream copy, no re-encode). A stream-copied section keeps the original
    stream's timestamps (e.g. starts at 1.17 s); browsers play from that offset while ffmpeg's -ss counts from the first frame,
    which would put the preview and the export about a second apart."""
    tmp = path.with_suffix(".norm.mp4")
    run_ok(["ffmpeg", "-y", "-v", "error", "-i", str(path), "-map", "0", "-c", "copy", "-output_ts_offset", f"{-start_time:.4f}",
            "-avoid_negative_ts", "make_zero", "-movflags", "+faststart", str(tmp)], "normalize source", timeout=600)
    tmp.replace(path)


def filmstrip(clip_id: int, src: Path, duration: float) -> dict:
    """One sprite image of evenly spaced thumbnails (cached)."""
    d = editor_dir(clip_id)
    n = int(min(30, max(8, round(duration / 6))))
    step = duration / n
    out, meta = d / "strip.jpg", d / "strip.json"
    if out.exists() and meta.exists():
        return json.loads(meta.read_text())
    run_ok(["ffmpeg", "-y", "-v", "error", "-i", str(src), "-vf", f"fps=1/{step:.4f},scale=-2:96,tile={n}x1", "-frames:v", "1",
            "-q:v", "5", str(out)], "filmstrip", timeout=300)
    info = {"n": n, "step": step, "thumb_h": 96}
    meta.write_text(json.dumps(info))
    return info


def waveform(clip_id: int, src: Path, points: int = 600) -> list[float]:
    """Peak amplitude (0..1) per slice of the audio track (cached)."""
    f = editor_dir(clip_id) / "wave.json"
    if f.exists():
        return json.loads(f.read_text())
    p = subprocess.run(["ffmpeg", "-v", "error", "-i", str(src), "-vn", "-ac", "1", "-ar", "4000", "-f", "s16le", "-"],
                       capture_output=True, timeout=300)
    pcm = array("h")
    pcm.frombytes(p.stdout[: len(p.stdout) // 2 * 2])
    if not pcm:
        vals = [0.0] * points
    else:
        per = max(1, len(pcm) // points)
        vals = [min(1.0, (max(abs(x) for x in pcm[i * per:(i + 1) * per]) / 32768) ** 0.6) if pcm[i * per:(i + 1) * per] else 0.0
                for i in range(points)]
    f.write_text(json.dumps([round(v, 3) for v in vals]))
    return json.loads(f.read_text())


# ---------------------------------------------------------------- source footage
def source_path(clip: dict) -> Path | None:
    f = clip.get("src_file")
    return Path(f) if f and Path(f).exists() else None


def ensure_source(con, cfg: dict, clip_id: int, progress=lambda f, t="": None) -> Path:
    """Download the footage around a clip when we do not have it (clips made before the editor existed)."""
    clip = store.get_clip(con, clip_id)
    have = source_path(clip)
    if have:
        return have
    progress(0.02, "Yayın bilgisi alınıyor")
    video = download.info(clip["video_url"])
    pad = float(cfg.get("source_pad", 30))
    start = max(0.0, clip["start"] - pad)
    end = min(video.duration, clip["end"] + pad) if video.duration else clip["end"] + pad
    out = config.data_dir() / "clips" / "source" / f"{clip_id}.mp4"
    progress(0.1, "Kaynak görüntü indiriliyor")
    download.fetch_range(clip["video_url"], start, end, out, cfg["max_height"])
    store.set_source(con, clip_id, str(out), start, end)
    _forget_edit(con, clip_id)          # the new file starts at a different offset: an old project's times would no longer fit
    return out


def _forget_edit(con, clip_id: int):
    store.delete_project(con, clip_id)
    d = editor_dir(clip_id)
    for name in ("strip.jpg", "strip.json", "wave.json", "probe.json", "words.json", "face.json", "export.mp4", "export.jpg"):
        (d / name).unlink(missing_ok=True)


def storage_usage(con) -> dict:
    """Disk used by the kept source footage."""
    files = [Path(c["src_file"]) for c in store.clips(con) if c.get("src_file") and Path(c["src_file"]).exists()]
    return {"files": len(files), "bytes": sum(f.stat().st_size for f in files)}


def clean_sources(con) -> dict:
    """Delete every source file (finished clips are untouched). The editor fetches the footage again when needed."""
    freed = n = 0
    for c in store.clips(con):
        f = Path(c["src_file"]) if c.get("src_file") else None
        if f and f.exists():
            freed += f.stat().st_size
            n += 1
            f.unlink()
        if c.get("src_file"):
            store.set_source(con, c["id"], None, None, None)
            _forget_edit(con, c["id"])
    return {"files": n, "bytes": freed}


def clean_old_sources(con, days: float) -> dict:
    """Delete source footage older than `days` days, but only of clips without a saved edit (an edit would be lost)."""
    import time
    freed = n = 0
    if days <= 0:
        return {"files": 0, "bytes": 0}
    for c in store.clips(con):
        f = Path(c["src_file"]) if c.get("src_file") else None
        if not f or not f.exists() or time.time() - f.stat().st_mtime < days * 86400 or store.get_project(con, c["id"]):
            continue
        freed += f.stat().st_size
        n += 1
        f.unlink()
        store.set_source(con, c["id"], None, None, None)
        _forget_edit(con, c["id"])
    return {"files": n, "bytes": freed}


# ---------------------------------------------------------------- face layout
def find_face(con, cfg: dict, clip_id: int, progress=lambda f, t="": None) -> dict | None:
    """Look for the streamer's camera in the clip's source footage; the result is cached in face.json."""
    clip = store.get_clip(con, clip_id)
    src = source_path(clip)
    if not src:
        raise RuntimeError("Kaynak görüntü yok; önce indirilmeli.")
    info = source_info(clip)
    progress(0.1, "Kamera aranıyor")
    face = faces.detect(src, info["duration"])
    faces.save(editor_dir(clip_id) / "face.json", face)
    return face


def face_layout(face: dict, W: int, H: int, split: float, top: str = "face") -> dict:
    """Two-window layout: the camera window on top (share `split` of the height) and the whole game view below."""
    th, bh = stack_heights(split)
    cam = faces.face_cell(face, W, H, OW, th)
    game = {"cx": 0.5, "cy": 0.5, "zoom": 1.0}
    return {"mode": "stack", "split": round(th / OH, 2), "cells": [cam, game] if top == "face" else [game, cam]}


# ---------------------------------------------------------------- export
def render_project(src: Path, project: dict, out: Path, info: dict, progress=lambda f, t="": None) -> Path:
    t_in, t_out = project["trim"]["in"], project["trim"]["out"]
    length = t_out - t_in
    af = []
    vol = project["audio"]["volume"]
    if abs(vol - 1.0) > 0.01:
        af.append(f"volume={vol:.3f}")
    if project["audio"]["normalize"]:
        af.append("loudnorm=I=-16:TP=-1.5:LRA=11")

    def on_line(line: str):
        m = re.match(r"out_time_(?:us|ms)=(\d+)", line)
        if m:
            progress(min(0.99, int(m.group(1)) / 1e6 / length), "Videoya işleniyor")
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as td:
        layers = texts.render_layers(Path(td), project.get("texts"), length)
        cmd = ["ffmpeg", "-y", "-v", "error", "-nostats", "-progress", "pipe:1", *power.input_args(), "-ss", f"{t_in:.3f}", "-t", f"{length:.3f}", "-i", str(src)]
        # text layers are chained on the laid-out video, the last overlay's output is [v]
        n_over = len(layers)
        label = lambda k: "v" if k == n_over else f"l{k}"           # noqa: E731
        graph = build_graph(project, info["width"], info["height"], label(0))
        step, idx = 0, 1
        for png, x, y, a, b in layers:
            cmd += ["-loop", "1", "-t", f"{length:.3f}", "-i", str(png)]
            graph += f";[{label(step)}][{idx}:v]overlay={x}:{y}:enable='between(t,{a:.3f},{b:.3f})':shortest=1:format=auto[{label(step + 1)}]"
            step, idx = step + 1, idx + 1
        cmd += [*power.filter_args(), "-filter_complex", graph, "-map", "[v]"]
        if info["audio"]:
            cmd += ["-map", "0:a?"] + (["-af", ",".join(af)] if af else []) + ["-ar", "48000", "-c:a", "aac", "-b:a", "128k"]
        cmd += ["-t", f"{length:.3f}", *power.video_args(), "-movflags", "+faststart", str(out)]
        p = run(cmd, "editor render", timeout=3600, on_line=on_line)
    if p.returncode:
        raise RuntimeError("Dışa aktarma başarısız: " + p.stdout.strip()[-300:])
    return out


def export_clip(con, cfg: dict, clip_id: int, project: dict, progress=lambda f, t="": None) -> Path:
    """Render the edit, save it next to the other finished clips, point the clip at it."""
    clip = store.get_clip(con, clip_id)
    src = source_path(clip)
    if not src:
        raise RuntimeError("Kaynak görüntü yok; önce indirilmeli.")
    info = probe(src)
    project = clean_project(project, info["duration"])
    store.save_project(con, clip_id, project)
    tmp = editor_dir(clip_id) / "export.mp4"
    render_project(src, project, tmp, info, lambda f, t="": progress(0.05 + f * 0.9, t))
    progress(0.96, "Kaydediliyor")
    thumb = editor_dir(clip_id) / "export.jpg"
    render.thumbnail(tmp, thumb)
    abs_start = clip["src_start"] + project["trim"]["in"]
    abs_end = clip["src_start"] + project["trim"]["out"]
    base = Path(clip["file"]) if clip["file"] else None
    saved = export.save(cfg, clip_id, (base.stem.split("_")[0] if base else "clip"), abs_start, tmp, thumb,
                        clip["title"] or "", clip["description"] or "")
    store.update_clip(con, clip_id, file=str(saved), start=round(abs_start, 2), end=round(abs_end, 2), status="done", error=None)
    if base and base.exists() and base.resolve() != saved.resolve():
        _archive(base)                  # the edited clip replaces it; keep the earlier version, tidied away
    tmp.unlink(missing_ok=True)
    thumb.unlink(missing_ok=True)
    return saved


def _archive(old: Path):
    """Move a superseded clip (video, cover, text) into an `_eski` folder next to it."""
    dest = old.parent / "_eski"
    dest.mkdir(exist_ok=True)
    for ext in (".mp4", ".jpg", ".txt"):
        f = old.with_suffix(ext)
        if f.exists():
            shutil.move(str(f), str(dest / f.name))


def source_info(clip: dict) -> dict | None:
    """Probe of the clip's source footage (cached), or None when we do not have it."""
    src = source_path(clip)
    if not src:
        return None
    f = editor_dir(clip["id"]) / "probe.json"
    if f.exists():
        info = json.loads(f.read_text())
        if "start_time" in info and info["start_time"] <= 0.1:       # caches from before normalization lack the key: re-check
            return info
    info = probe(src)
    if info["start_time"] > 0.1:                 # first look at a freshly downloaded section
        normalize_source(src, info["start_time"])
        info = probe(src)
    f.write_text(json.dumps(info))
    return info
