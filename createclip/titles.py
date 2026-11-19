"""Title / description / tag suggestions: Gemini (free tier, preferred) or the Claude API. Opt-in: it only runs when
a key is configured, because the clip's transcript is sent to that provider. Without a key the deterministic
suggestion from review.suggest() is used."""
import json
import os
import re
import urllib.request

from . import gemini

API = "https://api.anthropic.com/v1/messages"
MODEL = os.environ.get("CREATECLIP_TITLE_MODEL", "claude-sonnet-5-5")


class TitleError(RuntimeError):
    pass


def available() -> bool:
    return gemini.available() or bool(os.environ.get("ANTHROPIC_API_KEY"))


def _post(body: dict, key: str) -> dict:
    req = urllib.request.Request(API, json.dumps(body).encode(), {"content-type": "application/json", "x-api-key": key,
                                                                   "anthropic-version": "2023-06-01"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read())
    except Exception as e:  # noqa: BLE001
        raise TitleError(f"Claude isteği başarısız: {e}") from e


def prompt(m: dict, rec: dict, text: str) -> str:
    return (
        "Aşağıda bir yayından kesilmiş kısa klibin konuşma metni var. Kısa dikey video (Shorts/Reels/TikTok) için "
        "Türkçe 3 farklı başlık (en çok 60 karakter, merak uyandıran ama yanıltmayan), 2-3 cümlelik açıklama ve 5-8 "
        "etiket üret. Yalnızca şu JSON'u döndür: "
        '{"basliklar":["..","..",".."],"aciklama":"..","etiketler":["..",".."]}\n\n'
        f"Yayıncı: {m.get('slug', '')}\nYayın başlığı: {m.get('title', '')}\nKlip süresi: {rec['end'] - rec['start']:.0f} sn\n"
        f"Konuşma metni:\n{text[:3000]}")


def parse(reply: dict) -> dict:
    return parse_text("".join(b.get("text", "") for b in reply.get("content", []) if b.get("type") == "text"))


def parse_text(txt: str) -> dict:
    mt = re.search(r"\{.*\}", txt, re.S)
    if not mt:
        raise TitleError("Model yanıtında JSON yok.")
    try:
        d = json.loads(mt.group(0))
        titles = [str(t).strip() for t in d["basliklar"] if str(t).strip()][:3]
        tags = [str(t).strip().lstrip("#") for t in d.get("etiketler", []) if str(t).strip()][:10]
        desc = str(d.get("aciklama", "")).strip()
    except (ValueError, KeyError, TypeError) as e:
        raise TitleError("Model yanıtı beklenen biçimde değil.") from e
    if not titles:
        raise TitleError("Model başlık üretmedi.")
    return {"titles": titles, "description": desc, "tags": tags}


def generate(m: dict, rec: dict, text: str, post=_post, gem=None) -> dict:
    if len(text.split()) >= 4 and (gem or gemini.available()):
        try:
            return parse_text((gem or gemini.generate)(prompt(m, rec, text)))
        except gemini.GeminiError as e:
            raise TitleError(str(e)) from e
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise TitleError("ANTHROPIC_API_KEY ayarlı değil (terminalde: export ANTHROPIC_API_KEY=...).")
    if len(text.split()) < 4:
        raise TitleError("Klipte yeterli konuşma yok.")
    reply = post({"model": MODEL, "max_tokens": 600, "messages": [{"role": "user", "content": prompt(m, rec, text)}]}, key)
    return parse(reply)
