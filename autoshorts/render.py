"""Stage 3: raw footage -> finished vertical clip. Exact trim, 9:16 with a blurred background, 30 fps, one-pass
loudness normalisation (-16 LUFS), faststart. Platforms re-encode anyway, so one good H.264/AAC file is enough."""
from pathlib import Path

from .proc import run_ok

W, H = 1080, 1920
GRAPH = ("[0:v]fps=30,split[a][b];[a]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},boxblur=40:5[bg];"
         "[b]scale={W}:-2[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2[v]")


def vertical(raw: Path, offset: float, length: float, out: Path) -> Path:
    """Cut `length` seconds starting `offset` seconds into `raw`, reframe to 9:16."""
    out.parent.mkdir(parents=True, exist_ok=True)
    run_ok(["ffmpeg", "-y", "-v", "error", "-ss", f"{offset:.3f}", "-t", f"{length:.3f}", "-i", str(raw),
            "-filter_complex", GRAPH.format(W=W, H=H), "-map", "[v]", "-map", "0:a?",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-pix_fmt", "yuv420p",
            "-af", "loudnorm=I=-16:TP=-1.5:LRA=11", "-ar", "48000", "-c:a", "aac", "-b:a", "128k",
            "-movflags", "+faststart", str(out)], "render", timeout=1800)
    return out


def thumbnail(video: Path, out: Path, at: float = 1.0) -> Path:
    run_ok(["ffmpeg", "-y", "-v", "error", "-ss", f"{at}", "-i", str(video), "-frames:v", "1", "-q:v", "3", str(out)],
           "thumbnail", timeout=60)
    return out
