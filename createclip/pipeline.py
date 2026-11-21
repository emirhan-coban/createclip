"""Kick link -> clips (+ captions, 9:16 layouts). Everything lives under <root>/output/<vod>/ with a
manifest.json that the web editor and CLI both read/modify. Each clip keeps its raw padded footage,
so trimming/layout/caption edits never need a re-download (unless the cut moves outside the padding)."""
import copy
import json
import shutil
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, asdict
from pathlib import Path

from . import log as logmod
from .log import Cancelled, log
from . import audio_peaks, captions, clipper, kick, layout as layoutmod, overlay, peaks, render, sources, transcribe

CANDIDATES = 30
SCOUT_WORKERS = 6       # YouTube throttles each connection: 8 parallel 80 s ranges finished in 60 s (one takes ~50 s)
RENDER_WORKERS = 3      # trim/encode overlap with the (single) Whisper worker (gentle mode uses 2, scouting 4)
_LOCK = threading.RLock()       # guards manifest writes and the shared clip list
_WHISPER = threading.Lock()     # one speech-model run at a time (it already uses the whole GPU)


class NeedsAudioConfirm(RuntimeError):
    """Chat is unavailable; the only fallback (loudness from the audio) downloads the whole video, so ask first."""

    def __init__(self, reason: str, est_mb: int):
        super().__init__(f"{reason}. Ses analizi için videonun tamamı indirilir (tahmini ~{est_mb} MB); "
                         f"onay gerekiyor.")
        self.reason, self.est_mb = reason, est_mb


def audio_estimate_mb(duration: float, platform: str = "kick") -> int:
    """Rough download size of the loudness fallback. Kick has no audio-only stream, its 160p video is ~1.7 MB/min
    (read from yt-dlp's format list); YouTube has an audio-only stream at ~0.35 MB/min (112 min = 39 MiB for the
    48 kbps m4a). Estimates only."""
    return max(10, int(duration / 60 * (0.35 if platform == "youtube" else 1.7)))


def _noop(stage, frac, msg=""):
    pass


@dataclass
class Options:
    n: int = 5
    captions: bool = True        # produce captioned versions
    keep_plain: bool = False     # keep the caption-less version too (costs an extra encode; off = single-pass render)
    style: dict = field(default_factory=dict)       # font, size, ypos, chunk, active, color, mask
    layout: dict = field(default_factory=lambda: {"mode": "none", "cells": []})
    lead: float = 20
    min_len: float = 25
    max_len: float = 60
    max_height: int = 720
    snap: bool = True            # snap cuts to pauses in speech
    source: str = "auto"         # auto | chat | audio
    at: list = field(default_factory=list)   # manual clips: "1:44:50" or "1:44:50-1:45:40"
    audio_ok: bool = False       # allow the whole-video audio fallback when chat is unavailable (source=auto)
    chat_mode: str = "smart"     # smart (sparse sampling + dense around candidates) | full (every window)
    reactions: bool = False      # burn the viewers' chat messages of that moment into every clip
    drafts: int = 0              # extra candidate moments downloaded as raw previews only (rendered when picked)
    start_at: float = 0.0        # seconds: ignore everything before this (skip the crowded opening)
    vocab: str = ""              # optional names for the speech model, e.g. "Berk, Derbeder" (use sparingly)


def job_dir(root: Path, vod: kick.Vod) -> Path:
    return Path(root) / "output" / f"{vod.slug}-{vod.vod_id[:8]}"


def load(jd: Path) -> dict:
    return json.loads((Path(jd) / "manifest.json").read_text())


def save(jd: Path, m: dict):
    with _LOCK:
        tmp = Path(jd) / "manifest.json.tmp"
        tmp.write_text(json.dumps(m, ensure_ascii=False, indent=1))
        tmp.replace(Path(jd) / "manifest.json")


def get_clip(m: dict, i: int) -> dict:
    for c in m["clips"]:
        if c["i"] == i:
            return c
    raise KeyError(f"klip {i} yok")


def _rel(jd, p):
    return str(Path(p).relative_to(jd)) if p else None


# ---------------------------------------------------------------- building one clip
def _produce(jd: Path, m: dict, rec: dict, need_words: bool, need_base: bool, need_caps: bool, progress,
             need_ov: bool = False):
    jd = Path(jd)
    src = jd / rec["src"]
    name = rec["name"]
    if rec["captions"] and (need_words or not rec.get("words")):
        progress("captions", 0.2, f"Klip {rec['i']}: konuşma çözülüyor")
        prompt = transcribe.build_prompt(m.get("vocab", ""))   # old manifests' "prompt" key is ignored on purpose
        with _WHISPER:
            words = transcribe.clean_words(transcribe.strip_prompt_echo(transcribe.transcribe_words(src, prompt), prompt))
        wp = jd / "words" / f"{name}.json"
        transcribe.save_words(words, wp)
        transcribe.to_srt(words, jd / "words" / f"{name}.srt")
        rec["words"], rec["srt"] = _rel(jd, wp), f"words/{name}.srt"
        need_caps = True
    lay = rec["layout"]
    fused = bool(rec["captions"] and rec.get("words") and not rec.get("reactions") and not rec.get("banner")
                 and not m["defaults"]["keep_plain"])
    if fused:       # layout + captions in one encode (the old chain encoded the same minute three times)
        if need_base or need_caps or not rec.get("captioned") or rec.get("base"):
            if lay["mode"] == "face":
                progress("layout", 0.4, f"Klip {rec['i']}: yüz aranıyor")
                lay = rec["layout"] = layoutmod.auto_layout(src) or {"mode": "blur", "cells": []}
                log.info("klip %s yüz yerleşimi: %s", rec["i"], lay["mode"])
            progress("captions", 0.7, f"Klip {rec['i']}: dikey + altyazı")
            out = render.final(src, jd / "captioned" / f"{name}_altyazili.mp4", lay,
                               transcribe.load_words(jd / rec["words"]), rec["style"])
            rec["captioned"] = _rel(jd, out)
        rec["base"] = rec["overlaid"] = rec["plain"] = None
    else:
        lay = rec["layout"]
        if need_base or not rec.get("base"):
            W, H = captions.probe_size(src)
            if lay["mode"] == "face":                      # find the streamer's face; fall back to the blurred layout
                progress("layout", 0.4, f"Klip {rec['i']}: yüz aranıyor")
                lay = rec["layout"] = layoutmod.auto_layout(src) or {"mode": "blur", "cells": []}
                log.info("klip %s yüz yerleşimi: %s", rec["i"], lay["mode"])
            if lay["mode"] == "none":
                base = src
            else:
                progress("layout", 0.5, f"Klip {rec['i']}: 9:16 yerleşim")
                base = layoutmod.render(src, lay, jd / "clips" / f"{name}_dikey.mp4", W, H)
            rec["base"] = _rel(jd, base)
            need_caps = need_ov = True
        stage = rec["base"]
        if rec.get("reactions") or rec.get("banner"):
            if need_ov or not rec.get("overlaid"):
                progress("overlay", 0.65, f"Klip {rec['i']}: sohbet tepkisi / başlık kartı")
                try:
                    ov = overlay.apply(jd, m, rec, jd / rec["base"], jd / "clips" / f"{name}_tepki.mp4")
                    rec["overlaid"] = _rel(jd, ov)
                except ValueError as e:
                    log.warning("klip %s bindirme yok: %s", rec["i"], e)
                    rec["overlaid"] = None
                need_caps = True
            stage = rec.get("overlaid") or rec["base"]
        else:
            rec["overlaid"] = None
        rec["plain"] = stage if m["defaults"]["keep_plain"] else None
        if rec["captions"] and rec.get("words"):
            if need_caps or not rec.get("captioned"):
                progress("captions", 0.8, f"Klip {rec['i']}: altyazı basılıyor")
                out = captions.render(jd / stage, transcribe.load_words(jd / rec["words"]),
                                      jd / "captioned" / f"{name}_altyazili.mp4", rec["style"])
                rec["captioned"] = _rel(jd, out)
        else:
            rec["captioned"] = None
    rec["voiced"] = None
    if rec.get("voice") and (jd / rec["voice"]).exists():           # re-mix the recorded commentary over the result
        progress("voice", 0.95, f"Klip {rec['i']}: yorum sesi karıştırılıyor")
        final = jd / (rec["captioned"] or rec["plain"] or rec["base"])
        rec["voiced"] = _rel(jd, overlay.mix_voice(final, jd / rec["voice"], jd / "clips" / f"{name}_yorum.mp4"))


def scout_clip(jd: Path, m: dict, start: float, end: float, score: float, opts_like: dict, snap: bool | None = None):
    """Download the raw footage (no encoding) and register the moment as a draft clip: it can be watched at once
    and is rendered (speech, 9:16, captions) only when picked. Safe to call from several threads."""
    with _LOCK:
        i = m["next_i"]
        m["next_i"] += 1
    name = f"clip_{i:02d}_{clipper.hms(start).replace(':', '')}"
    d = m["defaults"]
    raw = jd / "raw" / f"{name}_raw.mp4"
    s, e, rs, re_ = clipper.fetch_raw(m["url"], start, end, raw, m["duration"], d["max_height"],
                                      snap_cuts=d["snap"] if snap is None else snap,
                                      min_len=d["min_len"] - 5, max_len=d["max_len"] + 15)
    rec = {"i": i, "name": name, "score": score, "start": round(s, 2), "end": round(e, 2), "status": "draft",
           "raw_start": rs, "raw_end": re_, "raw": _rel(jd, raw), "src": None,
           "captions": d["captions"], "style": dict(opts_like["style"]), "layout": json.loads(json.dumps(opts_like["layout"])),
           "words": None, "srt": None, "base": None, "plain": None, "captioned": None,
           "reactions": bool(opts_like.get("reactions")), "banner": None, "overlaid": None, "voice": None, "voiced": None}
    with _LOCK:
        m["clips"].append(rec)
        m["clips"].sort(key=lambda c: c["i"])
        save(jd, m)
    return rec


def scout_many(jd: Path, m: dict, plan: list, opts_like: dict, progress, snap: bool | None = None) -> list:
    """scout_clip for every (start, end, score), several downloads at once. Returns the new records in plan order;
    a moment that cannot be downloaded is skipped (logged), not fatal."""
    recs, done = [None] * len(plan), [0]

    def one(k):
        s, e, sc = plan[k]
        try:
            recs[k] = scout_clip(jd, m, s, e, sc, opts_like, snap)
        except Cancelled:
            raise
        except Exception as ex:  # noqa: BLE001
            log.warning("an indirilemedi %s: %s", clipper.hms(s), ex)
        with _LOCK:
            done[0] += 1
            progress("clips", done[0] / len(plan), f"{done[0]}/{len(plan)} önizleme indirildi")

    with ThreadPoolExecutor(min(4 if logmod.GENTLE else SCOUT_WORKERS, max(1, len(plan)))) as ex:
        for f in [ex.submit(one, k) for k in range(len(plan))]:
            f.result()
    got = [r for r in recs if r]
    if plan and not got:
        raise RuntimeError("Hiçbir an indirilemedi (ağ ya da yayın erişimi).")
    return got


def render_one(jd: Path, m: dict, rec: dict, progress=_noop):
    """Draft -> finished clip: exact trim, speech, 9:16 layout + captions. Works on a private copy of the record
    and publishes it under the lock, so several clips can render in parallel."""
    jd = Path(jd)
    r = copy.deepcopy(rec)
    if not r.get("src") or not (jd / r["src"]).exists():
        progress("clips", 0.1, f"Klip {r['i']}: kırpılıyor")
        src = jd / "clips" / f"{r['name']}.mp4"
        clipper.trim(jd / r["raw"], r["start"] - r["raw_start"], r["end"] - r["raw_start"], src)
        r["src"] = _rel(jd, src)
    r["status"] = "new"
    _produce(jd, m, r, True, True, True, progress)
    with _LOCK:
        rec.clear()
        rec.update(r)
        save(jd, m)
    return rec


def render_many(jd: Path, m: dict, recs: list, progress=_noop) -> list:
    """Render the given records with the stages overlapping: while one clip waits for the speech model the others
    trim and encode. A clip that fails is left as a draft (logged); cancellation stops everything."""
    done, ok = [0], []

    def one(rec):
        try:
            render_one(jd, m, rec, lambda st, fr, msg="": progress(st, (done[0] + fr * 0.9) / len(recs), msg))
            ok.append(rec)
        except Cancelled:
            raise
        except Exception as ex:  # noqa: BLE001
            log.exception("klip %s üretilemedi: %s", rec.get("i"), ex)
        with _LOCK:
            done[0] += 1
            progress("clips", done[0] / len(recs), f"{done[0]}/{len(recs)} klip hazır")

    if not recs:
        return []
    with ThreadPoolExecutor(min(2 if logmod.GENTLE else RENDER_WORKERS, len(recs))) as ex:
        for f in [ex.submit(one, r) for r in recs]:
            f.result()
    if not ok:
        raise RuntimeError("Hiçbir klip üretilemedi (günlüğe bak).")
    from . import autometa                    # lazy: autometa imports this module
    progress("meta", 0.98, "Başlık ve an puanı üretiliyor")
    autometa.fill(jd, only={r["i"] for r in ok if r.get("ai_score") is None and not r.get("ai_titles_done")})
    return ok


def _add_clip(jd: Path, m: dict, start: float, end: float, score: float, opts_like: dict, progress):
    """One clip start to finish (editor's 'add moment' / 'next moment')."""
    progress("clips", 0.0, f"Klip: indiriliyor ({clipper.hms(start)})")
    rec = scout_clip(jd, m, start, end, score, opts_like)
    render_one(jd, m, rec, progress)
    return rec


def render_clips(jd: Path, ids: list, progress=_noop) -> dict:
    """UI entry: render the picked drafts."""
    jd = Path(jd)
    m = load(jd)
    recs = [c for c in m["clips"] if c["i"] in set(ids) and c.get("status") == "draft"]
    if not recs:
        raise ValueError("Üretilecek taslak yok.")
    render_many(jd, m, recs, progress)
    m = load(jd)
    progress("done", 1.0, "Bitti")
    m["dir"] = str(jd)
    return m


def drop_drafts(jd: Path, ids: list | None = None):
    """Remove draft clips (and their raw files) that were not picked."""
    jd = Path(jd)
    m = load(jd)
    keep = []
    for c in m["clips"]:
        if c.get("status") == "draft" and (ids is None or c["i"] in ids):
            if c.get("raw") and (jd / c["raw"]).exists():
                (jd / c["raw"]).unlink()
        else:
            keep.append(c)
    m["clips"] = keep
    save(jd, m)


# ---------------------------------------------------------------- editing
def update_clip(jd: Path, i: int, changes: dict, progress=_noop) -> dict:
    """changes: start, end (VOD seconds) | text | style{...} | layout{...} | captions(bool)."""
    jd = Path(jd)
    m = load(jd)
    rec = get_clip(m, i)
    need_words = bool(changes.get("retranscribe"))
    need_base = need_caps = False

    if "start" in changes or "end" in changes:
        s = float(changes.get("start", rec["start"]))
        e = float(changes.get("end", rec["end"]))
        if not 5 <= e - s <= 180 or s < 0 or e > m["duration"]:
            raise ValueError("Geçersiz aralık (5-180 sn arası olmalı).")
        if abs(s - rec["start"]) > 0.01 or abs(e - rec["end"]) > 0.01:
            progress("clips", 0.0, "Klip yeniden kesiliyor")
            src = jd / rec["src"]
            if s >= rec["raw_start"] and e <= rec["raw_end"] and (jd / rec["raw"]).exists():
                clipper.trim(jd / rec["raw"], s - rec["raw_start"], e - rec["raw_start"], src)
            else:
                raw = jd / rec["raw"]
                _, _, rs, re_ = clipper.make_clip(m["url"], s, e, raw, src, m["duration"],
                                                  m["defaults"]["max_height"], snap_cuts=False, min_len=5, max_len=180)
                rec["raw_start"], rec["raw_end"] = rs, re_
            rec["start"], rec["end"] = round(s, 2), round(e, 2)
            need_words = need_base = True

    if "layout" in changes:
        lay = changes["layout"]
        mode = lay.get("mode", "none")
        if mode not in ("none", "blur", "crop", "stack", "face"):
            raise ValueError("Bilinmeyen yerleşim")
        cells = lay.get("cells") or layoutmod.default_cells(mode)
        if rec["layout"] != {"mode": mode, "cells": cells}:
            rec["layout"] = {"mode": mode, "cells": cells}
            need_base = True

    if "style" in changes:
        new = {**rec["style"], **changes["style"]}
        if new.get("font", "montserrat") not in captions.FONTS:
            raise ValueError("Bilinmeyen font")
        if new != rec["style"]:
            rec["style"] = new
            need_caps = True

    need_ov = False
    for key in ("reactions", "banner"):
        if key in changes and changes[key] != rec.get(key):
            rec[key] = changes[key] if key == "banner" else bool(changes[key])
            need_ov = True
    if "captions" in changes and bool(changes["captions"]) != rec["captions"]:
        rec["captions"] = bool(changes["captions"])
        need_caps = True

    if "text" in changes and rec.get("words"):
        wp = jd / rec["words"]
        words = transcribe.apply_text_edit(transcribe.load_words(wp), changes["text"])
        transcribe.save_words(words, wp)
        transcribe.to_srt(words, jd / rec["srt"])
        need_caps = True

    _produce(jd, m, rec, need_words, need_base, need_caps, progress, need_ov)
    save(jd, m)
    progress("done", 1.0, "Bitti")
    return rec


def set_voice(jd: Path, i: int, data: bytes | None, progress=_noop) -> dict:
    """Attach (or with None remove) the recorded commentary of a clip and re-mix."""
    jd = Path(jd)
    m = load(jd)
    rec = get_clip(m, i)
    old = jd / rec["voice"] if rec.get("voice") else None
    if data:
        p = jd / "voice" / f"{rec['name']}.webm"
        p.parent.mkdir(exist_ok=True)
        p.write_bytes(data)
        rec["voice"] = _rel(jd, p)
    else:
        rec["voice"] = None
        if old and old.exists():
            old.unlink()
    _produce(jd, m, rec, False, False, False, progress)
    save(jd, m)
    return rec


def delete_clip(jd: Path, i: int):
    jd = Path(jd)
    m = load(jd)
    rec = get_clip(m, i)
    for k in ("raw", "src", "base", "plain", "captioned", "words", "srt", "overlaid", "voice", "voiced"):
        p = rec.get(k)
        if p and (jd / p).exists():
            (jd / p).unlink()
    dikey = jd / "clips" / f"{rec['name']}_dikey.mp4"
    if dikey.exists():
        dikey.unlink()
    m["clips"] = [c for c in m["clips"] if c["i"] != i]
    save(jd, m)


def add_manual(jd: Path, start: float, end: float, progress=_noop) -> dict:
    jd = Path(jd)
    m = load(jd)
    if not 5 <= end - start <= 180 or end > m["duration"]:
        raise ValueError("Geçersiz aralık.")
    m["defaults"]["snap"], snap_old = False, m["defaults"]["snap"]
    try:
        rec = _add_clip(jd, m, start, end, 0.0, _style_layout(m), progress)
    finally:
        m["defaults"]["snap"] = snap_old
        save(jd, m)
    return rec


def add_next(jd: Path, progress=_noop) -> dict:
    """Add the next-best unused chat/audio peak as a new clip."""
    jd = Path(jd)
    m = load(jd)
    cand = next((c for c in m["candidates"] if not c["used"]), None)
    if not cand:
        raise ValueError("Başka aday an kalmadı.")
    cand["used"] = True
    return _add_clip(jd, m, cand["start"], cand["end"], cand["score"], _style_layout(m), progress)


def _style_layout(m):
    d = m["defaults"]
    return {"style": d["style"], "layout": d["layout"], "reactions": d.get("reactions", False)}


# ---------------------------------------------------------------- whole job
def _parse_at(spec: str, default_len=45.0):
    if "-" in spec:
        a, b = spec.split("-", 1)
        return clipper.parse_time(a), clipper.parse_time(b)
    s = clipper.parse_time(spec)
    return s, s + default_len


def _overlaps(s1: float, e1: float, s2: float, e2: float) -> bool:
    """True when the two time ranges share more than half of the shorter one."""
    inter = min(e1, e2) - max(s1, s2)
    return inter > 0.5 * min(e1 - s1, e2 - s2)


def run(url: str, root: Path, opts: Options, progress=_noop) -> dict:
    progress("info", 0, "VOD bilgisi alınıyor (~1 dk sürebilir)")
    vod = sources.vod_info(url)
    log.info("VOD: %s | %s | %.0f dk | platform=%s | mod=%s kaynak=%s", vod.slug, vod.title[:50],
             vod.duration / 60, sources.platform(url), opts.chat_mode, opts.source)
    jd = job_dir(root, vod)
    jd.mkdir(parents=True, exist_ok=True)

    manifest_path = jd / "manifest.json"
    old = load(jd) if manifest_path.exists() else None
    if old and "defaults" in old and "next_i" in old:
        m = old                            # re-running a known VOD keeps previous clips
        m["defaults"] = _defaults(opts)
    else:
        m = {"url": url, "slug": vod.slug, "vod_id": vod.vod_id, "title": vod.title, "duration": vod.duration,
             "source": None, "vocab": opts.vocab, "defaults": _defaults(opts), "candidates": [], "clips": [], "next_i": 1}
    m["vocab"] = opts.vocab

    msgs = []
    plan = []   # (start, end, score)
    if opts.at:
        m["source"] = "manual"
        plan = [(*_parse_at(a), 0.0) for a in opts.at]
    else:
        found, source = [], None
        if opts.source in ("auto", "chat"):
            try:
                progress("chat", 0, "Sohbet indiriliyor (yarıda kesilirse kaldığı yerden devam eder)")
                data = sources.fetch_chat(vod, jd, mode=opts.chat_mode, start=opts.start_at,
                                          progress=lambda f, n, st="": progress("chat", f, f"{st} · {n} mesaj"))
                msgs = data.msgs
                kw = dict(lead=opts.lead, min_len=opts.min_len, max_len=opts.max_len, skip_start=max(120.0, opts.start_at))
                if data.dense:
                    found = peaks.find_peaks(msgs, vod.duration, n=CANDIDATES, **kw)
                else:
                    found = peaks.find_peaks_sparse(msgs, data.coverage, data.baseline, vod.duration,
                                                    n=CANDIDATES, **kw)
                source = "chat"
                log.info("sohbet: %d mesaj, %d aday an", len(msgs), len(found))
            except kick.KickError as e:
                log.warning("sohbet alınamadı: %s", e)
                if opts.source == "chat":
                    raise
                if not opts.audio_ok:
                    raise NeedsAudioConfirm(f"Sohbet alınamadı ({e})", audio_estimate_mb(vod.duration, sources.platform(url))) from e
                progress("chat", 1.0, f"Sohbet alınamadı ({e}); ses seviyesine geçiliyor")
        if not found and opts.source in ("auto", "audio"):
            progress("audio", 0, f"Ses analizi için düşük kaliteli VOD indiriliyor (tahmini ~{audio_estimate_mb(vod.duration, sources.platform(url))} MB)")
            found = audio_peaks.find(url, jd, vod.duration, n=CANDIDATES, lead=opts.lead,
                                     min_len=opts.min_len, max_len=opts.max_len,
                                     skip_start=max(120.0, opts.start_at))
            source = "audio"
        if not found:
            raise RuntimeError("Belirgin bir an bulunamadı (sohbet boş / ses düz).")
        m["source"] = source
        m["candidates"] = [{"start": p.start, "end": p.end, "score": p.score, "used": False} for p in found]
        have = [(c["start"], c["end"]) for c in m["clips"]]            # resume: skip moments that already have a clip
        fresh = [p for p in found if not any(_overlaps(p.start, p.end, a, b) for a, b in have)]
        if have:
            log.info("devam: %d klip zaten var, %d aday an ona çakışmıyor", len(have), len(fresh))
        for p in fresh[:opts.n + max(0, opts.drafts)]:
            plan.append((p.start, p.end, p.score))
        picked = {(p.start, p.end) for p in fresh[:opts.n + max(0, opts.drafts)]}
        for c in m["candidates"]:
            c["used"] = (c["start"], c["end"]) in picked or any(_overlaps(c["start"], c["end"], a, b) for a, b in have)
        if not plan:
            raise RuntimeError("Bu yayında yeni klip çıkacak aday an kalmadı (hepsi zaten kesilmiş).")
    save(jd, m)

    snap = m["defaults"]["snap"] and not opts.at              # manual ranges are used exactly
    progress("clips", 0.0, f"{len(plan)} an indiriliyor (aynı anda birkaç tane)")
    recs = scout_many(jd, m, plan, _style_layout(m), lambda st, fr, msg="": progress(st, fr * 0.4, msg), snap)
    save(jd, m)
    k = len(recs) if opts.at else opts.n                       # the rest stay drafts, rendered when picked
    render_many(jd, m, recs[:k], lambda st, fr, msg="": progress(st, 0.4 + fr * 0.6, msg))
    m = load(jd)
    progress("done", 1.0, "Bitti")
    m["dir"] = str(jd)
    return m


def _defaults(o: Options) -> dict:
    return {"captions": o.captions, "keep_plain": o.keep_plain, "style": o.style, "layout": o.layout,
            "max_height": o.max_height, "snap": o.snap, "reactions": o.reactions, "min_len": o.min_len, "max_len": o.max_len}
