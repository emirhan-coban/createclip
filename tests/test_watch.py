from pathlib import Path

import pytest

from createclip import pipeline, watch


def vod(i, mins=120, ts=None):
    return {"id": str(i), "url": f"https://kick.com/k/videos/{i}", "title": f"yayin {i}", "duration": mins * 60.0,
            "ts": ts or 1000 + i}


def test_normalize_channel():
    assert watch.normalize_channel("https://kick.com/husam") == "https://kick.com/husam/videos"
    assert watch.normalize_channel("kick.com/husam/videos/") == "https://kick.com/husam/videos"
    assert watch.normalize_channel("https://www.youtube.com/@valorant") == "https://www.youtube.com/@valorant/streams"
    assert watch.normalize_channel("@valorant") == "https://www.youtube.com/@valorant/streams"
    with pytest.raises(ValueError):
        watch.normalize_channel("https://example.com/x")


def test_first_scan_backfills_only_newest_then_queues_new(tmp_path):
    watch.add_channel(tmp_path, "kick.com/k", backfill=1, min_minutes=30)
    vods = [vod(3), vod(2), vod(1)]                      # newest first, like yt-dlp
    added = watch.scan(tmp_path, lambda url: vods)
    assert [i["url"].rsplit("/", 1)[1] for i in added] == ["3"]          # only the newest on first sight
    assert watch.scan(tmp_path, lambda url: vods) == []                  # nothing new
    vods.insert(0, vod(4))
    assert [i["url"].rsplit("/", 1)[1] for i in watch.scan(tmp_path, lambda url: vods)] == ["4"]


def test_short_streams_are_skipped_but_remembered(tmp_path):
    watch.add_channel(tmp_path, "kick.com/k", backfill=5, min_minutes=60)
    assert watch.scan(tmp_path, lambda url: [vod(1, mins=20), vod(2, mins=90)]) and \
        [i["title"] for i in watch.queue(tmp_path)] == ["yayin 2"]
    assert watch.scan(tmp_path, lambda url: [vod(1, mins=20), vod(2, mins=90)]) == []


def test_oldest_processed_first_and_done(tmp_path):
    watch.add_channel(tmp_path, "kick.com/k", backfill=5)
    watch.scan(tmp_path, lambda url: [vod(3), vod(2), vod(1)])
    order = []

    def runner(url, root, opts, progress):
        order.append(url.rsplit("/", 1)[1])
        return {"dir": str(Path(root) / "output" / f"p{url[-1]}")}
    while watch.process_one(tmp_path, runner=runner):
        pass
    assert order == ["1", "2", "3"]
    assert {i["status"] for i in watch.queue(tmp_path)} == {"done"}


def test_audio_confirmation_and_retry_limits(tmp_path):
    watch.add_channel(tmp_path, "kick.com/k", backfill=1)
    watch.scan(tmp_path, lambda url: [vod(1)])

    def no_chat(url, root, opts, progress):
        if not opts.audio_ok:
            raise pipeline.NeedsAudioConfirm("Sohbet alınamadı", 500)
        return {"dir": str(tmp_path / "output" / "p1")}
    it = watch.process_one(tmp_path, runner=no_chat)
    assert it["status"] == "confirm_audio" and it["est_mb"] == 500
    assert watch.process_one(tmp_path, runner=no_chat) is None          # waits for the user, not retried blindly
    watch.confirm_audio(tmp_path, it["id"])
    assert watch.process_one(tmp_path, runner=no_chat)["status"] == "done"

    watch.scan(tmp_path, lambda url: [vod(2), vod(1)])

    def boom(*a, **k):
        raise RuntimeError("ağ")
    last = None
    for _ in range(watch.MAX_ATTEMPTS):
        last = watch.process_one(tmp_path, runner=boom)
    assert last["status"] == "error" and "ağ" in last["error"]
    watch.retry(tmp_path, last["id"])
    assert watch.queue(tmp_path)[-1]["status"] == "pending"


def test_running_items_recover_after_crash(tmp_path):
    watch.add_channel(tmp_path, "kick.com/k", backfill=1)
    watch.scan(tmp_path, lambda url: [vod(1)])
    assert watch.next_pending(tmp_path)["status"] == "running"
    watch.recover_running(tmp_path)
    assert watch.queue(tmp_path)[0]["status"] == "pending"


def test_options_from_channel(tmp_path):
    watch.add_channel(tmp_path, "kick.com/k", options={"n": 3, "max_height": 1080, "bogus": 1})
    watch.scan(tmp_path, lambda url: [vod(1)])
    o = watch.options_for(tmp_path, watch.queue(tmp_path)[0])
    assert o.n == 3 and o.max_height == 1080 and not o.audio_ok


def test_save_profile_applies_to_next_queue_items(tmp_path):
    watch.add_channel(tmp_path, "kick.com/Husam", options={"n": 3})
    ch = watch.save_profile(tmp_path, "husam", {"font": "poppins", "size": 0.06},
                            {"mode": "stack", "cells": [[0, 0, 1, 1]]}, {"max_height": 1080, "snap": False, "bogus": 1})
    assert ch["options"]["style"]["font"] == "poppins" and ch["options"]["max_height"] == 1080 and "bogus" not in ch["options"]
    watch.scan(tmp_path, lambda url: [vod(1)])
    o = watch.options_for(tmp_path, watch.queue(tmp_path)[0])
    assert o.n == 3 and o.layout["mode"] == "stack" and o.style["font"] == "poppins" and o.snap is False
    with pytest.raises(KeyError):
        watch.save_profile(tmp_path, "baskasi", {}, {}, {})


def test_doctor_reports_and_flags_failures(tmp_path, monkeypatch, capsys):
    from createclip import doctor
    monkeypatch.setattr(doctor, "_ver", lambda cmd: None if cmd[0] == "ffmpeg" else "x 1.0")
    rows = doctor.checks(tmp_path, net=False)
    assert ("HATA", "ffmpeg") == rows[0][:2] and doctor.report(tmp_path, net=False) == 1
    assert "ffmpeg" in capsys.readouterr().out
