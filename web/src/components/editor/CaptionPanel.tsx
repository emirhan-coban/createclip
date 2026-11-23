import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../../lib/api";
import { FONTS, applyTextEdit, defaultCaptions, type CapStyle, type FontKey, type Word } from "../../lib/captions";
import type { Project } from "../../lib/layout";
import { useJobPoll } from "../../lib/useJobPoll";

type Edit = (fn: (p: Project) => Project, key?: string) => void;

export function CaptionPanel({ clipId, project, edit }: { clipId: number; project: Project; edit: Edit }) {
  const cap = project.captions ?? defaultCaptions();
  const st = cap.style;
  const [status, setStatus] = useState<{ available: boolean; cached: boolean } | null>(null);
  const [jobId, setJobId] = useState<number | null>(null);
  const [err, setErr] = useState("");
  const job = useJobPoll(jobId);
  useEffect(() => { api<{ available: boolean; cached: boolean }>("/api/captions/status").then(setStatus).catch(() => {}); }, []);

  const apply = (words: Word[]) => edit((p) => { p.captions = { ...(p.captions ?? defaultCaptions()), words, enabled: true }; return p; });
  const generate = async (force: boolean) => {
    setErr("");
    try {
      if (!force) {
        const r = await api<{ words: Word[] }>(`/api/clips/${clipId}/words`);
        if (r.words.length) { apply(r.words); return; }       // already transcribed earlier
      }
      setJobId((await api<{ id: number }>(`/api/clips/${clipId}/transcribe`, {})).id);
    } catch (e) { setErr((e as Error).message); }
  };
  useEffect(() => {
    if (job?.status !== "done") return;
    setJobId(null);
    api<{ words: Word[] }>(`/api/clips/${clipId}/words`).then((r) => apply(r.words)).catch((e) => setErr((e as Error).message));
  }, [job?.status]); // eslint-disable-line react-hooks/exhaustive-deps

  const setStyle = (patch: Partial<CapStyle>, key: string) => edit((p) => { p.captions.style = { ...p.captions.style, ...patch }; return p; }, key);
  const running = job && (job.status === "running" || job.status === "queued");
  const failed = job && (job.status === "failed" || job.status === "blocked");

  // transcript of the part that is inside the cut; editing keeps the timing
  const inRange = useMemo(() => cap.words.map((w, i) => (w.end > project.trim.in && w.start < project.trim.out ? i : -1)).filter((i) => i >= 0), [cap.words, project.trim.in, project.trim.out]);
  const joined = inRange.map((i) => cap.words[i].word).join(" ");
  const [text, setText] = useState(joined);
  const own = useRef(false);
  useEffect(() => { if (own.current) own.current = false; else setText(joined); }, [joined]);
  const onText = (v: string) => {
    setText(v);
    own.current = true;
    edit((p) => {
      const all = p.captions.words;
      const idx = all.map((w, i) => (w.end > p.trim.in && w.start < p.trim.out ? i : -1)).filter((i) => i >= 0);
      if (!idx.length) return p;
      const first = idx[0], last = idx[idx.length - 1];
      p.captions.words = [...all.slice(0, first), ...applyTextEdit(all.slice(first, last + 1), v), ...all.slice(last + 1)];
      return p;
    }, "cap-text");
  };

  const range = (label: string, value: number, min: number, max: number, step: number, key: keyof CapStyle, show: (v: number) => string) => (
    <label className="block text-sm">
      <span className="flex justify-between"><span>{label}</span><span className="tnum text-ink-2">{show(value)}</span></span>
      <input type="range" min={min} max={max} step={step} value={value} className="mt-1 w-full accent-[var(--ink)]"
        onChange={(e) => setStyle({ [key]: Number(e.target.value) } as Partial<CapStyle>, `cap-${key}`)} />
    </label>
  );
  const field = "w-full rounded-xl border border-line bg-raised px-3 py-2 outline-none focus:border-ink";

  return (
    <section aria-label="Altyazı">
      <h2 className="title mb-3 text-lg">Altyazı</h2>
      {cap.words.length === 0 ? (
        <div>
          {running ? (
            <div role="status">
              <p className="text-sm font-medium">Konuşma çözülüyor…</p>
              <p className="mt-1 text-xs text-ink-2">Genellikle yarım dakika sürer. İlk seferde model belleğe yüklenir.</p>
              <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-paper-2"><div className="h-full w-1/3 animate-[slide_1.4s_ease-in-out_infinite] rounded-full bg-lime" /></div>
            </div>
          ) : (
            <>
              <p className="mb-3 text-sm text-ink-2">Konuşmayı kelime kelime yazıya döker; aktif kelime vurgulanır.</p>
              {status && !status.available ? (
                <p className="text-sm text-danger">Altyazı için mlx-whisper gerekli: <code className="rounded bg-paper-2 px-1">pip install -e ".[captions]"</code></p>
              ) : (
                <button onClick={() => generate(false)} className="rounded-full bg-lime px-5 py-2.5 text-sm font-semibold text-lime-ink active:scale-95">
                  {status && !status.cached ? "Modeli indir ve altyazı oluştur" : "Altyazı oluştur"}
                </button>
              )}
              {status && status.available && !status.cached && <p className="mt-2 text-xs text-ink-2">Konuşma modeli (~3 GB) bu bilgisayarda yok, ilk seferde indirilir.</p>}
            </>
          )}
          {(failed || err) && <p role="alert" className="mt-3 text-sm text-danger">{err || job?.error}</p>}
        </div>
      ) : (
        <div className="flex flex-col gap-4">
          <label className="flex items-center gap-2 text-sm font-medium">
            <input type="checkbox" checked={cap.enabled} onChange={(e) => edit((p) => { p.captions.enabled = e.target.checked; return p; })} className="size-4 accent-[var(--ink)]" />
            Altyazıyı göster
          </label>

          <div>
            <label htmlFor="cap-text" className="text-sm font-medium">Metin</label>
            <textarea id="cap-text" value={text} onChange={(e) => onText(e.target.value)} rows={5} spellCheck={false}
              className={`${field} mt-1 resize-y text-[0.95rem] leading-snug`} />
            <p className="mt-1 text-xs text-mute">Yalnızca kırpılan bölümün sözleri. Kelime sayısı aynı kalırsa zamanlama birebir korunur.</p>
            <button onClick={() => generate(true)} disabled={!!running} className="mt-1 text-xs text-ink-2 underline underline-offset-2">Konuşmayı yeniden çıkar</button>
          </div>

          <div>
            <label htmlFor="cap-font" className="text-sm font-medium">Yazı tipi</label>
            <select id="cap-font" value={st.font} onChange={(e) => setStyle({ font: e.target.value as FontKey }, "cap-font")} className={`${field} mt-1`}>
              {(Object.keys(FONTS) as FontKey[]).map((k) => <option key={k} value={k}>{FONTS[k].label}</option>)}
            </select>
          </div>
          {range("Boyut", st.size, 0.03, 0.14, 0.0025, "size", (v) => `${Math.round(v * 1000) / 10}`)}
          {range("Dikey konum", st.ypos, 0.05, 0.9, 0.005, "ypos", (v) => `%${Math.round(v * 100)}`)}
          {range("Ekrandaki kelime", st.chunk, 1, 6, 1, "chunk", (v) => String(v))}
          {range("Kontur", st.stroke, 0, 3, 0.1, "stroke", (v) => v.toFixed(1))}
          {range("Senkron", st.sync, -0.6, 0.6, 0.02, "sync", (v) => `${v > 0 ? "+" : ""}${v.toFixed(2)} sn`)}

          <div className="grid grid-cols-2 gap-3">
            <label className="block text-sm">Yazı rengi
              <input type="color" value={st.color} onChange={(e) => setStyle({ color: e.target.value.toUpperCase() }, "cap-color")} className="mt-1 block h-10 w-full cursor-pointer rounded-xl border border-line bg-raised p-1" />
            </label>
            <label className="block text-sm">Aktif kelime
              <input type="color" value={st.active} onChange={(e) => setStyle({ active: e.target.value.toUpperCase() }, "cap-active")} className="mt-1 block h-10 w-full cursor-pointer rounded-xl border border-line bg-raised p-1" />
            </label>
          </div>
          <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={st.upper} onChange={(e) => setStyle({ upper: e.target.checked }, "cap-upper")} className="size-4 accent-[var(--ink)]" />Büyük harf</label>
          <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={st.mask} onChange={(e) => setStyle({ mask: e.target.checked }, "cap-mask")} className="size-4 accent-[var(--ink)]" />Küfürleri yıldızla</label>
        </div>
      )}
    </section>
  );
}
