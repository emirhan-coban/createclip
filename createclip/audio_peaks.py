"""Fallback when chat is unavailable: find loud moments (shouting/laughter) from the VOD's audio.
Downloads the smallest audio-only stream when the platform has one (YouTube) and otherwise the smallest video
rendition (Kick has no audio-only format: 160p is ~1.7 MB/min), once, and measures loudness."""
import re
import shutil
import subprocess
from pathlib import Path

from . import peaks, ytdlp
from .log import log, run


AUDIO_FORMAT = "wa[abr>=32]/wa/worst[height>=160]/worst"   # smallest audio-only; else smallest video


def download_low(url: str, out: Path) -> Path:
    """Returns the downloaded media file (extension depends on the stream: m4a, webm, mp4)."""
    out.parent.mkdir(parents=True, exist_ok=True)
    have = [f for f in out.parent.glob(out.stem + ".*") if not f.name.endswith((".part", ".ytdl"))]
    if have:
        return have[0]
    p = run(ytdlp.cmd("-q", "-f", AUDIO_FORMAT, "-o", str(out.with_suffix("")) + ".%(ext)s", url),
            "ses indirme", timeout=3 * 3600)
    have = [f for f in out.parent.glob(out.stem + ".*") if not f.name.endswith((".part", ".ytdl"))]
    if p.returncode != 0 or not have:
        raise RuntimeError("Ses analizi için video/ses indirilemedi: " + p.stderr.strip()[-200:])
    log.info("ses dosyası: %s (%.0f MB)", have[0].name, have[0].stat().st_size / 1e6)
    return have[0]


def loudness_series(media: Path, bin_sec: int = peaks.BIN):
    """Mean RMS (dB, converted to linear) per bin via ffmpeg astats."""
    n = 16000 * bin_sec
    p = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(media), "-vn", "-ac", "1", "-ar", "16000", "-af",
         f"aresample=16000,asetnsamples=n={n}:p=0,astats=metadata=1:reset=1,ametadata=print:key=lavfi.astats.Overall.RMS_level:file=-",
         "-f", "null", "-"], capture_output=True, text=True)
    vals = []
    for m in re.finditer(r"RMS_level=(-?[\d.]+|-inf)", p.stdout):
        db = -90.0 if m.group(1) == "-inf" else float(m.group(1))
        vals.append(10 ** (max(db, -90.0) / 20))
    if not vals:
        raise RuntimeError("Ses seviyesi ölçülemedi.")
    return vals


def find(url: str, cache_dir: Path, duration: float, **kw):
    media = download_low(url, Path(cache_dir) / "audio_low.bin")
    raw = loudness_series(media)
    return peaks.peaks_from_scores(peaks.smooth(raw), duration, **kw)
