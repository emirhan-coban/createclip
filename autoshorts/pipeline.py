"""The whole chain: link -> moments -> raw cuts -> vertical clips -> saved in the output folder."""
import re
import sqlite3

from . import config, download, editor, export, faces, finder, meta, render, store
from .proc import Cancelled, log
from .sources import kick

PAD = 6.0      # fallback for `source_pad`: extra footage around a cut, so the exact trim never runs off the file


def _slug(url: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "-", url.split("://")[-1])[:60].strip("-")


def _parse_time(s: str) -> float:
    sec = 0.0
    for p in str(s).strip().split(":"):
        sec = sec * 60 + float(p)
    return sec


def parse_at(spec: str, default_len: float = 45.0) -> tuple[float, float]:
    """'1:44:50' (default length) or '1:44:50-1:45:40'."""
    if "-" in spec:
        a, b = spec.split("-", 1)
        return _parse_time(a), _parse_time(b)
    s = _parse_time(spec)
    return s, s + default_len


def clamp_live(moments: list, available: float, min_len: float = 5.0) -> list:
    """Manual moments on a running broadcast: cut the end back to what exists; a moment that starts at (or too close
    to) the live edge cannot be cut yet."""
    out = []
    for m in moments:
        if m.start >= available - min_len:
            raise finder.FinderError(f"{download.hms(m.start)} henüz yayınlanmadı: canlı yayında en fazla "
                                     f"{download.hms(available)}'e kadar kesilebilir.")
        out.append(finder.Moment(m.start, min(m.end, available), m.score, m.engine))
    return out


# ---------------------------------------------------------------- video -> clips
def _noop(frac, msg=""):
    pass


def _noop_emit(kind, **data):
    pass


def process_video(con, cfg: dict, url: str, n: int | None = None, at: list[str] | None = None,
                  engine: str | None = None, say=print, progress=_noop, emit=_noop_emit) -> list[int]:
    """Find moments, cut and render them. Returns the ids of the new clips. A BlockedError (429 / bot check) stops
    the run and leaves the video 'pending' so a later run retries it.
    progress(overall fraction 0..1, text) feeds the UI: info 0-3%, moment search 3-50% (skipped for manual times),
    clips the rest."""
    find_band = (0.03, 0.5) if not at else (0.03, 0.03)
    clip_band = (find_band[1], 1.0)
    store.upsert_video(con, url)
    say(f"Video bilgisi alınıyor: {url}")
    progress(0.0, "Video bilgisi alınıyor (YouTube'da ~1 dk sürebilir)")
    try:
        video = download.info(url)
    except download.BlockedError:
        raise
    except download.DownloadError as e:
        store.upsert_video(con, url, status="failed", error=str(e))
        raise
    store.upsert_video(con, url, title=video.title, duration=video.duration)
    emit("info", url=url, title=video.title, duration=video.duration, platform=video.platform,
         channel=video.channel, thumbnail=video.thumbnail, live=video.live)
    if video.live:
        say(f"Canlı yayın: şu ana kadar {download.hms(video.duration)} kesilebilir (son ~{int(kick.LIVE_MARGIN)} sn hariç)")
    cache = config.data_dir() / "cache" / _slug(url)
    try:
        if at:
            moments = [finder.Moment(*parse_at(a), 0.0, "manual") for a in at]
            if video.live:
                moments = clamp_live(moments, video.duration)
        else:
            say(f"{video.title[:60]} · {video.duration / 60:.0f} dk · an aranıyor ({engine or cfg['engine']})")
            moments = finder.find(video, cfg, cache, n, engine,
                                  lambda f, t="": progress(find_band[0] + f * (find_band[1] - find_band[0]), t), emit)
        if not moments:
            raise finder.FinderError("Belirgin bir an bulunamadı.")
        emit("moments", moments=[{"rank": r, "start": m.start, "end": m.end, "score": m.score, "engine": m.engine}
                                 for r, m in enumerate(moments, 1)])
        ids = []
        for k, m in enumerate(moments, 1):
            say(f"[{k}/{len(moments)}] {download.hms(m.start)}-{download.hms(m.end)} (skor {m.score})")
            label = f"Klip {k}/{len(moments)} · {download.hms(m.start)}–{download.hms(m.end)}"

            cid = store.add_clip(con, url, m.start, m.end, m.score, m.engine)

            def clip_progress(f, t, k=k, label=label, cid=cid):
                emit("clip", rank=k, n=len(moments), id=cid, stage=t, frac=round(f, 2))
                progress(clip_band[0] + (k - 1 + f) / len(moments) * (clip_band[1] - clip_band[0]), f"{label} · {t}")
            if cid is None:
                say("  zaten var, atlandı")
                old = store.find_clip(con, url, m.start)
                if old and old["status"] == "done":
                    emit("clip", rank=k, n=len(moments), id=old["id"], stage="daha önce hazırlanmıştı", frac=1.0, done=True,
                         title=old["title"], start=m.start, end=m.end, score=m.score)
                continue
            try:
                make_clip(con, cfg, video, cid, m, clip_progress)
                ids.append(cid)
                done = store.get_clip(con, cid)
                emit("clip", rank=k, n=len(moments), id=cid, stage="hazır", frac=1.0, done=True, title=done["title"],
                     start=m.start, end=m.end, score=m.score)
            except download.BlockedError:
                store.update_clip(con, cid, status="failed", error="blocked")
                raise
            except Cancelled:
                store.update_clip(con, cid, status="failed", error="iptal edildi")
                raise
            except Exception as e:  # noqa: BLE001 - one bad moment must not lose the others
                log.warning("clip %s failed: %s", cid, e)
                store.update_clip(con, cid, status="failed", error=str(e)[:300])
                say(f"  hata: {e}")
        store.upsert_video(con, url, status="done", error=None)
        emit("done", ids=ids)
        return ids
    except download.BlockedError:
        store.upsert_video(con, url, status="pending", error="blocked")
        raise
    except Cancelled:
        store.upsert_video(con, url, status="cancelled", error="iptal edildi")
        raise
    except Exception as e:  # noqa: BLE001
        store.upsert_video(con, url, status="failed", error=str(e)[:300])
        raise


def make_clip(con, cfg: dict, video: download.Video, clip_id: int, m: finder.Moment, progress=_noop):
    """Download the range, render it vertical and save it with
    title/description to the output folder."""
    base = config.data_dir() / "clips"
    raw = base / "source" / f"{clip_id}.mp4"                 # kept: the editor cuts from it
    pad = float(cfg.get("source_pad", PAD))
    start = max(0.0, m.start - pad)
    end = min(video.duration, m.end + pad) if video.duration else m.end + pad
    progress(0.05, "yayından indiriliyor")
    download.fetch_range(video.url, start, end, raw, cfg["max_height"])
    store.set_source(con, clip_id, str(raw), start, end)
    info = editor.source_info(store.get_clip(con, clip_id))   # also shifts the file's timestamps to start at 0
    cs, ce = m.start, m.end
    project = None
    if cfg.get("layout") == "face" and faces.available():
        progress(0.45, "kamera aranıyor")
        try:
            face = faces.detect(raw, info["duration"])
        except faces.FaceError as e:
            log.warning("clip %s: no face layout: %s", clip_id, e)
            face = None
        if face:
            project = editor.default_project(store.get_clip(con, clip_id))
            project["layout"] = editor.face_layout(face, info["width"], info["height"], float(cfg.get("split", 0.4)))
            project["trim"] = {"in": round(cs - start, 2), "out": round(ce - start, 2)}
    out = base / f"{clip_id}.mp4"
    progress(0.55, "dikeye çevriliyor, ses ayarlanıyor")
    if project:
        editor.render_project(raw, editor.clean_project(project, info["duration"]), out, info,
                              lambda f, t="": progress(0.55 + 0.4 * f, "dikeye çevriliyor, ses ayarlanıyor"))
        store.save_project(con, clip_id, editor.clean_project(project, info["duration"]))
    else:
        render.vertical(raw, cs - start, ce - cs, out)
    progress(0.95, "kaydediliyor")
    render.thumbnail(out, base / f"{clip_id}.jpg")
    meta_info = meta.make(video.title, video.channel, video.url, cs, cfg)
    saved = export.save(cfg, clip_id, video.channel, cs, out, base / f"{clip_id}.jpg", meta_info["title"], meta_info["description"])
    store.update_clip(con, clip_id, file=str(saved), title=meta_info["title"], description=meta_info["description"],
                      tags=meta_info["tags"], status="done", error=None)
    return saved


# ---------------------------------------------------------------- watching channels
def scan_sources(con, say=print, lister=download.list_videos) -> int:
    """Queue the new finished streams of every watched channel (first sight: only the newest `backfill`)."""
    added = 0
    for s in store.sources(con):
        try:
            vids = lister(s["url"], 10)
        except download.BlockedError:
            raise
        except download.DownloadError as e:
            say(f"{s['url']}: {e}")
            continue
        fresh = [v for v in vids if not store.known_video(con, v["url"])]
        first = not any(True for _ in con.execute("SELECT 1 FROM videos WHERE source_id=?", (s["id"],)))
        if first:
            for v in fresh[s["backfill"]:]:                      # older history is only marked as seen
                store.upsert_video(con, v["url"], status="skipped", source_id=s["id"], title=v["title"])
            fresh = fresh[:s["backfill"]]
        for v in sorted(fresh, key=lambda v: v["ts"]):
            store.upsert_video(con, v["url"], status="pending", source_id=s["id"], title=v["title"], duration=v["duration"])
            added += 1
    return added


def watch_once(con, cfg: dict, say=print, progress=_noop) -> dict:
    """One full round: scan channels and process the new videos."""
    out = {"new_videos": 0, "clips": 0, "blocked": False}
    try:
        progress(0.0, "Kanallar taranıyor")
        out["new_videos"] = scan_sources(con, say)
        pend = store.pending_videos(con)
        for i, v in enumerate(pend):
            out["clips"] += len(process_video(con, cfg, v["url"], say=say, progress=lambda f, t="", i=i: progress(
                (i + f) / len(pend), f"Yayın {i + 1}/{len(pend)}: {t}")))
    except download.BlockedError as e:
        say(str(e))
        out["blocked"] = True
    return out
