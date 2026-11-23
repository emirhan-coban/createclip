"""Background job runner for the web app: one job at a time, a queue behind it, cancellation, and an
append-only event log per job (the UI replays it, so a page opened mid-run still shows the whole story)."""
import queue
import threading
import time

from . import config, download, editor, pipeline, proc, store
from .proc import log


class App:
    def __init__(self):
        self.jobs: list[dict] = []
        self.q: queue.Queue = queue.Queue()
        self.lock = threading.Lock()
        threading.Thread(target=self._worker, daemon=True).start()

    def _persist(self, job: dict):
        """Write the job's state to the history table. A failing write must never kill the worker thread."""
        try:
            con = store.connect()
            try:
                store.update_job(con, job["id"], status=job["status"], error=job.get("error"),
                                 run_started=job.get("run_started"), ended=job.get("ended"))
            finally:
                con.close()
        except Exception as e:  # noqa: BLE001
            log.warning("job history not saved: %s", e)

    def submit(self, kind: str, **kw) -> dict:
        now = time.time()
        con = store.connect()
        try:
            jid = store.add_job(con, kind, kw.get("url"), now)       # autoincrement id: never reused after a restart
        finally:
            con.close()
        job = {"id": jid, "kind": kind, "status": "queued", "log": [], "events": [], "started": now, **kw}
        with self.lock:
            self.jobs.append(job)
        self.q.put(job)
        return job

    def cancel(self, job_id: int) -> bool:
        """Queued job: dropped. Running job: its subprocesses are killed and the next step raises Cancelled."""
        with self.lock:
            job = next((j for j in self.jobs if j["id"] == job_id), None)
            if not job:
                return False
            if job["status"] == "queued":
                job["status"], job["error"], job["ended"] = "cancelled", "İptal edildi", time.time()
                self._persist(job)
                return True
            if job["status"] == "running":
                job["cancelling"] = True
                proc.request_cancel()
                return True
            return False

    def _worker(self):
        while True:
            job = self.q.get()
            if job["status"] == "cancelled":                  # cancelled while waiting in the queue
                continue
            proc.clear_cancel()
            job["status"] = "running"
            job["run_started"] = job["updated"] = time.time()
            self._persist(job)
            say = lambda m, job=job: job["log"].append(str(m))     # noqa: E731

            def emit(kind, **data):
                job["events"].append({"i": len(job["events"]), "t": round(time.time(), 2), "kind": kind, **data})

            def prog(frac, msg="", job=job):
                job["frac"], job["msg"], job["updated"] = round(max(0.0, min(1.0, frac)), 3), msg, time.time()
            con = None
            try:
                con = store.connect()
                cfg = config.load()
                if job["kind"] == "run":
                    cfg["skip_start_min"] = job.get("start_min") or 0
                    cfg["max_len"] = job.get("max_len") or cfg["max_len"]
                    ids = pipeline.process_video(con, cfg, job["url"], job.get("n"), job.get("at") or None,
                                                 job.get("engine") or None, say, prog, emit)
                    say(f"{len(ids)} klip hazır")
                elif job["kind"] == "source":                      # editor: fetch the footage around an older clip
                    editor.ensure_source(con, cfg, job["clip_id"], prog)
                    editor.source_info(store.get_clip(con, job["clip_id"]))
                    say("Kaynak hazır")
                elif job["kind"] == "transcribe":                  # editor: speech to text for captions
                    words = editor.transcribe_source(con, cfg, job["clip_id"], prog)
                    say(f"{len(words)} kelime")
                elif job["kind"] == "export":                      # editor: render the edit
                    saved = editor.export_clip(con, cfg, job["clip_id"], job["project"], prog)
                    emit("exported", id=job["clip_id"], file=saved.name)
                    say(f"Kaydedildi: {saved.name}")
                else:                                              # scan: watched channels
                    say(str(pipeline.watch_once(con, cfg, say, prog)))
                job["status"] = "done"
            except proc.Cancelled:
                job["status"], job["error"] = "cancelled", "İptal edildi"
            except download.BlockedError as e:
                job["status"], job["error"] = "blocked", str(e)
            except Exception as e:  # noqa: BLE001
                job["status"], job["error"] = "failed", str(e)
            finally:
                emit("end", status=job["status"], error=job.get("error"))
                proc.clear_cancel()
                if job["status"] == "done":
                    job["frac"], job["msg"] = 1.0, "Bitti"
                job["ended"] = time.time()
                self._persist(job)
                if con is not None:
                    con.close()
