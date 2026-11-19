"""User settings kept in <root>/settings.json (mode 0600): API keys typed into the web UI and the auto-watch switch.
Environment variables still win, so a terminal-exported key keeps working."""
import json
import os
from pathlib import Path

DEFAULTS = {"gemini_key": "", "auto_watch": False, "watch_hours": 3.0}
_root: Path | None = None


def configure(root: Path):
    global _root
    _root = Path(root)


def _path() -> Path | None:
    return _root / "settings.json" if _root else None


def load() -> dict:
    p = _path()
    d = dict(DEFAULTS)
    if p and p.exists():
        try:
            d.update(json.loads(p.read_text()))
        except (ValueError, OSError):
            pass
    return d


def get(key: str):
    return load().get(key, DEFAULTS.get(key))


def update(**changes) -> dict:
    p = _path()
    if not p:
        raise RuntimeError("Ayar dosyası için kök klasör ayarlanmadı.")
    d = load()
    for k, v in changes.items():
        if k in DEFAULTS and v is not None:
            d[k] = v
    d["watch_hours"] = min(24.0, max(0.5, float(d["watch_hours"])))
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.write(json.dumps(d, ensure_ascii=False, indent=1))
    os.replace(tmp, p)
    return d


def public() -> dict:
    """What the UI may see: never the key itself."""
    d = load()
    k = d.get("gemini_key") or ""
    return {"gemini_set": bool(k or os.environ.get("GEMINI_API_KEY")), "gemini_hint": ("…" + k[-4:]) if len(k) > 8 else "",
            "auto_watch": bool(d["auto_watch"]), "watch_hours": d["watch_hours"]}
