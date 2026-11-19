import json
import subprocess
import threading
import time
from pathlib import Path

import pytest

from createclip import cleanup, clipper, compile as compilemod, dupes, log as logmod, overlay, pipeline, review, titles


def vid(path: Path, size="180x320", dur=3, audio=True):
    path.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"testsrc=size={size}:rate=10:duration={dur}"]
    if audio:
        cmd += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={dur}"]
    subprocess.run(cmd + ["-pix_fmt", "yuv420p", "-c:a", "aac", str(path)], check=True)
    return path


def dur(p: Path) -> float:
    return float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(p)],
                                capture_output=True, text=True, check=True).stdout)


def vdur(p: Path) -> float:
    return float(subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v", "-show_entries", "stream=duration", "-of",
                                 "csv=p=0", str(p)], capture_output=True, text=True, check=True).stdout.split()[0])


def test_captions_keep_full_video_length(tmp_path):
    from createclip import captions
    v = vid(tmp_path / "v.mp4", size="180x320", dur=6)
    words = [{"word": "merhaba", "start": 0.5, "end": 0.9}, {"word": "dünya", "start": 1.0, "end": 1.4}]   # speech ends at 1.4 s
    out = captions.render(v, words, tmp_path / "o.mp4", {})
    assert abs(vdur(out) - 6) < 0.3


def project(root: Path, name, texts, status="approved", keep=False):
    jd = root / "output" / name
    recs = []
    for k, text in enumerate(texts, 1):
        vid(jd / "captioned" / f"c{k}.mp4")
        words = [{"word": w, "start": i * .2, "end": i * .2 + .15} for i, w in enumerate(text.split())]
        (jd / "words").mkdir(exist_ok=True)
        (jd / "words" / f"c{k}.json").write_text(json.dumps(words))
        recs.append({"i": k, "name": f"c{k}", "score": 10.0 * k, "start": 100.0 * k, "end": 103.0 * k, "status": status,
                     "src": f"captioned/c{k}.mp4", "captioned": f"captioned/c{k}.mp4", "plain": None,
                     "words": f"words/c{k}.json", "title": f"Başlık {k}", "description": "d", "tags": []})
    pipeline.save(jd, {"url": "https://youtu.be/x", "slug": "kanal", "title": "Yayın", "clips": recs, "defaults": {},
                       "next_i": len(texts) + 1, "keep": keep, "duration": 5000.0})
    return jd


# ---------------------------------------------------------------- dead air / loudness
def test_trim_dead_air_cuts_silent_head_and_tail():
    a, b = clipper.trim_dead_air(10.0, 40.0, [(9.8, 12.0), (37.5, 41.0)])
    assert a == pytest.approx(11.8) and b == pytest.approx(37.7)
    assert clipper.trim_dead_air(10.0, 40.0, [(20.0, 25.0)]) == (10.0, 40.0)      # silence in the middle is kept
    assert clipper.trim_dead_air(10.0, 40.0, [(10.0, 10.5)]) == (10.0, 40.0)      # short pause is kept


def test_trim_normalizes_loudness(tmp_path):
    src = vid(tmp_path / "a.mp4", dur=4)
    out = clipper.trim(src, 0, 3, tmp_path / "o.mp4")
    assert 2.5 < dur(out) < 3.5


# ---------------------------------------------------------------- duplicates
def test_similarity_and_marking():
    a = "bu araba gerçekten uçtu abi inanamıyorum buna yemin ederim ki uçtu"
    assert dupes.similarity(a, a) == 1.0
    assert dupes.similarity(a, "tamamen başka bir konu hakkında konuşuyoruz şu an burada hiç alakası yok") < 0.1
    assert dupes.similarity("kısa", "kısa") == 0.0
    rows = [{"project": "p", "i": 1, "score": 5, "start": 0, "end": 40, "text": ""},
            {"project": "p", "i": 2, "score": 9, "start": 10, "end": 50, "text": ""},       # overlaps #1, higher score
            {"project": "q", "i": 1, "score": 3, "start": 0, "end": 40, "text": a},
            {"project": "r", "i": 1, "score": 2, "start": 0, "end": 40, "text": a}]
    dupes.mark(rows)
    by = {(r["project"], r["i"]): r["dup_of"] for r in rows}
    assert by[("p", 2)] is None and by[("p", 1)] == "p#2" and by[("q", 1)] is None and by[("r", 1)] == "q#1"


# ---------------------------------------------------------------- chat overlay
def test_pick_filters_and_spaces_messages():
    msgs = [{"t": 100 + k * 0.3, "u": "u", "c": c} for k, c in enumerate(
        ["!komut", "[emote:1:KEKW]", "[emote:1:KEKW]", "x" * 80, "güzel", "bir şey"])]
    got = overlay.pick(msgs, 100, 110)
    assert [g[2] for g in got] == [":KEKW:", "güzel"]    # commands, long texts, repeats and too-close messages dropped
    assert overlay.clean_text("[emote:37226:KEKW] selam") == ":KEKW: selam"


def test_visible_states_cover_clip_and_limit_lines():
    items = [(k * 0.5, "u", f"m{k}") for k in range(8)]
    st = overlay.visible_states(items, 6.0)
    assert st[0][0] == 0.0 and st[-1][1] == 6.0 and all(len(v) <= overlay.LINES for *_, v in st)


def test_apply_overlay_and_voice_mix(tmp_path):
    jd = tmp_path / "p"
    base = vid(jd / "clips" / "b.mp4", size="360x640", dur=4)
    rec = {"start": 100.0, "end": 104.0, "reactions": True, "banner": "Bir başlık"}
    rows = [["i1", 101.0, "ali", "selam"], ["i2", 102.5, "veli", "harika"]]
    (jd / "chat.log.jsonl").write_text(json.dumps({"a": 0, "b": 9, "m": rows}) + "\n")
    out = overlay.apply(jd, {"duration": 500.0}, rec, base, jd / "clips" / "t.mp4")
    assert abs(dur(out) - 4) < 0.5
    assert abs(vdur(out) - 4) < 0.3                                  # video must not end where the overlay ends
    voice = jd / "v.m4a"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=300:duration=2", "-c:a", "aac", str(voice)], check=True)
    mixed = overlay.mix_voice(out, voice, jd / "clips" / "m.mp4")
    assert abs(dur(mixed) - 4) < 0.5
    rec2 = {"start": 100.0, "end": 104.0, "reactions": True, "banner": ""}
    (jd / "chat.log.jsonl").write_text("")
    with pytest.raises(ValueError):
        overlay.apply(jd, {"duration": 500.0}, rec2, base, jd / "clips" / "x.mp4")


# ---------------------------------------------------------------- cleanup / keep
def test_cleanup_skips_protected_and_recent_projects(tmp_path):
    old = project(tmp_path, "old-01", ["bir iki üç dört beş altı yedi sekiz dokuz on"])
    kept = project(tmp_path, "kept-01", ["bir iki üç dört beş altı yedi sekiz dokuz on"], keep=True)
    new = project(tmp_path, "new-01", ["bir iki üç dört beş altı yedi sekiz dokuz on"])
    for jd in (old, kept, new):
        (jd / "raw").mkdir()
        (jd / "raw" / "r.mp4").write_bytes(b"x" * 1000)
    import os
    past = time.time() - 40 * 86400
    for jd in (old, kept):
        for f in jd.rglob("*"):
            os.utime(f, (past, past))
    items = cleanup.plan(tmp_path, 14)
    assert [p.parent.name for p, _ in items] == ["old-01"]
    assert cleanup.apply(items) == 1000
    assert not (old / "raw").exists() and (kept / "raw" / "r.mp4").exists() and (new / "raw" / "r.mp4").exists()
    assert (old / "captioned" / "c1.mp4").exists()                 # finished clips are never removed


def test_cleanup_only_removes_rejected_clip_files(tmp_path):
    import os
    jd = project(tmp_path, "p-01", ["bir iki üç dört beş altı yedi sekiz dokuz on", "a b c d e f g h i j"], status="new")
    m = pipeline.load(jd)
    m["clips"][0]["status"] = "rejected"
    pipeline.save(jd, m)
    past = time.time() - 40 * 86400
    for f in jd.rglob("*"):
        os.utime(f, (past, past))
    cleanup.apply(cleanup.plan(tmp_path, 14))
    assert not (jd / "captioned" / "c1.mp4").exists() and (jd / "captioned" / "c2.mp4").exists()


def test_protected_project_cannot_be_deleted_via_api(tmp_path):
    from fastapi.testclient import TestClient
    from createclip.web.app import make_app
    project(tmp_path, "k-01", ["bir iki üç dört beş altı yedi sekiz dokuz on"], keep=True)
    c = TestClient(make_app(tmp_path))
    assert c.delete("/api/projects/k-01").status_code == 400
    assert (tmp_path / "output" / "k-01").exists()
    assert c.post("/api/projects/k-01/keep?keep=false").json()["keep"] is False
    assert c.delete("/api/projects/k-01").status_code == 200


# ---------------------------------------------------------------- titles
def test_titles_parse_and_errors(monkeypatch):
    m, rec = {"slug": "k", "title": "T"}, {"start": 0, "end": 30}
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(titles.TitleError, match="ANTHROPIC_API_KEY"):
        titles.generate(m, rec, "bir iki üç dört beş")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    reply = {"content": [{"type": "text", "text": 'tamam: {"basliklar":["A","B","C","D"],"aciklama":"x","etiketler":["#gta","vice"]}'}]}
    got = titles.generate(m, rec, "bir iki üç dört beş", post=lambda body, key: reply)
    assert got == {"titles": ["A", "B", "C"], "description": "x", "tags": ["gta", "vice"]}
    with pytest.raises(titles.TitleError):
        titles.generate(m, rec, "bir iki üç dört beş", post=lambda body, key: {"content": [{"type": "text", "text": "yok"}]})
    with pytest.raises(titles.TitleError, match="yeterli"):
        titles.generate(m, rec, "az", post=lambda b, k: reply)


# ---------------------------------------------------------------- cancel
def test_cancel_kills_running_subprocess():
    logmod.clear_cancel()
    err = []

    def work():
        try:
            logmod.run(["sleep", "30"], "uyku")
        except logmod.Cancelled as e:
            err.append(e)
    th = threading.Thread(target=work)
    t0 = time.time()
    th.start()
    time.sleep(0.5)
    logmod.request_cancel()
    th.join(5)
    logmod.clear_cancel()
    assert err and time.time() - t0 < 5


# ---------------------------------------------------------------- compilation
def test_compile_builds_countdown_video_and_credits(tmp_path):
    project(tmp_path, "a-01", ["bu araba gerçekten uçtu abi inanamıyorum buna", "tamamen farklı konuşma burada geçiyor şimdi"])
    r = compilemod.build(tmp_path, n=2)
    out = Path(r["path"])
    assert out.exists() and r["clips"] == 2
    assert dur(out) > 2 * 3 + 3 * compilemod.CARD_S - 1
    txt = Path(r["credits"]).read_text()
    assert "#2" in txt and "Yayın" in txt and "0:03:20" in txt
    with pytest.raises(ValueError):
        compilemod.build(tmp_path, n=2, status="rejected")
