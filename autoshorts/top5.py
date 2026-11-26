"""Weekly countdown montage: 2-5 finished clips joined into one vertical video, played from the last place up to #1,
with the heading, the rank, the user's own comment and a source credit on every part. The result is saved as a clip of
its own (engine "top5"), so it is watched, retitled and uploaded like any other clip."""
import json
import re
import tempfile
import time
from pathlib import Path

from . import config, editor, export, meta, power, render, store, texts
from .proc import run

MIN_ITEMS, MAX_ITEMS = 2, 5
MAX_SECONDS = 180            # the longest video YouTube still treats as a Short
ENGINE = "top5"
W, H = texts.OW, texts.OH
# overlay positions (share of the height); the lowest line stays above the platforms' own captions
HEADING_Y, RANK_Y, NOTE_Y, CREDIT_Y = 0.09, 0.17, 0.73, 0.80


def channel_of(clip: dict) -> str:
    """The streamer's name: from the broadcast fingerprint, else from the saved file's name."""
    parts = (clip.get("video_fp") or "").split("|")
    if len(parts) > 2 and parts[1]:
        return parts[1]
    f = clip.get("file")
    return Path(f).stem.split("_")[0] if f else ""


def clean(con, heading, items) -> tuple[str, list[dict]]:
    """Validate the request; items are in rank order (first = #1). Raises ValueError with a message for the user."""
    heading = str(heading or "").strip()[:60]
    if not heading:
        raise ValueError("Bir başlık yaz.")
    if not isinstance(items, list) or not MIN_ITEMS <= len(items) <= MAX_ITEMS:
        raise ValueError(f"{MIN_ITEMS}–{MAX_ITEMS} klip seç.")
    out, seen = [], set()
    for it in items:
        if not isinstance(it, dict) or not isinstance(it.get("clip_id"), int):
            raise ValueError("Klip listesi anlaşılamadı.")
        cid = it["clip_id"]
        c = store.get_clip(con, cid)
        if cid in seen:
            raise ValueError("Aynı klip iki kez seçilmiş.")
        if not c or c["status"] != "done" or not c["file"] or not Path(c["file"]).exists():
            raise ValueError(f"Klip hazır değil ya da dosyası yok (#{cid}).")
        if c["engine"] == ENGINE:
            raise ValueError("Bir montaj başka bir montaja eklenemez.")
        seen.add(cid)
        credit = str(it.get("credit") or "").strip()[:40] or channel_of(c)
        if not credit:
            raise ValueError("Her klip için yayıncı adı yaz.")
        out.append({"clip_id": cid, "credit": credit, "note": str(it.get("note") or "").strip()[:120]})
    return heading, out


def _layers(heading: str, rank: int, note: str, credit: str) -> list[dict]:
    box = {"on": True, "color": "#000000", "opacity": 0.6}
    out = [{"text": heading, "y": HEADING_Y, "size": 0.058, "bg": box},
           {"text": f"#{rank}", "y": RANK_Y, "size": 0.13, "color": "#C8F84A", "stroke": 1.4},
           {"text": f"Kaynak: {credit}", "y": CREDIT_Y, "size": 0.032, "font": "poppins", "bg": box}]
    if note:
        out.append({"text": note, "y": NOTE_Y, "size": 0.05, "bg": box})
    return [l | {"start": 0.0, "end": MAX_SECONDS} for l in out]


def graph(parts: list[dict]) -> str:
    """filter_complex for the whole montage. Inputs 0..n-1 are the clips (in playing order), the overlay PNGs follow.
    Each part: {"duration", "audio", "overlays": [(png, x, y)]}."""
    chains, png = [], len(parts)
    for i, p in enumerate(parts):
        d = f"{p['duration']:.3f}"
        chain = (f"[{i}:v]fps=30,scale={W}:{H}:force_original_aspect_ratio=decrease,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:black,"
                 f"setsar=1,trim=duration={d},setpts=PTS-STARTPTS")
        for k, (_, x, y) in enumerate(p["overlays"]):
            chain += f"[s{i}_{k}];[s{i}_{k}][{png}:v]overlay={x}:{y}"
            png += 1
        chains.append(chain + f",format=yuv420p[v{i}]")
        audio = f"[{i}:a]aresample=48000,aformat=channel_layouts=stereo,apad" if p["audio"] else "anullsrc=r=48000:cl=stereo"
        chains.append(f"{audio},atrim=duration={d},asetpts=PTS-STARTPTS[a{i}]")
    joined = "".join(f"[v{i}][a{i}]" for i in range(len(parts)))
    chains.append(f"{joined}concat=n={len(parts)}:v=1:a=1[v][a]")
    return ";".join(chains)


def description(entries: list[dict], hashtags: list[str]) -> tuple[str, list[str]]:
    """Ranked list with a source link per clip (always: the montage must credit its sources), then the hashtags."""
    lines = []
    for rank, e in enumerate(entries, 1):
        label = e["note"] or meta.clean_title(e["title"], 60)
        link = meta._timestamp_link(e["url"], e["start"])
        lines.append(f"{rank}. {label}\n   Kaynak: {e['credit']} ({link})")
    tags = [h if h.startswith("#") else "#" + h for h in hashtags]
    tags += ["#" + re.sub(r"\W+", "", e["credit"]) for e in entries]
    tags = [t for t in dict.fromkeys(tags) if len(t) > 1]
    return "\n".join(lines + ["", " ".join(tags)]).strip(), [t.lstrip("#") for t in tags]


def build(con, cfg: dict, heading: str, items: list[dict], progress=lambda f, t="": None) -> int:
    """Render the montage and save it as a new clip; returns its id."""
    heading, items = clean(con, heading, items)
    entries = []
    for it in items:
        c = store.get_clip(con, it["clip_id"])
        info = editor.probe(Path(c["file"]))
        entries.append(it | {"file": c["file"], "title": c["title"] or "", "url": c["video_url"], "start": c["start"],
                             "duration": info["duration"], "audio": info["audio"]})
    total = sum(e["duration"] for e in entries)
    if total > MAX_SECONDS:
        raise RuntimeError(f"Montaj {total:.0f} sn oluyor, sınır {MAX_SECONDS} sn. Klipleri kısalt ya da daha az klip seç.")

    def on_line(line: str):
        m = re.match(r"out_time_(?:us|ms)=(\d+)", line)
        if m:
            progress(0.05 + 0.9 * min(1.0, int(m.group(1)) / 1e6 / total), "Montaj hazırlanıyor")

    work = config.data_dir() / "clips" / "top5"
    work.mkdir(parents=True, exist_ok=True)
    progress(0.02, "Yazılar çiziliyor")
    with tempfile.TemporaryDirectory(dir=work) as td:
        playing = list(enumerate(entries, 1))[::-1]            # last place first, #1 at the end
        parts = []
        for rank, e in playing:
            d = Path(td) / str(rank)
            d.mkdir()
            layers = texts.render_layers(d, _layers(heading, rank, e["note"], e["credit"]), e["duration"])
            parts.append(e | {"overlays": [(png, x, y) for png, x, y, _, _ in layers]})
        cmd = ["ffmpeg", "-y", "-v", "error", "-nostats", "-progress", "pipe:1"]
        for p in parts:
            cmd += [*power.input_args(), "-i", p["file"]]
        for p in parts:
            for png, _, _ in p["overlays"]:
                cmd += ["-i", str(png)]
        out, thumb = Path(td) / "top5.mp4", Path(td) / "top5.jpg"
        cmd += [*power.filter_args(), "-filter_complex", graph(parts), "-map", "[v]", "-map", "[a]", *power.video_args(),
                "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", str(out)]
        r = run(cmd, "top5 montage", timeout=3600, on_line=on_line)
        if r.returncode:
            raise RuntimeError("Montaj başarısız: " + r.stdout.strip()[-300:])
        progress(0.96, "Kaydediliyor")
        render.thumbnail(out, thumb)
        desc, tags = description(entries, cfg.get("hashtags", []))
        # a made-up, unique "video link": the clips table is keyed by it and no download ever uses it
        clip_id = store.add_clip(con, f"top5:{time.time_ns()}", 0.0, total, 0.0, ENGINE)
        saved = export.save(cfg, clip_id, ENGINE, 0.0, out, thumb, heading, desc)
        store.update_clip(con, clip_id, file=str(saved), title=heading, description=desc,
                          tags=json.dumps(tags, ensure_ascii=False), status="done", error=None)
    return clip_id
