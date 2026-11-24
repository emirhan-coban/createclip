"""Stage 3: raw footage -> finished vertical clip. Exact trim, 9:16 on a black background, 30 fps, one-pass
loudness normalisation (-16 LUFS), faststart. Platforms re-encode anyway, so one good H.264/AAC file is enough."""
from pathlib import Path

from . import power
from .proc import run_ok

W, H = 1080, 1920
# Black bars above and below: the footage is scaled to the full width and centred on a black 9:16 canvas.
GRAPH = "[0:v]fps=30,scale={W}:-2,pad={W}:{H}:0:(oh-ih)/2:black[v]"


def graph(W: int = W, H: int = H) -> str:
    return GRAPH.format(W=W, H=H)


def vertical(raw: Path, offset: float, length: float, out: Path) -> Path:
    """Cut `length` seconds starting `offset` seconds into `raw`, reframe to 9:16."""
    out.parent.mkdir(parents=True, exist_ok=True)
    run_ok(["ffmpeg", "-y", "-v", "error", *power.input_args(), "-ss", f"{offset:.3f}", "-t", f"{length:.3f}", "-i", str(raw),
            *power.filter_args(), "-filter_complex", graph(), "-map", "[v]", "-map", "0:a?",
            *power.video_args(),
            "-af", "loudnorm=I=-16:TP=-1.5:LRA=11", "-ar", "48000", "-c:a", "aac", "-b:a", "128k",
            "-movflags", "+faststart", str(out)], "render", timeout=1800)
    return out


def thumbnail(video: Path, out: Path, at: float = 1.0) -> Path:
    run_ok(["ffmpeg", "-y", "-v", "error", "-ss", f"{at}", "-i", str(video), "-frames:v", "1", "-q:v", "3", str(out)],
           "thumbnail", timeout=60)
    return out
