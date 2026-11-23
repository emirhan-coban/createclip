"""Title, description and hashtags for a clip. Rule based (no model needed): the source video's title as title, and a
description with a credit line (timestamped link back to the original) plus the configured hashtags."""
import re
from urllib.parse import urlencode


def _timestamp_link(url: str, start: float) -> str:
    t = int(start)
    if "youtube.com" in url or "youtu.be" in url:
        return url.split("&t=")[0] + ("&" if "?" in url else "?") + urlencode({"t": f"{t}s"})
    return url


def clean_title(title: str, limit: int = 90) -> str:
    t = re.sub(r"[#\U0001F300-\U0001FAFF]+", " ", title or "")      # hashtags/emoji from the stream title
    t = re.sub(r"\s+", " ", t).strip(" -|·")
    return (t[:limit].rsplit(" ", 1)[0] if len(t) > limit else t) or "Yayından en iyi an"


def make(video_title: str, channel: str, url: str, start: float, cfg: dict) -> dict:
    title = clean_title(video_title)
    tags = [h if h.startswith("#") else "#" + h for h in cfg.get("hashtags", [])]
    if channel:
        tags.append("#" + re.sub(r"\W+", "", channel))
    lines = []
    if cfg.get("credit", True):
        lines += [f"Kaynak yayın: {channel or 'yayıncı'} ({_timestamp_link(url, start)})", ""]
    lines.append(" ".join(dict.fromkeys(tags)))
    return {"title": title, "description": "\n".join(lines).strip(), "tags": [t.lstrip("#") for t in dict.fromkeys(tags)]}
