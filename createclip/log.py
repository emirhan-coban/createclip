"""Logging: everything goes to <root>/output/createclip.log (rotating) and, per web task, into a ring buffer
the UI shows live. `run()` wraps subprocesses so every external command leaves cmd, exit code, time, stderr tail."""
import logging
import logging.handlers
import subprocess
import threading
import time
from pathlib import Path

NAME = "createclip"
log = logging.getLogger(NAME)
_FMT = logging.Formatter("%(asctime)s %(levelname)-7s %(message)s", "%H:%M:%S")
_set_up = [None]


def setup(root: Path, verbose: bool = False) -> Path:
    """Idempotent. Returns the log file path."""
    path = Path(root) / "output" / "createclip.log"
    if _set_up[0] == path:
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    log.setLevel(logging.DEBUG)
    for h in list(log.handlers):
        if getattr(h, "_cc", False):
            log.removeHandler(h)
    fh = logging.handlers.RotatingFileHandler(path, maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    fh.setFormatter(_FMT)
    fh._cc = True
    log.addHandler(fh)
    if verbose:
        sh = logging.StreamHandler()
        sh.setFormatter(_FMT)
        sh.setLevel(logging.INFO)
        sh._cc = True
        log.addHandler(sh)
    _set_up[0] = path
    return path


class TaskBuffer(logging.Handler):
    """Collects log lines of one thread (one web task) into a bounded list."""

    def __init__(self, lines: list, limit: int = 400):
        super().__init__(logging.INFO)
        self.lines, self.limit, self.tid = lines, limit, threading.get_ident()
        self.setFormatter(_FMT)

    def emit(self, record):
        if record.thread == self.tid:
            self.lines.append(self.format(record))
            del self.lines[:-self.limit]


def tail(path: Path, n: int = 200) -> str:
    try:
        return "\n".join(Path(path).read_text(encoding="utf-8", errors="replace").splitlines()[-n:])
    except OSError:
        return ""


class Cancelled(RuntimeError):
    """The user pressed "İptal"; raised between steps and after a killed subprocess."""


_procs: set = set()
_proc_lock = threading.Lock()
_cancel = threading.Event()


def cancel_requested() -> bool:
    return _cancel.is_set()


def request_cancel():
    """Ask the running job to stop: later steps raise Cancelled, running subprocesses are killed."""
    _cancel.set()
    with _proc_lock:
        for p in list(_procs):
            try:
                p.kill()
            except OSError:
                pass


def clear_cancel():
    _cancel.clear()


def check_cancel():
    if _cancel.is_set():
        raise Cancelled("İptal edildi")


def run(cmd: list, what: str, timeout: float | None = None, **kw) -> subprocess.CompletedProcess:
    """subprocess.run(capture_output, text) + logging. Timeouts are logged and re-raised; the process can be
    killed by request_cancel()."""
    check_cancel()
    t0 = time.time()
    log.debug("%s: %s", what, " ".join(str(c) for c in cmd)[:300])
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, **kw)
    with _proc_lock:
        _procs.add(proc)
    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.communicate()
        log.error("%s: zaman aşımı (%ss)", what, timeout)
        raise
    finally:
        with _proc_lock:
            _procs.discard(proc)
    p = subprocess.CompletedProcess(cmd, proc.returncode, out, err)
    check_cancel()
    dt = time.time() - t0
    if p.returncode:
        log.warning("%s: çıkış kodu %s (%.1fs) %s", what, p.returncode, dt, (p.stderr or "").strip()[-300:])
    else:
        log.info("%s: tamam (%.1fs)", what, dt)
    return p


def run_ok(cmd: list, what: str, timeout: float | None = None) -> subprocess.CompletedProcess:
    """run() that raises RuntimeError (with the ffmpeg error tail) when the command fails."""
    p = run(cmd, what, timeout=timeout)
    if p.returncode:
        raise RuntimeError(f"{what} başarısız: {(p.stderr or '').strip()[-300:]}")
    return p
