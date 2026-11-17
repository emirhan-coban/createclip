import argparse
import sys
from pathlib import Path

from . import layout as layoutmod, pipeline

ROOT = Path(__file__).resolve().parent.parent


def _progress(stage, frac, msg=""):
    print(f"[{stage:8}] {int(frac * 100):3d}%  {msg}", flush=True)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="createclip", description="Kick VOD -> klipler (+altyazı, 9:16)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="Kick VOD linkinden klip üret")
    r.add_argument("url")
    r.add_argument("-n", type=int, default=5, help="klip sayısı")
    r.add_argument("--captions", action=argparse.BooleanOptionalAction, default=True,
                   help="altyazılı sürüm üret (--no-captions: üretme)")
    r.add_argument("--plain", action=argparse.BooleanOptionalAction, default=True,
                   help="altyazısız sürümü de tut")
    r.add_argument("--font", choices=["montserrat", "poppins", "gabarito"], default="montserrat")
    r.add_argument("--mask-profanity", action="store_true", help="küfürleri yıldızla")
    r.add_argument("--layout", choices=["none", "blur", "crop", "stack"], default="none",
                   help="9:16 yerleşim: none=yatay, blur=bulanık arka plan, crop=tek pencere, stack=iki pencere")
    r.add_argument("--source", choices=["auto", "chat", "audio"], default="auto",
                   help="an bulma kaynağı (auto: sohbet, olmazsa ses)")
    r.add_argument("--at", action="append", default=[], metavar="ZAMAN",
                   help="elle klip: '1:44:50' (45 sn) veya '1:44:50-1:45:40'; birden fazla verilebilir")
    r.add_argument("--full-chat", action="store_true", help="sohbeti eksiksiz indir (~19,6 dk; varsayılan hızlı mod ~18,4 dk, mesajların %%98'i)")
    r.add_argument("--vocab", default="", help="isteğe bağlı özel kelimeler (örn. 'Berk, Derbeder'); "
                   "kısa tut, uzun liste konuşmanın atlanmasına yol açabilir")
    r.add_argument("--size", type=float, help="altyazı boyutu (genişliğin oranı, örn. 0.06)")
    r.add_argument("--ypos", type=float, help="altyazı dikey konumu (0-1)")
    r.add_argument("--chunk", type=int, default=3, help="ekranda kaç kelime")
    r.add_argument("--sync", type=float, default=-0.08, help="altyazı kaydırma sn (+ geç, - erken)")
    r.add_argument("--min-len", type=float, default=25)
    r.add_argument("--max-len", type=float, default=60)
    r.add_argument("--max-height", type=int, default=720, choices=[480, 720, 1080])
    r.add_argument("--no-snap", action="store_true", help="kesimleri konuşma aralarına hizalama")
    r.add_argument("--out", type=Path, default=ROOT, help="çıktı kök klasörü")

    s = sub.add_parser("serve", help="yerel web arayüzünü başlat")
    s.add_argument("--port", type=int, default=8765)
    s.add_argument("--out", type=Path, default=ROOT)

    a = ap.parse_args(argv)
    if a.cmd == "run":
        o = pipeline.Options(n=a.n, captions=a.captions, keep_plain=a.plain,
                             style={"font": a.font, "mask": a.mask_profanity, "size": a.size, "ypos": a.ypos,
                                    "chunk": a.chunk, "sync": a.sync},
                             min_len=a.min_len, max_len=a.max_len, max_height=a.max_height,
                             layout={"mode": a.layout, "cells": layoutmod.default_cells(a.layout)},
                             snap=not a.no_snap, source=a.source, at=a.at, vocab=a.vocab, full_chat=a.full_chat)
        try:
            m = pipeline.run(a.url, a.out, o, _progress)
        except Exception as e:  # noqa: BLE001
            print(f"Hata: {e}", file=sys.stderr)
            return 1
        print(f"\nÇıktı klasörü: {m['dir']}  (kaynak: {m['source']})")
        for c in m["clips"]:
            print(f"  #{c['i']} skor {c['score']}  {c['captioned'] or c['plain']}")
        return 0
    if a.cmd == "serve":
        import uvicorn
        from .web.app import make_app
        print(f"http://127.0.0.1:{a.port}")
        uvicorn.run(make_app(a.out), host="127.0.0.1", port=a.port, log_level="warning")
        return 0


if __name__ == "__main__":
    sys.exit(main())
