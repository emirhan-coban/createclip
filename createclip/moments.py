"""Second opinion on a finished clip: Gemini listens to the clip's audio and reads its transcript, then rates how
good a short-video moment it is (1-10) and why. Chat/loudness peaks stay the primary signal; the rating only
re-orders the inbox (see `rank`) and is skipped silently when no key is set or a call fails."""
import json
import re
import tempfile
from pathlib import Path

from . import gemini
from .log import run

MAX_AUDIO_S = 75


def _audio(video: Path) -> bytes:
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "a.mp3"
        p = run(["ffmpeg", "-y", "-v", "error", "-i", str(video), "-t", str(MAX_AUDIO_S), "-vn", "-ac", "1", "-ar", "16000",
                 "-b:a", "48k", str(out)], "ses kesiti", timeout=120)
        if p.returncode or not out.exists():
            raise gemini.GeminiError("Klip sesi çıkarılamadı.")
        return out.read_bytes()


def prompt(m: dict, text: str) -> str:
    return ("Ekteki ses, bir yayından kesilmiş kısa klibe ait. Bu anın kısa dikey videoda (Shorts/Reels/TikTok) izleyiciyi "
            "tutup tutmayacağını değerlendir: komik, şaşırtıcı, gergin ya da duygusal bir an mı, yoksa sıradan sohbet mi? "
            'Yalnızca şu JSON\'u döndür: {"puan": 1-10 arası tam sayı, "neden": "tek kısa cümle (Türkçe)"}\n\n'
            f"Yayıncı: {m.get('slug', '')}\nKonuşma metni:\n{text[:2500]}")


def parse(txt: str) -> dict:
    mt = re.search(r"\{.*\}", txt, re.S)
    try:
        d = json.loads(mt.group(0))
        return {"ai_score": max(1, min(10, int(d["puan"]))), "ai_reason": str(d.get("neden", "")).strip()[:200]}
    except (AttributeError, ValueError, KeyError, TypeError) as e:
        raise gemini.GeminiError("Puan yanıtı beklenen biçimde değil.") from e


def score(jd: Path, m: dict, rec: dict, text: str, gen=None, audio=_audio) -> dict:
    video = Path(jd) / rec["src"]
    return parse((gen or gemini.generate)(prompt(m, text), audio=audio(video)))


def rank(rec: dict) -> float:
    """Inbox order: peak score nudged by the AI rating (x0.6 for a 1, x1.5 for a 10); unrated clips keep their score."""
    base = rec.get("score") or 0
    ai = rec.get("ai_score")
    return base * (0.5 + ai / 10) if ai else base
