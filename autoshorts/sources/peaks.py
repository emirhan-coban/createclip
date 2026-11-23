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


# ---------------------------------------------------------------- giveaway / copy-paste spam
# During a giveaway everybody types the same thing ("katılıyorum", "!katıl"): a huge, sustained chat peak that is not
# a moment. Laughter is repeated too, but it is a real reaction, so it is exempt.
LAUGH = re.compile(r"^(?:(?:a?ha)+h*|(?:he)+h*|k{3,}|l+o+l+|x+d+|a+s+|s+a+)$")
DOMINANT_MIN = 8        # messages of one text inside a 10 s bin ...
DOMINANT_SHARE = 0.4    # ... making up this share of the bin's messages: that text dominates the bin
CAMPAIGN_BINS = 15      # a text dominating this many bins within CAMPAIGN_SPAN seconds is a campaign ("çekiliş"): muted everywhere
CAMPAIGN_SPAN = 900     # (a hype wave of one word is a few bins long, a giveaway keeps coming for many minutes)
LOCAL_WEIGHT = 0.25     # a single bin dominated by one longer text (not yet a campaign): its votes count less
SHORT = 5               # short texts ("gol", "pog", "as", "+") are reactions, never muted by dominance


def norm_text(content: str) -> str:
    return re.sub(r"\s+", " ", EMOTE_RE.sub(" ", content).lower()).strip()


def analyze(msgs) -> tuple[set, set]:
    """(texts muted everywhere, {(bin, text)} that dominate one bin). Random different text is never touched: only a
    longer text that many people paste again and again counts as spam, so a hype moment where everybody mashes the
    keyboard (or shouts one short word) stays a moment."""
    bins: dict[int, Counter] = {}
    for m in msgs:
        t = norm_text(m["c"])
        if t:
            bins.setdefault(int(m["t"] // BIN), Counter())[t] += 1
    local, dom = set(), {}
    for b, c in bins.items():
        total = sum(c.values())
        for t, k in c.items():
            if k >= DOMINANT_MIN and k >= DOMINANT_SHARE * total and len(t) > SHORT and not LAUGH.match(t):
                local.add((b, t))
                dom.setdefault(t, []).append(b)
    span = CAMPAIGN_SPAN // BIN
    spam = set()
    for t, bs in dom.items():
        bs.sort()
        if any(bs[i + CAMPAIGN_BINS - 1] - bs[i] <= span for i in range(len(bs) - CAMPAIGN_BINS + 1)):
            spam.add(t)
    return spam, local


def weight(m, spam: set, local: set) -> float:
    """Vote weight of one message: 0 for bot commands and campaign spam, small inside a dominated bin, 0.35 emote-only."""
    t = norm_text(m["c"])
    if t.startswith("!") or t in spam:
        return 0.0
    if (int(m["t"] // BIN), t) in local:
        return LOCAL_WEIGHT
    return 0.35 if is_emote_only(m["c"]) else 1.0


def spam_report(msgs) -> tuple[int, list[str]]:
    """How many messages are ignored as giveaway/command spam, and the most common texts (for the terminal)."""
    spam, local = analyze(msgs)
    c = Counter(norm_text(m["c"]) for m in msgs if weight(m, spam, local) < 0.35)
    return sum(c.values()), [t[:40] for t, _ in c.most_common(3) if t]


def bin_scores(msgs, duration):
    n = int(duration // BIN) + 2
    users = [dict() for _ in range(n)]
    spam, local = analyze(msgs)
    for m in msgs:
        b = int(m["t"] // BIN)
        if 0 <= b < n:
            w = weight(m, spam, local)
            if w <= 0:
                continue
            u = users[b]
            u[m["u"]] = max(u.get(m["u"], 0), w)   # one vote per chatter per bin
    raw = [sum(u.values()) for u in users]
    return smooth(raw)


def smooth(raw):
    """2-bin (20 s) smoothing so a burst split across a bin edge still counts."""
    n = len(raw)
    return [raw[i] + (raw[i + 1] if i + 1 < n else 0) for i in range(n)]


def _crowded(times: list, cap_n: int, window: float) -> bool:
    """True when cap_n + 1 of the (sorted) times fall inside one `window`-second span."""
    return any(times[i + cap_n] - times[i] < window for i in range(len(times) - cap_n))


def peaks_from_scores(scores, duration, n=5, lead=20, min_len=25, max_len=60,
                      skip_start=120, skip_end=60, min_gap=90, mean=None, sd=None, cap_window=600, cap_n=3):
    if not scores:
        return []
    base = scores[int(skip_start // BIN):] or scores     # the skipped opening (crowded intro chat) must not skew the baseline
    mean = statistics.fmean(base) if mean is None else mean
    sd = (statistics.pstdev(base) if sd is None else sd) or 1.0
    z = [(s - mean) / sd for s in scores]
    order = sorted(range(len(z)), key=lambda i: -z[i])
    peaks = []
    for i in order:
        t = i * BIN
        if t < skip_start or t > duration - skip_end or z[i] <= 0:
            continue
        if any(abs(t - p.time) < min_gap for p in peaks):
            continue
        if cap_n and _crowded(sorted([p.time for p in peaks] + [t]), cap_n, cap_window):
            continue                       # variety: at most `cap_n` clips from any `cap_window` seconds (one long hype/giveaway)
        start = max(skip_start, t - lead)
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
    spam, local = analyze(msgs)
    for m in msgs:
        b = int(m["t"] // WIN)
        if 0 <= b < len(users):
            w = weight(m, spam, local)
            if w <= 0:
                continue
            u = users[b]
            u[m["u"]] = max(u.get(m["u"], 0), w)
    return [sum(u.values()) for u in users]


def _bins(ws):
    return smooth([ws[2 * i] + ws[2 * i + 1] for i in range(len(ws) // 2)])


def coarse_candidates(msgs, starts, duration, n=40, skip_start=120):
    """Peak times (s) estimated from the sparsely sampled windows only (stage 1 of smart mode)."""
    nw = int(duration // WIN) + 1
    ws = window_scores(msgs, nw)
    have = {int(s // WIN) for s in starts}
    k = max(1, min((b - a for a, b in zip(sorted(have), sorted(have)[1:])), default=1))
    filled = [0.0] * len(ws)
    for i in have:                      # a sampled window stands for its neighbours: only used to rank regions
        for j in range(max(0, i - k // 2), min(len(ws), i + k // 2 + 1)):
            filled[j] = max(filled[j], ws[i])
    pk = peaks_from_scores(_bins(filled), duration, n=n, min_gap=60, skip_start=skip_start)
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
