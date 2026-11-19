import argparse
import sys
from pathlib import Path

from . import cleanup as cleanupmod, compile as compilemod, doctor as doctormod, layout as layoutmod, log as logmod, pipeline, watch as watchmod

ROOT = Path(__file__).resolve().parent.parent


def _progress(stage, frac, msg=""):
    logmod.log.info("[%s] %d%% %s", stage, int(frac * 100), msg)
    print(f"[{stage:8}] {int(frac * 100):3d}%  {msg}", flush=True)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="createclip", description="Kick / YouTube yayın kaydı -> klipler (+altyazı, 9:16)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="Kick VOD veya YouTube (biten yayın) linkinden klip üret")
    r.add_argument("url")
    r.add_argument("-n", type=int, default=5, help="klip sayısı")
    r.add_argument("--captions", action=argparse.BooleanOptionalAction, default=True,
                   help="altyazılı sürüm üret (--no-captions: üretme)")
    r.add_argument("--plain", action=argparse.BooleanOptionalAction, default=True,
                   help="altyazısız sürümü de tut")
    r.add_argument("--font", choices=["montserrat", "poppins", "gabarito"], default="montserrat")
    r.add_argument("--mask-profanity", action="store_true", help="küfürleri yıldızla")
    r.add_argument("--layout", choices=["none", "blur", "crop", "stack", "face"], default="none",
                   help="9:16 yerleşim: none=yatay, blur=bulanık arka plan, crop=tek pencere, stack=iki pencere, "
                   "face=yüzü bul (üstte oyun, altta yüz; bulunamazsa blur)")
    r.add_argument("--reactions", action="store_true", help="o andaki izleyici sohbet mesajlarını videoya göm")
    r.add_argument("--source", choices=["auto", "chat", "audio"], default="auto",
                   help="an bulma kaynağı (auto: sohbet, olmazsa ses)")
    r.add_argument("--at", action="append", default=[], metavar="ZAMAN",
                   help="elle klip: '1:44:50' (45 sn) veya '1:44:50-1:45:40'; birden fazla verilebilir")
    r.add_argument("--full-chat", action="store_true",
                   help="sohbeti eksiksiz indir (varsayılan: akıllı mod, seyrek örnekleme + yoğun bölgeler)")
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

    r.add_argument("--audio-fallback", action="store_true",
                   help="sohbet yoksa ses analizine (tüm videoyu indirir) sormadan geç")
    r.add_argument("-v", "--verbose", action="store_true", help="ayrıntılı günlüğü ekrana da yaz")

    lg = sub.add_parser("logs", help="son günlük satırlarını göster")
    lg.add_argument("-n", type=int, default=80, help="kaç satır")
    lg.add_argument("--out", type=Path, default=ROOT)

    dc = sub.add_parser("doctor", help="kurulumu kontrol et (araçlar, model, disk, ağ)")
    dc.add_argument("--no-net", action="store_true", help="ağ kontrolünü atla")
    dc.add_argument("--out", type=Path, default=ROOT)

    ch = sub.add_parser("channels", help="izlenen kanalları yönet (add / list / rm)")
    ch.add_argument("action", choices=["add", "list", "rm"])
    ch.add_argument("url", nargs="?", help="kick.com/<kanal> veya youtube.com/@<kanal>")
    ch.add_argument("--min-minutes", type=float, default=30, help="bundan kısa yayınlar atlanır")
    ch.add_argument("--backfill", type=int, default=1, help="ilk eklemede kaç eski yayın kuyruğa girsin")
    ch.add_argument("-n", type=int, default=5, help="yayın başına klip sayısı")
    ch.add_argument("--layout", choices=["none", "blur", "crop", "stack", "face"], default="none")
    ch.add_argument("--max-height", type=int, default=720, choices=[480, 720, 1080])
    ch.add_argument("--out", type=Path, default=ROOT)

    w = sub.add_parser("watch", help="kanalları tara, yeni yayınları işle (gece çalıştırmak için)")
    w.add_argument("--every", type=float, default=6.0, help="tarama aralığı (saat)")
    w.add_argument("--once", action="store_true", help="bir kez tara + kuyruğu bitir, çık")
    w.add_argument("-v", "--verbose", action="store_true")
    w.add_argument("--out", type=Path, default=ROOT)

    qu = sub.add_parser("queue", help="kuyruk: list / retry <id> / confirm <id> / rm <id> / clear")
    qu.add_argument("action", choices=["list", "retry", "confirm", "rm", "clear"], nargs="?", default="list")
    qu.add_argument("id", nargs="?")
    qu.add_argument("--out", type=Path, default=ROOT)

    cl = sub.add_parser("cleanup", help="eski, yeniden üretilebilir dosyaları (ham kesit, kare, ses) temizle")
    cl.add_argument("--days", type=float, default=14, help="bundan yeni projelere dokunma")
    cl.add_argument("--yes", action="store_true", help="gerçekten sil (yoksa yalnız ne silineceğini göster)")
    cl.add_argument("--out", type=Path, default=ROOT)

    kp = sub.add_parser("keep", help="projeyi korumaya al (temizlik ve silme dokunmaz)")
    kp.add_argument("name")
    kp.add_argument("--off", action="store_true")
    kp.add_argument("--out", type=Path, default=ROOT)

    cp = sub.add_parser("compile", help='"Günün en iyi N anı" derlemesi (onaylanan kliplerden)')
    cp.add_argument("-n", type=int, default=5)
    cp.add_argument("--status", choices=["approved", "new", "all"], default="approved")
    cp.add_argument("--out", type=Path, default=ROOT)

    au = sub.add_parser("autostart", help="oturum açılınca arayüzü + otomatik izlemeyi kendiliğinden başlat (macOS)")
    au.add_argument("action", choices=["on", "off", "status"])
    au.add_argument("--port", type=int, default=8765)
    au.add_argument("--out", type=Path, default=ROOT)

    s = sub.add_parser("serve", help="yerel web arayüzünü başlat")
    s.add_argument("-v", "--verbose", action="store_true", help="ayrıntılı günlüğü ekrana da yaz")
    s.add_argument("--port", type=int, default=8765)
    s.add_argument("--out", type=Path, default=ROOT)

    a = ap.parse_args(argv)
    if a.cmd == "logs":
        print(logmod.tail(a.out / "output" / "createclip.log", a.n) or "(günlük boş)")
        return 0
    logfile = logmod.setup(a.out, getattr(a, "verbose", False))
    if a.cmd == "doctor":
        return doctormod.report(a.out, not a.no_net)
    if a.cmd == "cleanup":
        items = cleanupmod.plan(a.out, a.days)
        for pth, n in items:
            print(f"{n / 1e6:8.1f} MB  {pth}")
        total = sum(n for _, n in items)
        print(f"Toplam {total / 1e6:.1f} MB ({len(items)} öğe); korumalı ve {a.days:g} günden yeni projeler hariç.")
        if items and a.yes:
            print(f"Silindi: {cleanupmod.apply(items) / 1e6:.1f} MB")
        elif items:
            print("Silmek için --yes ekle.")
        return 0
    if a.cmd == "keep":
        cleanupmod.set_keep(a.out, a.name, not a.off)
        print("Korumaya alındı" if not a.off else "Koruma kaldırıldı")
        return 0
    if a.cmd == "compile":
        try:
            r = compilemod.build(a.out, a.n, a.status)
        except Exception as e:  # noqa: BLE001
            print(f"Hata: {e}", file=sys.stderr)
            return 1
        print(f"Derleme: {r['path']}\nKaynak listesi: {r['credits']}")
        return 0
    if a.cmd == "channels":
        if a.action == "list":
            for c in watchmod.load_channels(a.out):
                print(f"{c['name']:24} {c['url']}  (>= {c['min_minutes']:g} dk, ilk eklemede {c['backfill']} yayın)")
            return 0
        if not a.url:
            print("Kanal linki gerekli.", file=sys.stderr)
            return 2
        try:
            if a.action == "add":
                opts = {"n": a.n, "max_height": a.max_height,
                        "layout": {"mode": a.layout, "cells": layoutmod.default_cells(a.layout)}}
                c = watchmod.add_channel(a.out, a.url, min_minutes=a.min_minutes, backfill=a.backfill, options=opts)
                print(f"Eklendi: {c['name']}  →  `createclip watch --once` ile tara")
            else:
                print("Silindi" if watchmod.remove_channel(a.out, a.url) else "Böyle bir kanal yok")
        except ValueError as e:
            print(f"Hata: {e}", file=sys.stderr)
            return 1
        return 0
    if a.cmd == "queue":
        if a.action == "list":
            rows = watchmod.queue(a.out)
            for i in rows:
                print(f"{i['id']:14} {i['status']:13} {i['duration'] / 3600:5.1f}s  {i['title'][:46]:46} {i.get('project') or i.get('error') or ''}"[:200])
            print(f"({len(rows)} kayıt)")
        elif a.action == "clear":
            for i in watchmod.queue(a.out):
                if i["status"] in ("done", "skipped"):
                    watchmod.remove_item(a.out, i["id"])
        elif not a.id:
            print("Kayıt numarası (id) gerekli.", file=sys.stderr)
            return 2
        else:
            {"retry": watchmod.retry, "confirm": watchmod.confirm_audio, "rm": watchmod.remove_item}[a.action](a.out, a.id)
        return 0
    if a.cmd == "watch":
        print(f"İzleniyor; günlük: {logfile}  (Ctrl-C ile durdur, tekrar başlatınca kaldığı yerden devam eder)")
        try:
            watchmod.loop(a.out, a.every, a.once, _progress)
        except KeyboardInterrupt:
            print("\nDurduruldu.")
        return 0
    if a.cmd == "run":
        o = pipeline.Options(n=a.n, captions=a.captions, keep_plain=a.plain,
                             style={"font": a.font, "mask": a.mask_profanity, "size": a.size, "ypos": a.ypos,
                                    "chunk": a.chunk, "sync": a.sync},
                             min_len=a.min_len, max_len=a.max_len, max_height=a.max_height,
                             layout={"mode": a.layout, "cells": layoutmod.default_cells(a.layout)},
                             snap=not a.no_snap, source=a.source, at=a.at, vocab=a.vocab, reactions=a.reactions, chat_mode="full" if a.full_chat else "smart")
        try:
            try:
                m = pipeline.run(a.url, a.out, o, _progress)
            except pipeline.NeedsAudioConfirm as e:
                if a.audio_fallback or (sys.stdin.isatty() and input(f"{e}\nDevam edilsin mi? [e/H] ").strip().lower() in ("e", "evet", "y")):
                    o.audio_ok = True
                    m = pipeline.run(a.url, a.out, o, _progress)
                else:
                    print(f"{e}\nOnaylamak için --audio-fallback ekle (ya da --at ile elle zaman ver).", file=sys.stderr)
                    return 2
        except Exception as e:  # noqa: BLE001
            logmod.log.exception("run başarısız")
            print(f"Hata: {e}\nAyrıntı: {logfile}  (createclip logs)", file=sys.stderr)
            return 1
        print(f"\nÇıktı klasörü: {m['dir']}  (kaynak: {m['source']})")
        for c in m["clips"]:
            print(f"  #{c['i']} skor {c['score']}  {c['captioned'] or c['plain']}")
        return 0
    if a.cmd == "autostart":
        from . import autostart
        if a.action == "on":
            print(f"Açıldı: {autostart.on(a.out, a.port)}\nArayüz: http://127.0.0.1:{a.port}  (Ayarlar'dan 'Otomatik izle'yi aç)")
        elif a.action == "off":
            print("Kapatıldı." if autostart.off() else "Zaten kapalıydı.")
        else:
            print(autostart.status())
        return 0
    if a.cmd == "serve":
        import uvicorn
        from .web.app import make_app
        print(f"http://127.0.0.1:{a.port}   günlük: {logfile}")
        uvicorn.run(make_app(a.out), host="127.0.0.1", port=a.port, log_level="warning")
        return 0


if __name__ == "__main__":
    sys.exit(main())
