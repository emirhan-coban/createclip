import urllib.error

import pytest

from createclip import autometa, gemini, moments, pipeline, review, settings, titles


def _http(code):
    return urllib.error.HTTPError("u", code, "x", {}, None)


def test_gemini_no_key(monkeypatch, tmp_path):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    settings.configure(tmp_path)
    assert not gemini.available()
    with pytest.raises(gemini.GeminiError, match="anahtar"):
        gemini.generate("x")


def test_gemini_retries_429_then_ok(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    calls, waits = [], []

    def post(url, body, key):
        calls.append(key)
        if len(calls) < 3:
            raise _http(429)
        return {"candidates": [{"content": {"parts": [{"text": '{"a":1}'}]}}]}

    assert gemini.generate("p", post=post, sleep=waits.append) == '{"a":1}'
    assert waits == [4, 8]


def test_gemini_gives_up_and_hard_errors(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    with pytest.raises(gemini.GeminiError, match="429"):
        gemini.generate("p", post=lambda *a: (_ for _ in ()).throw(_http(429)), sleep=lambda s: None, retries=1)
    n = []
    with pytest.raises(gemini.GeminiError, match="400"):
        gemini.generate("p", post=lambda *a: n.append(1) or (_ for _ in ()).throw(_http(400)), sleep=lambda s: None)
    assert len(n) == 1                                   # 400 is not retried
    with pytest.raises(gemini.GeminiError, match="boş"):
        gemini.generate("p", post=lambda *a: {"candidates": []})


def test_settings_roundtrip_hides_key(tmp_path, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    settings.configure(tmp_path)
    settings.update(gemini_key="AIzaSECRET1234", auto_watch=True, watch_hours=99)
    assert (tmp_path / "settings.json").stat().st_mode & 0o777 == 0o600
    pub = settings.public()
    assert pub["gemini_set"] and "SECRET" not in str(pub) and pub["watch_hours"] == 24.0 and pub["auto_watch"]
    assert gemini.key() == "AIzaSECRET1234"


def test_titles_prefer_gemini(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    txt = '{"basliklar":["A","B"],"aciklama":"x","etiketler":["t"]}'
    got = titles.generate({"slug": "s"}, {"start": 0, "end": 30}, "bir iki üç dört beş", gem=lambda p: txt)
    assert got["titles"] == ["A", "B"] and got["tags"] == ["t"]


def test_moments_parse_and_rank():
    assert moments.parse('x {"puan": 14, "neden": "komik"} y') == {"ai_score": 10, "ai_reason": "komik"}
    with pytest.raises(gemini.GeminiError):
        moments.parse("yok")
    assert moments.rank({"score": 10}) == 10
    assert moments.rank({"score": 10, "ai_score": 10}) > moments.rank({"score": 10, "ai_score": 2})


def test_autometa_fills_new_but_never_overwrites_edits(tmp_path):
    jd = tmp_path / "p"
    (jd / "words").mkdir(parents=True)
    import json
    (jd / "words" / "a.json").write_text(json.dumps([{"word": w, "start": i, "end": i + .5} for i, w in enumerate("bir iki üç dört beş".split())]))
    m = {"url": "u", "slug": "s", "title": "T", "clips": [
        {"i": 1, "start": 5, "end": 40, "words": "words/a.json", "src": "x.mp4"},
        {"i": 2, "start": 5, "end": 40, "words": "words/a.json", "src": "x.mp4", "title": "benim başlığım"}]}
    pipeline.save(jd, m)
    t = lambda m_, r, text: {"titles": ["Yeni", "Alt"], "description": "açıklama", "tags": ["a"]}
    sc = lambda *a: {"ai_score": 8, "ai_reason": "iyi"}
    assert autometa.fill(jd, titles_fn=t, score_fn=sc) == 2
    got = pipeline.load(jd)["clips"]
    assert got[0]["title"] == "Yeni" and got[0]["title_options"] == ["Yeni", "Alt"] and "Kaynak yayın" in got[0]["description"]
    assert got[1]["title"] == "benim başlığım" and got[1]["ai_score"] == 8
    assert autometa.fill(jd, titles_fn=t, score_fn=sc) == 0           # idempotent


def test_overlap_resume_rule():
    assert pipeline._overlaps(100, 160, 110, 170)          # mostly the same moment
    assert not pipeline._overlaps(100, 160, 150, 210)      # touches only 10 of 60 seconds
    assert not pipeline._overlaps(100, 160, 400, 460)
