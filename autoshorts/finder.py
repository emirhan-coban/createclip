"""Stage 2: find the best moments of a long video.

Engines
  chat        chat activity (unique chatters per 10 s, emote spam down-weighted, z-score against the stream's own
              baseline). Best for live streams; Kick and YouTube chat replay.
  audio       loudness peaks (shouting / laughter). Works without chat; needs the audio track (YouTube ~0.35 MB/min,
              Kick has no audio-only stream so its smallest video, ~1.7 MB/min).
  transcript  ClipsAI (the library from the video): finds clips from the transcript. Built for podcasts, interviews
              and speeches, not for game streams. Optional: `pip install clipsai` plus whisperx.
  auto        chat, and audio when the chat is unavailable.
"""
import re
import time
from dataclasses import dataclass
from pathlib import Path

from . import download
from .proc import log, run
from .sources import kick, peaks, youtube


class FinderError(RuntimeError):
    pass


@dataclass
class Moment:
    start: float
    end: float
    score: float
    engine: str


def _skip(cfg: dict) -> float:
    return max(120.0, float(cfg.get("skip_start_min", 0)) * 60)


def _peak_kw(cfg: dict) -> dict:
    return dict(lead=cfg["lead"], min_len=cfg["min_len"], max_len=cfg["max_len"], skip_start=_skip(cfg))


def _from_peaks(found, engine, n) -> list[Moment]:
    return [Moment(p.start, p.end, p.score, engine) for p in found[:n]]


# ---------------------------------------------------------------- chat
def _noop(frac, msg=""):
    pass


def _noop_emit(kind, **data):
    pass


def _series(values, points=240):
    """Down-sample a per-bin series to at most `points` values (max of each group, so peaks survive)."""
    if len(values) <= points:
        return [round(v, 2) for v in values]
    step = len(values) / points
    return [round(max(values[int(i * step):max(int((i + 1) * step), int(i * step) + 1)]), 2) for i in range(points)]


def by_chat(video: download.Video, cfg: dict, cache: Path, n: int, progress=_noop, emit=_noop_emit) -> list[Moment]:
    cache.mkdir(parents=True, exist_ok=True)
    skip = _skip(cfg)

    def chat_progress(f, count, stage=""):
        # Kick runs two phases: sparse sampling (first quarter of the bar), then dense crawls around the candidates
        sub = f * 0.25 if stage == "örnekleme" else (0.25 + 0.75 * f if stage else f)
        progress(min(sub, 0.95), f"Sohbet indiriliyor: {stage or 'tamam'} %{int(f * 100)} · {count} mesaj")
        emit("chat", frac=round(f, 3), messages=count, stage=stage or "tamam")
    if video.platform == "kick":
        def snapshot(msgs):
            emit("activity", source="chat", partial=True, bin_sec=peaks.BIN, duration=video.duration, messages=len(msgs),
                 values=_series(peaks.bin_scores(msgs, video.duration)))
        data = kick.fetch_chat(video.vod, cache, mode="smart", start=skip, progress=chat_progress, on_snapshot=snapshot)
    elif video.platform == "youtube":
        progress(0.02, "YouTube sohbet tekrarı indiriliyor")
        data = youtube.fetch_chat(video.vod, cache, mode="smart", start=skip, progress=chat_progress)
    else:
        raise FinderError("Sohbet yalnızca Kick ve YouTube için destekleniyor.")
    progress(0.97, f"{len(data.msgs)} mesaj çözümleniyor, zirveler aranıyor")
    emit("activity", source="chat", partial=False, bin_sec=peaks.BIN, duration=video.duration, messages=len(data.msgs),
         values=_series(peaks.bin_scores(data.msgs, video.duration)))
    kw = _peak_kw(cfg)
    if data.dense:
        found = peaks.find_peaks(data.msgs, video.duration, n=n, **kw)
    else:
        found = peaks.find_peaks_sparse(data.msgs, data.coverage, data.baseline, video.duration, n=n, **kw)
    log.info("chat: %d messages, %d moments", len(data.msgs), len(found))
    return _from_peaks(found, "chat", n)


# ---------------------------------------------------------------- audio
def loudness_series(media: Path, bin_sec: int = peaks.BIN, duration: float = 0.0, progress=None) -> list[float]:
    """Linear RMS per `bin_sec` window via ffmpeg astats. progress(fraction) follows ffmpeg's own clock when the
    duration is known (a 5 hour stream takes a couple of minutes: the UI must not sit silent)."""
    sr = 16000
    last = [0.0]

    def on_line(line: str):
        m = re.match(r"out_time_(?:us|ms)=(\d+)", line)
        if m and progress and duration and time.time() - last[0] > 0.7:
            last[0] = time.time()
            progress(min(0.99, int(m.group(1)) / 1e6 / duration))
    p = run(["ffmpeg", "-v", "error", "-nostats", "-progress", "pipe:1", "-i", str(media), "-vn", "-ac", "1", "-ar", str(sr), "-af",
             f"asetnsamples=n={sr * bin_sec}:p=0,astats=metadata=1:reset=1,"
             "ametadata=print:key=lavfi.astats.Overall.RMS_level:file=-", "-f", "null", "-"],
            "loudness", timeout=3 * 3600, on_line=on_line)
    vals = []
    for m in re.finditer(r"RMS_level=(-?inf|-?[0-9.]+)", p.stdout):
        db = -90.0 if "inf" in m.group(1) else float(m.group(1))
        vals.append(10 ** (max(db, -90.0) / 20))
    if not vals:
        raise FinderError("Ses seviyesi ölçülemedi.")
    return vals


def by_audio(video: download.Video, cfg: dict, cache: Path, n: int, progress=_noop, emit=_noop_emit) -> list[Moment]:
    progress(0.02, "Ses indiriliyor")
    emit("audio", phase="download", frac=0.0, text="Ses indiriliyor")

    def dl(f, t):
        progress(0.02 + 0.5 * f, f"Ses indiriliyor: {t}")
        emit("audio", phase="download", frac=round(f, 3), text=f"Ses indiriliyor {t}")
    media = download.fetch_audio(video.url, cache / "audio.bin", dl)
    progress(0.55, "Ses seviyesi ölçülüyor (uzun yayınlarda birkaç dakika sürebilir)")
    emit("audio", phase="measure", frac=0.0, text="Ses seviyesi ölçülüyor")

    def meas(f):
        progress(0.55 + 0.4 * f, f"Ses seviyesi ölçülüyor %{int(f * 100)}")
        emit("audio", phase="measure", frac=round(f, 3), text=f"Ses seviyesi ölçülüyor %{int(f * 100)}")
    raw = loudness_series(media, duration=video.duration, progress=meas)
    progress(0.97, "Zirveler aranıyor")
    emit("activity", source="audio", partial=False, bin_sec=peaks.BIN, duration=video.duration, messages=0,
         values=_series(peaks.smooth(raw)))
    found = peaks.peaks_from_scores(peaks.smooth(raw), video.duration, n=n, **_peak_kw(cfg))
    return _from_peaks(found, "audio", n)


# ---------------------------------------------------------------- transcript (ClipsAI)
def by_transcript(video: download.Video, cfg: dict, cache: Path, n: int, progress=_noop, emit=_noop_emit) -> list[Moment]:
    try:
        from clipsai import ClipFinder, Transcriber
    except ImportError as e:
        raise FinderError("ClipsAI kurulu değil: pip install clipsai 'whisperx@git+https://github.com/m-bain/whisperx.git' "
                          "(torch gerekir; Python 3.15'te kurulmayabilir, 3.12 öner).") from e
    media = download.fetch_audio(video.url, cache / "audio.bin")
    transcription = Transcriber().transcribe(audio_file_path=str(media))
    clips = ClipFinder(min_clip_duration=cfg["min_len"], max_clip_duration=cfg["max_len"]).find_clips(transcription=transcription)
    skip = _skip(cfg)
    out = [Moment(c.start_time, c.end_time, 0.0, "transcript") for c in clips if c.start_time >= skip]
    return out[:n]


# ---------------------------------------------------------------- entry point
def find(video: download.Video, cfg: dict, cache: Path, n: int | None = None, engine: str | None = None,
         progress=_noop, emit=_noop_emit) -> list[Moment]:
    """progress(fraction 0..1 of the search, text); emit(kind, **data) for the UI's structured events."""
    n = n or cfg["clips_per_video"]
    engine = engine or cfg["engine"]
    if engine == "chat":
        return by_chat(video, cfg, cache, n, progress, emit)
    if engine == "audio":
        return by_audio(video, cfg, cache, n, progress, emit)
    if engine == "transcript":
        return by_transcript(video, cfg, cache, n, progress)
    try:                                                   # auto
        found = by_chat(video, cfg, cache, n, progress, emit)
        if found:
            return found
    except download.BlockedError:
        raise
    except (kick.KickError, FinderError, RuntimeError) as e:
        log.warning("chat unavailable (%s), using audio loudness", e)
        progress(0.0, f"Sohbet alınamadı ({str(e)[:80]}); ses seviyesine geçiliyor")
        emit("fallback", reason=str(e)[:160])
    return by_audio(video, cfg, cache, n, progress, emit)
