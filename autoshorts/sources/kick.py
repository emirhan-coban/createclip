"""Kick VOD metadata + chat download (unofficial public API, polite rate limit)."""
import json
import re
import shutil
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from . import ytdlp
from ..proc import check_cancel, run, say

UA = {"User-Agent": "Mozilla/5.0"}
URL_RE = re.compile(r"kick\.com/([^/?#]+)/videos/([0-9a-fA-F-]{36})")


class KickError(RuntimeError):
    pass


@dataclass
class Vod:
    vod_id: str
    slug: str
    title: str
    duration: float
    start_ts: int  # unix seconds of stream start (== chat time zero)
    channel_id: int
    url: str
    thumbnail: str = ""


def parse_url(url: str):
    m = URL_RE.search(url)
    if not m:
        raise KickError("Geçerli bir Kick VOD linki değil (kick.com/<kanal>/videos/<id> bekleniyor).")
    return m.group(1), m.group(2)


def vod_info(url: str) -> Vod:
    slug, vid = parse_url(url)
    try:
        cmd = ytdlp.cmd("-J", "--skip-download", url)
    except ytdlp.YtDlpMissing as e:
        raise KickError(str(e)) from e
    try:
        p = run(cmd, "kick bilgi", timeout=180)
    except subprocess.TimeoutExpired:
        raise KickError("VOD bilgisi 3 dk içinde gelmedi (ağ/Kick takıldı); tekrar dene.") from None
    if p.returncode != 0:
        raise KickError("VOD bilgisi alınamadı: " + p.stderr.strip()[-300:])
    d = json.loads(p.stdout)
    if not d.get("timestamp") or not d.get("channel_id"):
        raise KickError("VOD bilgisinde başlangıç zamanı/kanal kimliği yok.")
    return Vod(vid, slug, d.get("title") or "", float(d["duration"]), int(d["timestamp"]),
               int(d["channel_id"]), url, d.get("thumbnail") or "")


# Kick's chat endpoint tolerates about 1.5 requests/s sustained (measured over 150 s: 1.2/s and 1.5/s -> no
# HTTP 429; 1.8/s -> 21 of 274 rejected, net 1.69/s). We pace ourselves just under that instead of hammering
# and backing off. Faster is only possible by asking for less data (smart mode), not by asking faster.
WORKERS = 4
RATE = 1.5           # requests / second (adaptive: lowered on 429, slowly raised again)
RATE_MIN, RATE_MAX = 0.6, 1.7
PAGE_CAP = 20        # a response holding this many messages was probably cut by Kick's per-request cap
WIN = 5.0            # one request returns the messages of a ~5 s window
COARSE_EVERY = 8     # smart mode, stage 1: one window out of this many
REGION_PAD = 45.0    # smart mode, stage 2: crawl this many seconds around each candidate peak
LOG_NAME = "chat.log.jsonl"


class Limiter:
    """Shared pacing for all workers: one request slot every 1/rate seconds, AIMD on 429."""

    def __init__(self, rate: float = RATE):
        self.rate = rate
        self.next = 0.0
        self.good = 0
        self.lock = threading.Lock()

    def wait(self):
        with self.lock:
            now = time.time()
            self.next = max(self.next, now) + 1.0 / self.rate
            slot = self.next - 1.0 / self.rate
        if slot > now:
            time.sleep(slot - now)

    def ok(self):
        with self.lock:
            self.good += 1
            if self.good >= 60:
                self.good = 0
                self.rate = min(RATE_MAX, self.rate + 0.1)

    def throttle(self, cool: float = 6.0):
        with self.lock:
            self.good = 0
            self.rate = max(RATE_MIN, self.rate * 0.75)
            self.next = max(self.next, time.time() + cool)


_limiter = Limiter()


_stats = {"n": 0, "429": 0, "t": 0.0}


def _report(throttled: bool = False):
    """Kick requests are not run through proc.run: tell the terminal about them in a summary line every 10 s."""
    _stats["n"] += 1
    _stats["429"] += throttled
    if time.time() - _stats["t"] >= 10:
        _stats["t"] = time.time()
        say("cmd", f"GET kick.com/api … · {_stats['n']} istek · {_stats['429']} hız sınırı (429) · {_limiter.rate:.1f} istek/sn")


def _get(url: str, tries: int = 8):
    # curl, not urllib: Kick's edge answers curl in ~1 s but stalls Python's TLS client.
    last = None
    for i in range(tries):
        check_cancel()
        _limiter.wait()
        try:
            p = subprocess.run(["curl", "-s", "--max-time", "20", "-A", UA["User-Agent"], "-w", "\n%{http_code}", url],
                               capture_output=True, text=True)
            if p.returncode != 0:
                raise RuntimeError(f"curl exit {p.returncode}")
            body, _, code = p.stdout.rpartition("\n")
            _report(code == "429")
            if code == "429":
                _limiter.throttle(4 + 3 * i)
                raise RuntimeError("429 (hız sınırı)")
            d = json.loads(body)
            _limiter.ok()
            return d
        except Exception as e:  # noqa: BLE001
            last = e
            if "429" not in str(e):
                time.sleep(1.0 * (i + 1))
    raise KickError(f"Kick sohbet API'sine ulaşılamadı: {last}")


def _iso(ts: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(ts))


class Coverage:
    """Merged [a, b) intervals (seconds from VOD start) whose messages are all in the cache."""

    def __init__(self):
        self.iv: list[list[float]] = []
        self.lock = threading.Lock()

    def add(self, a: float, b: float):
        with self.lock:
            iv = self.iv + [[a, b]]
            iv.sort()
            out = [iv[0]]
            for x, y in iv[1:]:
                if x <= out[-1][1] + 1e-6:
                    out[-1][1] = max(out[-1][1], y)
                else:
                    out.append([x, y])
            self.iv = out

    def end_of(self, t: float) -> float:
        """First uncovered second at or after t."""
        with self.lock:
            for a, b in self.iv:
                if a - 1e-6 <= t < b:
                    return b
                if a > t:
                    break
        return t

    def covers(self, a: float, b: float) -> bool:
        return self.end_of(a) >= b - 1e-6


@dataclass
class ChatData:
    msgs: list
    coverage: Coverage
    dense: bool                      # True: whole VOD crawled; False: smart (sparse + dense regions)
    baseline: list                   # window start offsets that form an unbiased sample (smart mode)


class Chat:
    """Crawls and caches a VOD's chat. Every finished request is appended to <cache>/chat.log.jsonl, so an
    interrupted download (crash, sleep, closed tab) resumes where it stopped instead of starting over."""

    def __init__(self, vod: Vod, cache_dir: Path, progress=None, workers: int = WORKERS, on_snapshot=None):
        self.vod, self.progress, self.workers = vod, progress, workers
        self.on_snapshot, self._snap_at = on_snapshot, 0.0
        self.dir = Path(cache_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.path = self.dir / LOG_NAME
        self.base = float(vod.start_ts)
        self.cov, self.seen, self.msgs = Coverage(), set(), []
        self.lock = threading.Lock()
        self.requests = 0
        self._load()
        self.fh = open(self.path, "a", encoding="utf-8")

    def _load(self):
        if not self.path.exists():
            return
        for line in self.path.read_text(encoding="utf-8").splitlines():
            try:
                r = json.loads(line)
                self._ingest(r["m"], r["a"], r["b"])
            except (ValueError, KeyError):
                continue                      # torn last line from an interrupted run

    def _ingest(self, ms, a, b):
        for mid, t, u, c in ms:
            if mid not in self.seen:
                self.seen.add(mid)
                self.msgs.append({"t": t, "u": u, "c": c})
        self.cov.add(a, b)

    def _note(self, stage, done, total):
        if self.progress:
            self.progress(min(1.0, done / max(total, 1)), len(self.msgs), stage)
        if self.on_snapshot and time.time() - self._snap_at > 1.5:        # live view: messages read so far
            self._snap_at = time.time()
            with self.lock:
                self.on_snapshot(list(self.msgs))

    def fetch(self, t: float, adaptive: bool):
        """Fetch the window starting at offset t (adaptive: keep going while responses are full)."""
        end = min(t + WIN, self.vod.duration)
        cur = self.cov.end_of(t)
        while cur < end - 1e-6:
            data = _get(f"https://kick.com/api/v2/channels/{self.vod.channel_id}/messages?start_time={_iso(self.base + cur)}")["data"]
            ms = data.get("messages", [])
            rows = []
            for m in ms:
                off = _parse_ts(m["created_at"]) - self.base
                if 0 <= off <= self.vod.duration:
                    rows.append([m["id"], off, m["sender"]["username"], m["content"]])
            nxt = cur + WIN
            if adaptive and len(ms) >= PAGE_CAP:
                last = _parse_ts(ms[-1]["created_at"]) - self.base
                nxt = last if last > cur else cur + 1
            with self.lock:
                self._ingest(rows, cur, nxt)
                self.fh.write(json.dumps({"a": cur, "b": nxt, "m": rows}, ensure_ascii=False) + "\n")
                self.fh.flush()
                self.requests += 1
            cur = nxt

    def crawl(self, ranges, stage, adaptive=True):
        """ranges: list of (a, b) offsets, crawled in order by the worker pool."""
        total = sum(max(0.0, b - a) for a, b in ranges) or 1.0
        done = [0.0]

        def one(a, b):
            t = a
            while t < b - 1e-6:
                self.fetch(t, adaptive)
                t = max(t + WIN, self.cov.end_of(t))
                with self.lock:
                    done[0] = min(total, done[0] + WIN)
                self._note(stage, done[0], total)
        with ThreadPoolExecutor(self.workers) as ex:
            for fut in [ex.submit(one, a, b) for a, b in ranges]:
                fut.result()

    # ------------------------------------------------------------------ modes
    def full(self, start: float = 0.0):
        seg = max(60.0, self.vod.duration / 60)
        ranges, a = [], float(start)
        while a < self.vod.duration:
            ranges.append((a, min(a + seg, self.vod.duration)))
            a += seg
        self.crawl(ranges, "tam", adaptive=True)
        return ChatData(sorted(self.msgs, key=lambda m: m["t"]), self.cov, True, [])

    def smart(self, n_regions: int | None = None, start: float = 0.0):
        """Stage 1: one 5 s window out of every COARSE_EVERY. Stage 2: crawl densely only around the
        strongest candidates. Peaks are decided by the dense data, so the top moments match a full crawl
        (measured on real VODs: top-10 within one moment of a full crawl) at about a third of the requests."""
        from . import peaks
        dur = self.vod.duration
        if n_regions is None:      # tuned on a real 6 h VOD (59k messages): ~1/3 of the requests, top-10 intact
            n_regions = max(14, min(60, int(0.3 * (dur - start) / (2 * REGION_PAD))))
        first = int(start // WIN)
        starts = [i * WIN for i in range(first, int(dur // WIN) + 1, COARSE_EVERY)]
        self.crawl([(s, s + WIN) for s in starts if s < dur], "örnekleme", adaptive=False)
        coarse = peaks.coarse_candidates(self.msgs, starts, dur, n_regions, skip_start=max(120, start))
        ranges = [(max(float(start), c - REGION_PAD), min(dur, c + REGION_PAD)) for c in coarse]
        self.crawl(ranges, "yoğun bölgeler", adaptive=True)
        return ChatData(sorted(self.msgs, key=lambda m: m["t"]), self.cov, False, starts)

    def close(self):
        self.fh.close()


def fetch_chat(vod: Vod, cache_dir: Path, progress=None, mode: str = "smart", workers: int = WORKERS,
               start: float = 0.0, on_snapshot=None) -> ChatData:
    """mode: "smart" (default, fast) or "full" (every window, complete). Resumable; cache shared by both.
    start: seconds from the VOD start; nothing before it is requested (skips the crowded opening)."""
    c = Chat(vod, cache_dir, progress, workers, on_snapshot)
    try:
        return c.full(start) if mode == "full" else c.smart(start=start)
    finally:
        c.close()


def _parse_ts(s: str) -> float:
    import calendar
    return calendar.timegm(time.strptime(s.replace("Z", "")[:19], "%Y-%m-%dT%H:%M:%S"))
