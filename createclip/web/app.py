import io
import time
import traceback
import shutil
import subprocess
import threading
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .. import autometa, cleanup as cleanupmod, settings as settingsmod, compile as compilemod, layout as layoutmod, log as logmod, notify, pipeline, review as reviewmod, titles as titlesmod, transcribe, watch as watchmod

HTML = Path(__file__).with_name("index.html")


class JobReq(BaseModel):
    url: str
    n: int = 5
    captions: bool = True
    keep_plain: bool = False
    font: str = "montserrat"
    mask: bool = False
    layout: str = "none"
    source: str = "auto"
    at: list[str] = Field(default_factory=list)
    snap: bool = True
    vocab: str = ""
    full_chat: bool = False          # legacy flag; same as chat_mode="full"
    chat_mode: str = "smart"
    audio_ok: bool = False           # user confirmed the whole-video audio fallback
    style: dict = Field(default_factory=dict)     # size, ypos, chunk, active, color, stroke, upper, sync ...
    min_len: float = 25
    max_len: float = 60
    lead: float = 20
    max_height: int = 720
    reactions: bool = False
    start_min: float = 0             # skip the first N minutes (crowded opening)
    drafts: int = 0                  # extra moments fetched as raw previews, rendered only when picked


class Pick(BaseModel):
    project: str
    i: int


class RenderReq(BaseModel):
    picks: list[Pick]


class CompileReq(BaseModel):
    n: int = 5
    status: str = "approved"
    title: str | None = None


class SettingsReq(BaseModel):
    gemini_key: str | None = None
    auto_watch: bool | None = None
    watch_hours: float | None = Field(None, ge=0.5, le=24)
    fast: bool | None = None         # True = full speed, False = gentle (computer stays usable)


class CleanupReq(BaseModel):
    days: float = 14
    apply: bool = False


class ReviewReq(BaseModel):
    status: str | None = None
    title: str | None = None
    description: str | None = None
    tags: list[str] | None = None


class ExportReq(BaseModel):
    platform: str = "shorts"


class ChannelReq(BaseModel):
    url: str
    min_minutes: float = 30
    backfill: int = 1
    n: int = 5
    layout: str = "none"
    max_height: int = 720


class PreviewReq(BaseModel):
    style: dict = Field(default_factory=dict)
    portrait: bool = False
    text: str = "BU BİR ÖRNEK ALTYAZI"


class ClipChanges(BaseModel):
    retranscribe: bool | None = None
    start: float | None = None
    end: float | None = None
    text: str | None = None
    style: dict | None = None
    layout: dict | None = None
    captions: bool | None = None
    reactions: bool | None = None
    banner: str | None = None


class AddReq(BaseModel):
    next: bool = False
    start: float | None = None
    end: float | None = None


def make_app(root: Path) -> FastAPI:
    root = Path(root)
    (root / "output").mkdir(parents=True, exist_ok=True)
    logfile = logmod.setup(root)
    settingsmod.configure(root)
    logmod.set_gentle(not settingsmod.get("fast") and logmod.GENTLE)
    STALL = 120        # seconds without progress before a task is flagged as stalled
    app = FastAPI(title="createclip")
    tasks: dict[str, dict] = {}
    busy = threading.Lock()   # one heavy task at a time (whisper + ffmpeg)

    def spawn(fn, *a, label: str = "", **kw) -> str:
        tid = uuid.uuid4().hex[:8]
        t = tasks[tid] = {"status": "running", "stage": "queued", "frac": 0, "msg": "Sırada", "label": label,
                          "log": [], "stalled": 0, "last": time.time()}

        def prog(stage, frac, msg=""):
            if t.get("cancelled"):
                raise logmod.Cancelled("İptal edildi")
            if stage != t["stage"] or abs(frac - t["frac"]) >= 0.2:
                logmod.log.info("[%s] %d%% %s", stage, int(frac * 100), msg)
            t.update(stage=stage, frac=round(frac, 3), msg=msg, last=time.time(), stalled=0)

        def watchdog():
            while t["status"] == "running":
                time.sleep(5)
                idle = time.time() - t["last"]
                if t["status"] == "running" and idle > STALL and not t["stalled"]:
                    logmod.log.warning("[%s] %d sn'dir ilerleme yok (%s) - takılmış olabilir", t["stage"], idle, t["msg"])
                if idle > STALL:
                    t["stalled"] = int(idle)

        def work():
            h = logmod.TaskBuffer(t["log"])
            logmod.log.addHandler(h)
            try:
                with busy:
                    logmod.clear_cancel()
                    if t.get("cancelled"):
                        raise logmod.Cancelled("İptal edildi")
                    t["last"] = time.time()
                    logmod.log.info("İş başladı: %s", label)
                    res = fn(*a, progress=prog, **kw)
                t.update(status="done", result=res)
                logmod.log.info("İş bitti: %s", label)
                if label:
                    notify.notify("createclip: bitti", label[:80])
            except logmod.Cancelled:
                logmod.log.warning("İş iptal edildi: %s", label)
                t.update(status="cancelled", error="İptal edildi")
            except Exception as e:  # noqa: BLE001
                logmod.log.error("İş başarısız: %s\n%s", e, traceback.format_exc())
                extra = {"code": "confirm_audio", "est_mb": e.est_mb} if isinstance(e, pipeline.NeedsAudioConfirm) else {}
                t.update(status="error", error=str(e), **extra)
                if label:
                    notify.notify("createclip: hata", str(e)[:100])
            finally:
                logmod.log.removeHandler(h)

        threading.Thread(target=work, daemon=True).start()
        threading.Thread(target=watchdog, daemon=True).start()
        return tid

    def _dir(name: str) -> Path:
        d = root / "output" / name
        if "/" in name or ".." in name or not (d / "manifest.json").exists():
            raise HTTPException(404, "proje bulunamadı")
        return d

    @app.get("/", response_class=HTMLResponse)
    def index():
        return HTML.read_text()

    @app.get("/api/tasks")
    def task_list():
        """All known tasks (running first) - lets a reopened page re-attach to a job that is still running."""
        rows = [{"id": k, **{x: v.get(x) for x in ("status", "stage", "frac", "msg", "label", "error", "stalled", "code")}}
                for k, v in tasks.items()]
        return sorted(rows, key=lambda r: r["status"] != "running")

    @app.get("/api/log")
    def server_log(n: int = 200):
        return {"file": str(logfile), "text": logmod.tail(logfile, max(1, min(n, 2000)))}

    @app.get("/api/tasks/{tid}")
    def task(tid: str):
        if tid not in tasks:
            raise HTTPException(404)
        return tasks[tid]

    @app.post("/api/tasks/{tid}/cancel")
    def task_cancel(tid: str):
        t = tasks.get(tid)
        if not t:
            raise HTTPException(404)
        if t["status"] == "running":
            t["cancelled"] = True
            if t["stage"] != "queued":
                logmod.request_cancel()           # kills the ffmpeg/yt-dlp process that is running now
        return {"ok": True}

    @app.post("/api/jobs")
    def create(req: JobReq):
        o = pipeline.Options(
            n=req.n, captions=req.captions, keep_plain=req.keep_plain,
            style={**req.style, "font": req.font, "mask": req.mask},
            min_len=req.min_len, max_len=req.max_len, lead=req.lead, max_height=req.max_height,
            layout={"mode": req.layout, "cells": layoutmod.default_cells(req.layout)},
            source=req.source, at=req.at, snap=req.snap, vocab=req.vocab,
            chat_mode="full" if (req.full_chat or req.chat_mode == "full") else "smart", audio_ok=req.audio_ok,
            reactions=req.reactions, start_at=max(0.0, req.start_min) * 60, drafts=max(0, min(40, req.drafts)))

        def job(progress):
            m = pipeline.run(req.url, root, o, progress)
            return {"dir": Path(m["dir"]).name}
        return {"id": spawn(job, label=req.url)}

    previewing: set = set()
    checked: set = set()

    @app.get("/api/drafts")
    def drafts():
        """Raw previews waiting to be picked: [{project, i, score, video, a, b, ...}], newest project first."""
        out = []
        for d in sorted((root / "output").glob("*/manifest.json"), key=lambda p: -p.stat().st_mtime):
            try:
                m = pipeline.load(d.parent)
            except Exception:  # noqa: BLE001
                continue
            for c in sorted(m["clips"], key=lambda c: -(c.get("score") or 0)):
                if c.get("status") != "draft":
                    continue
                prev = c.get("preview") and (d.parent / c["preview"]).exists()
                if prev or (c.get("raw") and (d.parent / c["raw"]).exists()):
                    a, b = (0.0, c["end"] - c["start"]) if prev else (c["start"] - c["raw_start"], c["end"] - c["raw_start"])
                    out.append({"project": d.parent.name, "i": c["i"], "score": c.get("score") or 0, "slug": m["slug"],
                                "video": f"/files/{d.parent.name}/{c['preview'] if prev else c['raw']}", "a": round(a, 2),
                                "b": round(b, 2), "at": c["start"], "length": round(c["end"] - c["start"]),
                                "fixing": d.parent.name in previewing})
            if d.parent.name not in checked:                   # once per start: repair/rebuild previews in the background
                checked.add(d.parent.name)
                previewing.add(d.parent.name)

                def work(jd=d.parent):
                    try:
                        pipeline.backfill_previews(jd)
                    except Exception as e:  # noqa: BLE001
                        logmod.log.warning("önizleme onarımı: %s", e)
                    finally:
                        previewing.discard(jd.name)
                threading.Thread(target=work, daemon=True).start()
        return out

    @app.post("/api/render")
    def render_picks(req: RenderReq):
        """Render the picked drafts (grouped per project) and discard nothing; ✗ on a draft deletes it."""
        by = {}
        for p in req.picks:
            by.setdefault(_dir(p.project).name, []).append(p.i)

        def job(progress):
            done = 0
            for k, (name, ids) in enumerate(by.items()):
                pipeline.render_clips(root / "output" / name, ids,
                                      lambda st, fr, msg="", k=k: progress(st, (k + fr) / len(by), msg))
                done += len(ids)
            return {"rendered": done, "dir": next(iter(by))}
        return {"id": spawn(job, label=f"{sum(len(v) for v in by.values())} klip üretimi")}

    @app.get("/api/projects")
    def projects():
        out = []
        for d in sorted((root / "output").glob("*/manifest.json"), key=lambda p: -p.stat().st_mtime):
            try:
                m = pipeline.load(d.parent)
                out.append({"name": d.parent.name, "title": m["title"], "slug": m["slug"],
                            "clips": len(m["clips"]), "keep": bool(m.get("keep"))})
            except Exception:  # noqa: BLE001
                continue
        return out

    @app.get("/api/projects/{name}")
    def project(name: str):
        d = _dir(name)
        m = pipeline.load(d)
        for c in m["clips"]:
            if c.get("words") and (d / c["words"]).exists():
                c["text"] = transcribe.words_to_text(transcribe.load_words(d / c["words"]))
        m["clips"].sort(key=lambda c: (-(c.get("score") or 0), c["i"]))   # best first; manual clips (score 0) last
        for r, c in enumerate(m["clips"], 1):
            c["rank"] = r
        m["unused"] = sum(1 for c in m.get("candidates", []) if not c["used"])
        return m

    @app.post("/api/projects/{name}/clips/{i}")
    def edit(name: str, i: int, ch: ClipChanges):
        d = _dir(name)
        changes = ch.model_dump(exclude_none=True)

        def job(progress):
            return pipeline.update_clip(d, i, changes, progress)
        return {"id": spawn(job)}

    @app.delete("/api/projects/{name}")
    def delete_project(name: str):
        d = _dir(name)
        if pipeline.load(d).get("keep"):
            raise HTTPException(400, "Bu proje korumalı; önce korumayı kaldır.")
        shutil.rmtree(d)
        return {"ok": True}

    @app.post("/api/projects/{name}/keep")
    def project_keep(name: str, keep: bool = True):
        _dir(name)
        cleanupmod.set_keep(root, name, keep)
        return {"ok": True, "keep": keep}

    @app.put("/api/projects/{name}/clips/{i}/voice")
    async def voice_put(name: str, i: int, request: Request):
        d = _dir(name)
        data = await request.body()
        if not 1000 < len(data) < 60_000_000:
            raise HTTPException(400, "Ses kaydı boş ya da çok büyük.")

        def job(progress):
            return pipeline.set_voice(d, i, data, progress)
        return {"id": spawn(job)}

    @app.delete("/api/projects/{name}/clips/{i}/voice")
    def voice_del(name: str, i: int):
        d = _dir(name)
        return {"id": spawn(lambda progress: pipeline.set_voice(d, i, None, progress))}

    @app.post("/api/projects/{name}/clips/{i}/titles")
    def clip_titles(name: str, i: int):
        d = _dir(name)
        try:
            return reviewmod.ai_titles(d, i)
        except KeyError:
            raise HTTPException(404, "klip yok")
        except titlesmod.TitleError as e:
            raise HTTPException(400, str(e))

    @app.get("/api/titles-available")
    def titles_available():
        return {"available": titlesmod.available()}

    @app.post("/api/compile")
    def compile_(req: CompileReq):
        def job(progress):
            progress("compile", 0.1, "Derleme hazırlanıyor")
            return compilemod.build(root, req.n, req.status, req.title)
        return {"id": spawn(job, label="derleme")}

    @app.get("/api/storage")
    def storage():
        return cleanupmod.usage(root)

    @app.post("/api/cleanup")
    def cleanup(req: CleanupReq):
        items = cleanupmod.plan(root, req.days)
        total = sum(n for _, n in items)
        freed = cleanupmod.apply(items) if req.apply else 0
        return {"files": len(items), "bytes": total, "freed": freed, "applied": req.apply}

    # ---- review inbox, ready packages
    @app.get("/inbox", response_class=HTMLResponse)
    def inbox_page():
        return RedirectResponse("/#home")

    @app.get("/api/inbox")
    def inbox(status: str = "new"):
        return reviewmod.inbox(root, status)

    @app.post("/api/projects/{name}/clips/{i}/review")
    def review_clip(name: str, i: int, req: ReviewReq):
        d = _dir(name)
        try:
            rec = reviewmod.review(d, i, **req.model_dump())
            if rec.get("status") == "approved" and not rec.get("exported"):     # approved = ready package right away
                try:
                    reviewmod.export_pack(root, d, i, "shorts")
                    rec = pipeline.get_clip(pipeline.load(d), i)
                except Exception as e:  # noqa: BLE001
                    logmod.log.warning("otomatik paket hazırlanamadı: %s", e)
            return rec
        except KeyError:
            raise HTTPException(404, "klip yok")
        except ValueError as e:
            raise HTTPException(400, str(e))

    @app.post("/api/projects/{name}/clips/{i}/export")
    def export_clip(name: str, i: int, req: ExportReq):
        d = _dir(name)
        try:
            return reviewmod.export_pack(root, d, i, req.platform)
        except KeyError:
            raise HTTPException(404, "klip yok")
        except (ValueError, FileNotFoundError) as e:
            raise HTTPException(400, str(e))

    # ---- channels + queue
    @app.get("/api/channels")
    def channels():
        return watchmod.load_channels(root)

    @app.post("/api/channels")
    def channel_add(req: ChannelReq):
        try:
            opts = {"n": req.n, "max_height": req.max_height,
                    "layout": {"mode": req.layout, "cells": layoutmod.default_cells(req.layout)}}
            return watchmod.add_channel(root, req.url, min_minutes=req.min_minutes, backfill=req.backfill, options=opts)
        except ValueError as e:
            raise HTTPException(400, str(e))

    @app.delete("/api/channels")
    def channel_remove(url: str):
        return {"ok": watchmod.remove_channel(root, url)}

    @app.post("/api/projects/{name}/clips/{i}/save-profile")
    def save_profile(name: str, i: int):
        d = _dir(name)
        m = pipeline.load(d)
        try:
            rec = pipeline.get_clip(m, i)
            ch = watchmod.save_profile(root, m["slug"], rec["style"], rec["layout"], m.get("defaults", {}))
        except KeyError:
            raise HTTPException(404, f"'{m.get('slug')}' kanalı takip listende yok; önce \"Kanallar ve kuyruk\"tan ekle.")
        return {"channel": ch["name"]}

    @app.get("/api/queue")
    def queue_list():
        return watchmod.queue(root)

    @app.post("/api/queue/{iid}/{action}")
    def queue_action(iid: str, action: str):
        try:
            {"retry": watchmod.retry, "confirm": watchmod.confirm_audio, "rm": watchmod.remove_item}[action](root, iid)
        except (KeyError, TypeError):
            raise HTTPException(404, "kayıt/işlem yok")
        return {"ok": True}

    @app.post("/api/queue/run")
    def queue_run():
        """Scan the channels now and work through the queue (one task, shown like any other job)."""
        return {"id": spawn(queue_job, label="kuyruk")}

    auto = {"next": None, "last": None}

    def queue_job(progress):
        watchmod.recover_running(root)
        watchmod.scan(root)
        n = 0
        while watchmod.process_one(root, progress):
            n += 1
        return {"dir": str(root / "output"), "processed": n}

    def auto_loop():
        """Auto-watch: while the switch is on, scan the channels every `watch_hours` and process what is new."""
        while True:
            time.sleep(30)
            st = settingsmod.load()
            if not st["auto_watch"]:
                auto["next"] = None
                continue
            now = time.time()
            if auto["next"] is None:
                auto["next"] = now + 5
            if now >= auto["next"]:
                auto["next"] = now + st["watch_hours"] * 3600
                if not any(t.get("label") == "kuyruk" and t["status"] == "running" for t in tasks.values()):
                    auto["last"] = now
                    logmod.log.info("otomatik tarama başladı")
                    spawn(queue_job, label="kuyruk")

    threading.Thread(target=auto_loop, daemon=True).start()

    @app.get("/api/settings")
    def get_settings():
        return {**settingsmod.public(), "next_scan": auto["next"], "last_scan": auto["last"], "titles": titlesmod.available()}

    @app.put("/api/settings")
    def put_settings(req: SettingsReq):
        ch = req.model_dump(exclude_none=True)
        if "gemini_key" in ch:
            ch["gemini_key"] = ch["gemini_key"].strip()
        if ch.get("auto_watch") is False or "watch_hours" in ch:
            auto["next"] = None
        settingsmod.update(**ch)
        if "fast" in ch:
            logmod.set_gentle(not ch["fast"])          # applies to the next tools started, no restart needed
        return get_settings()

    @app.post("/api/projects/{name}/autometa")
    def run_autometa(name: str):
        d = _dir(name)
        return {"id": spawn(lambda progress: {"filled": autometa.fill(d), "dir": str(d)}, label="başlık/puan")}

    @app.post("/api/preview-style")
    def preview_style(req: PreviewReq):
        from .. import captions
        try:
            W, H = (720, 1280) if req.portrait else (1280, 720)
            im = captions.preview(req.style, W, H, req.text)
        except (ValueError, KeyError, TypeError) as e:
            raise HTTPException(400, str(e))
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=85)
        return Response(buf.getvalue(), media_type="image/jpeg")

    @app.delete("/api/projects/{name}/clips/{i}")
    def delete(name: str, i: int):
        d = _dir(name)
        try:
            pipeline.delete_clip(d, i)
        except KeyError:
            raise HTTPException(404, "klip yok")
        return {"ok": True}

    @app.post("/api/projects/{name}/add")
    def add(name: str, req: AddReq):
        d = _dir(name)

        def job(progress):
            if req.next:
                return pipeline.add_next(d, progress)
            if req.start is None or req.end is None:
                raise ValueError("start ve end gerekli")
            return pipeline.add_manual(d, req.start, req.end, progress)
        return {"id": spawn(job)}

    @app.get("/api/projects/{name}/clips/{i}/frame")
    def frame(name: str, i: int, t: float | None = None):
        d = _dir(name)
        try:
            rec = pipeline.get_clip(pipeline.load(d), i)
        except KeyError:
            raise HTTPException(404, "klip yok")
        t = max(0.0, (rec["end"] - rec["start"]) / 2 if t is None else t)
        out = d / "frames" / f"{rec['name']}_{int(t * 10)}.jpg"
        if not out.exists():
            src = d / rec["src"]
            if not src.exists():
                logmod.log.warning("kare istendi ama klip dosyası yok: %s", src)
                raise HTTPException(404, "klip dosyası bulunamadı (silinmiş olabilir)")
            out.parent.mkdir(exist_ok=True)
            p = logmod.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{t:.2f}", "-i", str(src),
                            "-frames:v", "1", "-q:v", "3", str(out)], f"kare {name}/{rec['name']}", timeout=60)
            if p.returncode or not out.exists():
                raise HTTPException(500, "kare çıkarılamadı: " + (p.stderr or "").strip()[-200:])
        return FileResponse(out, media_type="image/jpeg")

    (root / "ready").mkdir(exist_ok=True)
    app.mount("/files", StaticFiles(directory=root / "output"), name="files")
    app.mount("/ready", StaticFiles(directory=root / "ready"), name="ready")
    return app
