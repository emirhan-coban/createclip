"""Review inbox + ready-to-upload packages. Clip records get `status` (new | approved | rejected), `title`,
`description`, `tags`; approved clips can be exported as a folder: video, title, description, tags, cover."""
import re
import shutil
import subprocess
import time
from pathlib import Path

from . import pipeline, transcribe
from .log import log, run

STATUSES = ("new", "approved", "rejected")
PLATFORMS = {"shorts": {"label": "YouTube Shorts", "max_s": 60}, "tiktok": {"label": "TikTok", "max_s": 600},
             "reels": {"label": "Instagram Reels", "max_s": 90}}
_STOP = set("ve bir bu da de ki mi ama için ile çok daha gibi ne o ben sen biz var yok evet hayır işte şey yani".split())


def _clip_text(jd: Path, rec: dict) -> str:
    if rec.get("words") and (jd / rec["words"]).exists():
        return transcribe.words_to_text(transcribe.load_words(jd / rec["words"]))
    return ""


def _video(rec: dict):
    return rec.get("captioned") or rec.get("plain") or rec.get("src")


def _stamp(sec: float) -> str:
    sec = int(sec)
    return f"{sec // 3600}:{sec % 3600 // 60:02d}:{sec % 60:02d}"


def suggest(m: dict, rec: dict, text: str) -> dict:
    """Deterministic starting point (no model): first sentence as title, source credit with timestamp as description,
    frequent non-trivial words as tags. The user edits them in the inbox."""
    first = re.split(r"(?<=[.!?])\s+", text.strip())[0] if text.strip() else ""
    title = (first[:68].rsplit(" ", 1)[0] + "…") if len(first) > 70 else first
    title = title or (m.get("title") or "Klip")[:68]
    words = [w.lower() for w in re.findall(r"[\wçğıöşüÇĞİÖŞÜ]{4,}", text)]
    freq = {}
    for w in words:
        if w not in _STOP:
            freq[w] = freq.get(w, 0) + 1
    tags = [w for w, _ in sorted(freq.items(), key=lambda kv: (-kv[1], kv[0]))[:5]]
    src = m.get("url", "")
    desc = (f"{title}\n\nKaynak yayın: {m.get('title', '')}\n{src}\nAn: {_stamp(rec['start'])}\n"
            f"(Yayıncı: {m.get('slug', '')})")
    return {"title": title, "description": desc, "tags": tags}


def _ensure_meta(jd: Path, m: dict, rec: dict) -> bool:
    """Fill whatever the user has not written yet (title, description, tags), never overwrite their edits."""
    missing = [k for k in ("title", "description", "tags") if k not in rec or rec[k] in ("", None)]
    if not missing:
        return False
    sug = suggest(m, rec, _clip_text(jd, rec))
    for k in missing:
        rec[k] = sug[k]
    return True


def inbox(root: Path, status: str = "new") -> list:
    rows = []
    for mp in sorted((Path(root) / "output").glob("*/manifest.json"), key=lambda p: -p.stat().st_mtime):
        jd = mp.parent
        try:
            m = pipeline.load(jd)
        except Exception:  # noqa: BLE001
            continue
        dirty = False
        for rec in sorted(m.get("clips", []), key=lambda c: -(c.get("score") or 0)):
            st = rec.get("status", "new")
            if status != "all" and st != status:
                continue
            v = _video(rec)
            if not v or not (jd / v).exists():
                continue
            dirty |= _ensure_meta(jd, m, rec)
            rows.append({"project": jd.name, "i": rec["i"], "status": st, "score": rec.get("score") or 0,
                         "video": f"/files/{jd.name}/{v}", "start": rec["start"], "end": rec["end"],
                         "length": round(rec["end"] - rec["start"], 1), "title": rec["title"],
                         "description": rec["description"], "tags": rec.get("tags", []),
                         "source_title": m.get("title", ""), "slug": m.get("slug", ""), "exported": rec.get("exported")})
        if dirty:
            pipeline.save(jd, m)
    rows.sort(key=lambda r: (-r["score"], r["project"]))
    return rows


def review(jd: Path, i: int, **ch) -> dict:
    jd = Path(jd)
    m = pipeline.load(jd)
    rec = pipeline.get_clip(m, i)
    if ch.get("status") is not None:
        if ch["status"] not in STATUSES:
            raise ValueError("Geçersiz durum")
        rec["status"] = ch["status"]
    for k in ("title", "description"):
        if ch.get(k) is not None:
            rec[k] = str(ch[k])[:5000]
    if ch.get("tags") is not None:
        rec["tags"] = [t.strip().lstrip("#") for t in ch["tags"] if t.strip()][:15]
    pipeline.save(jd, m)
    return rec


def export_pack(root: Path, jd: Path, i: int, platform: str = "shorts") -> dict:
    """Copy the approved clip into ready/<date>/<project>_<clip>/ with text files and a cover frame."""
    if platform not in PLATFORMS:
        raise ValueError("Bilinmeyen platform")
    jd = Path(jd)
    m = pipeline.load(jd)
    rec = pipeline.get_clip(m, i)
    if _ensure_meta(jd, m, rec):
        pipeline.save(jd, m)
    v = jd / (_video(rec) or "")
    if not v.is_file():
        raise FileNotFoundError("Klip dosyası yok")
    out = Path(root) / "ready" / time.strftime("%Y-%m-%d") / f"{jd.name}_{rec['name']}"
    out.mkdir(parents=True, exist_ok=True)
    shutil.copy2(v, out / "video.mp4")
    tags = rec.get("tags", [])
    (out / "baslik.txt").write_text(rec["title"] + "\n")
    (out / "aciklama.txt").write_text(rec["description"] + ("\n\n" + " ".join("#" + t for t in tags) if tags else "") + "\n")
    (out / "etiketler.txt").write_text(", ".join(tags) + "\n")
    length = rec["end"] - rec["start"]
    p = run(["ffmpeg", "-y", "-v", "error", "-ss", f"{length / 2:.2f}", "-i", str(v), "-frames:v", "1", "-q:v", "2",
             str(out / "kapak.jpg")], "kapak karesi", timeout=60)
    warns = []
    if p.returncode:
        warns.append("Kapak karesi çıkarılamadı.")
    if length > PLATFORMS[platform]["max_s"]:
        warns.append(f"{PLATFORMS[platform]['label']} için {PLATFORMS[platform]['max_s']} sn üstü ({length:.0f} sn): sınır kontrol et.")
    w = h = 0
    try:
        from . import captions
        w, h = captions.probe_size(v)
    except Exception:  # noqa: BLE001
        pass
    if w and h and w >= h:
        warns.append("Video dikey (9:16) değil; Shorts/Reels/TikTok için yerleşim seç.")
    rec["exported"] = {"dir": str(out), "platform": platform, "at": time.strftime("%Y-%m-%d %H:%M")}
    pipeline.save(jd, m)
    log.info("hazır paket: %s", out)
    return {"dir": str(out), "warnings": warns}
