import json

import pytest

from createclip import captions, clipper, kick, layout, peaks, pipeline, transcribe


def _msgs(burst_at, users, emote=False, per_user=1):
    out = []
    for k in range(users):
        for j in range(per_user):
            out.append({"t": burst_at + (k % 8) + j * 0.1, "u": f"u{k}",
                        "c": "[emote:1:x]" if emote else "gelsin"})
    return out


def test_parse_url():
    assert kick.parse_url("https://kick.com/abc/videos/01a1c282-b788-7c55-b2d5-76547c65c8d0") == (
        "abc", "01a1c282-b788-7c55-b2d5-76547c65c8d0")
    with pytest.raises(kick.KickError):
        kick.parse_url("https://example.com")


def test_text_burst_beats_emote_burst():
    base = [{"t": t, "u": f"b{t}", "c": "x"} for t in range(0, 3600, 20)]
    msgs = base + _msgs(1000, 40, emote=True) + _msgs(2000, 40, emote=False)
    found = peaks.find_peaks(msgs, 3600, n=2)
    assert abs(found[0].time - 2000) <= 20
    assert found[0].score > found[1].score


def test_intro_skipped_and_spacing():
    msgs = _msgs(30, 80) + _msgs(1000, 50) + _msgs(1030, 50)
    found = peaks.find_peaks(msgs, 3600, n=3)
    assert all(p.time >= 120 for p in found)
    ts = sorted(p.time for p in found)
    assert all(b - a >= 90 for a, b in zip(ts, ts[1:]))


def test_window_bounds():
    for p in peaks.find_peaks(_msgs(1000, 60), 3600, n=1):
        assert 25 <= p.end - p.start <= 60


def test_score_series_peaks_for_audio_fallback():
    raw = [1.0] * 360
    raw[200] = raw[201] = 9.0          # loud moment at 2000 s
    found = peaks.peaks_from_scores(peaks.smooth(raw), 3600, n=1)
    assert abs(found[0].time - 2000) <= 20


def test_turkish_case_and_mask():
    assert captions.tr_upper("sevgilin ışık") == "SEVGİLİN IŞIK"
    assert captions.mask_word("siktim") == "s*****"
    assert captions.mask_word("sıkıntı") == "sıkıntı"
    assert captions.mask_word("merhaba") == "merhaba"


def test_apply_text_edit_keeps_timing():
    w = [{"word": "a", "start": 0, "end": 1}, {"word": "b", "start": 1, "end": 2}]
    assert [x["word"] for x in transcribe.apply_text_edit(w, "x y")] == ["x", "y"]
    r = transcribe.apply_text_edit(w, "bir iki üç")
    assert r[0]["start"] == 0 and abs(r[-1]["end"] - 2) < 1e-6 and len(r) == 3


def test_snap_moves_to_nearest_pause_within_window():
    sil = [(10.0, 10.6), (20.0, 21.0)]
    assert clipper.snap(11.0, sil) == pytest.approx(10.3)
    assert clipper.snap(15.0, sil, window=3) == 15.0       # nothing within 3 s -> unchanged
    assert clipper.snap(19.0, sil, lo=0, hi=19.5) == 19.0  # pause outside allowed range ignored


def test_prompt_echo_is_stripped():
    prompt = "Kick yayını, yayıncı abc. Sohbette geçen kelimeler: gelsin, tamam, güzel."
    w = [{"word": x, "start": i, "end": i + 1} for i, x in enumerate(
        "merhaba Sohbette geçen kelimeler: gelsin selam".split())]
    assert [x["word"] for x in transcribe.strip_prompt_echo(w, prompt)] == ["merhaba", "selam"]


def test_no_prompt_by_default_and_vocab_is_opt_in():
    assert transcribe.build_prompt("") == ""
    assert transcribe.build_prompt("Berk, Derbeder") == "Berk, Derbeder."


def test_clean_words_drops_zero_length_and_loops():
    loop = [{"word": t, "start": 24.0 + i * 0.3, "end": 24.2 + i * 0.3}
            for i, t in enumerate(["Nefes.", "Yurdaer"] * 4)]
    good = [{"word": "merhaba", "start": 40.0, "end": 40.5}, {"word": "sıfır", "start": 41.0, "end": 41.0}]
    out = transcribe.clean_words(loop + good)
    assert [w["word"] for w in out] == ["merhaba"]


def test_parse_time():
    assert clipper.parse_time("1:44:50") == 6290
    assert clipper.parse_time("104:50") == 6290
    assert clipper.parse_time("6290") == 6290


def test_crop_box_stays_inside_frame_and_keeps_aspect():
    for cell in ({"x": 0, "y": 0, "zoom": 1}, {"x": 1, "y": 1, "zoom": 3}, {"x": .5, "y": .5, "zoom": 1}):
        for asp in (1080 / 1920, 1080 / 960):
            w, h, x, y = layout.crop_box(1280, 720, asp, cell)
            assert x >= 0 and y >= 0 and x + w <= 1280 and y + h <= 720
            assert abs(w / h - asp) < 0.02


def test_filter_graphs_build():
    assert "vstack" in layout.filter_graph({"mode": "stack", "cells": layout.default_cells("stack")}, 1280, 720)
    assert "crop=" in layout.filter_graph({"mode": "crop", "cells": layout.default_cells("crop")}, 1280, 720)
    assert "boxblur" in layout.filter_graph({"mode": "blur", "cells": []}, 1280, 720)
    with pytest.raises(ValueError):
        layout.filter_graph({"mode": "x", "cells": []}, 1280, 720)


def test_update_clip_validates_and_deletes(tmp_path):
    m = {"url": "u", "duration": 1000.0, "defaults": {"captions": False, "keep_plain": True, "style": {},
         "layout": {"mode": "none", "cells": []}, "max_height": 720, "snap": True, "min_len": 25, "max_len": 60},
         "prompt": "", "candidates": [], "next_i": 2,
         "clips": [{"i": 1, "name": "c", "start": 100, "end": 140, "raw_start": 90, "raw_end": 150, "raw": "raw.mp4",
                    "src": "src.mp4", "captions": False, "style": {}, "layout": {"mode": "none", "cells": []},
                    "words": None, "srt": None, "base": "src.mp4", "plain": "src.mp4", "captioned": None}]}
    pipeline.save(tmp_path, m)
    with pytest.raises(ValueError):
        pipeline.update_clip(tmp_path, 1, {"start": 100, "end": 102})       # too short
    with pytest.raises(ValueError):
        pipeline.update_clip(tmp_path, 1, {"layout": {"mode": "weird"}})
    (tmp_path / "src.mp4").write_text("x")
    pipeline.delete_clip(tmp_path, 1)
    assert pipeline.load(tmp_path)["clips"] == [] and not (tmp_path / "src.mp4").exists()


def test_caption_states_never_overlap():
    from createclip.captions import build_states
    words = [{"word": "a", "start": 1.0, "end": 1.4}, {"word": "b,", "start": 1.5, "end": 2.5},
             {"word": "c", "start": 2.2, "end": 2.6},      # starts before the previous word ended
             {"word": "d", "start": 2.7, "end": 3.0}]
    st = build_states(words, 3, 0.0)
    for (s1, e1, *_), (s2, e2, *_) in zip(st, st[1:]):
        assert e1 <= s2 + 1e-9 and s1 < e1
    assert abs(st[0][0] - 1.0) < 1e-9
    shifted = build_states(words, 3, -0.08)
    assert abs(shifted[0][0] - 0.92) < 1e-9


def test_preview_and_style_options():
    from createclip import captions
    im = captions.preview({"font": "poppins", "stroke": 2.0, "upper": False, "size": 0.06}, 640, 360, "merhaba dünya")
    assert im.size == (640, 360)
    import pytest
    with pytest.raises(ValueError):
        captions.preview({"font": "yok"}, 640, 360, "x")


def test_project_endpoint_sorts_by_score(tmp_path):
    import json
    from fastapi.testclient import TestClient
    from createclip.web.app import make_app
    d = tmp_path / "output" / "p-1"
    d.mkdir(parents=True)
    clips = [{"i": i, "score": s, "words": None} for i, s in [(1, 0.0), (2, 5.1), (3, 9.7), (4, 2.0)]]
    (d / "manifest.json").write_text(json.dumps({"title": "t", "slug": "p", "clips": clips, "candidates": []}))
    r = TestClient(make_app(tmp_path)).get("/api/projects/p-1").json()
    assert [c["i"] for c in r["clips"]] == [3, 2, 4, 1]
    assert [c["rank"] for c in r["clips"]] == [1, 2, 3, 4]


def test_cli_parser_builds(capsys):
    import pytest
    from createclip.cli import main
    for args in (["--help"], ["run", "--help"], ["serve", "--help"]):
        with pytest.raises(SystemExit) as e:
            main(args)
        assert e.value.code == 0


def test_start_at_skips_opening_and_baseline():
    # crowded opening burst at 200 s, then a quieter stream with one real burst at 1500 s
    base = [{"t": t, "u": f"b{t}", "c": "x"} for t in range(0, 3600, 20)]
    msgs = base + _msgs(200, 80) + _msgs(1500, 30)
    assert abs(peaks.find_peaks(msgs, 3600, n=1)[0].time - 200) <= 20
    p = peaks.find_peaks(msgs, 3600, n=1, skip_start=600)[0]
    assert abs(p.time - 1500) <= 20 and p.start >= 600
