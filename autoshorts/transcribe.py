"""Word-level Turkish transcription with mlx-whisper (large-v3, Apple Silicon GPU). No separate alignment model:
word times come from Whisper's own attention (DTW). Needs the optional extra: pip install -e ".[speech]"."""
import importlib.util
import json
import os
import sys
import tempfile
import time
from pathlib import Path

from .proc import log, run

# large-v3 stays the default: on 6 real Turkish clips large-v3-turbo was 3-5x faster but dropped whole stretches of speech.
MODEL = os.environ.get("AUTOSHORTS_WHISPER_MODEL", "mlx-community/whisper-large-v3-mlx")


class TranscribeError(RuntimeError):
    pass


def available() -> bool:
    return importlib.util.find_spec("mlx_whisper") is not None      # not imported here: it would load the GPU libraries into the server


def cached() -> bool:
    """True when the model is already on disk (otherwise the first run would download ~3 GB)."""
    try:
        from huggingface_hub import snapshot_download
        snapshot_download(MODEL, local_files_only=True)
        return True
    except Exception:  # noqa: BLE001
        return False


def model_path() -> str:
    """The cached model, loaded offline: asking the hub (even only to check for updates) can hang forever on a
    half-working IPv6 route. A missing model is downloaded, with short timeouts."""
    try:
        from huggingface_hub import snapshot_download
        return snapshot_download(MODEL, local_files_only=True)
    except Exception:  # noqa: BLE001
        os.environ.setdefault("HF_HUB_ETAG_TIMEOUT", "20")
        os.environ.setdefault("HF_HUB_DOWNLOAD_TIMEOUT", "60")
        return MODEL


def _norm(w: str) -> str:
    return "".join(ch for ch in w.lower() if ch.isalnum())


def clean_asr(words):
    """Drop zero-length tokens and hallucination loops (one word repeated >=4 times within 4 s)."""
    words = [w for w in words if w["end"] - w["start"] >= 0.02]
    by_tok = {}
    for i, w in enumerate(words):
        by_tok.setdefault(_norm(w["word"]), []).append(i)
    drop = set()
    for idx in by_tok.values():
        for a in range(len(idx)):
            run = [j for j in idx[a:] if words[j]["start"] - words[idx[a]]["start"] <= 4.0]
            if len(run) >= 4:
                drop.update(run)
    return [w for i, w in enumerate(words) if i not in drop]


def transcribe_words(media: Path, language: str = "tr") -> list[dict]:
    """Runs Whisper in a child process: it can be cancelled, runs at the profile's priority, and the ~3 GB model is
    freed the moment it finishes instead of staying in the server."""
    if not available():
        raise TranscribeError("Konuşma analizi için mlx-whisper gerekli: ./.venv/bin/pip install -e '.[speech]'")
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "words.json"
        p = run([sys.executable, "-m", "autoshorts.transcribe", str(media), language, str(out)], "konuşma çözümü (Whisper)", timeout=3600)
        if p.returncode or not out.exists():
            raise TranscribeError("Konuşma çözülemedi: " + " ".join((p.stderr or "").split())[-300:])
        return json.loads(out.read_text())


def _transcribe_here(media: Path, language: str = "tr") -> list[dict]:
    if not available():
        raise TranscribeError("Konuşma analizi için mlx-whisper gerekli: ./.venv/bin/pip install -e '.[speech]'")
    import mlx_whisper
    t0 = time.time()
    log.info("transcribing %s", Path(media).name)
    r = mlx_whisper.transcribe(str(media), path_or_hf_repo=model_path(), language=language, word_timestamps=True,
                               condition_on_previous_text=False, no_speech_threshold=None, compression_ratio_threshold=2.4)
    words = []
    for seg in r["segments"]:
        for w in seg.get("words", []):
            txt = w["word"].strip()
            if txt and any(ch.isalnum() for ch in txt):      # drop "..." style tokens
                s = float(w["start"])
                e = min(float(w["end"]), s + 1.5)            # DTW sometimes stretches a word over silence
                words.append({"word": txt, "start": round(s, 3), "end": round(e, 3)})
    words = clean_asr(words)
    log.info("transcribed: %d words in %.1fs", len(words), time.time() - t0)
    return words


if __name__ == "__main__":           # python -m autoshorts.transcribe <media> <language> <out.json>
    media, language, dest = sys.argv[1:4]
    Path(dest).write_text(json.dumps(_transcribe_here(Path(media), language), ensure_ascii=False))
