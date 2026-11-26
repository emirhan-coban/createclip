"""Background job runner for the web app: one job at a time, a queue behind it, cancellation, and an
append-only event log per job (the UI replays it, so a page opened mid-run still shows the whole story)."""
import queue
import re
import threading
import time

from . import config, download, editor, pipeline, power, proc, publish, store
from .proc import log


MAX_EVENTS = 4000


class App:
    def __init__(self):
        self.jobs: list[dict] = []
        self.q: queue.Queue = queue.Queue()
        self.lock = threading.Lock()
        self._say_now = None                 # log function of the running job, for the watchdog
        threading.Thread(target=self._worker, daemon=True).start()
        threading.Thread(target=self._watchdog, daemon=True).start()

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

    def _watchdog(self):
        """Warn when a running job shows no sign of life, and stop it after `stall_min` minutes (a stuck download
        otherwise blocks the single worker for ever)."""
        warned = None
        while True:
            time.sleep(self.WATCH_EVERY)
            with self.lock:
                job = next((j for j in self.jobs if j["status"] == "running"), None)
            if not job or not self._say_now:
                warned = None
                continue
            idle = time.time() - max(job.get("updated") or 0, job.get("run_started") or 0)
            limit = float(config.load().get("stall_min", 20)) * 60
            if limit and idle >= limit and not job.get("cancelling"):
                self._say_now("err", f"✗ {idle / 60:.0f} dk'dır ilerleme yok, iş durduruluyor")
                job["stalled"] = idle
                job["cancelling"] = True
                proc.request_cancel()
            elif idle >= self.WARN_AFTER and warned != job["id"]:
                warned = job["id"]
                self._say_now("warn", f"⚠ {idle / 60:.0f} dk'dır ilerleme yok; indirme ya da dönüştürme takılmış olabilir")

    WATCH_EVERY = 30
    WARN_AFTER = 300

    def _worker(self):
        while True:
            job = self.q.get()
            if job["status"] == "cancelled":                  # cancelled while waiting in the queue
                continue
            proc.clear_cancel()
            job["status"] = "running"
            job["run_started"] = job["updated"] = time.time()
            self._persist(job)

            def emit(kind, **data):
                if kind == "log" and len(job["events"]) > MAX_EVENTS:      # a runaway log must not eat memory
                    return
                job["events"].append({"i": len(job["events"]), "t": round(time.time(), 2), "kind": kind, **data})

            def log_line(level, text):
                emit("log", level=level, text=str(text)[:400])

            def say(m, job=job):
                job["log"].append(str(m))
                log_line("info", m)

            seen = {"phase": None, "t": 0.0}

            def prog(frac, msg="", job=job):
                job["frac"], job["msg"], job["updated"] = round(max(0.0, min(1.0, frac)), 3), msg, time.time()
                # progress ticks into the terminal: at once when the step changes, otherwise at most every 8 s
                phase = re.sub(r"[\d%.,/]+", "", msg)[:48]
                if msg and (phase != seen["phase"] or time.time() - seen["t"] >= 8):
                    seen["phase"], seen["t"] = phase, time.time()
                    log_line("step", msg)
            proc.set_log_hook(log_line)
            self._say_now = log_line
            log_line("info", f"iş #{job['id']} başladı ({job['kind']})")
            con = None
            try:
                con = store.connect()
                cfg = config.load()
                power.apply(cfg)
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
                elif job["kind"] == "faces":                       # editor: find the camera for the two-window layout
                    face = editor.find_face(con, cfg, job["clip_id"], prog)
                    say("Kamera bulundu" if face else "Kamera bulunamadı")
                elif job["kind"] == "export":                      # editor: render the edit
                    saved = editor.export_clip(con, cfg, job["clip_id"], job["project"], prog)
                    emit("exported", id=job["clip_id"], file=saved.name)
                    say(f"Kaydedildi: {saved.name}")
                elif job["kind"] == "upload":                      # one clip to YouTube, asked for by the user
                    r = publish.publish_clip(con, cfg, job["clip_id"], job.get("when") or "slot", prog)
                    when = time.strftime("%d.%m %H:%M", time.localtime(r["publish_at"])) if r["publish_at"] else "hemen"
                    say(f"YouTube'a yüklendi (yayın: {when}): https://youtu.be/{r['id']}")
                else:                                              # scan: watched channels
                    say(str(pipeline.watch_once(con, cfg, say, prog)))
                job["status"] = "done"
            except proc.Cancelled:
                if job.get("stalled"):
                    job["status"], job["error"] = "failed", f"Takıldı: {job['stalled'] / 60:.0f} dakikadır ilerleme yoktu."
                else:
                    job["status"], job["error"] = "cancelled", "İptal edildi"
            except download.BlockedError as e:
                job["status"], job["error"] = "blocked", str(e)
            except Exception as e:  # noqa: BLE001
                job["status"], job["error"] = "failed", str(e)
            finally:
                proc.set_log_hook(None)
                self._say_now = None
                if job["kind"] in ("run", "scan") and con is not None:         # tidy old footage after the big jobs
                    try:
                        editor.clean_old_sources(con, float(config.load().get("keep_source_days", 14)))
                    except Exception as e:  # noqa: BLE001
                        log.warning("source cleanup skipped: %s", e)
                if job["status"] == "done":
                    log_line("ok", "✓ bitti")
                else:
                    word = {"cancelled": "iptal edildi", "blocked": "platform engelledi", "failed": "hata"}.get(job["status"], job["status"])
                    log_line("err" if job["status"] in ("failed", "blocked") else "info",
                             f"✗ {word}" + (f": {job['error']}" if job.get("error") and job["status"] != "cancelled" else ""))
                emit("end", status=job["status"], error=job.get("error"))
                proc.clear_cancel()
                if job["status"] == "done":
                    job["frac"], job["msg"] = 1.0, "Bitti"
                job["ended"] = time.time()
                self._persist(job)
                if con is not None:
                    con.close()
