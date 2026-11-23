"""FastAPI server for the React app in web/: JSON API, live job events (SSE), range-capable media, and the built
front end (web/dist). Safety: bound to 127.0.0.1, local Host headers only, JSON-only POSTs."""
import asyncio
import contextlib
import json
import re
import subprocess
import sys
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import config, download, editor, faces, store
from .jobs import App

def _clip_json(c: dict) -> dict:
    return {"id": c["id"], "status": c["status"], "score": c["score"], "start": c["start"], "end": c["end"],
            "title": c["title"] or "", "description": c["description"] or "", "video_title": c["video_title"] or "",
            "video_url": c["video_url"], "engine": c["engine"], "error": c["error"], "has_file": bool(c["file"] and Path(c["file"]).exists()),
            "file": Path(c["file"]).name if c["file"] else "", "created": c["created"]}


DIST = config.ui_dist()
LOCAL_HOSTS = {"127.0.0.1", "localhost", "[::1]", "testserver"}


def _public_job(j: dict) -> dict:
    return {k: v for k, v in j.items() if k not in ("log", "events")} | {"log": j["log"][-30:], "events": len(j["events"]), "live": True}


def _history_job(r: dict) -> dict:
    """A job from before the current server start: status only, no event log to replay."""
    return {"id": r["id"], "kind": r["kind"], "url": r["url"], "status": r["status"], "error": r["error"],
            "started": r["started"], "run_started": r["run_started"], "ended": r["ended"], "log": [], "events": 0, "live": False}


# editable settings: name -> validator returning the cleaned value (raises ValueError)
def _num(lo, hi, cast=float):
    def check(v):
        v = cast(v)
        if not lo <= v <= hi:
            raise ValueError(f"{lo}–{hi} arası olmalı")
        return v
    return check


def _engine(v):
    if v not in ("auto", "chat", "audio", "transcript"):
        raise ValueError("auto, chat, audio ya da transcript olmalı")
    return v


def _choice(v, allowed):
    if v not in allowed:
        raise ValueError("geçersiz seçenek")
    return v


def _text(v):
    v = str(v).strip()
    if not v or len(v) > 300:
        raise ValueError("boş olamaz")
    return v


def _dir(v):
    v = _text(v)
    if ".." in Path(v).parts:
        raise ValueError("'..' içeremez; tam yol ya da proje klasörüne göre kısa bir yol yaz")
    return v


def _tags(v):
    if not isinstance(v, list) or len(v) > 10:
        raise ValueError("en çok 10 etiket")
    return [("#" + t.lstrip("#")) for t in (str(x).strip() for x in v) if t]


EDITABLE = {"engine": _engine, "clips_per_video": _num(1, 20, int), "min_len": _num(10, 120, int), "max_len": _num(15, 180, int),
            "lead": _num(0, 60, int), "skip_start_min": _num(0, 600), "output_dir": _dir, "hashtags": _tags,
            "credit": lambda v: bool(v),
            "layout": lambda v: _choice(v, ("blur", "face")), "split": _num(0.25, 0.75), "keep_source_days": _num(0, 365, int),
            "stall_min": _num(0, 240, int), "power": lambda v: _choice(v, ("eco", "normal"))}


@contextlib.contextmanager
def db():
    """A database connection that is always closed, even when the handler raises."""
    con = store.connect()
    try:
        yield con
    finally:
        con.close()


async def read_json(request: Request) -> dict:
    """The JSON object in the request body; anything else is a clear 400 instead of a 500."""
    try:
        b = await request.json()
    except ValueError:
        raise HTTPException(400, "İstek gövdesi geçerli JSON değil.") from None
    if not isinstance(b, dict):
        raise HTTPException(400, "İstek gövdesi bir JSON nesnesi olmalı.")
    return b


def _bounded(b: dict, key: str, lo: float, hi: float, cast=float, default=0):
    """b[key] as a number inside [lo, hi]; wrong type or out of range -> 400."""
    v = b.get(key)
    if v in (None, ""):
        return default
    try:
        v = cast(v)
    except (TypeError, ValueError):
        raise HTTPException(400, f"{key}: sayı olmalı") from None
    if not lo <= v <= hi:
        raise HTTPException(400, f"{key}: {lo:g}–{hi:g} arası olmalı")
    return v


def create_app(jobs: App | None = None) -> FastAPI:
    jobs = jobs or App()
    app = FastAPI(title="autoshorts", docs_url=None, redoc_url=None)

    @app.middleware("http")
    async def guard(request: Request, call_next):
        host = request.headers.get("host", "")
        host = host.split("]")[0] + "]" if host.startswith("[") else host.rsplit(":", 1)[0]
        if host not in LOCAL_HOSTS:
            return JSONResponse({"error": "forbidden host"}, 403)
        if request.method in ("POST", "PUT") and "application/json" not in request.headers.get("content-type", ""):
            return JSONResponse({"error": "forbidden"}, 403)          # blocks cross-site form posts
        return await call_next(request)

    def clip_row(cid: int) -> dict:
        con = store.connect()
        try:
            c = store.get_clip(con, cid)
        finally:
            con.close()
        if not c:
            raise HTTPException(404, "not found")
        return c

    # ---------------------------------------------------------------- state
    @app.get("/api/state")
    def state():
        import time
        con = store.connect()
        try:
            cfg = config.load()
            mem = jobs.jobs[-20:]
            seen = {j["id"] for j in jobs.jobs}
            old = [_history_job(r) for r in store.recent_jobs(con, 20) if r["id"] not in seen]
            merged = sorted([_public_job(j) for j in mem] + old, key=lambda j: -j["id"])[:20]
            return {"now": time.time(), "jobs": merged,
                    "clips": [_clip_json(c) for c in store.clips(con)][::-1], "sources": store.sources(con),
                    "config": {k: cfg[k] for k in EDITABLE},
                    "output": str(config.root() / cfg["output_dir"])}
        finally:
            con.close()

    @app.post("/api/config")
    async def set_config(request: Request):
        b = await read_json(request)
        changes, errors = {}, {}
        for k, v in b.items():
            if k not in EDITABLE:
                errors[k] = "bilinmeyen ayar"
                continue
            try:
                changes[k] = EDITABLE[k](v)
            except (ValueError, TypeError) as e:
                errors[k] = str(e)
        if errors:
            raise HTTPException(400, "; ".join(f"{k}: {m}" for k, m in errors.items()))
        cfg = config.save(changes)
        return {"config": {k: cfg[k] for k in EDITABLE}}

    # ---------------------------------------------------------------- jobs
    @app.post("/api/run")
    async def run(request: Request):
        b = await read_json(request)
        url = str(b.get("url", "")).strip()
        if not re.match(r"https?://", url):
            raise HTTPException(400, "Geçerli bir link gir (https://…).")
        raw_at = b.get("at") or []
        if not isinstance(raw_at, list):
            raise HTTPException(400, "at: liste olmalı")
        at = [str(a).strip() for a in raw_at if str(a).strip()][:20]
        job = jobs.submit("run", url=url, n=_bounded(b, "n", 1, 20, int, None), start_min=_bounded(b, "start_min", 0, 600),
                          engine=b.get("engine") if b.get("engine") in ("auto", "chat", "audio", "transcript") else None,
                          at=at, max_len=_bounded(b, "max_len", 15, 180, float, None))
        return {"id": job["id"]}

    @app.post("/api/scan")
    async def scan():
        return {"id": jobs.submit("scan")["id"]}

    @app.post("/api/jobs/{job_id}/cancel")
    async def cancel(job_id: int):
        return {"ok": jobs.cancel(job_id)}

    @app.get("/api/jobs/{job_id}/events")
    async def events(job_id: int, request: Request, after: int = -1):
        """Server-sent events: replays the job's event log from `after`, then follows it until the job ends."""
        job = next((j for j in jobs.jobs if j["id"] == job_id), None)
        if not job:
            raise HTTPException(404, "not found")
        last_header = request.headers.get("last-event-id")
        start = int(last_header) + 1 if last_header and last_header.isdigit() else after + 1

        async def gen():
            i, idle = start, 0
            while True:
                if await request.is_disconnected():
                    return
                evs = job["events"]
                while i < len(evs):
                    e = evs[i]
                    yield f"id: {i}\ndata: {json.dumps(e, ensure_ascii=False)}\n\n"
                    i += 1
                    idle = 0
                    if e["kind"] == "end":
                        return
                idle += 1
                if idle % 50 == 0:
                    yield ": keep-alive\n\n"
                await asyncio.sleep(0.3)
        return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-store"})

    # ---------------------------------------------------------------- sources
    @app.post("/api/sources")
    async def add_source(request: Request):
        b = await read_json(request)
        url = download.normalize_channel(str(b.get("url", "")).strip())
        if not url.startswith("http"):
            raise HTTPException(400, "Kanal linki anlaşılamadı.")
        backfill = _bounded(b, "backfill", 0, 20, int, 3)
        with db() as con:
            store.add_source(con, url, backfill=backfill)
        return {"ok": True}

    @app.post("/api/sources/delete")
    async def del_source(request: Request):
        b = await read_json(request)
        with db() as con:
            store.remove_source(con, str(b.get("url", "")))
        return {"ok": True}

    # ---------------------------------------------------------------- clips
    @app.post("/api/clips/{cid}/edit")
    async def edit(cid: int, request: Request):
        c, b = clip_row(cid), await read_json(request)
        title, desc = str(b.get("title", c["title"]))[:200], str(b.get("description", c["description"]))[:5000]
        with db() as con:
            store.update_clip(con, cid, title=title, description=desc)
        f = Path(c["file"]) if c["file"] else None
        if f and f.parent.exists():
            f.with_suffix(".txt").write_text(f"{title}\n\n{desc}\n", encoding="utf-8")
        return {"ok": True}

    @app.post("/api/clips/{cid}/delete")
    async def delete(cid: int):
        c = clip_row(cid)
        f = Path(c["file"]) if c["file"] else None
        if f:
            for ext in (".mp4", ".jpg", ".txt"):
                f.with_suffix(ext).unlink(missing_ok=True)
        with db() as con:
            store.update_clip(con, cid, status="deleted", file=None)
        return {"ok": True}

    @app.post("/api/clips/{cid}/reveal")
    async def reveal(cid: int):
        c = clip_row(cid)
        if c["file"] and Path(c["file"]).exists() and sys.platform == "darwin":
            subprocess.run(["open", "-R", c["file"]], check=False)
        return {"ok": True}

    @app.get("/media/{cid}.{ext}")
    def media(cid: int, ext: str):
        if ext not in ("mp4", "jpg"):
            raise HTTPException(404, "not found")
        c = clip_row(cid)
        f = Path(c["file"]) if c["file"] else None
        f = f.with_suffix("." + ext) if f else None
        if not f or not f.exists():
            raise HTTPException(404, "file missing")
        return FileResponse(f)                         # Starlette answers Range requests, so seeking works

    # ---------------------------------------------------------------- editor
    @app.get("/api/clips/{cid}/editor")
    def editor_state(cid: int):
        c = clip_row(cid)
        info = editor.source_info(c)
        con = store.connect()
        try:
            proj = store.get_project(con, cid)
        finally:
            con.close()
        if info and not proj:
            proj = editor.default_project(c)
        return {"clip": _clip_json(c), "source": ({**info, "start": c["src_start"], "end": c["src_end"]} if info else None),
                "project": proj}

    @app.get("/api/clips/{cid}/assets")
    def editor_assets(cid: int):
        c = clip_row(cid)
        src = editor.source_path(c)
        info = editor.source_info(c)
        if not src or not info:
            raise HTTPException(404, "Kaynak görüntü yok")
        return {"strip": editor.filmstrip(cid, src, info["duration"]), "wave": editor.waveform(cid, src)}

    @app.get("/api/storage")
    def storage():
        con = store.connect()
        try:
            return editor.storage_usage(con)
        finally:
            con.close()

    @app.post("/api/storage/clean")
    async def storage_clean():
        con = store.connect()
        try:
            return editor.clean_sources(con)
        finally:
            con.close()

    @app.get("/api/faces/status")
    def faces_status():
        return {"available": faces.available()}

    @app.post("/api/clips/{cid}/faces")
    async def start_faces(cid: int):
        c = clip_row(cid)
        if not editor.source_path(c):
            raise HTTPException(409, "Kaynak görüntü yok")
        if not faces.available():
            raise HTTPException(409, "Yüz bulmak için OpenCV gerekli: ./.venv/bin/pip install -e '.[faces]'")
        return {"id": jobs.submit("faces", clip_id=cid)["id"]}

    @app.get("/api/clips/{cid}/face-layout")
    def face_layout(cid: int, split: float = 0.4, top: str = "face"):
        """The two-window layout for the camera found in this clip (404 when none was found yet)."""
        c = clip_row(cid)
        info = editor.source_info(c)
        face = faces.load(editor.editor_dir(cid) / "face.json")
        if not info or not face:
            raise HTTPException(404, "Kamera bulunamadı")
        return {"face": face, "layout": editor.face_layout(face, info["width"], info["height"], split, "game" if top == "game" else "face")}

    @app.post("/api/clips/{cid}/source")
    async def fetch_source(cid: int):
        clip_row(cid)
        return {"id": jobs.submit("source", clip_id=cid)["id"]}

    @app.put("/api/clips/{cid}/project")
    async def save_project(cid: int, request: Request):
        c = clip_row(cid)
        info = editor.source_info(c)
        if not info:
            raise HTTPException(409, "Kaynak görüntü yok")
        try:
            proj = editor.clean_project(await read_json(request), info["duration"])
        except (ValueError, TypeError) as e:
            raise HTTPException(400, str(e))
        with db() as con:
            store.save_project(con, cid, proj)
        return {"project": proj}

    @app.post("/api/clips/{cid}/export")
    async def export_clip(cid: int, request: Request):
        c = clip_row(cid)
        info = editor.source_info(c)
        if not info:
            raise HTTPException(409, "Kaynak görüntü yok")
        try:
            proj = editor.clean_project(await read_json(request), info["duration"])
        except (ValueError, TypeError) as e:
            raise HTTPException(400, str(e))
        return {"id": jobs.submit("export", clip_id=cid, project=proj)["id"]}

    @app.get("/media/source/{cid}.mp4")
    def media_source(cid: int):
        f = editor.source_path(clip_row(cid))
        if not f:
            raise HTTPException(404, "file missing")
        return FileResponse(f)

    @app.get("/media/strip/{cid}.jpg")
    def media_strip(cid: int):
        f = editor.editor_dir(cid) / "strip.jpg"
        if not f.exists():
            raise HTTPException(404, "file missing")
        return FileResponse(f)

    # ---------------------------------------------------------------- front end
    if (DIST / "assets").exists():
        app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{path:path}")
    def spa(path: str):
        if path.startswith("api/"):
            raise HTTPException(404, "not found")
        f = (DIST / path).resolve()
        if path and DIST in f.parents and f.is_file():
            return FileResponse(f)
        index = DIST / "index.html"
        if index.exists():
            return FileResponse(index)
        return JSONResponse({"error": "Arayüz derlenmemiş: cd web && npm install && npm run build"}, 404)

    return app


def serve(port: int = 8765, open_browser: bool = False):
    import uvicorn
    url = f"http://127.0.0.1:{port}"
    print(f"Arayüz: {url}   (Ctrl-C ile durdur)")
    if open_browser and sys.platform == "darwin":
        subprocess.run(["open", url], check=False)
    uvicorn.run(create_app(), host="127.0.0.1", port=port, log_level="warning")
