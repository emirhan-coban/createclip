"""Cut a time range from a Kick VOD without downloading the whole stream, then trim it
precisely (snapping the cut points to pauses in speech so clips don't start/end mid-word)."""
import re
import shutil
import subprocess
from pathlib import Path

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


def download_range(url: str, start: float, end: float, out: Path, max_height: int = 720) -> Path:
    ytdlp = shutil.which("yt-dlp")
    out.parent.mkdir(parents=True, exist_ok=True)
    for old in out.parent.glob(out.stem + ".*"):
        old.unlink()
    produced = out.with_suffix(".mp4")
    err = "bilinmeyen hata"
    for attempt in range(3):                       # Kick's CDN sometimes stalls mid-download
        for old in out.parent.glob(out.stem + ".*"):
            old.unlink()
        try:
            p = subprocess.run(
                [ytdlp, "-q", "--socket-timeout", "30", "-f", f"best[height<={max_height}]/best",
                 "--download-sections", f"*{hms(start)}-{hms(end)}", "--force-keyframes-at-cuts", "-o",
                 str(out.with_suffix("")) + ".%(ext)s", url], capture_output=True, text=True, timeout=240)
        except subprocess.TimeoutExpired:
            err = "indirme zaman aşımına uğradı"
            continue
        if p.returncode == 0 and produced.exists():
            return produced
        err = p.stderr.strip()[-300:] or err
    raise RuntimeError("Klip kesilemedi: " + err)


def silences(media: Path, noise_db: int = -30, min_len: float = 0.3):
    """Pauses in the audio as (start, end) pairs, seconds from the media start."""
    p = subprocess.run(["ffmpeg", "-v", "info", "-i", str(media), "-vn", "-af",
                        f"silencedetect=noise={noise_db}dB:d={min_len}", "-f", "null", "-"],
                       capture_output=True, text=True)
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


def trim(raw: Path, a: float, b: float, out: Path) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{a:.3f}", "-to", f"{b:.3f}", "-i", str(raw),
                    "-c:v", "libx264", "-crf", "18", "-preset", "veryfast", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", str(out)], check=True)
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
    trim(r, a, b, out)
    return raw_start + a, raw_start + b, raw_start, raw_end
