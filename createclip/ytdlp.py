"""One place that builds yt-dlp command lines.

On some setups (seen with Python 3.15 on macOS) yt-dlp's default HTTP handler stalls forever at
"Downloading webpage" for both Kick and YouTube, while the curl_cffi handler (--impersonate chrome) answers in
seconds. So whenever a Chrome impersonation target is available we use it; otherwise plain yt-dlp."""
import functools
import shutil
import subprocess


class YtDlpMissing(RuntimeError):
    pass


@functools.lru_cache(maxsize=1)
def _impersonation(path: str) -> tuple:
    try:
        out = subprocess.run([path, "--list-impersonate-targets"], capture_output=True, text=True, timeout=30).stdout
    except (OSError, subprocess.TimeoutExpired):
        return ()
    for line in out.splitlines():
        parts = line.split()
        if parts and parts[0].lower().startswith("chrome") and "unavailable" not in line.lower():
            return ("--impersonate", "chrome")
    return ()


def cmd(*args: str) -> list:
    """['yt-dlp', '--impersonate', 'chrome', *args] (impersonation only if this install supports it)."""
    path = shutil.which("yt-dlp")
    if not path:
        raise YtDlpMissing("yt-dlp bulunamadı (brew install yt-dlp).")
    return [path, *_impersonation(path), *args]
