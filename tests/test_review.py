import json
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from createclip import pipeline, review
from createclip.web.app import make_app


def make_project(root: Path, name="kanal-01abcdef", clips=2, portrait=True):
    jd = root / "output" / name
    (jd / "captioned").mkdir(parents=True)
    (jd / "words").mkdir()
    size = "180x320" if portrait else "320x180"
    recs = []
    for k in range(1, clips + 1):
        v = jd / "captioned" / f"c{k}.mp4"
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"testsrc=size={size}:rate=10:duration=3",
                        "-pix_fmt", "yuv420p", str(v)], check=True)
        (jd / "words" / f"c{k}.json").write_text(json.dumps(
            [{"word": w, "start": i * .3, "end": i * .3 + .2} for i, w in enumerate(
                "Vay be inanılmıyor. Bu çok güzel güzel güzel oldu".split())]))
        recs.append({"i": k, "name": f"c{k}", "score": 10.0 * k, "start": 100.0 * k, "end": 103.0 * k,
                     "src": f"captioned/c{k}.mp4", "captioned": f"captioned/c{k}.mp4", "plain": None,
                     "words": f"words/c{k}.json"})
    pipeline.save(jd, {"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ", "slug": "kanal", "title": "Büyük yayın",
                       "clips": recs, "defaults": {}, "next_i": clips + 1})
    return jd


def test_inbox_is_score_sorted_with_suggested_meta(tmp_path):
    make_project(tmp_path)
    rows = review.inbox(tmp_path)
    assert [r["i"] for r in rows] == [2, 1]                      # best score first
    r = rows[1]
    assert r["title"].startswith("Vay be inanılmıyor") and "güzel" in r["tags"]
    assert "dQw4w9WgXcQ" in r["description"] and "0:01:40" in r["description"]
    assert r["video"] == "/files/kanal-01abcdef/captioned/c1.mp4"


def test_review_status_and_edit_persist(tmp_path):
    jd = make_project(tmp_path)
    review.review(jd, 1, status="approved", title="Yeni başlık", tags=["#a", " b "])
    assert [r["i"] for r in review.inbox(tmp_path, "new")] == [2]
    ap = review.inbox(tmp_path, "approved")
    assert ap[0]["title"] == "Yeni başlık" and ap[0]["tags"] == ["a", "b"]
    with pytest.raises(ValueError):
        review.review(jd, 1, status="bogus")


def test_export_pack_files_and_warnings(tmp_path):
    jd = make_project(tmp_path, portrait=False)
    out = review.export_pack(tmp_path, jd, 1, "shorts")
    d = Path(out["dir"])
    assert (d / "video.mp4").is_file() and (d / "kapak.jpg").is_file()
    assert "Vay be" in (d / "baslik.txt").read_text() and "#" in (d / "aciklama.txt").read_text()
    assert any("dikey" in w for w in out["warnings"])            # landscape test video
    assert review.inbox(tmp_path, "all")[1]["exported"]["platform"] == "shorts"
    with pytest.raises(ValueError):
        review.export_pack(tmp_path, jd, 1, "myspace")


def test_web_inbox_review_export_and_queue(tmp_path):
    make_project(tmp_path)
    c = TestClient(make_app(tmp_path))
    assert len(c.get("/api/inbox").json()) == 2 and "Hazır klipler" in c.get("/inbox").text
    assert c.post("/api/projects/kanal-01abcdef/clips/1/review", json={"status": "approved"}).status_code == 200
    assert c.post("/api/projects/kanal-01abcdef/clips/9/review", json={"status": "approved"}).status_code == 404
    r = c.post("/api/projects/kanal-01abcdef/clips/1/export", json={"platform": "tiktok"})
    assert r.status_code == 200 and Path(r.json()["dir"]).is_dir()
    assert c.post("/api/channels", json={"url": "https://example.com/x"}).status_code == 400
    assert c.post("/api/channels", json={"url": "kick.com/abc"}).status_code == 200
    assert c.post("/api/channels", json={"url": "kick.com/abc"}).status_code == 400     # duplicate
    assert c.get("/api/channels").json()[0]["url"] == "https://kick.com/abc/videos"
    assert c.get("/api/queue").json() == []
    assert c.post("/api/queue/nope/retry").status_code == 404
    assert c.delete("/api/channels", params={"url": "kick.com/abc"}).json()["ok"]
