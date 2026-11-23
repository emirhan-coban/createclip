"""Settings in <root>/autoshorts.json (optional; every key has a default)."""
import json
import os
from pathlib import Path

DEFAULTS = {
    "engine": "auto",          # auto | chat | audio | transcript(ClipsAI)
    "clips_per_video": 5,
    "min_len": 20,
    "max_len": 55,
    "lead": 12,                # seconds before the peak
    "skip_start_min": 10,      # ignore the first N minutes of a stream (crowded intro chat); 0 = use the whole stream
    "max_height": 1080,
    "source_pad": 30,          # seconds of extra footage kept around every clip so the editor can extend the cut
    "output_dir": "ready",     # finished clips are saved here (relative to the working folder), one subfolder per day
    "language": "tr",          # spoken language of the streams (Whisper), for captions
    "hashtags": ["#shorts"],
    "credit": True,            # put the source link in the description file
    "watch_every_min": 60,
    "smart_cut": "auto",       # snap cuts to sentence boundaries + title from speech (Whisper): auto = when the model is on disk
    "layout": "blur",          # layout of new clips: blur (blurred background) | face (camera on top, game below)
    "split": 0.4,              # face layout: share of the height given to the camera window (0.25-0.75)
    "keep_source_days": 14,    # source footage of clips with no saved edit is deleted after N days (0 = keep)
    "stall_min": 20,           # a job that makes no progress for N minutes is stopped (0 = never)
}
_root = Path.cwd()


def configure(root):
    global _root
    _root = Path(root)


def ui_dist() -> Path:
    """The built web app: bundled in the package (autoshorts/webdist, made by `autoshorts build-ui`) or the repo's web/dist."""
    here = Path(__file__).resolve().parent
    for d in (here / "webdist", here.parent / "web" / "dist"):
        if (d / "index.html").exists():
            return d
    return here.parent / "web" / "dist"


def root() -> Path:
    return _root


def path() -> Path:
    return _root / "autoshorts.json"


def data_dir() -> Path:
    d = _root / "data"
    d.mkdir(parents=True, exist_ok=True)
    return d


def load() -> dict:
    d = json.loads(json.dumps(DEFAULTS))
    p = path()
    if p.exists():
        try:
            d.update(json.loads(p.read_text()))
        except (ValueError, OSError):
            pass
    return d


def save(changes: dict) -> dict:
    cur = {}
    p = path()
    if p.exists():
        try:
            cur = json.loads(p.read_text())
        except ValueError:
            cur = {}
    cur.update(changes)
    p.write_text(json.dumps(cur, indent=2, ensure_ascii=False))
    os.chmod(p, 0o600)
    return load()
