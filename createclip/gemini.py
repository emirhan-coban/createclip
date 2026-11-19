"""Minimal Gemini API client (urllib, no dependency). Used for clip titles and for scoring moments.
Free-tier note: Google may use free-tier inputs to improve its products, so the UI says so before a key is added.
Limits are not hard-coded; 429 / 5xx are retried with exponential back-off."""
import base64
import json
import os
import time
import urllib.error
import urllib.request

from . import settings
from .log import log

BASE = "https://generativelanguage.googleapis.com/v1beta/models"
MODEL = os.environ.get("CREATECLIP_GEMINI_MODEL", "gemini-flash-latest")      # Google's moving alias for Flash


class GeminiError(RuntimeError):
    pass


def key() -> str:
    return os.environ.get("GEMINI_API_KEY") or settings.get("gemini_key") or ""


def available() -> bool:
    return bool(key())


def _post(url: str, body: dict, api_key: str, timeout: int = 90) -> dict:
    req = urllib.request.Request(url, json.dumps(body).encode(),
                                 {"content-type": "application/json", "x-goog-api-key": api_key})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def generate(prompt: str, audio: bytes | None = None, json_out: bool = True, post=_post, sleep=time.sleep,
             retries: int = 3) -> str:
    """One request; returns the reply text. `audio` is mp3 bytes sent inline (keep it small, ~1 MB)."""
    k = key()
    if not k:
        raise GeminiError("Gemini anahtarı yok (Ayarlar'dan ekle ya da GEMINI_API_KEY ayarla).")
    parts = [{"text": prompt}]
    if audio:
        parts.append({"inline_data": {"mime_type": "audio/mp3", "data": base64.b64encode(audio).decode()}})
    body = {"contents": [{"parts": parts}], "generationConfig": {"temperature": 0.7}}
    if json_out:
        body["generationConfig"]["responseMimeType"] = "application/json"
    last = None
    for attempt in range(retries + 1):
        try:
            reply = post(f"{BASE}/{MODEL}:generateContent", body, k)
            break
        except urllib.error.HTTPError as e:
            last = e
            if e.code not in (429, 500, 502, 503, 504) or attempt == retries:
                raise GeminiError(f"Gemini hatası {e.code}" + (" (limit doldu, biraz sonra dene)" if e.code == 429 else "")) from e
            wait = 2 ** attempt * 4
            log.warning("Gemini %s, %d sn sonra tekrar", e.code, wait)
            sleep(wait)
        except Exception as e:  # noqa: BLE001
            raise GeminiError(f"Gemini isteği başarısız: {e}") from e
    try:
        return "".join(p.get("text", "") for p in reply["candidates"][0]["content"]["parts"])
    except (KeyError, IndexError, TypeError) as e:
        raise GeminiError("Gemini yanıtı boş (içerik engellenmiş olabilir).") from e
