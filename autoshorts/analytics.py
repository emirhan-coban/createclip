"""How the uploaded clips are doing: one YouTube Analytics "top videos" report, joined with the clips the panel
uploaded and summed per streamer. Read only, asked for when the page is opened; nothing is stored.

The report is limited to the 200 most viewed videos of the period, and YouTube's numbers arrive 2-3 days late."""
import json
import time
from datetime import date, timedelta
from urllib.parse import urlencode

from . import publish, store, top5

REPORTS = "https://youtubeanalytics.googleapis.com/v2/reports"
LIMIT = 200                      # the API's maximum for this report
FIRST_DAY = "2020-01-01"         # "all time": long before any of these uploads
# API metric name -> our key
METRICS = {"views": "views", "engagedViews": "engaged", "averageViewPercentage": "view_pct", "averageViewDuration": "view_secs",
           "subscribersGained": "subs", "likes": "likes", "comments": "comments", "shares": "shares"}
SUMS = ("views", "engaged", "subs", "likes", "comments", "shares")


def fetch(days: int, today: date | None = None) -> tuple[dict[str, dict], str, str]:
    """({video id: numbers}, start date, end date) for the last `days` days (0 = all time)."""
    today = today or date.today()
    start = (today - timedelta(days=days)).isoformat() if days else FIRST_DAY
    end = today.isoformat()
    url = REPORTS + "?" + urlencode({"ids": "channel==MINE", "startDate": start, "endDate": end, "dimensions": "video",
                                     "metrics": ",".join(METRICS), "sort": "-views", "maxResults": LIMIT})
    code, _, body = publish._http("GET", url, {"Authorization": f"Bearer {publish.access_token()}"}, timeout=30)
    if code != 200:
        text = publish._error_text(body)
        if "accessNotConfigured" in text or "has not been used" in text or "is disabled" in text:
            raise publish.PublishError("Google Cloud projesinde \"YouTube Analytics API\" etkin değil. APIs & Services > Library'den "
                                       "etkinleştir, birkaç dakika sonra yeniden dene.")
        raise publish.PublishError(f"YouTube analiz verisi alınamadı ({code}): {text}")
    d = json.loads(body)
    names = [h["name"] for h in d.get("columnHeaders", [])]
    out = {}
    for row in d.get("rows") or []:
        r = dict(zip(names, row))
        out[r["video"]] = {key: r.get(api) or 0 for api, key in METRICS.items()}
    return out, start, end


def summarize(videos: list[dict]) -> list[dict]:
    """One line per streamer from the videos that have numbers; average view percentage is weighted by views."""
    groups: dict[str, list[dict]] = {}
    for v in videos:
        if v["state"] == "data":
            groups.setdefault(v["streamer"], []).append(v)
    out = []
    for name, vs in groups.items():
        g = {"streamer": name, "videos": len(vs)} | {k: sum(v[k] for v in vs) for k in SUMS}
        g["avg_views"] = round(g["views"] / len(vs))
        g["view_pct"] = round(sum(v["view_pct"] * v["views"] for v in vs) / g["views"], 1) if g["views"] else 0
        out.append(g)
    return sorted(out, key=lambda g: (-g["avg_views"], g["streamer"]))


def streamer_of(clip: dict) -> str:
    if clip["engine"] == top5.ENGINE:
        return "Top 5 montajı"
    return clip.get("yt_streamer") or top5.channel_of(clip) or "bilinmiyor"


def report(con, days: int) -> dict:
    numbers, start, end = fetch(days)
    now = time.time()
    videos = []
    for c in store.clips(con):                       # deleted clips too: their video is still on YouTube
        if not c["yt_id"]:
            continue
        n = numbers.get(c["yt_id"])
        state = "data" if n else "scheduled" if (c["yt_publish_at"] or 0) > now else "waiting"
        videos.append({"clip_id": c["id"], "yt_id": c["yt_id"], "title": c["title"] or "", "streamer": streamer_of(c),
                       "published": c["yt_publish_at"], "state": state} | (n or {k: 0 for k in METRICS.values()}))
    videos.sort(key=lambda v: (v["state"] != "data", -v["views"], -(v["published"] or 0)))
    ours = {v["yt_id"] for v in videos}
    return {"start": start, "end": end, "videos": videos, "streamers": summarize(videos),
            "totals": {k: sum(v[k] for v in videos) for k in SUMS},
            "other": len(set(numbers) - ours), "truncated": len(numbers) >= LIMIT}
