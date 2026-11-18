import calendar
import random
import time

import pytest

from createclip import kick, peaks

BASE = 1_700_000_000
DUR = 3600.0


def _iso(ts):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))


def make_chat(seed=1):
    rnd = random.Random(seed)
    msgs, mid = [], 0
    for t in range(int(DUR)):
        n = 1 if rnd.random() < 0.8 else 2
        burst = any(b <= t < b + 25 for b in (1000, 2500))
        if burst:
            n = 12
        for _ in range(n):
            mid += 1
            u = f"u{rnd.randrange(400 if burst else 40)}"
            msgs.append({"id": f"m{mid}", "created_at": _iso(BASE + t), "sender": {"username": u}, "content": "lol"})
    return msgs


class FakeKick:
    def __init__(self, msgs, fail_after=None):
        self.msgs, self.calls, self.fail_after = msgs, 0, fail_after

    def __call__(self, url, tries=8):
        if self.fail_after is not None and self.calls >= self.fail_after:
            raise kick.KickError("kesildi")
        self.calls += 1
        t0 = calendar.timegm(time.strptime(url.split("start_time=")[1][:19], "%Y-%m-%dT%H:%M:%S"))
        ms = [m for m in self.msgs if t0 <= calendar.timegm(time.strptime(m["created_at"][:19], "%Y-%m-%dT%H:%M:%S")) < t0 + 5]
        return {"data": {"messages": ms[:25], "cursor": None}}


@pytest.fixture
def vod():
    return kick.Vod("v", "ch", "t", DUR, BASE, 1, "u")


@pytest.fixture(autouse=True)
def fast_limiter(monkeypatch):
    monkeypatch.setattr(kick, "_limiter", kick.Limiter(10_000))


def test_coverage_merge():
    c = kick.Coverage()
    c.add(0, 5)
    c.add(5, 10)
    c.add(20, 25)
    assert c.covers(0, 10) and not c.covers(0, 11) and c.end_of(12) == 12 and c.end_of(22) == 25


def test_smart_finds_bursts_with_fewer_requests(monkeypatch, vod, tmp_path):
    api = FakeKick(make_chat())
    monkeypatch.setattr(kick, "_get", api)
    data = kick.fetch_chat(vod, tmp_path / "s", mode="smart")
    smart_calls = api.calls
    found = peaks.find_peaks_sparse(data.msgs, data.coverage, data.baseline, DUR, n=5)
    assert any(abs(p.time - 1000) < 40 for p in found[:2]) and any(abs(p.time - 2500) < 40 for p in found[:2])
    api2 = FakeKick(make_chat())
    monkeypatch.setattr(kick, "_get", api2)
    full = kick.fetch_chat(vod, tmp_path / "f", mode="full")
    assert full.dense and api2.calls > smart_calls * 1.3
    top = peaks.find_peaks(full.msgs, DUR, n=2)
    assert {round(p.time, -2) for p in top} == {round(p.time, -2) for p in found[:2]}


def test_download_resumes_after_interruption(monkeypatch, vod, tmp_path):
    msgs = make_chat()
    api = FakeKick(msgs, fail_after=120)
    monkeypatch.setattr(kick, "_get", api)
    with pytest.raises(kick.KickError):
        kick.fetch_chat(vod, tmp_path / "r", mode="smart", workers=1)
    done = api.calls
    assert done == 120 and (tmp_path / "r" / kick.LOG_NAME).exists()
    api2 = FakeKick(msgs)
    monkeypatch.setattr(kick, "_get", api2)
    kick.fetch_chat(vod, tmp_path / "r", mode="smart", workers=1)
    api3 = FakeKick(msgs)
    monkeypatch.setattr(kick, "_get", api3)
    ref = kick.fetch_chat(vod, tmp_path / "ref", mode="smart", workers=1)
    assert api2.calls + done <= api3.calls + 2          # nothing is downloaded twice
    again = FakeKick(msgs)
    monkeypatch.setattr(kick, "_get", again)
    out = kick.fetch_chat(vod, tmp_path / "r", mode="smart", workers=1)
    assert again.calls == 0 and len(out.msgs) == len(ref.msgs)


def test_limiter_lowers_rate_on_429():
    lim = kick.Limiter(2.0)
    lim.throttle(0.0)
    assert lim.rate < 2.0
