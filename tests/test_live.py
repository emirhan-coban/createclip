import json
import subprocess
import time

import pytest

from autoshorts import download, finder, pipeline
from autoshorts.sources import kick

URL = "https://kick.com/kanal/videos/01234567-89ab-cdef-0123-456789abcdef"


def _fake_run(payload):
    def run(cmd, what, timeout=None, **kw):
        return subprocess.CompletedProcess(cmd, 0, json.dumps(payload), "")
    return run


def _info(**over):
    d = {"title": "T", "duration": None, "timestamp": int(time.time()) - 3600, "channel_id": 5, "is_live": True,
         "live_status": "is_live"}
    d.update(over)
    return d


def test_live_vod_duration_is_elapsed_minus_margin(monkeypatch):
    monkeypatch.setattr(kick, "run", _fake_run(_info()))
    monkeypatch.setattr(kick.ytdlp, "cmd", lambda *a: ["yt-dlp"])
    v = kick.vod_info(URL)
    assert v.live and abs(v.duration - (3600 - kick.LIVE_MARGIN)) < 5
    assert download.info(URL).live is True


def test_finished_vod_unchanged(monkeypatch):
    monkeypatch.setattr(kick, "run", _fake_run(_info(duration=5400, is_live=False, live_status="was_live")))
    monkeypatch.setattr(kick.ytdlp, "cmd", lambda *a: ["yt-dlp"])
    v = kick.vod_info(URL)
    assert not v.live and v.duration == 5400.0


def test_just_started_live_and_unknown_duration_are_clear_errors(monkeypatch):
    monkeypatch.setattr(kick.ytdlp, "cmd", lambda *a: ["yt-dlp"])
    monkeypatch.setattr(kick, "run", _fake_run(_info(timestamp=int(time.time()) - 30)))
    with pytest.raises(kick.KickError, match="yeni başladı"):
        kick.vod_info(URL)
    monkeypatch.setattr(kick, "run", _fake_run(_info(is_live=False, live_status="was_live")))
    with pytest.raises(kick.KickError, match="süresi bilinmiyor"):
        kick.vod_info(URL)


def test_clamp_live_cuts_end_and_rejects_the_live_edge():
    ms = [finder.Moment(100, 200, 0, "manual"), finder.Moment(3000, 3200, 0, "manual")]
    out = pipeline.clamp_live(ms, 3100.0)
    assert (out[0].start, out[0].end) == (100, 200) and (out[1].start, out[1].end) == (3000, 3100.0)
    with pytest.raises(finder.FinderError, match="henüz yayınlanmadı"):
        pipeline.clamp_live([finder.Moment(3098, 3140, 0, "manual")], 3100.0)


def _flat(lines):
    def run(cmd, what, timeout=None, **kw):
        return subprocess.CompletedProcess(cmd, 0, "\n".join(json.dumps(x) for x in lines), "")
    return run


def test_channel_link_resolves_to_the_running_broadcast(monkeypatch):
    live = "https://kick.com/kanal/videos/01234567-89ab-cdef-0123-456789abcdef"
    monkeypatch.setattr(download.ytdlp, "cmd", lambda *a: ["yt-dlp"])
    monkeypatch.setattr(download, "run", _flat([{"url": live + "#__youtubedl_smuggle=%7B%7D", "live_status": "is_live"},
                                                {"url": "https://kick.com/kanal/videos/old", "live_status": "was_live"}]))
    for link in ("https://kick.com/kanal", "kick.com/kanal/", "https://www.kick.com/kanal?x=1"):
        assert download.resolve(link) == live
    assert download.resolve(live) == live                          # VOD links, YouTube and reserved pages untouched
    assert download.resolve("https://www.youtube.com/watch?v=abcdefghijk") == "https://www.youtube.com/watch?v=abcdefghijk"
    assert download.resolve("https://kick.com/categories") == "https://kick.com/categories"


def test_channel_not_live_is_a_clear_error(monkeypatch):
    monkeypatch.setattr(download.ytdlp, "cmd", lambda *a: ["yt-dlp"])
    monkeypatch.setattr(download, "run", _flat([{"url": "https://kick.com/kanal/videos/old", "live_status": "was_live"}]))
    with pytest.raises(download.DownloadError, match="canlı yayında değil"):
        download.resolve("https://kick.com/kanal")
