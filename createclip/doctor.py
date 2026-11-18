"""`createclip doctor`: check the things that actually broke on real setups (stalling yt-dlp handler, Whisper model
asking the hub, missing tools, low disk, unreachable sites) and say what to do about each."""
import shutil
import subprocess
from pathlib import Path

from . import transcribe, ytdlp

OK, WARN, FAIL = "ok", "uyarı", "HATA"


def _ver(cmd):
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
        return (out.stdout or out.stderr).strip().splitlines()[0]
    except (OSError, subprocess.TimeoutExpired, IndexError):
        return None


def _reach(url: str) -> bool:
    try:
        p = subprocess.run(["curl", "-s", "-o", "/dev/null", "-m", "12", "-w", "%{http_code}", "-A", "Mozilla/5.0", url],
                           capture_output=True, text=True, timeout=20)
        return p.stdout.strip().startswith(("2", "3", "4"))        # any HTTP answer = reachable (Cloudflare may 403)
    except (OSError, subprocess.TimeoutExpired):
        return False


def checks(root: Path, net: bool = True) -> list:
    rows = []

    def add(level, name, msg):
        rows.append((level, name, msg))

    for tool, fix in (("ffmpeg", "brew install ffmpeg"), ("ffprobe", "brew install ffmpeg"), ("curl", "")):
        v = _ver([tool, "-version"]) if tool != "curl" else _ver(["curl", "--version"])
        add(OK if v else FAIL, tool, v or f"bulunamadı. {fix}")
    y = shutil.which("yt-dlp")
    if not y:
        add(FAIL, "yt-dlp", "bulunamadı: brew install yt-dlp")
    else:
        add(OK, "yt-dlp", _ver([y, "--version"]) or "?")
        ytdlp._impersonation.cache_clear()
        imp = ytdlp._impersonation(y)
        add(OK if imp else WARN, "yt-dlp bağlantısı",
            "Chrome taklidi (curl_cffi) açık" if imp else
            "curl_cffi/Chrome taklidi yok; bazı kurulumlarda yt-dlp 'Downloading webpage'de takılır. "
            "Çözüm: yt-dlp'yi curl_cffi ile kur (pip install 'yt-dlp[curl-cffi]')")
    try:
        from huggingface_hub import snapshot_download
        snapshot_download(transcribe.MODEL, local_files_only=True)
        add(OK, "Whisper modeli", "önbellekte (çevrimdışı yüklenir)")
    except Exception:  # noqa: BLE001
        add(WARN, "Whisper modeli", "önbellekte yok; ilk altyazıda ~3 GB iner")
    free = shutil.disk_usage(Path(root) if Path(root).exists() else Path.home()).free / 1e9
    add(OK if free > 20 else WARN if free > 5 else FAIL, "disk", f"{free:.0f} GB boş" + ("" if free > 20 else " (klipler yer kaplar; ready/ ve raw/ temizle)"))
    if net:
        for name, url in (("Kick", "https://kick.com/"), ("YouTube", "https://www.youtube.com/")):
            ok = _reach(url)
            add(OK if ok else WARN, f"{name} erişimi", "erişildi" if ok else "yanıt yok (ağ/engel)")
    return rows


def report(root: Path, net: bool = True) -> int:
    rows = checks(root, net)
    for level, name, msg in rows:
        print(f"[{level:5}] {name:18} {msg}")
    return 1 if any(r[0] == FAIL for r in rows) else 0
