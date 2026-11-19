"""Cut a time range from a Kick VOD without downloading the whole stream, then trim it
precisely (snapping the cut points to pauses in speech so clips don't start/end mid-word)."""
import re
import shutil
import subprocess
from pathlib import Path

from . import ytdlp
from .log import run, run_ok

PAD = 10.0  # seconds of extra footage kept around a clip so edits can nudge without re-downloading


def hms(sec: float) -> str:
    sec = int(max(sec, 0))
    return f"{sec // 3600:02d}:{sec % 3600 // 60:02d}:{sec % 60:02d}"


def parse_time(s: str) -> float:
    """'1:44:50', '104:50', '6290' -> seconds."""
    parts = [float(x) for x in str(s).strip().split(":")]
    sec = 0.0
    for p in parts:
        sec = sec * 60 + p
    return sec


def format_selector(h: int) -> str:
    """yt-dlp format for "best quality up to h px". YouTube only offers progressive (video+audio in one file)
    up to 360p; 720p/1080p are separate video and audio streams, so `best[height<=h]` silently picked 360p there
    (measured: format 18, 640x360). Prefer H.264 video + best audio merged by ffmpeg, then any codec, then a
    progressive file. Kick serves combined HLS renditions, which the same string also resolves (720p60/1080p60)."""
    return (f"bv*[height<={h}][vcodec^=avc1]+ba/b[height<={h}][vcodec^=avc1]/"
            f"bv*[height<={h}]+ba/b[height<={h}]/b")


def download_range(url: str, start: float, end: float, out: Path, max_height: int = 720) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    for old in out.parent.glob(out.stem + ".*"):
        old.unlink()
    produced = out.with_suffix(".mp4")
    err = "bilinmeyen hata"
    for attempt in range(3):                       # Kick's CDN sometimes stalls mid-download
        for old in out.parent.glob(out.stem + ".*"):
            old.unlink()
        try:
            p = run(
                ytdlp.cmd("-q", "--socket-timeout", "30", "-f", format_selector(max_height),
                 "--merge-output-format", "mp4", "--download-sections", f"*{hms(start)}-{hms(end)}", "--force-keyframes-at-cuts", "-o",
                 str(out.with_suffix("")) + ".%(ext)s", url), f"indirme {hms(start)}-{hms(end)} (deneme {attempt + 1})", timeout=240)
        except subprocess.TimeoutExpired:
            err = "indirme zaman aşımına uğradı"
            continue
        if p.returncode == 0 and produced.exists():
            return produced
        err = p.stderr.strip()[-300:] or err
    raise RuntimeError("Klip kesilemedi: " + err)


def silences(media: Path, noise_db: int = -30, min_len: float = 0.3):
    """Pauses in the audio as (start, end) pairs, seconds from the media start."""
    p = run(["ffmpeg", "-v", "info", "-i", str(media), "-vn", "-af",
             f"silencedetect=noise={noise_db}dB:d={min_len}", "-f", "null", "-"], "sessizlik taraması")
    s = [float(x) for x in re.findall(r"silence_start: (-?[\d.]+)", p.stderr)]
    e = [float(x) for x in re.findall(r"silence_end: (-?[\d.]+)", p.stderr)]
    return list(zip(s, e))


def snap(target: float, sil, window: float = 6.0, lo: float = 0.0, hi: float = 1e9) -> float:
    """Move a cut point to the middle of the nearest pause within +-window seconds."""
    best, bd = target, window
    for a, b in sil:
        mid = (a + b) / 2
        if lo <= mid <= hi and abs(mid - target) <= bd:
            best, bd = mid, abs(mid - target)
    return best


LOUDNORM = "loudnorm=I=-16:TP=-1.5:LRA=11"      # streaming loudness target (EBU R128), so clips are equally loud


def trim_dead_air(a: float, b: float, sil, min_gap: float = 0.7, keep: float = 0.2, min_len: float = 5.0):
    """Cut leading/trailing silence from [a, b]: if the clip opens (or ends) in a pause longer than `min_gap`,
    start (end) `keep` seconds before speech resumes (after it stops). Both video and audio are cut, so nothing
    drifts. Silences are (start, end) pairs in the same time base as a and b."""
    for s0, s1 in sil:
        if s0 <= a + 0.15 and s1 - a > min_gap and s1 < b - min_len:      # silence covers the opening
            a = max(a, s1 - keep)
        if s1 >= b - 0.15 and b - s0 > min_gap and s0 > a + min_len:      # silence covers the ending
            b = min(b, s0 + keep)
    return a, b


def trim(raw: Path, a: float, b: float, out: Path, normalize: bool = True) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["ffmpeg", "-y", "-v", "error", "-ss", f"{a:.3f}", "-to", f"{b:.3f}", "-i", str(raw),
           "-c:v", "libx264", "-crf", "18", "-preset", "veryfast", "-pix_fmt", "yuv420p"]
    if normalize:
        cmd += ["-af", LOUDNORM, "-ar", "48000"]
    run_ok(cmd + ["-c:a", "aac", str(out)], "klip kırpma")
    return out


def make_clip(url: str, start: float, end: float, raw: Path, out: Path, duration: float,
              max_height: int = 720, snap_cuts: bool = True, min_len: float = 20, max_len: float = 75):
    """Download [start-PAD, end+PAD], snap the cuts to pauses, trim into `out`.
    Returns (final_start, final_end, raw_start, raw_end) in VOD seconds."""
    raw_start = max(0.0, start - PAD)
    raw_end = min(duration, end + PAD)
    r = download_range(url, raw_start, raw_end, raw, max_height)
    a, b = start - raw_start, end - raw_start
    if snap_cuts:
        sil = silences(r)
        a2 = snap(a, sil, lo=0, hi=a + PAD)
        b2 = snap(b, sil, lo=b - PAD, hi=raw_end - raw_start)
        if min_len <= b2 - a2 <= max_len:
            a, b = a2, b2
        a3, b3 = trim_dead_air(a, b, sil)
        if b3 - a3 >= min_len:
            a, b = a3, b3
    trim(r, a, b, out)
    return raw_start + a, raw_start + b, raw_start, raw_end
