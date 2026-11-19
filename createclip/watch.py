"""Channel watcher + job queue: new finished streams of the channels you follow are found, queued and processed
one after another (overnight), so the morning starts with clips waiting for review.

Files (under <root>):
  channels.json          [{"url", "name", "min_minutes", "backfill", "options": {...Options fields...}}]
  output/queue.json      {"items": [...], "seen": [urls]}       (resumable; every write is atomic + locked)
Statuses: pending -> running -> done | error | confirm_audio (chat unavailable, whole-audio download needs a yes)."""
import fcntl
import json
import os
import re
import time
from contextlib import contextmanager
from dataclasses import fields
from pathlib import Path

from . import pipeline, sources, ytdlp
from . import notify
from .log import log, run

STATUSES = ("pending", "running", "done", "error", "confirm_audio", "skipped")
MAX_ATTEMPTS = 3


# ------------------------------------------------------------------ files
def _paths(root: Path):
    root = Path(root)
    return root / "channels.json", root / "output" / "queue.json", root / "output" / "queue.lock"


@contextmanager
def _locked(root: Path):
    _, _, lock = _paths(root)
    lock.parent.mkdir(parents=True, exist_ok=True)
    with open(lock, "w") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def _write(path: Path, data):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1))
    os.replace(tmp, path)


def load_channels(root: Path) -> list:
    p, _, _ = _paths(root)
    return json.loads(p.read_text()) if p.exists() else []


def save_channels(root: Path, chans: list):
    p, _, _ = _paths(root)
    _write(p, chans)


def add_channel(root: Path, url: str, **kw) -> dict:
    url = normalize_channel(url)
    chans = load_channels(root)
    if any(c["url"] == url for c in chans):
        raise ValueError("Bu kanal zaten ekli.")
    c = {"url": url, "name": kw.get("name") or _channel_name(url), "min_minutes": kw.get("min_minutes", 30),
         "backfill": kw.get("backfill", 1), "options": kw.get("options", {})}
    save_channels(root, chans + [c])
    return c


def remove_channel(root: Path, url: str) -> bool:
    chans = load_channels(root)
    keep = [c for c in chans if c["url"] != normalize_channel(url) and c.get("name") != url]
    save_channels(root, keep)
    return len(keep) != len(chans)


def _load_q(root: Path) -> dict:
    _, q, _ = _paths(root)
    return json.loads(q.read_text()) if q.exists() else {"items": [], "seen": []}


def _save_q(root: Path, data: dict):
    _, q, _ = _paths(root)
    q.parent.mkdir(parents=True, exist_ok=True)
    _write(q, data)


def queue(root: Path) -> list:
    with _locked(root):
        return _load_q(root)["items"]


def update_item(root: Path, iid: str, **changes) -> dict:
    with _locked(root):
        d = _load_q(root)
        for it in d["items"]:
            if it["id"] == iid:
                it.update(changes)
                _save_q(root, d)
                return it
    raise KeyError(iid)


def remove_item(root: Path, iid: str):
    with _locked(root):
        d = _load_q(root)
        d["items"] = [i for i in d["items"] if i["id"] != iid]
        _save_q(root, d)


# ------------------------------------------------------------------ channel -> VODs
def normalize_channel(url: str) -> str:
    """Kick: kick.com/<kanal>[/videos] -> .../videos ; YouTube: @kanal or channel URL -> .../streams."""
    url = url.strip().rstrip("/")
    m = re.match(r"(?:https?://)?(?:www\.)?kick\.com/([^/?#]+)", url)
    if m and m.group(1) not in ("video", "categories"):
        return f"https://kick.com/{m.group(1)}/videos"
    m = re.match(r"(?:https?://)?(?:www\.|m\.)?youtube\.com/((?:@|channel/|c/|user/)[^/?#]+)", url)
    if m:
        return f"https://www.youtube.com/{m.group(1)}/streams"
    if url.startswith("@"):
        return f"https://www.youtube.com/{url}/streams"
    raise ValueError("Kanal linki anlaşılamadı: kick.com/<kanal> ya da youtube.com/@<kanal> bekleniyor.")


def _channel_name(url: str) -> str:
    return re.sub(r"https?://(www\.)?(kick|youtube)\.com/|/(videos|streams)$", "", url)


def list_vods(channel_url: str, limit: int = 10) -> list:
    """Recent finished streams, newest first: [{id, url, title, duration, ts}]. Live/upcoming/zero-length are dropped."""
    p = run(ytdlp.cmd("--flat-playlist", "--playlist-end", str(limit), "--print",
                      "%(.{id,url,title,duration,timestamp,release_timestamp,live_status})j", channel_url),
            f"kanal listesi {channel_url}", timeout=120)
    if p.returncode:
        raise RuntimeError("Kanal listesi alınamadı: " + p.stderr.strip()[-200:])
    out = []
    for line in p.stdout.splitlines():
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if d.get("live_status") in ("is_live", "is_upcoming") or not d.get("duration"):
            continue
        url = (d.get("url") or "").split("#")[0]
        if url:
            out.append({"id": d.get("id"), "url": url, "title": d.get("title") or "", "duration": float(d["duration"]),
                        "ts": d.get("timestamp") or d.get("release_timestamp") or 0})
    return out


def scan(root: Path, lister=list_vods) -> list:
    """Look at every channel, queue the new finished streams. First sight of a channel queues only the newest
    `backfill` ones (so adding a channel doesn't queue its whole history). Returns the new queue items."""
    added = []
    for ch in load_channels(root):
        try:
            vods = lister(ch["url"])
        except Exception as e:  # noqa: BLE001
            log.warning("kanal taranamadı %s: %s", ch["url"], e)
            continue
        with _locked(root):
            d = _load_q(root)
            seen = set(d["seen"])
            first = not any(i.get("channel") == ch["url"] for i in d["items"]) and not any(
                v["url"] in seen for v in vods)
            fresh = [v for v in vods if v["url"] not in seen]
            if first:
                keep, skip = fresh[:max(0, int(ch.get("backfill", 1)))], fresh[max(0, int(ch.get("backfill", 1))):]
            else:
                keep, skip = fresh, []
            for v in skip:
                seen.add(v["url"])
            for v in sorted(keep, key=lambda v: v["ts"]):             # oldest first: Kick VODs expire after 7-30 days
                seen.add(v["url"])
                if v["duration"] < 60 * float(ch.get("min_minutes", 30)):
                    log.info("atlandı (çok kısa, %.0f dk): %s", v["duration"] / 60, v["title"])
                    continue
                it = {"id": f"q{int(time.time() * 1000) % 10**10}{len(d['items'])}", "url": v["url"],
                      "channel": ch["url"], "name": ch.get("name"), "title": v["title"], "duration": v["duration"],
                      "ts": v["ts"], "status": "pending", "attempts": 0, "error": None, "project": None,
                      "added": time.time()}
                d["items"].append(it)
                added.append(it)
            d["seen"] = sorted(seen)
            _save_q(root, d)
    if added:
        log.info("%d yeni yayın kuyruğa eklendi", len(added))
    return added


# ------------------------------------------------------------------ processing
def options_for(root: Path, item: dict, confirmed: bool = False) -> pipeline.Options:
    ch = next((c for c in load_channels(root) if c["url"] == item.get("channel")), {})
    names = {f.name for f in fields(pipeline.Options)}
    kw = {k: v for k, v in (ch.get("options") or {}).items() if k in names}
    kw["audio_ok"] = bool(kw.get("audio_ok")) or confirmed or bool(item.get("confirmed"))
    return pipeline.Options(**kw)


def next_pending(root: Path):
    with _locked(root):
        d = _load_q(root)
        for it in sorted(d["items"], key=lambda i: i.get("ts") or 0):
            if it["status"] == "pending":
                it["status"], it["attempts"] = "running", it["attempts"] + 1
                _save_q(root, d)
                return dict(it)
    return None


def recover_running(root: Path):
    """A crash/kill leaves items 'running'; put them back (the chat log makes the retry cheap)."""
    with _locked(root):
        d = _load_q(root)
        for it in d["items"]:
            if it["status"] == "running":
                it["status"] = "pending" if it["attempts"] < MAX_ATTEMPTS else "error"
        _save_q(root, d)


def process_one(root: Path, progress=None, runner=None) -> dict | None:
    """Run the oldest pending item. Returns the finished item, or None if nothing is pending."""
    it = next_pending(root)
    if not it:
        return None
    runner = runner or pipeline.run
    log.info("kuyruk: %s (%s)", it["title"][:60], it["url"])
    try:
        m = runner(it["url"], Path(root), options_for(root, it), progress or (lambda *a, **k: None))
        return update_item(root, it["id"], status="done", error=None, project=Path(m["dir"]).name)
    except pipeline.NeedsAudioConfirm as e:
        return update_item(root, it["id"], status="confirm_audio", error=str(e), est_mb=e.est_mb)
    except Exception as e:  # noqa: BLE001
        log.exception("kuyruk işi başarısız: %s", it["url"])
        retry = it["attempts"] < MAX_ATTEMPTS
        return update_item(root, it["id"], status="pending" if retry else "error", error=str(e))


def confirm_audio(root: Path, iid: str):
    update_item(root, iid, status="pending", confirmed=True, error=None)


def retry(root: Path, iid: str):
    update_item(root, iid, status="pending", attempts=0, error=None)


def loop(root: Path, every_hours: float = 6.0, once: bool = False, progress=None, sleep=time.sleep):
    """scan -> drain the queue -> sleep. Safe to stop with Ctrl-C and start again."""
    recover_running(root)
    while True:
        scan(root)
        done = failed = 0
        while (it := process_one(root, progress)):
            done += it["status"] == "done"
            failed += it["status"] == "error"
        if done or failed:
            notify.notify("createclip", f"{done} yayın işlendi" + (f", {failed} hata" if failed else "") + " — onay kutusu hazır")
        if once:
            return
        log.info("sonraki tarama %.1f saat sonra", every_hours)
        sleep(every_hours * 3600)


def find_channel(root: Path, slug: str):
    """The followed channel a project came from (project slug == channel name, ignoring a leading @)."""
    key = (slug or "").lower().lstrip("@")
    for c in load_channels(root):
        if str(c.get("name", "")).lower().lstrip("@") == key:
            return c
    return None


def save_profile(root: Path, slug: str, style: dict, layout: dict, defaults: dict) -> dict:
    """Make one clip's caption style + 9:16 layout (+ quality/length settings) the profile of its channel, so every
    future clip of that streamer comes out like this without touching the editor."""
    ch = find_channel(root, slug)
    if not ch:
        raise KeyError(slug)
    opts = dict(ch.get("options") or {})
    opts["style"] = dict(style or {})
    opts["layout"] = layout
    for k in ("max_height", "min_len", "max_len", "captions", "keep_plain", "snap"):
        if k in (defaults or {}):
            opts[k] = defaults[k]
    ch["options"] = opts
    save_channels(root, [ch if c["url"] == ch["url"] else c for c in load_channels(root)])
    return ch
