"""Speech-aware cutting and wording, rule based (no model, no network).

Input is a Whisper word list [{word, start, end}] in source seconds. Used to
  * snap a cut to sentence boundaries, so a clip does not begin or end in the middle of a sentence,
  * score how much is actually said (a chat peak with no speech is a different kind of moment),
  * pick a title sentence and keyword hashtags for the clip."""
import re
from collections import Counter

END = re.compile(r"[.!?…]+[\"')\]]*$")
GAP = 0.7          # seconds of silence that also end a sentence

# short Turkish + English function words that make poor hashtags
STOP = set("""ve ama fakat ya da de ki mi mı mu mü bu şu o bir iki çok daha en gibi için ile ne nasıl neden var yok
değil evet hayır tamam işte yani şey ben sen biz siz onlar bana sana ona bizi sizi beni seni onu bunu şunu bunlar
şimdi sonra önce hani aslında zaten bile sadece artık hem ise ya yine kadar olarak olan oldu olur olacak bence
the a an and or but to of in on is are was were it this that i you we they he she be do not so just like
""".split())


def sentences(words: list[dict]) -> list[dict]:
    """Group words into sentences: {start, end, text, words}. A sentence ends at ./?/! or after a pause."""
    out, cur = [], []
    for i, w in enumerate(words):
        cur.append(w)
        nxt = words[i + 1] if i + 1 < len(words) else None
        if END.search(w["word"].strip()) or nxt is None or nxt["start"] - w["end"] > GAP:
            out.append({"start": cur[0]["start"], "end": cur[-1]["end"], "words": cur,
                        "text": " ".join(x["word"].strip() for x in cur).strip()})
            cur = []
    return out


def snap(words: list[dict], start: float, end: float, *, min_len: float, max_len: float,
         before: float = 8.0, after_start: float = 4.0, before_end: float = 4.0, after: float = 8.0) -> tuple[float, float]:
    """Move [start, end] to the nearest sentence start / end (inside the given reach) and keep the length in range.
    Nothing is changed when there is no speech near the edge."""
    sent = sentences(words)
    if not sent:
        return start, end
    starts = [s["start"] for s in sent if start - before <= s["start"] <= start + after_start]
    ns = min(starts, key=lambda t: abs(t - start)) if starts else start
    ends = [s["end"] for s in sent if end - before_end <= s["end"] <= end + after and s["end"] > ns + min_len]
    ne = min(ends, key=lambda t: abs(t - end)) if ends else end
    ns, ne = max(0.0, ns - 0.15), ne + 0.3                     # breathing room, so the first/last word is not clipped
    if ne - ns > max_len + after:                              # never let snapping run away with the length
        ne = ns + max_len
    if ne - ns < min_len:
        return start, end
    return round(ns, 2), round(ne, 2)


def density(words: list[dict], start: float, end: float) -> float:
    """Spoken words per second inside [start, end]."""
    n = sum(1 for w in words if w["end"] > start and w["start"] < end)
    return round(n / max(1.0, end - start), 2)


def _tokens(text: str) -> list[str]:
    return [t for t in re.findall(r"[\wçğıöşüÇĞİÖŞÜ]+", text.lower()) if len(t) > 2 and t not in STOP and not t.isdigit()]


def keywords(words: list[dict], n: int = 3) -> list[str]:
    """Most repeated meaningful words, as hashtag candidates."""
    c = Counter(_tokens(" ".join(w["word"] for w in words)))
    return [w for w, k in c.most_common(n * 3) if k >= 2][:n]


def title(words: list[dict], limit: int = 70) -> str | None:
    """The most 'quotable' sentence: 4-14 words, early in the clip, with rarer words. None when little is said."""
    best, best_score = None, 0.0
    sent = sentences(words)
    if not sent:
        return None
    freq = Counter(_tokens(" ".join(s["text"] for s in sent)))
    for i, s in enumerate(sent):
        toks = _tokens(s["text"])
        n = len(s["text"].split())
        if n < 4 or n > 16 or not toks:
            continue
        score = sum(1.0 / freq[t] for t in toks) + (1.5 if s["text"].rstrip().endswith(("!", "?")) else 0) - 0.15 * i
        if score > best_score:
            best, best_score = s["text"], score
    if not best:
        return None
    best = best.strip(" ,;:-")
    best = best[:1].upper() + best[1:]
    if len(best) > limit:
        best = best[:limit].rsplit(" ", 1)[0].rstrip(",;:-") + "…"
    return best
