"""Final step: a finished clip is saved into the output folder (default <root>/ready/<date>/) next to a .txt with the
title and description, ready to upload by hand wherever you want."""
import re
import shutil
from datetime import date
from pathlib import Path

from . import config


def _safe(s: str) -> str:
    return re.sub(r"[^\w.-]+", "-", s).strip("-")[:40] or "clip"


def save(cfg: dict, clip_id: int, channel: str, start: float, video: Path, thumb: Path | None,
         title: str, description: str) -> Path:
    out = Path(cfg["output_dir"])
    out = out if out.is_absolute() else config.root() / out
    out = out / date.today().isoformat()
    out.mkdir(parents=True, exist_ok=True)
    t = int(start)
    stem = f"{_safe(channel)}_{t // 3600:02d}h{t % 3600 // 60:02d}m{t % 60:02d}s_{clip_id}"
    dest = out / f"{stem}.mp4"
    shutil.copy2(video, dest)
    if thumb and Path(thumb).exists():
        shutil.copy2(thumb, out / f"{stem}.jpg")
    (out / f"{stem}.txt").write_text(f"{title}\n\n{description}\n", encoding="utf-8")
    return dest
