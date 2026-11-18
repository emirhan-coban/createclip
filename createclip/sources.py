"""Platform dispatch: a link is either Kick or YouTube; both yield the same Vod / ChatData shapes."""
from . import kick, youtube


def platform(url: str) -> str:
    if youtube.is_youtube(url):
        return "youtube"
    if kick.URL_RE.search(url):
        return "kick"
    raise kick.KickError("Desteklenen bir link değil: Kick VOD (kick.com/<kanal>/videos/<id>) "
                         "veya YouTube (youtube.com/watch?v=… / youtu.be/…) bekleniyor.")


def vod_info(url: str) -> kick.Vod:
    return youtube.vod_info(url) if platform(url) == "youtube" else kick.vod_info(url)


def fetch_chat(vod: kick.Vod, cache_dir, progress=None, mode: str = "smart") -> kick.ChatData:
    if platform(vod.url) == "youtube":
        return youtube.fetch_chat(vod, cache_dir, progress, mode)
    return kick.fetch_chat(vod, cache_dir, progress=progress, mode=mode)
