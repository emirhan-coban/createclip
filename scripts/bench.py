"""Encode benchmark: old chain (trim -> layout -> captions, 60 fps, medium preset) against the single-pass render.
usage: python scripts/bench.py <raw.mp4> [--seconds 60]   (needs an idle machine; synthetic captions, timing only)"""
import argparse
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from createclip import captions, clipper, encode, layout, render  # noqa: E402


def sh(cmd):
    t = time.time()
    p = subprocess.run([str(c) for c in cmd], capture_output=True, text=True, stdin=subprocess.DEVNULL)
    if p.returncode:
        raise SystemExit(p.stderr[-400:])
    return time.time() - t


def words(n, dur):
    return [{"word": f"kelime{i}", "start": i * dur / n, "end": i * dur / n + 0.3} for i in range(n)]


def info(p):
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height,avg_frame_rate",
                          "-of", "csv=p=0", str(p)], capture_output=True, text=True).stdout.strip()
    return f"{out} {Path(p).stat().st_size / 1e6:.1f}MB"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("raw")
    ap.add_argument("--seconds", type=float, default=60)
    ap.add_argument("--mode", default="stack", choices=["blur", "stack", "crop"])
    a = ap.parse_args()
    lay = {"mode": a.mode, "cells": layout.default_cells(a.mode)}
    ws = words(int(a.seconds * 2.2), a.seconds)
    rows = []
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        # ---- old chain
        t0 = time.time()
        t_trim = sh(["ffmpeg", "-y", "-v", "error", "-ss", "5", "-to", str(5 + a.seconds), "-i", a.raw, "-c:v", "libx264", "-crf", "18",
                     "-preset", "veryfast", "-pix_fmt", "yuv420p", "-af", clipper.LOUDNORM, "-ar", "48000", "-c:a", "aac", td / "old_trim.mp4"])
        W, H = captions.probe_size(td / "old_trim.mp4")
        t_lay = sh(["ffmpeg", "-y", "-v", "error", "-i", td / "old_trim.mp4", "-filter_complex", layout.filter_graph(lay, W, H), "-map", "[v]",
                    "-map", "0:a?", "-c:v", "libx264", "-crf", "20", "-pix_fmt", "yuv420p", "-c:a", "aac", td / "old_lay.mp4"])
        # old captions: full-frame PNGs, 60 fps source, default preset
        t = time.time()
        d = captions._Drawer(1080, 1920, {**captions.DEFAULT_STYLE})
        sts = captions.build_states(ws, 3)
        with tempfile.TemporaryDirectory() as tq:
            tq = Path(tq)
            from PIL import Image
            Image.new("RGBA", (1080, 1920), (0, 0, 0, 0)).save(tq / "b.png")
            ent, tt = [], 0.0
            for n, (s, e, ai, ch) in enumerate(sts):
                if s > tt + .01:
                    ent.append(f"file '{tq / 'b.png'}'\nduration {s - tt:.3f}")
                p = tq / f"s{n}.png"
                d.draw(ch, ai).save(p)
                ent.append(f"file '{p}'\nduration {e - s:.3f}")
                tt = e
            ent.append(f"file '{tq / 'b.png'}'\nduration {a.seconds - tt + 1:.3f}")
            (tq / "l.txt").write_text("\n".join(ent + [ent[-1].split("\n")[0]]) + "\n")
            sh(["ffmpeg", "-y", "-v", "error", "-i", td / "old_lay.mp4", "-f", "concat", "-safe", "0", "-i", tq / "l.txt", "-filter_complex",
                "[1:v]fps=30,format=rgba[o];[0:v][o]overlay=shortest=1:format=auto", "-c:v", "libx264", "-crf", "20", "-pix_fmt", "yuv420p",
                "-c:a", "aac", td / "old_cap.mp4"])
        t_cap = time.time() - t
        rows.append(("eski zincir (trim+yerleşim+altyazı, 60fps, medium)", time.time() - t0, info(td / "old_cap.mp4")))
        rows.append(("  - trim", t_trim, "")); rows.append(("  - yerleşim", t_lay, "")); rows.append(("  - altyazı (+PNG)", t_cap, ""))
        # ---- new chain, per encoder
        for enc in ("x264", "videotoolbox"):
            encode.ENCODER = enc
            t0 = time.time()
            clipper.trim(Path(a.raw), 5, 5 + a.seconds, td / f"n_trim_{enc}.mp4")
            t1 = time.time() - t0
            out = render.final(td / f"n_trim_{enc}.mp4", td / f"n_final_{enc}.mp4", lay, ws, None)
            rows.append((f"yeni: trim + tek geçiş ({enc}, 30fps)", time.time() - t0, info(out)))
            rows.append(("  - trim", t1, ""))
    for name, sec, extra in rows:
        print(f"{name:58} {sec:6.1f} sn  {extra}")


if __name__ == "__main__":
    main()
