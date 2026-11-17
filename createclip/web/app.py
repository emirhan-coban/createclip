import io
import shutil
import subprocess
import threading
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .. import layout as layoutmod, pipeline, transcribe

HTML = Path(__file__).with_name("index.html")


class JobReq(BaseModel):
    url: str
    n: int = 5
    captions: bool = True
    keep_plain: bool = True
    font: str = "montserrat"
    mask: bool = False
    layout: str = "none"
    source: str = "auto"
    at: list[str] = Field(default_factory=list)
    snap: bool = True
    vocab: str = ""
    full_chat: bool = False
    style: dict = Field(default_factory=dict)     # size, ypos, chunk, active, color, stroke, upper, sync ...
    min_len: float = 25
    max_len: float = 60
    lead: float = 20
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


class AddReq(BaseModel):
    next: bool = False
    start: float | None = None
    end: float | None = None


def make_app(root: Path) -> FastAPI:
    root = Path(root)
    (root / "output").mkdir(parents=True, exist_ok=True)
    app = FastAPI(title="createclip")
    tasks: dict[str, dict] = {}
    busy = threading.Lock()   # one heavy task at a time (whisper + ffmpeg)

    def spawn(fn, *a, **kw) -> str:
        tid = uuid.uuid4().hex[:8]
        t = tasks[tid] = {"status": "running", "stage": "queued", "frac": 0, "msg": "Sırada"}

        def prog(stage, frac, msg=""):
            t.update(stage=stage, frac=round(frac, 3), msg=msg)

        def work():
            try:
                with busy:
                    res = fn(*a, progress=prog, **kw)
                t.update(status="done", result=res)
            except Exception as e:  # noqa: BLE001
                t.update(status="error", error=str(e))

        threading.Thread(target=work, daemon=True).start()
        return tid

    def _dir(name: str) -> Path:
        d = root / "output" / name
        if "/" in name or ".." in name or not (d / "manifest.json").exists():
            raise HTTPException(404, "proje bulunamadı")
        return d

    @app.get("/", response_class=HTMLResponse)
    def index():
        return HTML.read_text()

    @app.get("/api/tasks/{tid}")
    def task(tid: str):
        if tid not in tasks:
            raise HTTPException(404)
        return tasks[tid]

    @app.post("/api/jobs")
    def create(req: JobReq):
        o = pipeline.Options(
            n=req.n, captions=req.captions, keep_plain=req.keep_plain,
            style={**req.style, "font": req.font, "mask": req.mask},
            min_len=req.min_len, max_len=req.max_len, lead=req.lead, max_height=req.max_height,
            layout={"mode": req.layout, "cells": layoutmod.default_cells(req.layout)},
            source=req.source, at=req.at, snap=req.snap, vocab=req.vocab, full_chat=req.full_chat)

        def job(progress):
            m = pipeline.run(req.url, root, o, progress)
            return {"dir": Path(m["dir"]).name}
        return {"id": spawn(job)}

    @app.get("/api/projects")
    def projects():
        out = []
        for d in sorted((root / "output").glob("*/manifest.json"), key=lambda p: -p.stat().st_mtime):
            try:
                m = pipeline.load(d.parent)
                out.append({"name": d.parent.name, "title": m["title"], "slug": m["slug"],
                            "clips": len(m["clips"])})
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
        shutil.rmtree(d)
        return {"ok": True}

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
        out.parent.mkdir(exist_ok=True)
        if not out.exists():
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{t:.2f}", "-i", str(d / rec["src"]),
                            "-frames:v", "1", "-q:v", "3", str(out)], check=True)
        return FileResponse(out, media_type="image/jpeg")

    app.mount("/files", StaticFiles(directory=root / "output"), name="files")
    return app
