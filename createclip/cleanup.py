"""Disk cleanup that never touches finished work: only re-creatable files (raw padded footage, low-quality audio
download, frame thumbnails, rejected clips) of projects that are old enough and not protected.
A project is protected when its manifest has "keep": true. Clips, captions, chat logs, ready/ are never removed."""
import shutil
import time
from pathlib import Path

from . import pipeline
from .log import log

REMOVABLE = ("raw", "frames")           # directories
REMOVABLE_GLOB = ("audio_low.*",)       # files in the project root


def _size(p: Path) -> int:
    if p.is_file():
        return p.stat().st_size
    return sum(f.stat().st_size for f in p.rglob("*") if f.is_file())


def _newest(jd: Path) -> float:
    return max((f.stat().st_mtime for f in jd.rglob("*") if f.is_file()), default=0.0)


def projects(root: Path):
    for mp in sorted((Path(root) / "output").glob("*/manifest.json")):
        yield mp.parent


def usage(root: Path) -> list:
    out = []
    for jd in projects(root):
        try:
            m = pipeline.load(jd)
        except Exception:  # noqa: BLE001
            continue
        out.append({"name": jd.name, "title": m.get("title", ""), "keep": bool(m.get("keep")), "bytes": _size(jd),
                    "removable": sum(_size(p) for p in _targets(jd)), "age_days": round((time.time() - _newest(jd)) / 86400, 1)})
    return out


def _targets(jd: Path) -> list:
    t = [jd / d for d in REMOVABLE if (jd / d).exists()]
    for g in REMOVABLE_GLOB:
        t += list(jd.glob(g))
    try:
        m = pipeline.load(jd)
        if any(c.get("status") == "draft" for c in m.get("clips", [])):       # drafts play from their raw footage
            t = [p for p in t if p.name != "raw"]
        for c in m.get("clips", []):
            if c.get("status") == "rejected":
                t += [jd / c[k] for k in ("src", "base", "plain", "captioned", "overlaid", "voiced") if c.get(k) and (jd / c[k]).exists()]
    except Exception:  # noqa: BLE001
        pass
    return t


def plan(root: Path, days: float = 14.0) -> list:
    """[(path, bytes)] that would be removed: only from unprotected projects untouched for `days` days."""
    out = []
    for jd in projects(root):
        try:
            if pipeline.load(jd).get("keep"):
                continue
        except Exception:  # noqa: BLE001
            continue
        if time.time() - _newest(jd) < days * 86400:
            continue
        out += [(p, _size(p)) for p in _targets(jd)]
    return out


def apply(items: list) -> int:
    freed = 0
    for p, n in items:
        try:
            shutil.rmtree(p) if p.is_dir() else p.unlink()
            freed += n
            log.info("temizlendi: %s (%.1f MB)", p, n / 1e6)
        except OSError as e:
            log.warning("silinemedi %s: %s", p, e)
    return freed


def set_keep(root: Path, name: str, keep: bool = True):
    jd = Path(root) / "output" / name
    m = pipeline.load(jd)
    m["keep"] = keep
    pipeline.save(jd, m)
