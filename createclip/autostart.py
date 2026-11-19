"""`createclip autostart on|off|status`: a macOS LaunchAgent that starts the web UI (and with it the auto-watch)
at login, so the machine keeps scanning the followed channels without a terminal."""
import os
import plistlib
import subprocess
import sys
from pathlib import Path

LABEL = "com.createclip.serve"


def plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def build(root: Path, port: int = 8765) -> dict:
    return {"Label": LABEL, "ProgramArguments": [sys.executable, "-m", "createclip", "serve", "--port", str(port), "--out", str(root)],
            "RunAtLoad": True, "KeepAlive": True, "WorkingDirectory": str(root),
            "StandardOutPath": str(root / "output" / "autostart.log"), "StandardErrorPath": str(root / "output" / "autostart.log"),
            "EnvironmentVariables": {"PATH": os.environ.get("PATH", "/usr/bin:/bin:/opt/homebrew/bin:/usr/local/bin")}}


def _launchctl(*args) -> int:
    return subprocess.run(["launchctl", *args], capture_output=True).returncode


def on(root: Path, port: int = 8765) -> Path:
    p = plist_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    (Path(root) / "output").mkdir(parents=True, exist_ok=True)
    p.write_bytes(plistlib.dumps(build(Path(root), port)))
    _launchctl("bootout", f"gui/{os.getuid()}", str(p))
    if _launchctl("bootstrap", f"gui/{os.getuid()}", str(p)):
        raise RuntimeError("launchctl yükleyemedi; plist yazıldı, oturumu kapatıp açınca devreye girer.")
    return p


def off() -> bool:
    p = plist_path()
    _launchctl("bootout", f"gui/{os.getuid()}", str(p))
    existed = p.exists()
    p.unlink(missing_ok=True)
    return existed


def status() -> str:
    return "açık" if plist_path().exists() else "kapalı"
