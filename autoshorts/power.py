"""Power profile: how hard the heavy work (ffmpeg, Whisper) may push the machine.

eco     (default) the hardware H.264 encoder where there is one (VideoToolbox on a Mac: the media engine does the
        encoding, ~60 % fewer CPU-seconds than x264 in our measurement), ffmpeg limited to 2 threads, and every
        child process at lower priority (`nice`), so the machine stays usable while clips are made.
normal  x264 (slightly smaller files at the same quality), all cores, normal priority: finishes soonest.
Measured here (M3, 40 s of 1080p -> 9:16 with blurred background): old full-resolution blur 84 s / 103 CPU-s,
blur at 1/8 size + x264 15 s / 48 CPU-s, + VideoToolbox 7 s / 19 CPU-s."""
import functools
import os
import shutil
import subprocess
import sys

from . import proc

_mode = "eco"
THREADS = 2
NICE = 10
VT_QUALITY = 65         # h264_videotoolbox -q:v (0-100); ~ the visual quality of x264 crf 21 at ~40 % more bitrate


def apply(cfg: dict):
    """Set the profile from the settings (called when a job or the CLI starts)."""
    global _mode
    _mode = "normal" if cfg.get("power") == "normal" else "eco"
    proc.set_nice(NICE if _mode == "eco" else 0)


def mode() -> str:
    return _mode


@functools.lru_cache(maxsize=1)
def has_videotoolbox() -> bool:
    if sys.platform != "darwin" or not shutil.which("ffmpeg"):
        return False
    try:
        out = subprocess.run(["ffmpeg", "-hide_banner", "-encoders"], capture_output=True, text=True, timeout=20).stdout
    except (OSError, subprocess.SubprocessError):
        return False
    return "h264_videotoolbox" in out


def input_args() -> list:
    """Decoder threads (an input option: goes before -i)."""
    return ["-threads", str(THREADS)] if _mode == "eco" else []


def filter_args() -> list:
    return ["-filter_threads", str(THREADS), "-filter_complex_threads", str(THREADS)] if _mode == "eco" else []


def video_args() -> list:
    """Encoder options for the finished clip (yuv420p, 30 fps come from the filter graph)."""
    if _mode == "eco" and has_videotoolbox():
        return ["-c:v", "h264_videotoolbox", "-q:v", str(VT_QUALITY), "-pix_fmt", "yuv420p"]
    args = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-pix_fmt", "yuv420p"]
    return args + (["-threads", str(THREADS)] if _mode == "eco" else [])


def cpu_count() -> int:
    return os.cpu_count() or 1
