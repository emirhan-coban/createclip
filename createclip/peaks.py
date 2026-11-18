"""Peak finding. Chat: emote-only chatter is down-weighted. Scores are z-scores against the
stream's own baseline; intro/outro skipped; peaks spaced apart. Works on any per-bin score
series, so the audio-loudness fallback shares the same logic."""
import re
import statistics
from collections import Counter
from dataclasses import dataclass

EMOTE_RE = re.compile(r"\[emote:\d+:[^\]]*\]")
BIN = 10  # seconds


def is_emote_only(content: str) -> bool:
    return not EMOTE_RE.sub("", content).strip()


@dataclass
class Peak:
    time: float      # start of the hot bin (seconds)
    score: float     # z-score
    start: float     # suggested clip start
    end: float       # suggested clip end


def bin_scores(msgs, duration):
    n = int(duration // BIN) + 2
    users = [dict() for _ in range(n)]
    for m in msgs:
        b = int(m["t"] // BIN)
        if 0 <= b < n:
            w = 0.35 if is_emote_only(m["c"]) else 1.0
            u = users[b]
            u[m["u"]] = max(u.get(m["u"], 0), w)   # one vote per chatter per bin
    raw = [sum(u.values()) for u in users]
    return smooth(raw)


def smooth(raw):
    """2-bin (20 s) smoothing so a burst split across a bin edge still counts."""
    n = len(raw)
    return [raw[i] + (raw[i + 1] if i + 1 < n else 0) for i in range(n)]


def peaks_from_scores(scores, duration, n=5, lead=20, min_len=25, max_len=60,
                      skip_start=120, skip_end=60, min_gap=90, mean=None, sd=None):
    if not scores:
        return []
    mean = statistics.fmean(scores) if mean is None else mean
    sd = (statistics.pstdev(scores) if sd is None else sd) or 1.0
    z = [(s - mean) / sd for s in scores]
    order = sorted(range(len(z)), key=lambda i: -z[i])
    peaks = []
    for i in order:
        t = i * BIN
        if t < skip_start or t > duration - skip_end or z[i] <= 0:
            continue
        if any(abs(t - p.time) < min_gap for p in peaks):
            continue
        start = max(0.0, t - lead)
        j = i + 2                        # extend while density stays clearly above baseline
        while j < len(z) and (j * BIN - start) < max_len and z[j] > 0.5:
            j += 1
        end = min(duration, max(start + min_len, j * BIN), start + max_len)
        peaks.append(Peak(t, round(z[i], 2), start, end))
        if len(peaks) >= n:
            break
    return sorted(peaks, key=lambda p: -p.score)


def find_peaks(msgs, duration, **kw):
    if not msgs:
        return []
    return peaks_from_scores(bin_scores(msgs, duration), duration, **kw)


def top_words(msgs, k=20):
    """Frequent non-emote words in chat (biases the speech model's vocabulary)."""
    c = Counter()
    for m in msgs:
        txt = EMOTE_RE.sub(" ", m["c"])
        for w in re.findall(r"[A-Za-zÇĞİÖŞÜçğıöşü]{4,}", txt):
            c[w.replace("İ", "i").replace("I", "ı").lower()] += 1   # Turkish-aware lowercase
    return [w for w, _ in c.most_common(k)]


# ---------------------------------------------------------------- smart (sparse) chat
WIN = 5  # seconds covered by one chat request


def window_scores(msgs, n_windows):
    """Weighted unique chatters per 5 s window (emote-only chatters count 0.35)."""
    users = [dict() for _ in range(n_windows + 2)]
    for m in msgs:
        b = int(m["t"] // WIN)
        if 0 <= b < len(users):
            w = 0.35 if is_emote_only(m["c"]) else 1.0
            u = users[b]
            u[m["u"]] = max(u.get(m["u"], 0), w)
    return [sum(u.values()) for u in users]


def _bins(ws):
    return smooth([ws[2 * i] + ws[2 * i + 1] for i in range(len(ws) // 2)])


def coarse_candidates(msgs, starts, duration, n=40):
    """Peak times (s) estimated from the sparsely sampled windows only (stage 1 of smart mode)."""
    nw = int(duration // WIN) + 1
    ws = window_scores(msgs, nw)
    have = {int(s // WIN) for s in starts}
    k = max(1, min((b - a for a, b in zip(sorted(have), sorted(have)[1:])), default=1))
    filled = [0.0] * len(ws)
    for i in have:                      # a sampled window stands for its neighbours: only used to rank regions
        for j in range(max(0, i - k // 2), min(len(ws), i + k // 2 + 1)):
            filled[j] = max(filled[j], ws[i])
    pk = peaks_from_scores(_bins(filled), duration, n=n, min_gap=60)
    return [p.time for p in pk]


def find_peaks_sparse(msgs, covered, baseline_starts, duration, **kw):
    """Peaks when only part of the stream was crawled. Bins that were not crawled count as an average bin
    (so they can never win); the z-score baseline comes from the evenly spaced stage-1 windows, which are an
    unbiased sample. `covered` has .covers(a, b)."""
    if not msgs:
        return []
    nw = int(duration // WIN) + 1
    ws = window_scores(msgs, nw)
    base = [ws[int(s // WIN)] for s in baseline_starts if int(s // WIN) < len(ws)] or [0.0]
    mw = statistics.fmean(base)
    sw = statistics.pstdev(base) or 1.0
    raw = []
    for j in range(len(ws) // 2):
        got = [covered.covers((2 * j + k) * WIN, (2 * j + k + 1) * WIN) for k in (0, 1)]
        if all(got):
            raw.append(ws[2 * j] + ws[2 * j + 1])
        elif any(got):
            raw.append(2 * ws[2 * j + (0 if got[0] else 1)])
        else:
            raw.append(2 * mw)
    return peaks_from_scores(smooth(raw), duration, mean=4 * mw, sd=3 * sw, **kw)
