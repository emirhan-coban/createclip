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


def parse_url(url: str):
    m = URL_RE.search(url)
    if not m:
        raise KickError("Geçerli bir Kick VOD linki değil (kick.com/<kanal>/videos/<id> bekleniyor).")
    return m.group(1), m.group(2)


def vod_info(url: str) -> Vod:
    slug, vid = parse_url(url)
    ytdlp = shutil.which("yt-dlp")
    if not ytdlp:
        raise KickError("yt-dlp bulunamadı (brew install yt-dlp).")
    p = subprocess.run([ytdlp, "-J", "--skip-download", url], capture_output=True, text=True)
    if p.returncode != 0:
        raise KickError("VOD bilgisi alınamadı: " + p.stderr.strip()[-300:])
    d = json.loads(p.stdout)
    if not d.get("timestamp") or not d.get("channel_id"):
        raise KickError("VOD bilgisinde başlangıç zamanı/kanal kimliği yok.")
    return Vod(vid, slug, d.get("title") or "", float(d["duration"]), int(d["timestamp"]),
               int(d["channel_id"]), url)


WORKERS = 4          # Kick answers HTTP 429 from ~8 parallel requests; 4 is safe (measured)
PAGE_CAP = 20        # a response holding this many messages was probably cut by Kick's per-request cap
CACHE_VERSION = "v2"      # complete crawl. (v1 followed the API's `cursor`, which skips ~2/3 of the messages)
FAST_VERSION = "v2-fast"  # one request per 5 s window; dense moments are truncated by Kick's per-request cap
_cool = {"until": 0.0}
_cool_lock = threading.Lock()


def _get(url: str, tries: int = 6):
    # curl, not urllib: Kick's edge answers curl in ~1 s but stalls Python's TLS client.
    last = None
    for i in range(tries):
        wait = _cool["until"] - time.time()
        if wait > 0:
            time.sleep(wait)
        try:
            p = subprocess.run(["curl", "-s", "--max-time", "20", "-A", UA["User-Agent"], "-w", "\n%{http_code}", url],
                               capture_output=True, text=True)
            if p.returncode != 0:
                raise RuntimeError(f"curl exit {p.returncode}")
            body, _, code = p.stdout.rpartition("\n")
            if code == "429":
                with _cool_lock:                       # every worker backs off together
                    _cool["until"] = max(_cool["until"], time.time() + 4 + 3 * i)
                raise RuntimeError("429 (hız sınırı)")
            return json.loads(body)
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(1.0 * (i + 1))
    raise KickError(f"Kick sohbet API'sine ulaşılamadı: {last}")


def _iso(ts: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(ts))


def fetch_chat(vod: Vod, cache_dir: Path, progress=None, workers: int = WORKERS, fast: bool = True):
    """Returns list of {t: seconds-from-vod-start, u: user, c: content}. Cached per VOD.

    The API returns the messages of a ~5 s window starting at `start_time` (at most ~25 of them).
    We step by 5 s, or - when a response is full - continue from its last message so busy moments are
    complete (full mode). fast mode takes one request per 5 s. Measured on a 2.5 h VOD: fast 18.4 min / 16080
    msgs, full 19.6 min / 16449 msgs - Kick's rate limit (HTTP 429) dominates, not the request count. The VOD is cut into many short
    segments crawled by a small pool of workers."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    f, done = cache_dir / "chat.jsonl", cache_dir / "chat.done"
    ok = {CACHE_VERSION} if not fast else {CACHE_VERSION, FAST_VERSION}   # a full cache also serves fast
    if f.exists() and done.exists() and done.read_text().strip() in ok:
        return [json.loads(l) for l in f.read_text().splitlines() if l.strip()]

    base, end = float(vod.start_ts), float(vod.start_ts) + vod.duration
    seen, msgs = set(), []
    lock = threading.Lock()
    covered = [0.0]

    def crawl(a: float, b: float):
        t = a
        while t < b:
            data = _get(f"https://kick.com/api/v2/channels/{vod.channel_id}/messages?start_time={_iso(t)}")["data"]
            ms = data.get("messages", [])
            with lock:
                for m in ms:
                    if m["id"] in seen:
                        continue
                    seen.add(m["id"])
                    off = _parse_ts(m["created_at"]) - base
                    if 0 <= off <= vod.duration:
                        msgs.append({"t": off, "u": m["sender"]["username"], "c": m["content"]})
            if not fast and len(ms) >= PAGE_CAP:
                last = _parse_ts(ms[-1]["created_at"])
                nt = last if last > t else t + 1
            else:
                nt = t + 5
            with lock:
                covered[0] += min(nt, b) - t
                if progress:
                    progress(min(1.0, covered[0] / vod.duration), len(msgs))
            t = nt

    seg = max(60.0, vod.duration / 60)
    bounds = []
    a = base
    while a < end:
        bounds.append((a, min(a + seg, end)))
        a += seg
    with ThreadPoolExecutor(workers) as ex:
        for fut in [ex.submit(crawl, a, b) for a, b in bounds]:
            fut.result()
    msgs.sort(key=lambda m: m["t"])
    f.write_text("\n".join(json.dumps(m, ensure_ascii=False) for m in msgs))
    done.write_text(FAST_VERSION if fast else CACHE_VERSION)
    return msgs


def _parse_ts(s: str) -> float:
    import calendar
    return calendar.timegm(time.strptime(s.replace("Z", "")[:19], "%Y-%m-%dT%H:%M:%S"))
