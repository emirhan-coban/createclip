"""YouTube (finished live streams / VODs): metadata and chat replay via yt-dlp.

Chat replay is fetched by yt-dlp as the `live_chat` pseudo-subtitle: one JSON object per line, each holding
replayChatItemAction entries with a `videoOffsetTimeMsec` relative to the video start, so no clock arithmetic
is needed. The whole replay is one yt-dlp call (no Kick-style request budget), cached as chat.live_chat.json.
Streams that are still live cannot be cut yet and are rejected with a clear message."""
import json
import re
import subprocess
import time
from pathlib import Path

from . import ytdlp
from ..proc import run
from .kick import ChatData, Coverage, KickError, Vod

URL_RE = re.compile(
    r"(?:youtube\.com/(?:watch\?(?:[^#]*&)?v=|live/|shorts/|embed/)|youtu\.be/)([A-Za-z0-9_-]{11})")
CHAT_FILE = "chat.live_chat.json"


class YouTubeError(KickError):
    """Subclass of KickError so the pipeline's chat fallback (audio peaks) handles it the same way."""


def is_youtube(url: str) -> bool:
    return bool(URL_RE.search(url))


def parse_url(url: str) -> str:
    m = URL_RE.search(url)
    if not m:
        raise YouTubeError("Geçerli bir YouTube linki değil (youtube.com/watch?v=… veya youtu.be/… bekleniyor).")
    return m.group(1)


def _slug(s: str) -> str:
    s = re.sub(r"[^\w-]+", "", (s or "").lstrip("@"), flags=re.UNICODE)
    return s[:40] or "youtube"


def _cmd(*args: str) -> list:
    try:
        return ytdlp.cmd(*args)
    except ytdlp.YtDlpMissing as e:
        raise YouTubeError(str(e)) from e


def vod_info(url: str) -> Vod:
    vid = parse_url(url)
    try:
        p = run(_cmd("-J", "--skip-download", "--no-playlist", url), "youtube bilgi", timeout=180)
    except subprocess.TimeoutExpired:
        raise YouTubeError("Video bilgisi 3 dk içinde gelmedi (ağ/YouTube takıldı); tekrar dene.") from None
    if p.returncode != 0:
        raise YouTubeError("Video bilgisi alınamadı: " + p.stderr.strip()[-300:])
    d = json.loads(p.stdout)
    status = d.get("live_status")
    if status in ("is_live", "is_upcoming"):
        raise YouTubeError("Yayın hâlâ sürüyor (ya da başlamadı). Bitince (kayıt hazır olunca) tekrar dene.")
    if not d.get("duration"):
        raise YouTubeError("Videonun süresi alınamadı.")
    ts = d.get("release_timestamp") or d.get("timestamp") or 0
    return Vod(vid, _slug(d.get("uploader_id") or d.get("channel") or d.get("uploader")), d.get("title") or "",
               float(d["duration"]), int(ts), 0, url, d.get("thumbnail") or "")


def _text(msg: dict) -> str:
    """Message runs -> text; emoji runs become Kick-style [emote:0:name] so peaks' emote-only weighting applies."""
    out = []
    for r in (msg.get("runs") or []):
        if "text" in r:
            out.append(r["text"])
        elif "emoji" in r:
            e = r["emoji"]
            name = (e.get("shortcuts") or [e.get("emojiId") or "e"])[0]
            out.append(f"[emote:0:{name.strip(':')}]")
    return "".join(out).strip()


_RENDERERS = ("liveChatTextMessageRenderer", "liveChatPaidMessageRenderer", "liveChatMembershipItemRenderer")


def parse_chat(path: Path, duration: float) -> list:
    """live_chat JSON lines -> [{"t": seconds, "u": author, "c": text}], sorted, only inside the video."""
    msgs, seen = [], set()
    for line in Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        rep = obj.get("replayChatItemAction")
        if not rep:
            continue
        try:
            t = int(rep.get("videoOffsetTimeMsec", "")) / 1000.0
        except (TypeError, ValueError):
            continue
        for act in rep.get("actions", []):
            item = (act.get("addChatItemAction") or {}).get("item") or {}
            for k in _RENDERERS:
                r = item.get(k)
                if not r:
                    continue
                mid = r.get("id")
                if mid in seen or not (0 <= t <= duration):
                    break
                text = _text(r.get("message") or {})
                if text:
                    seen.add(mid)
                    msgs.append({"t": t, "u": (r.get("authorName") or {}).get("simpleText") or "?", "c": text})
                break
    msgs.sort(key=lambda m: m["t"])
    return msgs


def fetch_chat(vod: Vod, cache_dir: Path, progress=None, mode: str = "smart", workers: int = 0, start: float = 0.0, on_snapshot=None) -> ChatData:
    """Whole chat replay in one go (mode/workers are accepted for interface parity and ignored)."""
    cache_dir = Path(cache_dir)
    f = cache_dir / CHAT_FILE
    if not f.exists() or f.stat().st_size == 0:
        if progress:
            progress(0.0, 0, "sohbet tekrarı indiriliyor")
        for old in cache_dir.glob("chat.*"):
            if old.name != CHAT_FILE and old.suffix != ".jsonl":
                old.unlink()
        last = [0.0]

        def on_line(line: str):
            """yt-dlp prints fragment progress while it walks the replay: '[download]  12.3% ... (frag 12/100)'."""
            m = re.search(r"(\d+(?:\.\d+)?)%", line)
            if m and progress and time.time() - last[0] > 0.7:
                last[0] = time.time()
                progress(min(0.99, float(m.group(1)) / 100), 0, "sohbet tekrarı indiriliyor")
        p = run(_cmd("--newline", "--skip-download", "--no-playlist", "--write-subs", "--sub-langs", "live_chat",
                     "-o", str(cache_dir / "chat.%(ext)s"), vod.url), "youtube sohbet tekrarı", timeout=1800, on_line=on_line)
        if not f.exists():
            why = p.stderr.strip()[-250:] if p.returncode else "bu videoda sohbet tekrarı yok"
            raise YouTubeError("Sohbet tekrarı alınamadı: " + why)
    msgs = [m for m in parse_chat(f, vod.duration) if m["t"] >= start]
    if not msgs:
        raise YouTubeError("Sohbet tekrarı boş.")
    cov = Coverage()
    cov.add(float(start), vod.duration)
    if progress:
        progress(1.0, len(msgs), "tam")
    return ChatData(msgs, cov, True, [])
