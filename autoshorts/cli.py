import argparse
import json
import logging
import shutil
import sys
import time
from pathlib import Path

from . import config, download, pipeline, store


def _parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="autoshorts", description="video linki -> en iyi anlar -> dikey klipler -> klasöre kaydet")
    ap.add_argument("--root", type=Path, default=Path.cwd(), help="çalışma klasörü (varsayılan: bulunduğun klasör)")
    ap.add_argument("-v", "--verbose", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("doctor", help="gerekli araçları kontrol et")

    r = sub.add_parser("run", help="bir video linkinden klipleri üret ve ready/ klasörüne kaydet")
    r.add_argument("url")
    r.add_argument("-n", type=int, help="klip sayısı")
    r.add_argument("--engine", choices=["auto", "chat", "audio", "transcript"])
    r.add_argument("--at", action="append", default=[], metavar="ZAMAN", help="elle: '1:44:50' ya da '1:44:50-1:45:40'")
    r.add_argument("--start", metavar="ZAMAN", help="bu zamandan öncesini yok say (örn. 10:00)")

    a = sub.add_parser("add", help="kanalı izlemeye al (kick.com/<kanal> ya da youtube.com/@kanal)")
    a.add_argument("url")
    a.add_argument("--backfill", type=int, default=3, help="ilk eklemede kaç eski yayın işlensin")
    sub.add_parser("sources", help="izlenen kanallar")
    rm = sub.add_parser("remove", help="kanalı izlemeden çıkar")
    rm.add_argument("url")

    w = sub.add_parser("watch", help="kanalları tara ve yeni yayınların kliplerini üret")
    w.add_argument("--once", action="store_true")
    w.add_argument("--every", type=float, help="dakika")

    sv = sub.add_parser("serve", help="yerel web arayüzünü başlat")
    sv.add_argument("--port", type=int, default=8765)
    sv.add_argument("--open", action="store_true", help="tarayıcıyı aç")
    sub.add_parser("clips", help="üretilen klipler ve durumları")

    c = sub.add_parser("config", help="ayar göster / değiştir: autoshorts config anahtar=değer")
    c.add_argument("pairs", nargs="*")
    return ap


def _coerce(v: str):
    if v.lower() in ("true", "false"):
        return v.lower() == "true"
    try:
        return json.loads(v)
    except ValueError:
        return v


def main(argv=None) -> int:
    a = _parser().parse_args(argv)
    config.configure(a.root)
    logging.basicConfig(level=logging.DEBUG if a.verbose else logging.ERROR, format="%(asctime)s %(levelname)s %(message)s")
    cfg, con = config.load(), store.connect()

    if a.cmd == "doctor":
        bad = 0
        for tool in ("ffmpeg", "ffprobe", "yt-dlp", "curl"):
            ok = bool(shutil.which(tool))
            bad += not ok
            print(f"[{'ok' if ok else 'HATA'}] {tool}")
        print(f"çıktı klasörü: {config.root() / cfg['output_dir']}")
        # optional parts: not errors, but say what is missing and how to get it
        import importlib.util
        from . import transcribe
        dist = Path(__file__).resolve().parent.parent / "web" / "dist"        # not imported from api: FastAPI is optional
        opt = [("web arayüzü (FastAPI)", importlib.util.find_spec("fastapi") is not None and importlib.util.find_spec("uvicorn") is not None, "pip install -e '.'"),
               ("arayüz derlemesi", (dist / "index.html").exists(), "cd web && npm install && npm run build"),
               ("altyazı: Pillow", importlib.util.find_spec("PIL") is not None, "pip install -e '.[captions]'"),
               ("altyazı: mlx-whisper", transcribe.available(), "pip install -e '.[captions]'"),
               ("altyazı: konuşma modeli", transcribe.cached(), "ilk altyazıda ~3 GB iner")]
        for name, ok, fix in opt:
            print(f"[{'ok' if ok else 'uyarı'}] {name}" + ("" if ok else f"  ({fix})"))
        free = shutil.disk_usage(config.root()).free / 1e9
        print(f"[{'ok' if free > 5 else 'uyarı'}] boş disk: {free:.0f} GB")
        return 1 if bad else 0

    if a.cmd == "run":
        if a.start:
            cfg["skip_start_min"] = pipeline._parse_time(a.start) / 60
        try:
            ids = pipeline.process_video(con, cfg, a.url, a.n, a.at, a.engine)
        except download.BlockedError as e:
            print(e)
            return 2
        except (download.DownloadError, RuntimeError) as e:
            print(f"Hata: {e}")
            return 1
        print(f"{len(ids)} klip hazır -> {config.root() / cfg['output_dir']}")
        return 0

    if a.cmd == "add":
        print("eklendi" if store.add_source(con, download.normalize_channel(a.url), backfill=a.backfill) else "zaten ekli")
        return 0
    if a.cmd == "sources":
        for s in store.sources(con):
            print(s["url"])
        return 0
    if a.cmd == "remove":
        store.remove_source(con, download.normalize_channel(a.url))
        print("kaldırıldı")
        return 0

    if a.cmd == "watch":
        every = (a.every or cfg["watch_every_min"]) * 60
        while True:
            print(time.strftime("%H:%M"), pipeline.watch_once(con, cfg))
            if a.once:
                return 0
            time.sleep(every)

    if a.cmd == "serve":
        from . import api
        api.serve(a.port, a.open)
        return 0

    if a.cmd == "clips":
        for c in store.clips(con):
            print(f"#{c['id']:<4} {c['status']:<8} skor {c['score']:<6} {c['file'] or c['error'] or ''}")
        return 0

    if a.cmd == "config":
        if not a.pairs:
            print(json.dumps(cfg, indent=2, ensure_ascii=False))
            return 0
        changes = {}
        for p in a.pairs:
            k, _, v = p.partition("=")
            if k not in config.DEFAULTS:
                print(f"bilinmeyen ayar: {k}")
                return 1
            changes[k] = _coerce(v)
        config.save(changes)
        return 0
    return 0
