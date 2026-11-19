"""After a VOD is processed: fill every new clip's title/description/tags and its AI moment rating automatically
(no button). Each step is best-effort: no key or an API failure leaves the clip as it was."""
from pathlib import Path

from . import gemini, moments, pipeline, review, titles
from .log import log


def fill_clip(jd: Path, m: dict, rec: dict, titles_fn=None, score_fn=None) -> bool:
    """Returns True if the record changed."""
    changed = False
    text = review._clip_text(jd, rec)
    if len(text.split()) >= 4:
        if not rec.get("title") and not rec.get("ai_titles_done") and (titles_fn or titles.available()):
            try:
                got = (titles_fn or titles.generate)(m, rec, text)
                rec["title"] = got["titles"][0]
                rec["title_options"] = got["titles"]
                rec["description"] = (got["description"] + "\n\n" if got["description"] else "") + review.credit(m, rec)
                rec["tags"] = got["tags"]
                rec["ai_titles_done"] = changed = True
            except titles.TitleError as e:
                log.warning("klip %s başlık üretilemedi: %s", rec["i"], e)
        if rec.get("ai_score") is None and (score_fn or gemini.available()):
            try:
                rec.update((score_fn or moments.score)(jd, m, rec, text))
                changed = True
            except gemini.GeminiError as e:
                log.warning("klip %s puanlanamadı: %s", rec["i"], e)
    return changed


def fill(jd: Path, only=None, **kw) -> int:
    jd = Path(jd)
    m = pipeline.load(jd)
    n = 0
    for rec in m["clips"]:
        if only is not None and rec["i"] not in only:
            continue
        n += fill_clip(jd, m, rec, **kw)
    if n:
        pipeline.save(jd, m)
        log.info("otomatik başlık/puan: %d klip", n)
    return n
