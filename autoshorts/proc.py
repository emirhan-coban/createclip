"""Subprocess helper used for every external tool (yt-dlp, ffmpeg, curl).

Each command runs in its own process group and the whole group is killed on timeout. yt-dlp starts ffmpeg as a
child; killing only yt-dlp leaves ffmpeg holding the output pipes open and the caller hangs forever (seen in
practice with a stalled Kick HLS download)."""
import logging
import os
import shlex
import signal
import subprocess
import threading
import time

log = logging.getLogger("autoshorts")


class Cancelled(Exception):
    """The user cancelled the running job. Deliberately not a RuntimeError: broad `except RuntimeError` fallbacks
    (e.g. chat -> audio) must not swallow it."""


_hook = None            # callable(level, text) set by the job runner: the UI's terminal shows every command we run


def set_log_hook(fn):
    global _hook
    _hook = fn


def _say(level: str, text: str):
    h = _hook
    if h:
        try:
            h(level, text)
        except Exception:  # noqa: BLE001 - a broken display must never break the work
            pass


say = _say              # public name for modules that report progress of their own requests (Kick chat crawler)

_procs: set = set()
_lock = threading.Lock()
_cancel = threading.Event()


def check_cancel():
    if _cancel.is_set():
        raise Cancelled("İptal edildi")


def request_cancel():
    """Stop the running job: later steps raise Cancelled and every running subprocess group is killed."""
    _cancel.set()
    with _lock:
        for p in list(_procs):
            _kill(p)


def clear_cancel():
    _cancel.clear()


def _kill(p: subprocess.Popen):
    try:
        os.killpg(p.pid, signal.SIGKILL)
    except (OSError, ProcessLookupError):
        try:
            p.kill()
        except OSError:
            pass


def run(cmd: list, what: str, timeout: float | None = None, on_line=None) -> subprocess.CompletedProcess:
    """Run `cmd`, capture text output, log the outcome. Raises subprocess.TimeoutExpired after killing the group.
    With `on_line`, stdout+stderr are merged and every line is passed to the callback while the command runs."""
    check_cancel()
    t0 = time.time()
    log.debug("%s: %s", what, " ".join(str(c) for c in cmd)[:300])
    _say("cmd", "$ " + " ".join(shlex.quote(str(c)) for c in cmd)[:260])
    proc = subprocess.Popen([str(c) for c in cmd], stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT if on_line else subprocess.PIPE, text=True, start_new_session=True)
    with _lock:
        _procs.add(proc)
    timed_out = []
    timer = None
    if on_line and timeout:
        timer = threading.Timer(timeout, lambda: (timed_out.append(1), _kill(proc)))
        timer.start()
    try:
        if on_line:
            lines = []
            for line in proc.stdout:
                lines.append(line)
                on_line(line.rstrip("\r\n"))
            proc.stdout.close()
            proc.wait()
            out = err = "".join(lines)
            if timed_out:
                raise subprocess.TimeoutExpired(cmd, timeout)
        else:
            out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        _kill(proc)
        if on_line:
            proc.wait()                    # stdout is already drained and closed
        else:
            proc.communicate()
        log.error("%s: timeout (%ss)", what, timeout)
        _say("err", f"✗ {what}: zaman aşımı ({timeout:g} sn)")
        raise
    finally:
        if timer:
            timer.cancel()
        with _lock:
            _procs.discard(proc)
    check_cancel()
    p = subprocess.CompletedProcess(cmd, proc.returncode, out, err)
    dt = time.time() - t0
    if p.returncode:
        log.warning("%s: exit %s (%.1fs) %s", what, p.returncode, dt, (err or "").strip()[-300:])
        _say("warn", f"✗ {what}: çıkış kodu {p.returncode} · {dt:.1f} sn · " + " ".join((err or "").strip().split())[-200:])
    else:
        log.info("%s: ok (%.1fs)", what, dt)
        _say("ok", f"✓ {what} · {dt:.1f} sn")
    return p


def run_ok(cmd: list, what: str, timeout: float | None = None) -> subprocess.CompletedProcess:
    p = run(cmd, what, timeout=timeout)
    if p.returncode:
        raise RuntimeError(f"{what} failed: {(p.stderr or '').strip()[-300:]}")
    return p
