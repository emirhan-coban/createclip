"""Caption/audio sync helpers: measure how well word starts match audible speech onsets and snap them.

Whisper's word timestamps (DTW over attention) are usually within ~0.1-0.2 s but can drift on music or
overlapping speech. We look at the real audio envelope: wherever speech *starts after a pause* near a word
start, the word start is moved to that rising edge."""
import subprocess
from pathlib import Path

import numpy as np

SR = 16000
HOP = 160            # 10 ms frames


def envelope(media: Path):
    """-> (rms per 10 ms frame as float array)."""
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(media), "-vn", "-ac", "1", "-ar", str(SR),
                          "-f", "f32le", "-"], capture_output=True, check=True).stdout
    x = np.frombuffer(raw, dtype=np.float32)
    n = len(x) // HOP
    if n == 0:
        return np.zeros(0)
    return np.sqrt((x[:n * HOP].reshape(n, HOP) ** 2).mean(axis=1))


def speech_mask(env, smooth=5):
    if len(env) == 0:
        return np.zeros(0, bool)
    k = np.ones(smooth) / smooth
    e = np.convolve(env, k, mode="same")
    floor = np.percentile(e, 20)
    thr = max(floor * 3.0, float(e.max()) * 0.03, 1e-4)
    return e > thr


def onsets(mask, min_gap=0.15):
    """Frame times (s) where speech starts after >= min_gap of non-speech."""
    gap = int(min_gap * 100)
    out = []
    quiet = gap          # treat the very beginning as quiet
    for i, m in enumerate(mask):
        if m:
            if quiet >= gap:
                out.append(i / 100.0)
            quiet = 0
        else:
            quiet += 1
    return out


def offsets(words, ons, window=0.3):
    """Signed distance (onset - word start) for each word that has an onset within `window`."""
    res = []
    if not ons:
        return res
    arr = np.array(ons)
    for w in words:
        d = arr - w["start"]
        j = int(np.argmin(np.abs(d)))
        if abs(d[j]) <= window:
            res.append(float(d[j]))
    return res


def report(media: Path, words) -> dict:
    env = envelope(media)
    ons = onsets(speech_mask(env))
    off = offsets(words, ons)
    if not off:
        return {"n": 0, "median": None, "mad": None, "words": len(words)}
    a = np.array(off)
    return {"n": len(off), "median": float(np.median(a)), "mad": float(np.median(np.abs(a - np.median(a)))),
            "words": len(words)}


def refine(media: Path, words, window=0.25):
    """Snap word starts that sit near a speech onset onto it; keep order and non-negative durations."""
    env = envelope(media)
    ons = onsets(speech_mask(env))
    if not ons or not words:
        return words
    arr = np.array(ons)
    out = [dict(w) for w in words]
    used = set()
    for w in out:
        d = arr - w["start"]
        j = int(np.argmin(np.abs(d)))
        if abs(d[j]) <= window and j not in used:
            used.add(j)
            shift = float(d[j])
            w["start"] = round(w["start"] + shift, 3)
            w["end"] = round(max(w["end"] + shift, w["start"] + 0.05), 3)
    out.sort(key=lambda w: w["start"])
    for a, b in zip(out, out[1:]):
        if a["end"] > b["start"]:
            a["end"] = round(max(b["start"], a["start"] + 0.03), 3)
    return out
