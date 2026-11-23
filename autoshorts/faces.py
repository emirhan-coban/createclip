"""Find the streamer's camera (face) in a source video with OpenCV, to fill the face window of a two-window layout.

Samples frames across the footage, detects faces (Haar cascade, bundled with OpenCV) and keeps the position that shows
up most consistently: a facecam sits at the same place the whole stream. Optional extra: pip install -e ".[faces]"."""
import json
import tempfile
from pathlib import Path

from .proc import run_ok


class FaceError(RuntimeError):
    pass


def available() -> bool:
    try:
        import cv2  # noqa: F401
        return True
    except ImportError:
        return False


def _boxes(frames: list[Path]) -> list[list[tuple[float, float, float, float]]]:
    import cv2
    cas = cv2.CascadeClassifier(str(Path(cv2.data.haarcascades) / "haarcascade_frontalface_default.xml"))
    if cas.empty():
        raise FaceError("Yüz tanıma modeli yüklenemedi.")
    out = []
    for f in frames:
        img = cv2.imread(str(f))
        if img is None:
            out.append([])
            continue
        h, w = img.shape[:2]
        gray = cv2.equalizeHist(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY))
        found = cas.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=6, minSize=(max(24, w // 40), max(24, w // 40)))
        out.append([((x + bw / 2) / w, (y + bh / 2) / h, bw / w, bh / h) for x, y, bw, bh in found])
    return out


def pick(per_frame: list[list[tuple[float, float, float, float]]], min_share: float = 0.25) -> dict | None:
    """The face position seen in the most frames: boxes within 8% of each other count as the same place."""
    allb = [b for fr in per_frame for b in fr]
    if not allb or not per_frame:
        return None
    best: list = []
    for cx, cy, _, _ in allb:
        grp = [b for b in allb if abs(b[0] - cx) < 0.08 and abs(b[1] - cy) < 0.08]
        if len(grp) > len(best):
            best = grp
    frames_with = sum(1 for fr in per_frame if any(b in best for b in fr))
    if frames_with / len(per_frame) < min_share:
        return None
    med = lambda i: sorted(b[i] for b in best)[len(best) // 2]          # noqa: E731
    return {"cx": round(med(0), 4), "cy": round(med(1), 4), "w": round(med(2), 4), "h": round(med(3), 4),
            "seen": round(frames_with / len(per_frame), 2)}


def detect(src: Path, duration: float, samples: int = 14) -> dict | None:
    """{cx, cy, w, h, seen}: the face box as fractions of the frame, or None when no steady face is found."""
    if not available():
        raise FaceError("Yüz bulmak için OpenCV gerekli: ./.venv/bin/pip install -e '.[faces]'")
    with tempfile.TemporaryDirectory() as td:
        fps = max(0.05, samples / max(duration, 1.0))
        run_ok(["ffmpeg", "-y", "-v", "error", "-i", str(src), "-vf", f"fps={fps:.4f},scale=960:-2", "-frames:v", str(samples),
                "-q:v", "3", str(Path(td) / "f%03d.jpg")], "face frames", timeout=300)
        frames = sorted(Path(td).glob("f*.jpg"))
        if not frames:
            raise FaceError("Karelerden örnek alınamadı.")
        return pick(_boxes(frames))


def face_cell(face: dict, W: float, H: float, aw: float, ah: float, margin: float = 2.4) -> dict:
    """A cell {cx, cy, zoom} whose window (aspect aw:ah) frames the face with `margin` times its size around it."""
    fw, fh = face["w"] * W, face["h"] * H
    wh = max(fh * margin, fw * margin * ah / aw)               # window height that holds the face both ways
    zoom = min(8.0, max(1.0, H / wh))
    return {"cx": round(face["cx"], 3), "cy": round(min(1.0, face["cy"] + 0.02), 3), "zoom": round(zoom, 2)}


def save(path: Path, face: dict | None):
    path.write_text(json.dumps(face))


def load(path: Path) -> dict | None:
    return json.loads(path.read_text()) if path.exists() else None
