import json
import threading
import time
from pathlib import Path

import pytest

from createclip import captions, clipper, encode, layout, pipeline, render, transcribe
from createclip.log import Cancelled


# ---------------------------------------------------------------- filter graphs
@pytest.mark.parametrize("mode", ["none", "blur", "crop", "stack"])
def test_fused_graph_is_well_formed(mode):
    lay = {"mode": mode, "cells": layout.default_cells(mode)}
    g = render.graph(lay, 1280, 720, 1200)
    assert g.startswith("[0:v]fps=30[f];[f]")             # frame-rate cap comes first
    assert g.count("[lay]") == 2 and g.endswith("overlay=0:1200:shortest=1:format=auto[v]")
    assert "[1:v]fps=30,format=rgba[o]" in g
    plain = layout.timed_graph(lay, 1280, 720)
    assert plain.endswith("[v]") and "[lay]" not in plain


def test_no_captions_graph_has_no_second_input():
    assert "[1:v]" not in render.graph({"mode": "blur", "cells": []}, 1280, 720, None)


def test_encoder_args_switch(monkeypatch):
    monkeypatch.setattr(encode, "ENCODER", "x264")
    assert "libx264" in encode.video_args() and "veryfast" in encode.video_args()
    monkeypatch.setattr(encode, "ENCODER", "videotoolbox")
    assert "h264_videotoolbox" in encode.video_args() and "-crf" not in encode.video_args()


# ---------------------------------------------------------------- caption band
def test_caption_band_is_small_and_even():
    st = {**captions.DEFAULT_STYLE}
    full = captions._Drawer(1080, 1920, st)
    band = captions._Drawer(1080, 1920, st, band=True)
    assert full.bh == 1920 and full.y0 == 0                 # preview() keeps whole-frame images
    assert band.y0 % 2 == 0 and band.bh % 2 == 0 and 0 < band.bh < 400
    assert band.y0 <= band.ypos and band.ypos + band.size < band.y0 + band.bh   # text fits inside the band
    img = band.draw([{"word": "MERHABA", "start": 0, "end": 1}], 0)
    assert img.size == (1080, band.bh)


def test_prepare_writes_band_list_padded_to_duration(tmp_path):
    words = [{"word": "bir", "start": 1.0, "end": 1.4}, {"word": "iki", "start": 1.5, "end": 1.9}]
    lst, y0 = captions.prepare(tmp_path, 1080, 1920, words, None, 10.0)
    txt = lst.read_text()
    durs = [float(x.split()[1]) for x in txt.splitlines() if x.startswith("duration")]
    assert abs(sum(durs) - 10.0) < 0.05 and y0 > 0         # padded to the full clip length
    with pytest.raises(RuntimeError):
        captions.prepare(tmp_path, 1080, 1920, [], None, 5.0)


# ---------------------------------------------------------------- draft -> render state machine
def _manifest(tmp_path, n=0):
    jd = tmp_path / "p"
    jd.mkdir()
    m = {"url": "u", "slug": "s", "title": "T", "duration": 3600, "next_i": 1, "clips": [], "candidates": [],
         "defaults": {"captions": True, "keep_plain": False, "style": {}, "layout": {"mode": "blur", "cells": []},
                      "max_height": 720, "snap": True, "min_len": 25, "max_len": 60}}
    pipeline.save(jd, m)
    return jd, m


def _fake_fetch(delay=0.0, fail_at=None):
    def fetch(url, start, end, raw, duration, max_height=720, snap_cuts=True, min_len=20, max_len=75):
        time.sleep(delay)
        if fail_at is not None and abs(start - fail_at) < 1:
            raise RuntimeError("ağ")
        raw.parent.mkdir(parents=True, exist_ok=True)
        raw.write_bytes(b"x")
        return start + 1, end - 1, max(0, start - 10), end + 10
    return fetch


def test_scout_many_creates_ordered_drafts_in_parallel(tmp_path, monkeypatch):
    jd, m = _manifest(tmp_path)
    monkeypatch.setattr(clipper, "fetch_raw", _fake_fetch(delay=0.2, fail_at=500))
    plan = [(100 + 100 * k, 160 + 100 * k, 10 - k) for k in range(6)]        # k=4 starts at 500 -> fails
    t0 = time.time()
    recs = pipeline.scout_many(jd, m, plan, pipeline._style_layout(m), lambda *a, **k: None)
    assert time.time() - t0 < 0.2 * 6 * 0.7                 # clearly overlapped, not sequential
    assert [r["score"] for r in recs] == [10, 9, 8, 7, 5]   # plan order, failed moment skipped
    assert all(r["status"] == "draft" and r["src"] is None for r in recs)
    saved = pipeline.load(jd)
    assert len(saved["clips"]) == 5 and len({c["i"] for c in saved["clips"]}) == 5
    assert all((jd / c["raw"]).exists() for c in saved["clips"])


def test_scout_all_failing_raises(tmp_path, monkeypatch):
    jd, m = _manifest(tmp_path)
    monkeypatch.setattr(clipper, "fetch_raw", _fake_fetch(fail_at=100))
    with pytest.raises(RuntimeError, match="indirilemedi"):
        pipeline.scout_many(jd, m, [(100, 160, 1)], pipeline._style_layout(m), lambda *a, **k: None)


def test_render_many_only_touches_picked_and_survives_a_failure(tmp_path, monkeypatch):
    jd, m = _manifest(tmp_path)
    monkeypatch.setattr(clipper, "fetch_raw", _fake_fetch())
    recs = pipeline.scout_many(jd, m, [(100 * k, 100 * k + 60, k) for k in range(1, 5)], pipeline._style_layout(m), lambda *a, **k: None)
    monkeypatch.setattr(clipper, "trim", lambda raw, a, b, out: (out.parent.mkdir(parents=True, exist_ok=True), out.write_bytes(b"y")))

    def produce(jd_, m_, rec, *a, **k):
        if rec["i"] == 2:
            raise RuntimeError("kodlama patladı")
        rec["captioned"] = f"captioned/{rec['name']}.mp4"
    monkeypatch.setattr(pipeline, "_produce", produce)
    monkeypatch.setattr("createclip.autometa.fill", lambda *a, **k: 0)
    done = pipeline.render_many(jd, m, [r for r in recs if r["i"] in (1, 2, 3)], lambda *a, **k: None)
    assert sorted(r["i"] for r in done) == [1, 3]
    st = {c["i"]: c["status"] for c in pipeline.load(jd)["clips"]}
    assert st == {1: "new", 2: "draft", 3: "new", 4: "draft"}      # failed + unpicked stay drafts


def test_whisper_runs_one_at_a_time(tmp_path, monkeypatch):
    jd, m = _manifest(tmp_path)
    monkeypatch.setattr(clipper, "fetch_raw", _fake_fetch())
    recs = pipeline.scout_many(jd, m, [(100 * k, 100 * k + 60, k) for k in range(1, 7)], pipeline._style_layout(m), lambda *a, **k: None)
    monkeypatch.setattr(clipper, "trim", lambda raw, a, b, out: (out.parent.mkdir(parents=True, exist_ok=True), out.write_bytes(b"y")))
    live, peak = [0], [0]
    lock = threading.Lock()

    def fake_words(src, prompt=""):
        with lock:
            live[0] += 1
            peak[0] = max(peak[0], live[0])
        time.sleep(0.05)
        with lock:
            live[0] -= 1
        return [{"word": "merhaba", "start": 0.0, "end": 0.4}]
    monkeypatch.setattr(transcribe, "transcribe_words", fake_words)
    monkeypatch.setattr(captions, "probe_size", lambda p: (1280, 720))
    monkeypatch.setattr(render, "final", lambda src, out, lay, words, style: (out.parent.mkdir(parents=True, exist_ok=True), out.write_bytes(b"z"), out)[2])
    monkeypatch.setattr("createclip.autometa.fill", lambda *a, **k: 0)
    done = pipeline.render_many(jd, m, recs, lambda *a, **k: None)
    assert len(done) == 6 and peak[0] == 1                       # never two speech-model runs at once
    c = pipeline.load(jd)["clips"][0]
    assert c["status"] == "new" and c["captioned"].startswith("captioned/") and c["base"] is None and c["plain"] is None


def test_cancel_stops_render(tmp_path, monkeypatch):
    jd, m = _manifest(tmp_path)
    monkeypatch.setattr(clipper, "fetch_raw", _fake_fetch())
    recs = pipeline.scout_many(jd, m, [(100, 160, 1), (300, 360, 2)], pipeline._style_layout(m), lambda *a, **k: None)
    monkeypatch.setattr(pipeline, "render_one", lambda *a, **k: (_ for _ in ()).throw(Cancelled("iptal")))
    with pytest.raises(Cancelled):
        pipeline.render_many(jd, m, recs, lambda *a, **k: None)


def test_drop_drafts_removes_raw_only_for_drafts(tmp_path, monkeypatch):
    jd, m = _manifest(tmp_path)
    monkeypatch.setattr(clipper, "fetch_raw", _fake_fetch())
    a, b = pipeline.scout_many(jd, m, [(100, 160, 2), (300, 360, 1)], pipeline._style_layout(m), lambda *a, **k: None)
    m2 = pipeline.load(jd)
    m2["clips"][1]["status"] = "new"
    pipeline.save(jd, m2)
    pipeline.drop_drafts(jd)
    left = pipeline.load(jd)["clips"]
    assert [c["i"] for c in left] == [b["i"]] and (jd / b["raw"]).exists() and not (jd / a["raw"]).exists()


def test_pipeline_module_has_no_duplicate_definitions():
    import ast
    names = [n.name for n in ast.parse(Path(pipeline.__file__).read_text()).body if isinstance(n, (ast.FunctionDef, ast.ClassDef))]
    assert len(names) == len(set(names)), [n for n in names if names.count(n) > 1]


def test_run_scouts_all_but_renders_only_n(tmp_path, monkeypatch):
    from createclip import kick, sources
    vod = kick.Vod(vod_id="01234567-89ab-cdef-0123-456789abcdef", slug="kanal", title="T", duration=7200.0, start_ts=0, channel_id=1,
                   url="https://kick.com/kanal/videos/01234567-89ab-cdef-0123-456789abcdef")
    monkeypatch.setattr(sources, "vod_info", lambda url: vod)
    monkeypatch.setattr(clipper, "fetch_raw", _fake_fetch())
    monkeypatch.setattr(clipper, "trim", lambda raw, a, b, out: (out.parent.mkdir(parents=True, exist_ok=True), out.write_bytes(b"y")))
    rendered = []
    monkeypatch.setattr(pipeline, "_produce", lambda jd, m, rec, *a, **k: rendered.append(rec["i"]))
    monkeypatch.setattr("createclip.autometa.fill", lambda *a, **k: 0)
    o = pipeline.Options(n=2, drafts=3, at=["0:10:00", "0:20:00", "0:30:00"])        # manual: all rendered
    m = pipeline.run(vod.url, tmp_path, o)
    assert len(m["clips"]) == 3 and sorted(rendered) == [1, 2, 3]


def test_speed_switch_changes_priority_threads_and_workers(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from createclip import log as logmod, settings
    from createclip.web.app import make_app
    monkeypatch.delenv("CREATECLIP_FAST", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    c = TestClient(make_app(tmp_path))
    assert c.get("/api/settings").json()["fast"] is False and logmod.GENTLE is True
    assert "-threads" in encode.video_args()
    c.put("/api/settings", json={"fast": True})
    assert c.get("/api/settings").json()["fast"] is True and logmod.GENTLE is False
    assert "-threads" not in encode.video_args()
    c.put("/api/settings", json={"fast": False})
    assert logmod.GENTLE is True
    logmod.set_gentle(True)


def _make(tmp_path, name, video=True):
    import subprocess
    p = tmp_path / name
    cmd = ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "sine=d=1"]
    if video:
        cmd += ["-f", "lavfi", "-i", "testsrc=s=64x64:d=1", "-pix_fmt", "yuv420p"]
    subprocess.run(cmd + [str(p)], check=True, stdin=subprocess.DEVNULL)
    return p


def test_has_video_detects_audio_only(tmp_path):
    assert clipper.has_video(_make(tmp_path, "av.mp4")) and not clipper.has_video(_make(tmp_path, "a.m4a", video=False))


def test_kick_gets_longer_probe_others_do_not():
    assert "-probesize" in " ".join(clipper._kick_args("https://kick.com/x/videos/1"))
    assert clipper._kick_args("https://www.youtube.com/watch?v=1") == []


def test_audio_only_download_is_retried_then_fails(tmp_path, monkeypatch):
    import subprocess
    calls = []

    def fake_run(cmd, what, timeout=None, **kw):
        calls.append(what)
        _make(tmp_path / "raw", "c.mp4", video=False) if (tmp_path / "raw").mkdir(exist_ok=True) is None else None
        return subprocess.CompletedProcess(cmd, 0, "", "")
    monkeypatch.setattr(clipper, "run", fake_run)
    with pytest.raises(RuntimeError, match="görüntü akışı yok"):
        clipper.download_range("https://kick.com/x/videos/1", 100, 160, tmp_path / "raw" / "c.mp4")
    assert len(calls) == 3


def test_backfill_redownloads_videoless_raw_and_rebuilds_preview(tmp_path, monkeypatch):
    jd, m = _manifest(tmp_path)
    (jd / "raw").mkdir()
    (jd / "preview").mkdir()
    bad_raw = _make(jd / "raw", "r.mp4", video=False)
    bad_prev = _make(jd / "preview", "p.mp4", video=False)
    m["clips"] = [{"i": 1, "name": "c1", "status": "draft", "start": 110.0, "end": 150.0, "raw_start": 100.0, "raw_end": 160.0,
                   "raw": "raw/r.mp4", "preview": "preview/p.mp4", "score": 1}]
    pipeline.save(jd, m)
    fetched = []

    def fake_dl(url, s, e, out, h=720):
        fetched.append((s, e))
        _make(out.parent, out.name, video=True)
        return out
    monkeypatch.setattr(clipper, "download_range", fake_dl)
    monkeypatch.setattr(clipper, "make_preview", lambda raw, a, b, out: _make(out.parent, out.name, video=True))
    assert pipeline.backfill_previews(jd) == 1
    assert fetched == [(100.0, 160.0)]
    assert clipper.has_video(jd / "raw/r.mp4") and clipper.has_video(jd / "preview/c1.mp4")
    assert pipeline.load(jd)["clips"][0]["preview"] == "preview/c1.mp4"
    assert pipeline.backfill_previews(jd) == 0                       # healthy drafts are left alone
