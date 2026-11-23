import { useEffect, useRef, useState } from "react";
import { motion } from "motion/react";
import { Link } from "react-router-dom";
import { api, hms, type Clip } from "../lib/api";

export function ClipDialog({ clip, onClose, onChanged }: { clip: Clip; onClose: () => void; onChanged: () => void }) {
  const [title, setTitle] = useState(clip.title);
  const [desc, setDesc] = useState(clip.description);
  const [note, setNote] = useState("");
  const closeBtn = useRef<HTMLButtonElement>(null);
  const panel = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const before = document.activeElement as HTMLElement | null;
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";                 // the page behind must not scroll
    closeBtn.current?.focus();
    const k = (e: KeyboardEvent) => {
      if (e.key === "Escape") { onClose(); return; }
      if (e.key !== "Tab" || !panel.current) return;        // keep Tab inside the dialog
      const f = panel.current.querySelectorAll<HTMLElement>("button, a[href], input, textarea, video");
      if (!f.length) return;
      const first = f[0], last = f[f.length - 1];
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    };
    window.addEventListener("keydown", k);
    return () => { window.removeEventListener("keydown", k); document.body.style.overflow = overflow; before?.focus?.(); };
  }, [onClose]);
  const flash = (m: string) => { setNote(m); setTimeout(() => setNote(""), 1600); };

  const save = async () => { await api(`/api/clips/${clip.id}/edit`, { title, description: desc }); onChanged(); flash("Kaydedildi"); };
  const copy = async () => { await navigator.clipboard.writeText(`${title}\n\n${desc}`); flash("Kopyalandı"); };
  const del = async () => { if (confirm("Bu klip ve dosyaları silinsin mi?")) { await api(`/api/clips/${clip.id}/delete`, {}); onChanged(); onClose(); } };

  return (
    <motion.div className="fixed inset-0 z-50 grid place-items-center bg-ink/45 p-4 backdrop-blur-sm" initial={{ opacity: 0 }} animate={{ opacity: 1 }}
      onMouseDown={(e) => e.target === e.currentTarget && onClose()} role="dialog" aria-modal="true" aria-label={clip.title || "Klip"}>
      <motion.div ref={panel} initial={{ y: 24, scale: 0.98 }} animate={{ y: 0, scale: 1 }} transition={{ type: "spring", stiffness: 260, damping: 26 }}
        className="grid max-h-[92vh] w-full max-w-4xl grid-cols-1 overflow-auto rounded-[28px] bg-paper shadow-lift md:grid-cols-[auto_1fr]">
        <div className="bg-black md:max-h-[92vh]">
          <video src={`/media/${clip.id}.mp4`} poster={`/media/${clip.id}.jpg`} controls autoPlay muted loop playsInline
            className="mx-auto block h-[min(70vh,640px)] max-w-full bg-black object-contain" />
        </div>
        <div className="flex flex-col gap-3 p-6">
          <div className="flex items-start justify-between gap-3">
            <p className="tnum text-sm text-ink-2">{hms(clip.start)}–{hms(clip.end)} · skor {clip.score.toFixed(1)}</p>
            <button ref={closeBtn} onClick={onClose} aria-label="Kapat" className="grid size-8 place-items-center rounded-full border border-line text-lg leading-none hover:border-ink">×</button>
          </div>
          <label className="text-sm text-ink-2" htmlFor="ct">Başlık</label>
          <input id="ct" value={title} onChange={(e) => setTitle(e.target.value)} className="rounded-xl border border-line bg-raised px-3 py-2.5 text-[1.05rem] font-semibold outline-none focus:border-ink" />
          <label className="text-sm text-ink-2" htmlFor="cd">Açıklama</label>
          <textarea id="cd" value={desc} onChange={(e) => setDesc(e.target.value)} rows={6} className="resize-y rounded-xl border border-line bg-raised px-3 py-2.5 text-[0.95rem] outline-none focus:border-ink" />
          <div className="mt-1 flex flex-wrap items-center gap-2">
            <button onClick={save} className="rounded-full bg-lime px-5 py-2.5 text-sm font-semibold text-lime-ink active:scale-95">Kaydet</button>
            <Link to={`/editor/${clip.id}`} className="rounded-full bg-ink px-5 py-2.5 text-sm font-semibold text-paper active:scale-95">Düzenle</Link>
            <button onClick={copy} className="rounded-full border border-line px-4 py-2.5 text-sm hover:border-ink">Kopyala</button>
            <a href={`/media/${clip.id}.mp4`} download={clip.file} className="rounded-full border border-line px-4 py-2.5 text-sm hover:border-ink">İndir</a>
            <button onClick={() => api(`/api/clips/${clip.id}/reveal`, {})} className="rounded-full border border-line px-4 py-2.5 text-sm hover:border-ink">Finder'da göster</button>
            <button onClick={del} className="rounded-full px-3 py-2.5 text-sm text-danger hover:underline">Sil</button>
            <span role="status" className="text-sm text-ink-2">{note}</span>
          </div>
          <p className="mt-auto pt-3 text-sm text-ink-2">
            Kaynak: <a className="underline underline-offset-2" href={clip.video_url} target="_blank" rel="noopener noreferrer">{clip.video_title || clip.video_url}</a>
          </p>
        </div>
      </motion.div>
    </motion.div>
  );
}
