import json
from pathlib import Path
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from autoshorts import config, download, export, meta, pipeline, store
from autoshorts.sources import peaks


@pytest.fixture
def env(tmp_path):
    config.configure(tmp_path)
    con = store.connect()
    yield tmp_path, con
    con.close()


# ---------------------------------------------------------------- export
def test_export_saves_video_and_text(env):
    tmp_path, con = env
    f = tmp_path / "c.mp4"
    f.write_bytes(b"video")
    t = tmp_path / "c.jpg"
    t.write_bytes(b"jpg")
    cfg = config.load()
    dest = export.save(cfg, 7, "Kanal Adı!", 3725, f, t, "Başlık", "Açıklama")
    assert dest.parent.parent == tmp_path / "ready" and dest.read_bytes() == b"video"
    assert dest.name == "Kanal-Adı_01h02m05s_7.mp4"
    assert dest.with_suffix(".jpg").exists()
    assert dest.with_suffix(".txt").read_text(encoding="utf-8") == "Başlık\n\nAçıklama\n"


def test_make_clip_marks_done_and_saves(env, monkeypatch):
    tmp_path, con = env
    from autoshorts import finder
    monkeypatch.setattr(download, "fetch_range", lambda url, s, e, out, h: (out.parent.mkdir(parents=True, exist_ok=True), out.write_bytes(b"raw"), out)[-1])
    monkeypatch.setattr(pipeline.render, "vertical", lambda raw, off, ln, out: out.write_bytes(b"vid") or out)
    monkeypatch.setattr(pipeline.render, "thumbnail", lambda v, o, at=1.0: o.write_bytes(b"j") or o)
    video = download.Video("https://kick.com/a/videos/x", "Big stream", 3600.0, "kick", "a")
    store.upsert_video(con, video.url, title=video.title)
    m = finder.Moment(100, 150, 4.2, "chat")
    cid = store.add_clip(con, video.url, m.start, m.end, m.score, m.engine)
    saved = pipeline.make_clip(con, config.load(), video, cid, m)
    c = store.get_clip(con, cid)
    assert c["status"] == "done" and c["file"] == str(saved) and saved.exists()
    assert saved.with_suffix(".txt").read_text(encoding="utf-8").startswith("Big stream")


# ---------------------------------------------------------------- watching channels, downloads, metadata
def test_scan_backfill_and_new_only(env):
    _, con = env
    store.add_source(con, "https://kick.com/a/videos", backfill=2)
    vids = [{"url": f"https://kick.com/a/videos/{i}", "title": f"t{i}", "duration": 3600.0, "ts": 100 - i} for i in range(5)]
    assert pipeline.scan_sources(con, lister=lambda u, n: vids) == 2      # only the newest 2 queued
    assert len(store.pending_videos(con)) == 2
    vids.insert(0, {"url": "https://kick.com/a/videos/new", "title": "n", "duration": 3600.0, "ts": 200})
    assert pipeline.scan_sources(con, lister=lambda u, n: vids) == 1      # later: just the new one


def test_download_helpers():
    assert download.hms(3725) == "01:02:05"
    assert download.normalize_channel("kick.com/abc") == "https://kick.com/abc/videos"
    assert download.normalize_channel("@abc") == "https://www.youtube.com/@abc/streams"
    for text in ("HTTP Error 429: Too Many Requests", "Sign in to confirm you're not a bot"):
        with pytest.raises(download.BlockedError):
            download._check_blocked(text)
    download._check_blocked("some other error")


def test_manual_times_and_meta():
    assert pipeline.parse_at("1:44:50") == (6290.0, 6335.0)
    assert pipeline.parse_at("0:10:00-0:11:00") == (600.0, 660.0)
    m = meta.make("GTA 6 🌴 İLK GÜN #shorts", "kanal", "https://www.youtube.com/watch?v=abc", 90, config.load())
    assert "t=90s" in m["description"] and "kanal" in m["description"] and "GTA 6" in m["title"]
    assert "🌴" not in m["title"]


def test_skip_start_ignores_crowded_intro():
    base = [{"t": t, "u": f"b{t}", "c": "x"} for t in range(0, 3600, 20)]
    intro = [{"t": 200 + k % 8, "u": f"u{k}", "c": "gelsin"} for k in range(80)]
    real = [{"t": 1500 + k % 8, "u": f"v{k}", "c": "gelsin"} for k in range(30)]
    msgs = base + intro + real
    assert abs(peaks.find_peaks(msgs, 3600, n=1)[0].time - 200) <= 20
    p = peaks.find_peaks(msgs, 3600, n=1, skip_start=600)[0]
    assert abs(p.time - 1500) <= 20 and p.start >= 600


# ---------------------------------------------------------------- web UI
@pytest.fixture
def web(env):
    """The FastAPI app behind a small `call(method, path, body, headers) -> (status, headers, bytes)` helper."""
    from fastapi.testclient import TestClient
    from autoshorts import api as apimod
    from autoshorts.jobs import App
    tmp_path, con = env
    app = App()
    client = TestClient(apimod.create_app(app))

    def call(method, path, body=None, headers=None):
        r = client.request(method, path, json=body, headers=headers or {})
        return r.status_code, dict(r.headers), r.content
    yield call, app, con, tmp_path


def _done_clip(con, tmp_path):
    f = tmp_path / "ready" / "d" / "c.mp4"
    f.parent.mkdir(parents=True)
    f.write_bytes(bytes(range(100)))
    f.with_suffix(".jpg").write_bytes(b"jpg")
    store.upsert_video(con, "https://kick.com/a/videos/x", title="V")
    cid = store.add_clip(con, "https://kick.com/a/videos/x", 10, 60, 2.5, "chat")
    store.update_clip(con, cid, file=str(f), title="T", description="D", status="done")
    return cid, f


def test_api_state_media_range_and_host_check(web):
    call, app, con, tmp_path = web
    cid, f = _done_clip(con, tmp_path)
    code, _, body = call("GET", "/api/state")
    st = json.loads(body)
    assert code == 200 and st["clips"][0]["id"] == cid and st["clips"][0]["has_file"]
    code, h, body = call("GET", f"/media/{cid}.mp4", headers={"Range": "bytes=10-19"})
    assert code == 206 and body == bytes(range(10, 20)) and h["content-range"] == "bytes 10-19/100"
    code, _, body = call("GET", f"/media/{cid}.mp4")
    assert code == 200 and len(body) == 100
    assert call("GET", "/media/999.mp4")[0] == 404
    assert call("GET", "/api/state", headers={"Host": "evil.example.com"})[0] == 403    # DNS rebinding
    assert call("GET", "/")[0] in (200, 404)                       # the built front end when present, a JSON hint otherwise


def test_api_edit_delete_and_post_rules(web):
    call, app, con, tmp_path = web
    cid, f = _done_clip(con, tmp_path)
    assert call("POST", f"/api/clips/{cid}/edit", {"title": "Yeni", "description": "Açıklama"})[0] == 200
    assert store.get_clip(con, cid)["title"] == "Yeni"
    assert f.with_suffix(".txt").read_text(encoding="utf-8") == "Yeni\n\nAçıklama\n"
    # a cross-site form post (no JSON content type) is refused
    assert call("POST", f"/api/clips/{cid}/delete", {}, headers={"Content-Type": "text/plain"})[0] == 403
    assert call("POST", "/api/run", {"url": "not a url"})[0] == 400
    assert call("POST", f"/api/clips/{cid}/delete", {})[0] == 200
    assert not f.exists() and store.get_clip(con, cid)["status"] == "deleted"


def test_api_run_job_goes_through_pipeline(web, monkeypatch):
    call, app, con, tmp_path = web
    seen = {}

    def fake(con_, cfg, url, n, at, engine, say, progress=None, emit=None):
        seen.update(url=url, n=n, at=at, engine=engine, skip=cfg["skip_start_min"])
        say("working")
        return [1, 2]
    monkeypatch.setattr(pipeline, "process_video", fake)
    code, _, body = call("POST", "/api/run", {"url": "https://kick.com/a/videos/x", "n": 3, "start_min": 10, "at": ["1:00:00"]})
    assert code == 200
    for _ in range(50):
        job = app.jobs[0]
        if job["status"] in ("done", "failed"):
            break
        threading.Event().wait(0.05)
    assert job["status"] == "done" and seen == {"url": "https://kick.com/a/videos/x", "n": 3, "at": ["1:00:00"], "engine": None, "skip": 10.0}
    assert "2 klip hazır" in job["log"][-1]


# ---------------------------------------------------------------- cancel
def test_cancel_kills_running_subprocess_group():
    import time
    from autoshorts import proc
    proc.clear_cancel()
    result = {}

    def work():
        try:
            proc.run(["sh", "-c", "sleep 30 & sleep 30"], "slow", timeout=60)       # child + grandchild
        except proc.Cancelled:
            result["cancelled"] = time.time()
    t = threading.Thread(target=work)
    t0 = time.time()
    t.start()
    time.sleep(0.5)
    proc.request_cancel()
    t.join(10)
    assert result.get("cancelled") and result["cancelled"] - t0 < 5
    with pytest.raises(proc.Cancelled):
        proc.run(["true"], "after cancel")           # flag stays set until cleared
    proc.clear_cancel()
    assert proc.run(["true"], "ok").returncode == 0


def test_api_cancel_queued_and_running(web, monkeypatch):
    call, app, con, tmp_path = web
    from autoshorts import proc

    def slow(con_, cfg, url, n, at, engine, say, progress=None, emit=None):
        for _ in range(200):
            proc.check_cancel()
            threading.Event().wait(0.05)
        return []
    monkeypatch.setattr(pipeline, "process_video", slow)
    j1 = json.loads(call("POST", "/api/run", {"url": "https://kick.com/a/videos/1"})[2])["id"]
    j2 = json.loads(call("POST", "/api/run", {"url": "https://kick.com/a/videos/2"})[2])["id"]
    for _ in range(50):
        if app.jobs[0]["status"] == "running":
            break
        threading.Event().wait(0.05)
    assert json.loads(call("POST", f"/api/jobs/{j2}/cancel", {})[2])["ok"]          # still queued
    assert app.jobs[1]["status"] == "cancelled"
    assert json.loads(call("POST", f"/api/jobs/{j1}/cancel", {})[2])["ok"]          # running
    for _ in range(100):
        if app.jobs[0]["status"] == "cancelled":
            break
        threading.Event().wait(0.05)
    assert app.jobs[0]["status"] == "cancelled"
    assert json.loads(call("POST", "/api/jobs/99/cancel", {})[2])["ok"] is False


# ---------------------------------------------------------------- progress
def test_run_streams_lines_and_times_out():
    from autoshorts import proc
    seen = []
    p = proc.run(["sh", "-c", "echo 10%; echo 50%; echo err >&2"], "t", on_line=seen.append)
    assert p.returncode == 0 and seen[:2] == ["10%", "50%"] and "err" in p.stderr
    import subprocess
    with pytest.raises(subprocess.TimeoutExpired):
        proc.run(["sh", "-c", "echo hi; sleep 30"], "t", timeout=1, on_line=lambda l: None)


def test_pipeline_reports_progress_in_order(env, monkeypatch):
    tmp_path, con = env
    from autoshorts import finder
    video = download.Video("https://kick.com/a/videos/x", "Big", 3600.0, "kick", "a")
    monkeypatch.setattr(download, "info", lambda url: video)

    def fake_find(v, cfg, cache, n, engine, progress, emit=None):
        progress(0.5, "Sohbet indiriliyor: yoğun bölgeler %50 · 100 mesaj")
        return [finder.Moment(100, 150, 3.0, "chat"), finder.Moment(400, 450, 2.0, "chat")]
    monkeypatch.setattr(finder, "find", fake_find)
    monkeypatch.setattr(download, "fetch_range", lambda url, s, e, out, h: (out.parent.mkdir(parents=True, exist_ok=True), out.write_bytes(b"r"), out)[-1])
    monkeypatch.setattr(pipeline.render, "vertical", lambda raw, off, ln, out: out.write_bytes(b"v") or out)
    monkeypatch.setattr(pipeline.render, "thumbnail", lambda v, o, at=1.0: o.write_bytes(b"j") or o)
    ticks = []
    ids = pipeline.process_video(con, config.load(), video.url, say=lambda *_: None, progress=lambda f, t="": ticks.append((f, t)))
    assert len(ids) == 2
    fr = [f for f, _ in ticks]
    assert fr == sorted(fr) and fr[0] == 0.0 and fr[-1] > 0.9 and max(fr) <= 1.0     # monotone, within 0..1
    texts = " | ".join(t for _, t in ticks)
    assert "yoğun bölgeler" in texts and "Klip 1/2" in texts and "Klip 2/2" in texts and "indiriliyor" in texts


# ---------------------------------------------------------------- FastAPI (React app backend)
@pytest.fixture
def api(env):
    from fastapi.testclient import TestClient
    from autoshorts import api as apimod
    from autoshorts.jobs import App
    tmp_path, con = env
    app = App()
    return TestClient(apimod.create_app(app)), app, con, tmp_path


def test_api_state_media_range_and_guard(api):
    client, app, con, tmp_path = api
    cid, f = _done_clip(con, tmp_path)
    st = client.get("/api/state").json()
    assert st["clips"][0]["id"] == cid and st["clips"][0]["has_file"]
    r = client.get(f"/media/{cid}.mp4", headers={"Range": "bytes=10-19"})
    assert r.status_code == 206 and r.content == bytes(range(10, 20))
    assert client.get("/api/state", headers={"host": "evil.example.com"}).status_code == 403
    assert client.post("/api/run", content="x", headers={"content-type": "text/plain"}).status_code == 403
    assert client.post("/api/run", json={"url": "nope"}).status_code == 400
    assert client.get("/media/999.mp4").status_code == 404


def test_api_events_stream_replays_and_ends(api, monkeypatch):
    client, app, con, tmp_path = api

    def fake(con_, cfg, url, n, at, engine, say, progress=None, emit=None):
        emit("info", title="T", duration=100)
        emit("moments", moments=[{"rank": 1, "start": 1, "end": 40, "score": 3.0}])
        return []
    monkeypatch.setattr(pipeline, "process_video", fake)
    jid = client.post("/api/run", json={"url": "https://kick.com/a/videos/x"}).json()["id"]
    with client.stream("GET", f"/api/jobs/{jid}/events") as r:
        body = "".join(r.iter_text())
    evs = [json.loads(l[6:]) for l in body.splitlines() if l.startswith("data: ")]
    assert [e["kind"] for e in evs] == ["info", "moments", "end"] and evs[-1]["status"] == "done"
    with client.stream("GET", f"/api/jobs/{jid}/events?after=0") as r:        # reconnect: resumes after event 0
        again = [json.loads(l[6:]) for l in "".join(r.iter_text()).splitlines() if l.startswith("data: ")]
    assert [e["kind"] for e in again] == ["moments", "end"]


def test_api_config_validation_and_job_history(api, monkeypatch):
    client, app, con, tmp_path = api
    monkeypatch.setattr(pipeline, "process_video", lambda *a, **k: [])
    r = client.post("/api/config", json={"clips_per_video": 8, "engine": "chat", "hashtags": ["oyun", "#komik"]})
    assert r.status_code == 200 and r.json()["config"]["clips_per_video"] == 8
    assert r.json()["config"]["hashtags"] == ["#oyun", "#komik"]
    assert client.get("/api/state").json()["config"]["engine"] == "chat"
    for bad in ({"clips_per_video": 99}, {"engine": "x"}, {"nope": 1}, {"output_dir": "  "}):
        assert client.post("/api/config", json=bad).status_code == 400
    # job history survives a "restart": a new App has no memory of the job but the state still lists it
    from autoshorts.jobs import App
    from autoshorts import api as apimod
    from fastapi.testclient import TestClient
    j = app.submit("run", url="https://kick.com/a/videos/1")
    for _ in range(100):
        if j["status"] == "done":
            break
        threading.Event().wait(0.05)
    assert j["status"] == "done"
    fresh = TestClient(apimod.create_app(App()))
    jobs = fresh.get("/api/state").json()["jobs"]
    assert jobs[0]["id"] == j["id"] and jobs[0]["live"] is False and jobs[0]["status"] == "done"
    assert fresh.post("/api/run", json={"url": "https://kick.com/a/videos/2"}).json()["id"] > j["id"]     # ids keep counting


# ---------------------------------------------------------------- editor
def _make_source(path):
    import subprocess
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=640x360:rate=30", "-f", "lavfi", "-i",
                    "sine=frequency=440:sample_rate=48000", "-t", "8", "-pix_fmt", "yuv420p", "-c:v", "libx264", "-c:a", "aac",
                    "-shortest", str(path)], check=True)
    return path


def test_layout_geometry_matches_between_modes():
    from autoshorts import editor
    # 16:9 source, 9:16 window at zoom 1: full height, a third of the width, centred
    x0, y0, w, h = editor.cell_rect(1920, 1080, {"cx": 0.5, "cy": 0.5, "zoom": 1}, 9, 16)
    assert (round(w), round(h), round(x0), round(y0)) == (608, 1080, 656, 0)
    # centre near the edge is clamped inside the frame
    x0, _, w, _ = editor.cell_rect(1920, 1080, {"cx": 0.0, "zoom": 1}, 9, 16)
    assert x0 == 0
    x0, _, w, _ = editor.cell_rect(1920, 1080, {"cx": 1.0, "zoom": 1}, 9, 16)
    assert round(x0 + w) == 1920
    # zoom 2 halves the window
    _, _, w2, h2 = editor.cell_rect(1920, 1080, {"zoom": 2}, 9, 16)
    assert round(h2) == 540 and round(w2) == round(w / 2)
    g = editor.build_graph({"layout": {"mode": "stack", "cells": [{"cx": .5, "cy": .5, "zoom": 1}, {"cx": .85, "cy": .8, "zoom": 3}]}}, 1920, 1080)
    assert "vstack" in g and g.count("crop=") == 2 and "scale=1080:960" in g
    assert "boxblur" in editor.build_graph({"layout": {"mode": "blur", "cells": []}}, 1920, 1080)


def test_clean_project_clamps_and_rejects():
    from autoshorts import editor
    p = editor.clean_project({"trim": {"in": -5, "out": 999}, "layout": {"mode": "crop", "cells": [{"cx": 5, "zoom": 0.2}]},
                              "audio": {"volume": 9}}, 20.0)
    assert p["trim"] == {"in": 0.0, "out": 20.0} and p["layout"]["cells"][0]["cx"] == 1.0 and p["layout"]["cells"][0]["zoom"] == 1.0
    assert p["audio"]["volume"] == 3.0 and len(p["layout"]["cells"]) == 2
    with pytest.raises(ValueError):
        editor.clean_project({"trim": {"in": 3, "out": 3.4}}, 20.0)
    with pytest.raises(ValueError):
        editor.clean_project({"layout": {"mode": "weird"}, "trim": {"in": 0, "out": 5}}, 20.0)


def test_editor_export_roundtrip(env):
    import subprocess
    from autoshorts import editor
    tmp_path, con = env
    src = _make_source(tmp_path / "data" / "clips" / "source" / "1.mp4")
    store.upsert_video(con, "https://kick.com/a/videos/x", title="V")
    cid = store.add_clip(con, "https://kick.com/a/videos/x", 110, 116, 3.0, "chat")
    old = tmp_path / "ready" / "d" / "a_00h01m50s_1.mp4"
    old.parent.mkdir(parents=True)
    old.write_bytes(b"old")
    store.update_clip(con, cid, file=str(old), title="T", description="D", status="done")
    store.set_source(con, cid, str(src), 100.0, 108.0)
    clip = store.get_clip(con, cid)
    info = editor.source_info(clip)
    assert info["width"] == 640 and info["audio"] and 7.5 < info["duration"] < 8.5
    proj = editor.default_project(clip)
    assert proj["trim"] == {"in": 10.0, "out": 16.0}          # clip 110-116 vs source starting at 100 (beyond the 8 s file: clamped on clean)
    proj["trim"] = {"in": 1.0, "out": 5.0}
    for mode in ("crop", "stack", "blur"):
        proj["layout"]["mode"] = mode
        saved = editor.export_clip(con, config.load(), cid, proj)
        out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=width,height,codec_type:format=duration", "-of", "json", str(saved)],
                             capture_output=True, text=True).stdout
        d = json.loads(out)
        v = next(s for s in d["streams"] if s["codec_type"] == "video")
        assert (v["width"], v["height"]) == (1080, 1920) and abs(float(d["format"]["duration"]) - 4.0) < 0.3
        assert any(s["codec_type"] == "audio" for s in d["streams"])
    c = store.get_clip(con, cid)
    assert c["start"] == 101.0 and c["end"] == 105.0 and Path(c["file"]).exists()
    assert (old.parent / "_eski" / old.name).read_bytes() == b"old" and not old.exists()      # earlier version tidied away, not lost
    assert Path(c["file"]).name == "a_00h01m41s_1.mp4"
    assert store.get_project(con, cid)["layout"]["mode"] == "blur"
    assets_strip = editor.filmstrip(cid, src, info["duration"])
    assert assets_strip["n"] >= 8 and (editor.editor_dir(cid) / "strip.jpg").exists()
    wave = editor.waveform(cid, src)
    assert len(wave) == 600 and max(wave) > 0.1


def test_api_editor_endpoints(api):
    client, app, con, tmp_path = api
    src = _make_source(tmp_path / "data" / "clips" / "source" / "1.mp4")
    store.upsert_video(con, "https://kick.com/a/videos/x", title="V")
    cid = store.add_clip(con, "https://kick.com/a/videos/x", 101, 106, 3.0, "chat")
    f = tmp_path / "ready" / "d" / "c.mp4"
    f.parent.mkdir(parents=True)
    f.write_bytes(b"x")
    store.update_clip(con, cid, file=str(f), title="T", description="D", status="done")
    r = client.get(f"/api/clips/{cid}/editor").json()
    assert r["source"] is None and r["project"] is None                     # no source yet
    assert client.put(f"/api/clips/{cid}/project", json={}).status_code == 409
    store.set_source(con, cid, str(src), 100.0, 108.0)
    r = client.get(f"/api/clips/{cid}/editor").json()
    assert r["source"]["width"] == 640 and r["project"]["trim"] == {"in": 1.0, "out": 6.0}
    assert client.get(f"/media/source/{cid}.mp4", headers={"Range": "bytes=0-9"}).status_code == 206
    a = client.get(f"/api/clips/{cid}/assets").json()
    assert a["strip"]["n"] >= 8 and len(a["wave"]) == 600
    assert client.get(f"/media/strip/{cid}.jpg").status_code == 200
    proj = {**r["project"], "trim": {"in": 2, "out": 6}, "layout": {"mode": "crop", "cells": [{"cx": 0.3, "cy": 0.5, "zoom": 1.5}]}}
    saved = client.put(f"/api/clips/{cid}/project", json=proj).json()["project"]
    assert saved["trim"] == {"in": 2.0, "out": 6.0} and saved["layout"]["mode"] == "crop"
    assert client.get(f"/api/clips/{cid}/editor").json()["project"]["layout"]["mode"] == "crop"
    assert client.put(f"/api/clips/{cid}/project", json={"trim": {"in": 3, "out": 3.2}}).status_code == 400
    jid = client.post(f"/api/clips/{cid}/export", json=proj).json()["id"]
    for _ in range(200):
        j = next(x for x in app.jobs if x["id"] == jid)
        if j["status"] in ("done", "failed"):
            break
        threading.Event().wait(0.1)
    assert j["status"] == "done", j.get("error")
    assert any(e["kind"] == "exported" for e in j["events"])
    assert store.get_clip(con, cid)["start"] == 102.0


def test_storage_usage_and_clean(env):
    from autoshorts import editor
    tmp_path, con = env
    src = _make_source(tmp_path / "data" / "clips" / "source" / "1.mp4")
    store.upsert_video(con, "https://kick.com/a/videos/x", title="V")
    cid = store.add_clip(con, "https://kick.com/a/videos/x", 101, 106, 3.0, "chat")
    done = tmp_path / "ready" / "d" / "c.mp4"
    done.parent.mkdir(parents=True)
    done.write_bytes(b"finished")
    store.update_clip(con, cid, file=str(done), status="done")
    store.set_source(con, cid, str(src), 100.0, 108.0)
    editor.filmstrip(cid, src, 8.0)
    store.save_project(con, cid, editor.default_project(store.get_clip(con, cid)))
    u = editor.storage_usage(con)
    assert u["files"] == 1 and u["bytes"] == src.stat().st_size
    freed = editor.clean_sources(con)
    assert freed == {"files": 1, "bytes": u["bytes"]}
    assert not src.exists() and done.exists()                                  # finished clips stay
    c = store.get_clip(con, cid)
    assert c["src_file"] is None and store.get_project(con, cid) is None
    assert not (editor.editor_dir(cid) / "strip.jpg").exists()
    assert editor.storage_usage(con) == {"files": 0, "bytes": 0}


# ---------------------------------------------------------------- captions
def test_caption_states_sequential_and_synced():
    from autoshorts import captions
    words = [{"word": "bir", "start": 1.0, "end": 1.4}, {"word": "iki", "start": 1.3, "end": 1.9},     # overlapping ASR times
             {"word": "üç.", "start": 2.0, "end": 2.5}, {"word": "dört", "start": 4.0, "end": 4.4}]
    st = captions.build_states(words, 3, 0.0)
    assert [s[2] for s in st] == [0, 1, 2, 0]                       # active word index inside each chunk
    for a, b in zip(st, st[1:]):
        assert a[1] <= b[0] + 1e-9 and a[0] < a[1]                  # strictly sequential: no drift can accumulate
    shifted = captions.build_states(words, 3, -0.08)
    assert abs(shifted[0][0] - 0.92) < 1e-9
    assert captions.tr_upper("ığdır iş") == "IĞDIR İŞ" and captions.mask_word("amk") == "a**"


def test_caption_style_and_words_are_cleaned():
    from autoshorts import captions
    s = captions.clean_style({"size": 9, "ypos": -1, "chunk": 99, "font": "poppins", "color": "#ABCDEF"})
    assert s["size"] == 0.16 and s["ypos"] == 0.02 and s["chunk"] == 6 and s["active"] == "#FFDD00"
    for bad in ({"font": "comic"}, {"color": "red"}):
        with pytest.raises(ValueError):
            captions.clean_style(bad)
    w = captions.clean_words([{"word": "  b ", "start": 2, "end": 1}, {"word": "", "start": 0, "end": 1}, {"word": "a", "start": 1, "end": 1.5}])
    assert [x["word"] for x in w] == ["a", "b"] and w[1]["end"] > w[1]["start"]


def test_export_burns_captions_in_the_right_place(env):
    import subprocess
    from PIL import Image, ImageChops
    from autoshorts import editor
    tmp_path, con = env
    src = _make_source(tmp_path / "data" / "clips" / "source" / "1.mp4")
    store.upsert_video(con, "https://kick.com/a/videos/x", title="V")
    cid = store.add_clip(con, "https://kick.com/a/videos/x", 101, 107, 3.0, "chat")
    f = tmp_path / "ready" / "d" / "a_1.mp4"
    f.parent.mkdir(parents=True)
    f.write_bytes(b"x")
    store.update_clip(con, cid, file=str(f), title="T", description="D", status="done")
    store.set_source(con, cid, str(src), 100.0, 108.0)
    base = editor.default_project(store.get_clip(con, cid))
    base["trim"] = {"in": 1.0, "out": 6.0}
    base["audio"]["normalize"] = False
    words = [{"word": "MERHABA", "start": 2.0, "end": 2.6}, {"word": "DÜNYA", "start": 2.6, "end": 3.4}]    # source seconds
    def frame(path, t, out):
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", str(t), "-i", str(path), "-frames:v", "1", str(out)], check=True)
        return Image.open(out).convert("RGB")

    def changed(a, b):
        return ImageChops.difference(a, b).convert("L").point(lambda v: 255 if v > 40 else 0).getbbox()
    # every export of the same cut writes the same file name, so grab the frames before the next export
    plain = editor.export_clip(con, config.load(), cid, base)
    p_on, p_off = frame(plain, 1.5, tmp_path / "p.png"), frame(plain, 4.5, tmp_path / "p2.png")
    caps = {"enabled": True, "words": words, "style": {"ypos": 0.62}}
    with_caps = editor.export_clip(con, config.load(), cid, {**base, "captions": caps})
    c_on, c_off = frame(with_caps, 1.5, tmp_path / "c.png"), frame(with_caps, 4.5, tmp_path / "c2.png")
    box = changed(p_on, c_on)          # clip time 1.5 s == source 2.5 s: a caption is on screen
    assert box and 0.55 * 1920 < box[1] and box[3] < 0.75 * 1920 and box[0] > 40 and box[2] < 1040      # band around ypos 0.62, inside the frame
    assert changed(p_off, c_off) is None                                     # 4.5 s: no words, frames identical
    off = editor.export_clip(con, config.load(), cid, {**base, "captions": {**caps, "enabled": False}})
    assert changed(p_on, frame(off, 1.5, tmp_path / "o.png")) is None        # captions off -> same as plain


def test_api_captions_endpoints(api, monkeypatch):
    client, app, con, tmp_path = api
    from autoshorts import transcribe
    src = _make_source(tmp_path / "data" / "clips" / "source" / "1.mp4")
    store.upsert_video(con, "https://kick.com/a/videos/x", title="V")
    cid = store.add_clip(con, "https://kick.com/a/videos/x", 101, 106, 3.0, "chat")
    f = tmp_path / "ready" / "d" / "c.mp4"
    f.parent.mkdir(parents=True)
    f.write_bytes(b"x")
    store.update_clip(con, cid, file=str(f), title="T", status="done")
    assert client.post(f"/api/clips/{cid}/transcribe", json={}).status_code == 409           # no source yet
    store.set_source(con, cid, str(src), 100.0, 108.0)
    monkeypatch.setattr(transcribe, "available", lambda: True)
    monkeypatch.setattr(transcribe, "transcribe_words", lambda media, language="tr": [{"word": "selam", "start": 1.0, "end": 1.4}])
    st = client.get("/api/captions/status").json()
    assert st["available"] is True and isinstance(st["cached"], bool)
    jid = client.post(f"/api/clips/{cid}/transcribe", json={}).json()["id"]
    for _ in range(100):
        j = next(x for x in app.jobs if x["id"] == jid)
        if j["status"] in ("done", "failed"):
            break
        threading.Event().wait(0.05)
    assert j["status"] == "done", j.get("error")
    assert client.get(f"/api/clips/{cid}/words").json()["words"] == [{"word": "selam", "start": 1.0, "end": 1.4}]
    monkeypatch.setattr(transcribe, "available", lambda: False)
    assert client.post(f"/api/clips/{cid}/transcribe", json={}).status_code == 409
    r = client.get(f"/api/clips/{cid}/editor").json()
    assert r["project"]["captions"] == {"enabled": False, "words": [], "style": r["project"]["captions"]["style"]}


def test_source_with_timestamp_offset_is_normalized_to_zero(env):
    import subprocess
    from autoshorts import editor
    tmp_path, con = env
    good = _make_source(tmp_path / "g.mp4")
    src = tmp_path / "data" / "clips" / "source" / "1.mp4"
    src.parent.mkdir(parents=True, exist_ok=True)
    # a section cut from the middle of a stream keeps its original timestamps: simulate with an offset
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(good), "-c", "copy", "-output_ts_offset", "1.2", str(src)], check=True)
    assert editor.probe(src)["start_time"] > 1.0
    store.upsert_video(con, "https://kick.com/a/videos/x", title="V")
    cid = store.add_clip(con, "https://kick.com/a/videos/x", 101, 106, 3.0, "chat")
    store.set_source(con, cid, str(src), 100.0, 108.0)
    info = editor.source_info(store.get_clip(con, cid))
    assert info["start_time"] < 0.1 and info["audio"] and 7.5 < info["duration"] < 8.5
    assert editor.probe(src)["start_time"] < 0.1


# ---------------------------------------------------------------- text layers
def test_text_layers_are_cleaned_and_wrapped():
    from autoshorts import texts
    ls = texts.clean_layers([{"text": "a‍b\rc", "size": 9, "x": 5, "start": 3, "end": 1, "bg": {"on": 1, "opacity": 9}}])
    assert ls[0]["text"] == "ab" + "c" and ls[0]["size"] == 0.2 and ls[0]["x"] == 1.0
    assert ls[0]["end"] >= ls[0]["start"] + 0.1 and ls[0]["bg"]["opacity"] == 1.0 and ls[0]["bg"]["on"] is True
    for bad in ({"font": "comic"}, {"color": "red"}):
        with pytest.raises(ValueError):
            texts.clean_layers([bad])
    r = texts.Renderer(texts.clean_layers([{"text": "çok uzun bir başlık metni burada yazıyor ve satır atlamalı mutlaka", "size": 0.09}])[0])
    lines = r.wrap()
    assert len(lines) >= 2 and all(r.font.getlength(" ".join(ln)) <= 1080 * texts.MAX_W + 1 for ln in lines)
    assert texts.runs("a😂b") == [(False, "a"), (True, "😂"), (False, "b")]
    img, x, y = texts.Renderer(texts.clean_layers([{"text": "Merhaba", "x": 0.5, "y": 0.2}])[0]).render()
    assert abs((x + img.size[0] / 2) - 540) < 3 and abs((y + img.size[1] / 2) - 384) < 3         # centred on its (x, y)


def test_export_shows_text_only_in_its_time_range(env):
    import subprocess
    from PIL import Image, ImageChops
    from autoshorts import editor
    tmp_path, con = env
    src = _make_source(tmp_path / "data" / "clips" / "source" / "1.mp4")
    store.upsert_video(con, "https://kick.com/a/videos/x", title="V")
    cid = store.add_clip(con, "https://kick.com/a/videos/x", 101, 107, 3.0, "chat")
    f = tmp_path / "ready" / "d" / "a_1.mp4"
    f.parent.mkdir(parents=True)
    f.write_bytes(b"x")
    store.update_clip(con, cid, file=str(f), title="T", description="D", status="done")
    store.set_source(con, cid, str(src), 100.0, 108.0)
    base = editor.default_project(store.get_clip(con, cid))
    base["trim"] = {"in": 1.0, "out": 7.0}                                   # 6 s clip
    base["audio"]["normalize"] = False

    def frame(path, t, out):
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", str(t), "-i", str(path), "-frames:v", "1", str(out)], check=True)
        return Image.open(out).convert("RGB")

    def changed(a, b):
        return ImageChops.difference(a, b).convert("L").point(lambda v: 255 if v > 40 else 0).getbbox()
    plain = editor.export_clip(con, config.load(), cid, base)
    p1, p4 = frame(plain, 1.0, tmp_path / "p1.png"), frame(plain, 4.0, tmp_path / "p4.png")
    layer = {"id": "a", "text": "Merhaba 😂", "start": 0.5, "end": 2.5, "x": 0.5, "y": 0.2, "size": 0.09, "bg": {"on": True}}
    out = editor.export_clip(con, config.load(), cid, {**base, "texts": [layer]})
    box = changed(p1, frame(out, 1.0, tmp_path / "o1.png"))                  # inside 0.5-2.5 s: text on screen
    assert box and box[1] > 0.2 * 1920 - 200 and box[3] < 0.2 * 1920 + 200 and 100 < box[0] and box[2] < 980
    assert changed(p4, frame(out, 4.0, tmp_path / "o4.png")) is None        # after it ended: identical to the plain export
    both = editor.export_clip(con, config.load(), cid, {**base, "texts": [layer, {**layer, "id": "b", "text": "İkinci", "y": 0.8, "start": 3.0, "end": 5.0}]})
    assert changed(p4, frame(both, 4.0, tmp_path / "b4.png")) is not None  # the second layer shows at 4 s
    assert changed(p1, frame(both, 1.0, tmp_path / "b1.png")) is not None


def test_api_rejects_bad_input_with_clear_errors(api, monkeypatch):
    client, app, con, tmp_path = api
    H = {"content-type": "application/json"}
    ok = {"url": "https://kick.com/a/videos/b"}
    cases = [
        ("/api/run", "{bad", 400), ("/api/run", "[1]", 400), ("/api/run", "", 400), ("/api/run", json.dumps({**ok, "n": "x"}), 400),
        ("/api/run", json.dumps({**ok, "n": 99999}), 400), ("/api/run", json.dumps({**ok, "n": 0}), 400),
        ("/api/run", json.dumps({**ok, "start_min": -3}), 400), ("/api/run", json.dumps({**ok, "at": 5}), 400),
        ("/api/run", json.dumps({"url": "javascript:alert(1)"}), 400), ("/api/config", "[1, 2]", 400),
        ("/api/config", json.dumps({"clips_per_video": "abc"}), 400), ("/api/config", json.dumps({"output_dir": "../../etc"}), 400), ("/api/sources", json.dumps({"url": "javascript:x"}), 400),
        ("/api/sources", json.dumps({**ok, "backfill": 999}), 400),
    ]
    for path, body, want in cases:
        r = client.post(path, content=body, headers=H)
        assert r.status_code == want, (path, body, r.status_code, r.text)
        assert "detail" in r.json()                                         # a message a person can read, not a stack trace
    assert client.get("/api/jobs/999/events").status_code == 404
    assert client.get("/../../etc/passwd").status_code in (200, 404) and b"root:" not in client.get("/../../etc/passwd").content
    assert client.get("/%2e%2e/%2e%2e/etc/passwd").content[:1] != b"r"
    # a valid run still queues (pipeline stubbed so no network)
    monkeypatch.setattr(pipeline, "process_video", lambda *a, **k: [])
    assert client.post("/api/run", content=json.dumps({**ok, "n": 5, "start_min": 10, "engine": "weird"}), headers=H).status_code == 200
