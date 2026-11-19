"""macOS desktop notifications (osascript). Silent no-op elsewhere or on any failure."""
import subprocess
import sys


def notify(title: str, text: str = "") -> bool:
    if sys.platform != "darwin":
        return False
    esc = lambda s: str(s).replace("\\", "\\\\").replace('"', '\\"')[:200]  # noqa: E731
    try:
        subprocess.run(["osascript", "-e", f'display notification "{esc(text)}" with title "{esc(title)}"'],
                       capture_output=True, timeout=10)
        return True
    except (OSError, subprocess.SubprocessError):
        return False
