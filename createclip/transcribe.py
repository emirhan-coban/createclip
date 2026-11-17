"""Word-level Turkish transcription with mlx-whisper (large-v3, Apple Silicon GPU).
No separate alignment model is needed: word times come from Whisper's own attention (DTW)."""
import json
from pathlib import Path

MODEL = "mlx-community/whisper-large-v3-mlx"


def build_prompt(vocab: str = "") -> str:
    """No prompt by default. Measured on real clips: a descriptive prompt (streamer, title, chat words)
    made Whisper skip whole stretches of speech (27 vs 69 words, 15 vs 51) and read the prompt out loud.
    Only an explicit, user-supplied vocabulary is passed, and it is opt-in."""
    vocab = (vocab or "").strip()
    return f"{vocab}." if vocab else ""


def clean_words(words):
    """Drop zero-length tokens and hallucination loops (one word repeated >=4 times within 4 s)."""
    words = [w for w in words if w["end"] - w["start"] >= 0.02]
    by_tok = {}
    for i, w in enumerate(words):
        by_tok.setdefault(_norm(w["word"]), []).append(i)
    drop = set()
    for tok, idx in by_tok.items():
        for a in range(len(idx)):
            run = [j for j in idx[a:] if words[j]["start"] - words[idx[a]]["start"] <= 4.0]
            if len(run) >= 4:
                drop.update(run)
    return [w for i, w in enumerate(words) if i not in drop]


def _norm(w: str) -> str:
    return "".join(ch for ch in w.lower() if ch.isalnum())


def strip_prompt_echo(words, prompt: str):
    """Whisper sometimes 'reads out' the prompt during silence; drop runs of >=3 words from it."""
    if not prompt:
        return words
    ptoks = [_norm(t) for t in prompt.split()]
    grams = {tuple(ptoks[i:i + 3]) for i in range(len(ptoks) - 2)}
    drop = set()
    toks = [_norm(w["word"]) for w in words]
    for i in range(len(toks) - 2):
        if tuple(toks[i:i + 3]) in grams:
            drop.update((i, i + 1, i + 2))
    return [w for i, w in enumerate(words) if i not in drop]


def transcribe_words(media: Path, prompt: str = "", language: str = "tr"):
    import mlx_whisper
    r = mlx_whisper.transcribe(
        str(media), path_or_hf_repo=MODEL, language=language, word_timestamps=True,
        initial_prompt=prompt or None, condition_on_previous_text=False,
        no_speech_threshold=None, compression_ratio_threshold=2.4)
    words = []
    for seg in r["segments"]:
        for w in seg.get("words", []):
            txt = w["word"].strip()
            if txt and any(ch.isalnum() for ch in txt):      # drop "..." style tokens
                s = float(w["start"])
                e = min(float(w["end"]), s + 1.5)            # DTW sometimes stretches a word over silence
                words.append({"word": txt, "start": round(s, 3), "end": round(e, 3)})
    return words


def save_words(words, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(words, ensure_ascii=False, indent=1))


def load_words(path: Path):
    return json.loads(path.read_text())


def words_to_text(words) -> str:
    return " ".join(w["word"] for w in words)


def apply_text_edit(words, new_text: str):
    """Replace the transcript text but keep the timing. Same word count -> 1:1.
    Different count -> re-time evenly (by length) across the original span."""
    toks = new_text.split()
    if not toks or not words:
        return words
    if len(toks) == len(words):
        return [{**w, "word": t} for w, t in zip(words, toks)]
    s, e = words[0]["start"], words[-1]["end"]
    total = sum(len(t) for t in toks) or 1
    out, cur = [], s
    for t in toks:
        d = (e - s) * len(t) / total
        out.append({"word": t, "start": round(cur, 3), "end": round(cur + d, 3)})
        cur += d
    return out


def to_srt(words, path: Path, per_line: int = 5):
    def ts(x):
        ms = int(round(x * 1000))
        return f"{ms // 3600000:02d}:{ms % 3600000 // 60000:02d}:{ms % 60000 // 1000:02d},{ms % 1000:03d}"
    lines = []
    for i in range(0, len(words), per_line):
        ch = words[i:i + per_line]
        lines.append(f"{i // per_line + 1}\n{ts(ch[0]['start'])} --> {ts(ch[-1]['end'])}\n"
                     + " ".join(w["word"] for w in ch) + "\n")
    path.write_text("\n".join(lines))
