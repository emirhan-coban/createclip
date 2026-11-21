"""One place for how video is encoded and how fast (kept here so the choice can be measured and changed in one line).
OUT_FPS: platforms (TikTok/Reels/Shorts) are happy with 30 fps and the work is roughly half of 60 fps.
Encoder: libx264 `veryfast` (CPU) by default; CREATECLIP_ENCODER=videotoolbox uses the Apple hardware encoder."""
import os

from . import log as logmod

OUT_FPS = 30
GENTLE_THREADS = 4      # gentle mode (default): x264 uses 4 of the 8 cores so the computer stays responsive
ENCODER = os.environ.get("CREATECLIP_ENCODER", "x264")
VT_QUALITY = os.environ.get("CREATECLIP_VT_Q", "65")


def video_args(crf: int = 21, preset: str = "veryfast") -> list:
    """ffmpeg video-encoder arguments for a final or intermediate encode."""
    if ENCODER == "videotoolbox":
        return ["-c:v", "h264_videotoolbox", "-q:v", VT_QUALITY, "-pix_fmt", "yuv420p"]
    return ["-c:v", "libx264", "-preset", preset, "-crf", str(crf), "-pix_fmt", "yuv420p"] + (
        ["-threads", str(GENTLE_THREADS)] if logmod.GENTLE else [])


def fps_filter() -> str:
    return f"fps={OUT_FPS}"
