"""Stage 1, as in the video: yt-dlp pulls the raw material. Only the needed time range is downloaded.

Failures are classified: YouTube sometimes answers a burst of requests with 429 / "Sign in to confirm you're not a
bot"; that is a temporary block of your IP, so we raise BlockedError (callers stop hammering) instead of retrying
twenty clips into the same wall."""
import json
import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from .proc import log, run
from .sources import kick, youtube, ytdlp


class DownloadError(RuntimeError):
    pass


class BlockedError(DownloadError):
    """The platform temporarily refuses us (rate limit / bot check). Wait; do not retry in a loop."""


# The audio track is ~3000 small fragments and YouTube throttles each connection. Measured on a 296 min stream
# (103 MiB, 35 s windows): 1 connection 0.12 MB/s, 8 -> 0.84, 16 -> 1.28, 32 -> 1.35 MB/s. 16 is the knee.
AUDIO_FRAGMENTS = 16

BLOCK_MARKERS = ("429", "Too Many Requests", "Sign in to confirm", "not a bot", "HTTP Error 403")


@dataclass
class Video:
    url: str
    title: str
    duration: float
    platform: str          # kick | youtube | other
    channel: str
    vod: object = None     # kick.Vod / youtube Vod, used by the chat engine
    thumbnail: str = ""
    live: bool = False     # still broadcasting (Kick): `duration` = footage available so far


def hms(sec: float) -> str:
    sec = max(0, int(sec))
    return f"{sec // 3600:02d}:{sec % 3600 // 60:02d}:{sec % 60:02d}"


def platform(url: str) -> str:
    if "kick.com" in url:
        return "kick"
    if youtube.is_youtube(url):
        return "youtube"
    return "other"


def _check_blocked(text: str):
    if any(m.lower() in text.lower() for m in BLOCK_MARKERS):
        raise BlockedError("Platform şu an isteklerimizi engelliyor (429 / bot kontrolü). Birkaç saat bekle; "
                           "sık denemek süreyi uzatır.")


def info(url: str) -> Video:
    pf = platform(url)
    try:
        if pf == "kick":
            v = kick.vod_info(url)
            return Video(url, v.title, v.duration, pf, v.slug, v, v.thumbnail, v.live)
        if pf == "youtube":
            v = youtube.vod_info(url)
            return Video(url, v.title, v.duration, pf, v.slug, v, v.thumbnail)
    except kick.KickError as e:
        _check_blocked(str(e))
        raise DownloadError(str(e)) from e
    p = run(ytdlp.cmd("-J", "--skip-download", "--no-playlist", url), "info", timeout=180)
    if p.returncode:
        _check_blocked(p.stderr)
        raise DownloadError("Video bilgisi alınamadı: " + p.stderr.strip()[-300:])
    d = json.loads(p.stdout)
    return Video(url, d.get("title") or "", float(d.get("duration") or 0), pf, d.get("uploader") or "", None, d.get("thumbnail") or "")


def format_selector(h: int) -> str:
    """Best quality up to h px. YouTube only has progressive files up to 360p, 720p/1080p are separate video and
    audio streams, so ask for H.264 video + best audio first, then looser fallbacks."""
    return (f"bv*[height<={h}][vcodec^=avc1]+ba/b[height<={h}][vcodec^=avc1]/"
            f"bv*[height<={h}]+ba/b[height<={h}]/b")


def has_video(p: Path) -> bool:
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=codec_type",
                          "-of", "csv=p=0", str(p)], capture_output=True, text=True).stdout
    return "video" in out


def fetch_range(url: str, start: float, end: float, out: Path, max_height: int = 1080, tries: int = 3) -> Path:
    """Stream-copy [start, end] of the video into `out` (.mp4). Retries stalls; raises BlockedError on 429/bot check."""
    out.parent.mkdir(parents=True, exist_ok=True)
    stem = str(out.with_suffix(""))
    kick_args = ["--downloader-args", "ffmpeg_i:-analyzeduration 60M -probesize 60M"] if "kick.com" in url else []
    err = "unknown error"
    for attempt in range(1, tries + 1):
        for old in out.parent.glob(out.stem + ".*"):
            old.unlink()
        try:
            p = run(ytdlp.cmd("-q", "--socket-timeout", "30", *kick_args, "-f", format_selector(max_height),
                              "--merge-output-format", "mp4", "--download-sections", f"*{hms(start)}-{hms(end)}",
                              "-o", stem + ".%(ext)s", url),
                    f"download {hms(start)}-{hms(end)} (try {attempt})", timeout=240)
        except subprocess.TimeoutExpired:
            err = "download timed out (stalled stream)"
            continue
        if p.returncode == 0 and out.exists():
            if has_video(out):
                return out
            err = "downloaded section has no video stream"
            continue
        _check_blocked(p.stderr)
        err = p.stderr.strip()[-300:] or err
    raise DownloadError(f"{hms(start)}-{hms(end)} could not be downloaded: {err}")


def fetch_audio(url: str, out: Path, progress=None) -> Path:
    """Whole audio track at the lowest quality, for loudness analysis (YouTube ~0.35 MB/min).
    progress(fraction, text) is called with yt-dlp's live percentage."""
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists() and out.stat().st_size:
        return out
    last = [0.0]

    def on_line(line: str):
        m = re.search(r"(\d+(?:\.\d+)?)%(?:\s+of\s+~?\s*([0-9.]+\s*\w+))?", line)
        if m and progress and time.time() - last[0] > 0.7:
            last[0] = time.time()
            progress(float(m.group(1)) / 100, f"%{float(m.group(1)):.0f}" + (f" ({m.group(2)})" if m.group(2) else ""))
    p = run(ytdlp.cmd("-N", str(AUDIO_FRAGMENTS), "--newline", "-f", "worstaudio/worst", "--no-playlist", "-o", str(out), url), "audio",
            timeout=3600, on_line=on_line)
    if p.returncode or not out.exists():
        _check_blocked(p.stderr)
        raise DownloadError("Ses indirilemedi: " + p.stderr.strip()[-300:])
    return out


# ---------------------------------------------------------------- channels
def normalize_channel(url: str) -> str:
    """kick.com/<channel> -> .../videos ; youtube.com/@x or @x -> .../streams ; anything else is returned as is."""
    url = url.strip().rstrip("/")
    m = re.match(r"(?:https?://)?(?:www\.)?kick\.com/([^/?#]+)", url)
    if m and m.group(1) not in ("video", "categories"):
        return f"https://kick.com/{m.group(1)}/videos"
    m = re.match(r"(?:https?://)?(?:www\.|m\.)?youtube\.com/((?:@|channel/|c/|user/)[^/?#]+)", url)
    if m:
        return f"https://www.youtube.com/{m.group(1)}/streams"
    if url.startswith("@"):
        return f"https://www.youtube.com/{url}/streams"
    return url


KICK_CHANNEL = re.compile(r"^(?:https?://)?(?:www\.)?kick\.com/([A-Za-z0-9_.-]+)/?(?:[?#].*)?$")
KICK_RESERVED = {"video", "videos", "categories", "category", "browse", "following", "dashboard", "search", "clips"}


def resolve(url: str) -> str:
    """A Kick channel link (kick.com/<channel>) is turned into the link of its running broadcast, so the page you are
    looking at can be pasted as it is. A finished or watchable VOD link is returned unchanged."""
    m = KICK_CHANNEL.match(url.strip())
    if not m or m.group(1).lower() in KICK_RESERVED:
        return url
    name = m.group(1)
    p = run(ytdlp.cmd("--flat-playlist", "--playlist-end", "5", "--print", "%(.{url,live_status})j",
                      f"https://kick.com/{name}/videos"), f"{name} canlı mı", timeout=120)
    if p.returncode:
        _check_blocked(p.stderr)
        raise DownloadError(f"{name} kanalının yayın listesi alınamadı: " + p.stderr.strip()[-200:])
    for line in p.stdout.splitlines():
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if d.get("live_status") == "is_live" and d.get("url"):
            return d["url"].split("#")[0]
    raise DownloadError(f"{name} şu an canlı yayında değil. Biten bir yayın için kanalın Videolar sekmesinden "
                        "yayının linkini (…/videos/…) kopyala.")


def list_videos(channel_url: str, limit: int = 10) -> list[dict]:
    """Recent finished streams of a channel, newest first: [{url, title, duration, ts}]. Live/upcoming are dropped."""
    p = run(ytdlp.cmd("--flat-playlist", "--playlist-end", str(limit), "--print",
                      "%(.{id,url,title,duration,timestamp,release_timestamp,live_status})j", normalize_channel(channel_url)),
            "channel list", timeout=120)
    if p.returncode:
        _check_blocked(p.stderr)
        raise DownloadError("Kanal listesi alınamadı: " + p.stderr.strip()[-200:])
    out = []
    for line in p.stdout.splitlines():
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if d.get("live_status") in ("is_live", "is_upcoming") or not d.get("duration"):
            continue
        url = (d.get("url") or "").split("#")[0]
        if url:
            out.append({"url": url, "title": d.get("title") or "", "duration": float(d["duration"]),
                        "ts": d.get("timestamp") or d.get("release_timestamp") or 0})
    return out
