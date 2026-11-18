import json

import pytest

from createclip import kick, peaks, sources, youtube


def _line(ms, mid, text_runs, author="u"):
    item = {"liveChatTextMessageRenderer": {"id": mid, "authorName": {"simpleText": author},
                                            "message": {"runs": text_runs}}}
    return json.dumps({"replayChatItemAction": {"videoOffsetTimeMsec": str(ms),
                                                "actions": [{"addChatItemAction": {"item": item}}]}})


def test_url_detection():
    for u in ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "https://youtu.be/dQw4w9WgXcQ?t=5",
              "https://www.youtube.com/live/dQw4w9WgXcQ", "https://youtube.com/watch?feature=x&v=dQw4w9WgXcQ"):
        assert youtube.parse_url(u) == "dQw4w9WgXcQ" and sources.platform(u) == "youtube"
    assert sources.platform("https://kick.com/abc/videos/01a1db53-5ce0-7eb5-ae96-cf056188217d") == "kick"
    with pytest.raises(kick.KickError):
        sources.platform("https://example.com/x")


def test_parse_chat_and_peaks(tmp_path):
    lines = [_line(1000 * t, f"a{t}", [{"text": "merhaba"}], f"u{t % 5}") for t in range(0, 600, 2)]
    lines += [_line(300_000 + 100 * i, f"b{i}", [{"text": "kral"}], f"x{i}") for i in range(200)]   # burst at 300 s
    lines += [_line(5000, "e1", [{"emoji": {"shortcuts": [":pog:"]}}]), _line(-5000, "neg", [{"text": "pre"}]),
              _line(1000, "a0", [{"text": "dup"}]), "not json", ""]
    f = tmp_path / youtube.CHAT_FILE
    f.write_text("\n".join(lines))
    msgs = youtube.parse_chat(f, 600)
    assert len(msgs) == 501                              # dup id and negative offset dropped
    assert all(0 <= m["t"] <= 600 for m in msgs) and msgs == sorted(msgs, key=lambda m: m["t"])
    assert any(peaks.is_emote_only(m["c"]) for m in msgs)
    assert not any(m["c"] in ("pre", "dup") for m in msgs)
    found = peaks.find_peaks(msgs, 600, n=3)
    assert found and abs(found[0].start + 20 - 300) < 60


def test_fetch_chat_uses_cache(tmp_path, monkeypatch):
    (tmp_path / youtube.CHAT_FILE).write_text(_line(10_000, "m1", [{"text": "selam"}]))
    monkeypatch.setattr(youtube.subprocess, "run", lambda *a, **k: pytest.fail("cache must be used"))
    vod = kick.Vod("dQw4w9WgXcQ", "kanal", "t", 100.0, 0, 0, "https://youtu.be/dQw4w9WgXcQ")
    d = sources.fetch_chat(vod, tmp_path)
    assert d.dense and len(d.msgs) == 1 and d.coverage.covers(0, 100)


def test_live_stream_rejected(monkeypatch):
    class P:
        returncode, stdout, stderr = 0, json.dumps({"live_status": "is_live", "duration": None}), ""
    monkeypatch.setattr(youtube.subprocess, "run", lambda *a, **k: P())
    monkeypatch.setattr(youtube, "_cmd", lambda *a: ["yt-dlp", *a])
    with pytest.raises(youtube.YouTubeError, match="sürüyor"):
        youtube.vod_info("https://youtu.be/dQw4w9WgXcQ")


def test_log_run_and_tail(tmp_path):
    from createclip import log as logmod
    f = logmod.setup(tmp_path)
    p = logmod.run(["python3", "-c", "import sys; sys.stderr.write('boom'); sys.exit(3)"], "deneme")
    assert p.returncode == 3
    text = logmod.tail(f, 10)
    assert "deneme" in text and "çıkış kodu 3" in text and "boom" in text


def test_task_buffer_and_api_log(tmp_path):
    from fastapi.testclient import TestClient
    from createclip.web.app import make_app
    c = TestClient(make_app(tmp_path))
    r = c.post("/api/jobs", json={"url": "https://example.com/x"})
    tid = r.json()["id"]
    import time
    for _ in range(50):
        j = c.get(f"/api/tasks/{tid}").json()
        if j["status"] != "running":
            break
        time.sleep(0.1)
    assert j["status"] == "error" and "Desteklenen" in j["error"]
    assert any("başarısız" in line for line in j["log"])
    assert "Desteklenen" in c.get("/api/log").json()["text"]


def test_audio_fallback_needs_confirmation(tmp_path, monkeypatch):
    from createclip import pipeline
    vod = kick.Vod("dQw4w9WgXcQ", "kanal", "t", 24894.0, 0, 0, "https://youtu.be/dQw4w9WgXcQ")
    monkeypatch.setattr(pipeline.sources, "vod_info", lambda url: vod)

    def no_chat(*a, **k):
        raise youtube.YouTubeError("Sohbet tekrarı alınamadı: bu videoda sohbet tekrarı yok")
    monkeypatch.setattr(pipeline.sources, "fetch_chat", no_chat)
    with pytest.raises(pipeline.NeedsAudioConfirm) as ei:
        pipeline.run(vod.url, tmp_path, pipeline.Options())
    assert ei.value.est_mb == 145 and "onay" in str(ei.value)
    # confirmed -> goes on to the audio path
    monkeypatch.setattr(pipeline.audio_peaks, "find", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("AUDIO")))
    with pytest.raises(RuntimeError, match="AUDIO"):
        pipeline.run(vod.url, tmp_path, pipeline.Options(audio_ok=True))
    # explicit chat-only never falls back
    with pytest.raises(youtube.YouTubeError):
        pipeline.run(vod.url, tmp_path, pipeline.Options(source="chat"))


def test_frame_of_missing_clip_is_404_not_500(tmp_path):
    from fastapi.testclient import TestClient
    from createclip import pipeline
    from createclip.web.app import make_app
    jd = tmp_path / "output" / "p-1"
    jd.mkdir(parents=True)
    pipeline.save(jd, {"clips": [{"i": 1, "name": "clip_01", "src": "clips/clip_01.mp4", "start": 0, "end": 40}],
                       "defaults": {}, "next_i": 2})
    c = TestClient(make_app(tmp_path), raise_server_exceptions=False)
    r = c.get("/api/projects/p-1/clips/1/frame")
    assert r.status_code == 404 and "bulunamadı" in r.text
    assert c.get("/api/projects/silinmis/clips/1/frame").status_code == 404


def test_format_selector_prefers_hd_split_streams():
    from createclip import clipper
    f = clipper.format_selector(720)
    first = f.split("/")[0]
    assert first == "bv*[height<=720][vcodec^=avc1]+ba"          # separate H.264 video + audio first
    assert f.endswith("/b") and "best[height" not in f           # old selector picked 360p progressive on YouTube
    assert "height<=1080" in clipper.format_selector(1080)
