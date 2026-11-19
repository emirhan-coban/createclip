"""Near-duplicate clips: the same moment found twice (overlapping time ranges in one project) or the same
spoken content in different projects (e.g. two channels covering one event)."""
import re

MIN_WORDS = 8


def tokens(text: str) -> list:
    return re.findall(r"[\wçğıöşüÇĞİÖŞÜ]+", (text or "").lower())


def similarity(a: str, b: str) -> float:
    """Jaccard similarity of 3-word shingles (0..1); 0 for texts too short to compare."""
    ta, tb = tokens(a), tokens(b)
    if len(ta) < MIN_WORDS or len(tb) < MIN_WORDS:
        return 0.0
    sa = {tuple(ta[i:i + 3]) for i in range(len(ta) - 2)}
    sb = {tuple(tb[i:i + 3]) for i in range(len(tb) - 2)}
    return len(sa & sb) / max(1, len(sa | sb))


def overlap(a0, a1, b0, b1) -> float:
    """Shared fraction of the shorter range."""
    inter = max(0.0, min(a1, b1) - max(a0, b0))
    return inter / max(1e-9, min(a1 - a0, b1 - b0))


def mark(rows: list, thr: float = 0.5) -> list:
    """Adds row["dup_of"] = "<project>#<i>" to the lower-scored of every duplicate pair. rows need project, i,
    score, start, end, text."""
    best = sorted(rows, key=lambda r: -r["score"])
    kept = []
    for r in best:
        r["dup_of"] = None
        for k in kept:
            same_proj = k["project"] == r["project"]
            if (same_proj and overlap(k["start"], k["end"], r["start"], r["end"]) > 0.5) or \
                    similarity(k.get("text", ""), r.get("text", "")) >= thr:
                r["dup_of"] = f"{k['project']}#{k['i']}"
                break
        if not r["dup_of"]:
            kept.append(r)
    return rows
