"""Fallback when chat is unavailable: find loud moments (shouting/laughter) from the VOD's audio.
Downloads the smallest video rendition (~250 MB for 2.5 h) once and measures loudness."""
import re
import shutil
import subprocess
from pathlib import Path

from . import peaks


def download_low(url: str, out: Path):
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        return out
    p = subprocess.run([shutil.which("yt-dlp"), "-q", "-f", "worst[height>=160]/worst", "-o",
                        str(out.with_suffix("")) + ".%(ext)s", url], capture_output=True, text=True)
    if p.returncode != 0 or not out.exists():
        raise RuntimeError("Ses için düşük kalite VOD indirilemedi: " + p.stderr.strip()[-200:])
    return out


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
    media = download_low(url, Path(cache_dir) / "audio_low.mp4")
    raw = loudness_series(media)
    return peaks.peaks_from_scores(peaks.smooth(raw), duration, **kw)
