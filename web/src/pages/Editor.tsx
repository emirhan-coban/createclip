import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, dur, friendlyError, type Clip } from "../lib/api";
import { useJobPoll } from "../lib/useJobPoll";
import { useJob } from "../lib/useJob";
import { Terminal } from "../components/Terminal";
import { OW, OH, type Mode, type Project } from "../lib/layout";
import { useProject } from "../lib/useProject";
import { Stage } from "../components/editor/Stage";
import { EditTimeline } from "../components/editor/EditTimeline";
import { TextLayer } from "../components/editor/TextLayer";
import { TextPanel } from "../components/editor/TextPanel";

type Source = { width: number; height: number; duration: number; audio: boolean; start: number; end: number };
type EditorState = { clip: Clip; source: Source | null; project: Project | null };
type Ready = { clip: Clip; source: Source; project: Project };
type Assets = { strip: { n: number; step: number; thumb_h: number }; wave: number[] };
const clamp = (v: number, a: number, b: number) => Math.min(b, Math.max(a, v));

export default function Editor() {
  const id = Number(useParams().id);
  const [data, setData] = useState<EditorState | null>(null);
  const [error, setError] = useState("");
  const load = useCallback(() => api<EditorState>(`/api/clips/${id}/editor`).then(setData).catch((e) => setError((e as Error).message)), [id]);
  useEffect(() => { void load(); }, [load]);

  if (error) return <Centered title="Klip bulunamadı" hint={error} />;
  if (!data) return <Centered title="Yükleniyor…" />;
  if (!data.source || !data.project) return <GetSource clip={data.clip} onReady={load} />;
  return <Workspace key={data.clip.id} data={data as Ready} reload={load} />;
}

function Centered({ title, hint, children }: { title: string; hint?: string; children?: React.ReactNode }) {
  return (
    <div className="grid min-h-dvh place-items-center px-6 text-center">
      <div className="max-w-md">
        <h1 className="title text-2xl">{title}</h1>
        {hint && <p className="mt-2 text-ink-2">{hint}</p>}
        <div className="mt-5 flex justify-center gap-2">{children}</div>
        <Link to="/panel/klipler" className="mt-6 inline-block text-sm text-ink-2 underline underline-offset-2">Kliplere dön</Link>
      </div>
    </div>
  );
}

/* ---------------------------------------------------------------- clips made before the editor have no source footage */
function GetSource({ clip, onReady }: { clip: Clip; onReady: () => void }) {
  const [jobId, setJobId] = useState<number | null>(null);
  const [err, setErr] = useState("");
  const job = useJobPoll(jobId);
  useEffect(() => { if (job?.status === "done") onReady(); }, [job?.status, onReady]);
  const start = async () => {
    setErr("");
    try { setJobId((await api<{ id: number }>(`/api/clips/${clip.id}/source`, {})).id); } catch (e) { setErr((e as Error).message); }
  };
  const running = job && (job.status === "running" || job.status === "queued");
  const failed = job && ["failed", "blocked", "cancelled"].includes(job.status);
  const f = failed ? friendlyError(job!.status, job!.error) : null;
  return (
    <Centered title="Düzenlemek için kaynak görüntü gerekiyor"
      hint={running ? job!.msg || "Sırada…" : "Klibin çevresindeki yaklaşık 1 dakikalık görüntü yayından indirilecek."}>
      {running ? (
        <div className="w-64"><div className="h-1.5 overflow-hidden rounded-full bg-paper-2"><div className="h-full rounded-full bg-lime transition-all" style={{ width: `${Math.round((job!.frac ?? 0) * 100)}%` }} /></div></div>
      ) : (
        <button onClick={start} className="rounded-full bg-lime px-6 py-3 font-semibold text-lime-ink active:scale-95">Kaynağı indir</button>
      )}
      {(f || err) && <p role="alert" className="mt-4 basis-full text-sm text-danger">{f ? `${f.title}. ${f.hint}` : err}</p>}
    </Centered>
  );
}

/* ---------------------------------------------------------------- the editor */
function Workspace({ data, reload }: { data: Ready; reload: () => void }) {
  const { clip, source } = data;
  // older projects lack some blocks (layout split, text layers; captions were removed): fill in what is missing
  const initial = useMemo(() => ({ ...data.project, layout: { ...data.project.layout, split: data.project.layout.split ?? 0.5 }, texts: data.project.texts ?? [] }), [data.project]);
  const { project, edit, undo, redo, canUndo, canRedo, saving } = useProject(clip.id, initial);
  const [assets, setAssets] = useState<Assets | null>(null);
  const [master, setMaster] = useState<HTMLVideoElement | null>(null);
  const onMaster = useCallback((v: HTMLVideoElement | null) => setMaster(v), []);
  const [time, setTime] = useState(data.project.trim.in);
  const [playing, setPlaying] = useState(false);
  const [exportId, setExportId] = useState<number | null>(null);
  const [termId, setTermId] = useState<number | null>(null);          // job shown in the terminal (export or camera search)
  const term = useJob(termId);
  const [exportErr, setExportErr] = useState("");
  const [videoErr, setVideoErr] = useState(false);
  const [selText, setSelText] = useState<string | null>(null);
  const job = useJobPoll(exportId);
  const trimRef = useRef(data.project.trim);
  if (project) trimRef.current = project.trim;

  useEffect(() => { api<Assets>(`/api/clips/${clip.id}/assets`).then(setAssets).catch(() => {}); }, [clip.id]);
  useEffect(() => {
    if (!master) return;
    const bad = () => setVideoErr(true);
    master.addEventListener("error", bad);
    return () => master.removeEventListener("error", bad);
  }, [master]);

  // player: loop inside the trim, report the time
  const timeRef = useRef(data.project.trim.in);
  timeRef.current = time;
  useEffect(() => {
    if (!master) return;
    master.currentTime = timeRef.current;               // a new master (layout change) continues where the old one was
    let raf = 0;
    const tick = () => {
      const t = master.currentTime, { in: a, out: b } = trimRef.current;
      if (!master.paused && t >= b) { master.pause(); master.currentTime = a; setTime(a); }
      else setTime(t);
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    const on = () => setPlaying(!master.paused);
    master.addEventListener("play", on); master.addEventListener("pause", on);
    return () => { cancelAnimationFrame(raf); master.removeEventListener("play", on); master.removeEventListener("pause", on); };
  }, [master]);

  useEffect(() => { if (master && project) master.volume = clamp(project.audio.volume, 0, 1); }, [master, project?.audio.volume]); // eslint-disable-line react-hooks/exhaustive-deps

  const seek = useCallback((t: number) => { if (master) { master.currentTime = clamp(t, 0, source.duration); setTime(master.currentTime); } }, [master, source.duration]);
  const toggle = useCallback(() => {
    if (!master) return;
    if (master.paused) {
      const { in: a, out: b } = trimRef.current;
      if (master.currentTime < a || master.currentTime >= b - 0.05) master.currentTime = a;
      void master.play().catch(() => {});
    } else master.pause();
  }, [master]);
  const setTrim = useCallback((which: "in" | "out", t: number) => {
    edit((p) => { p.trim[which] = clamp(t, 0, source.duration); return p; }, `trim-${which}`);
    if (master && which === "in" && master.paused) { master.currentTime = t; setTime(t); }
  }, [edit, master, source.duration]);

  useEffect(() => {
    const k = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement;
      if (el.closest("input, textarea, select, [role=slider]")) return;
      if (e.key === " " && el.closest("button, a")) return;          // a keyboard-focused button keeps its own Space
      const meta = e.metaKey || e.ctrlKey;
      if (meta && e.key.toLowerCase() === "z") { e.preventDefault(); if (e.shiftKey) redo(); else undo(); return; }
      if (e.key === " ") { e.preventDefault(); toggle(); }
      else if (e.key === "ArrowLeft") { e.preventDefault(); seek(time - (e.shiftKey ? 1 : 0.1)); }
      else if (e.key === "ArrowRight") { e.preventDefault(); seek(time + (e.shiftKey ? 1 : 0.1)); }
      else if (e.key.toLowerCase() === "i") setTrim("in", Math.min(time, trimRef.current.out - 1));
      else if (e.key.toLowerCase() === "o") setTrim("out", Math.max(time, trimRef.current.in + 1));
      else if (e.key === "Home") seek(trimRef.current.in);
      else if (e.key === "End") seek(trimRef.current.out);
    };
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, [seek, toggle, setTrim, time, undo, redo]);

  const pan = useCallback((cell: number, dcx: number, dcy: number) => {
    edit((p) => { const c = p.layout.cells[cell]; c.cx = clamp(c.cx + dcx, 0, 1); c.cy = clamp(c.cy + dcy, 0, 1); return p; }, `pan-${cell}`);
  }, [edit]);

  const startExport = async () => {
    setExportErr("");
    try { const id = (await api<{ id: number }>(`/api/clips/${clip.id}/export`, project)).id; setExportId(id); setTermId(id); } catch (e) { setExportErr((e as Error).message); }
  };
  useEffect(() => { if (job?.status === "done") reload(); }, [job?.status]); // eslint-disable-line react-hooks/exhaustive-deps
  if (!project) return null;

  const len = project.trim.out - project.trim.in;
  const busy = job && (job.status === "running" || job.status === "queued");
  return (
    <div className="flex min-h-dvh flex-col lg:h-dvh" onMouseUp={(e) => (e.target as HTMLElement).closest("button")?.blur()}>
      <header className="flex h-14 shrink-0 items-center gap-3 border-b border-line px-4">
        <Link to="/panel/klipler" className="rounded-full border border-line px-3 py-1.5 text-sm hover:border-ink">← Klipler</Link>
        <p className="min-w-0 flex-1 truncate font-semibold">{clip.title || "Klip"}</p>
        <span className="hidden text-sm text-ink-2 sm:block" role="status">{saving === "saving" ? "Kaydediliyor…" : saving === "error" ? "Kaydedilemedi" : "Kaydedildi"}</span>
        <button onClick={undo} disabled={!canUndo} aria-label="Geri al" title="Geri al (⌘Z)" className="grid size-9 place-items-center rounded-full border border-line disabled:opacity-35">↶</button>
        <button onClick={redo} disabled={!canRedo} aria-label="Yinele" title="Yinele (⇧⌘Z)" className="grid size-9 place-items-center rounded-full border border-line disabled:opacity-35">↷</button>
        <button onClick={startExport} disabled={!!busy} className="rounded-full bg-lime px-5 py-2 text-sm font-semibold text-lime-ink active:scale-95 disabled:opacity-60">Dışa aktar</button>
      </header>

      <div className="grid min-h-0 flex-1 lg:grid-cols-[1fr_21rem]">
        <section className="flex min-h-0 flex-col">
          <div className="relative h-[58vh] min-h-0 flex-1 bg-paper-2 p-4 lg:h-auto">
            <div className="h-full w-full" role="group" aria-label="Önizleme">
              <Stage project={project} src={`/media/source/${clip.id}.mp4`} W={source.width} H={source.height} onMaster={onMaster} onPan={pan}>
                {(scale: number) => (
                  <>
                    <TextLayer layers={project.texts} time={time - project.trim.in} selected={selText} scale={scale} onSelect={setSelText}
                      onMove={(id, x, y) => edit((p) => { const l = p.texts.find((t) => t.id === id); if (l) { l.x = x; l.y = y; } return p; }, `text-move-${id}`)} />
                  </>
                )}
              </Stage>
            </div>
            {videoErr && (
              <p role="alert" className="absolute inset-x-6 top-6 rounded-xl border border-line bg-raised p-3 text-sm text-danger">
                Kaynak video oynatılamadı. Dosya silinmiş olabilir; kliplere dönüp tekrar aç, gerekirse kaynak yeniden indirilir.
              </p>
            )}
          </div>
          <div className="flex items-center gap-3 border-t border-line px-4 py-2.5">
            <button onClick={toggle} aria-label={playing ? "Duraklat" : "Oynat"} className="grid size-10 place-items-center rounded-full bg-ink text-paper active:scale-95">
              {playing ? <svg viewBox="0 0 16 16" className="size-4"><path d="M4 3h3v10H4zM9 3h3v10H9z" fill="currentColor" /></svg> : <svg viewBox="0 0 16 16" className="size-4"><path d="M4 2.5v11l9-5.5z" fill="currentColor" /></svg>}
            </button>
            <span className="tnum text-sm">{dur(Math.max(0, time - project.trim.in))} <span className="text-mute">/ {dur(len)}</span></span>
            <span className="flex-1" />
            <button onClick={() => setTrim("in", Math.min(time, project.trim.out - 1))} className="rounded-full border border-line px-3 py-1.5 text-sm hover:border-ink" title="Başlangıcı buraya al (I)">Başlangıç</button>
            <button onClick={() => setTrim("out", Math.max(time, project.trim.in + 1))} className="rounded-full border border-line px-3 py-1.5 text-sm hover:border-ink" title="Bitişi buraya al (O)">Bitiş</button>
          </div>
          <div className="border-t border-line px-4 pb-3 pt-2">
            <EditTimeline duration={source.duration} offset={source.start} trim={project.trim} time={time}
              strip={assets?.strip ?? null} stripUrl={`/media/strip/${clip.id}.jpg`} wave={assets?.wave ?? null} onSeek={seek} onTrim={setTrim}
              bars={project.texts.map((l) => ({ id: l.id, start: project.trim.in + l.start, end: project.trim.in + Math.min(l.end, len), label: l.text || "metin" }))}
              selectedBar={selText} onBarSelect={setSelText}
              onBarMove={(id, ns) => edit((p) => {
                const l = p.texts.find((t) => t.id === id);
                if (l) { const d = l.end - l.start, s = clamp(ns - p.trim.in, 0, Math.max(0, len - d)); l.start = +s.toFixed(2); l.end = +(s + d).toFixed(2); }
                return p;
              }, `text-bar-${id}`)} />
          </div>
        </section>

        <aside className="overflow-y-auto border-t border-line p-5 lg:border-l lg:border-t-0" aria-label="Düzenleme ayarları">
          <Inspector project={project} edit={edit} hasAudio={source.audio} clipId={clip.id} now={time - project.trim.in} selText={selText} onSelText={setSelText} onJob={setTermId} />
          <p className="mt-6 text-xs leading-relaxed text-mute">
            Boşluk: oynat/duraklat · ← → : 0,1 sn (⇧ ile 1 sn) · I / O: başlangıç / bitiş · ⌘Z: geri al
          </p>
        </aside>
      </div>

      {termId != null && <Terminal logs={term.logs} running={term.status === "running" || term.status === "waiting"} jobId={termId} />}

      {(job || exportErr) && (
        <div role="status" className="fixed inset-x-0 bottom-16 z-40 mx-auto w-[min(26rem,92vw)] rounded-2xl border border-line bg-raised p-4 shadow-lift">
          {exportErr ? <p className="text-sm text-danger">{exportErr}</p> : busy ? (
            <>
              <p className="text-sm font-semibold">Dışa aktarılıyor… <span className="tnum font-normal text-ink-2">%{Math.round((job!.frac ?? 0) * 100)}</span></p>
              <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-paper-2"><div className="h-full rounded-full bg-lime transition-all" style={{ width: `${Math.round((job!.frac ?? 0) * 100)}%` }} /></div>
            </>
          ) : job!.status === "done" ? (
            <div className="flex items-center justify-between gap-3">
              <p className="text-sm font-semibold">Hazır, klip güncellendi.</p>
              <span className="flex gap-2">
                <Link to="/panel/klipler" className="rounded-full bg-lime px-4 py-1.5 text-sm font-semibold text-lime-ink">Kliplere git</Link>
                <button onClick={() => setExportId(null)} className="rounded-full border border-line px-3 py-1.5 text-sm">Tamam</button>
              </span>
            </div>
          ) : (
            <div className="flex items-center justify-between gap-3">
              <p className="text-sm text-danger">{job!.error || friendlyError(job!.status).title}</p>
              <button onClick={() => setExportId(null)} className="rounded-full border border-line px-3 py-1.5 text-sm">Kapat</button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

/* ---------------------------------------------------------------- camera search */
function FacePanel({ clipId, split, edit, onJob }: { clipId: number; split: number; edit: (fn: (p: Project) => Project, key?: string) => void; onJob: (id: number) => void }) {
  const [available, setAvailable] = useState<boolean | null>(null);
  const [jobId, setJobId] = useState<number | null>(null);
  const [msg, setMsg] = useState("");
  const job = useJobPoll(jobId);
  useEffect(() => { api<{ available: boolean }>("/api/faces/status").then((r) => setAvailable(r.available)).catch(() => setAvailable(false)); }, []);
  const apply = useCallback(async () => {
    try {
      const r = await api<{ layout: Project["layout"] }>(`/api/clips/${clipId}/face-layout?split=${split}`);
      edit((p) => { p.layout = r.layout; return p; });
      setMsg("Kamera bulundu, üst pencereye yerleştirildi. İstersen kaydırıp yakınlaştır.");
    } catch { setMsg("Bu klipte sabit bir kamera yüzü bulunamadı. Pencereyi elle ayarlayabilirsin."); }
  }, [clipId, split, edit]);
  useEffect(() => { if (job?.status === "done") void apply(); else if (job && ["failed", "cancelled", "blocked"].includes(job.status)) setMsg(job.error || "Kamera aranamadı."); }, [job?.status]); // eslint-disable-line react-hooks/exhaustive-deps
  const busy = !!job && (job.status === "running" || job.status === "queued");
  const start = async () => {
    setMsg("");
    try { const id = (await api<{ id: number }>(`/api/clips/${clipId}/faces`, {})).id; setJobId(id); onJob(id); } catch (e) { setMsg((e as Error).message); }
  };
  if (available === false) return <p className="mt-3 text-xs text-mute">Kamerayı otomatik bulmak için OpenCV gerekli: <code>pip install -e ".[faces]"</code></p>;
  return (
    <div className="mt-3">
      <button onClick={start} disabled={busy || available === null} className="rounded-full bg-lime px-4 py-2 text-sm font-semibold text-lime-ink active:scale-95 disabled:opacity-60">
        {busy ? `Kamera aranıyor… %${Math.round((job?.frac ?? 0) * 100)}` : "Kamerayı bul, üste koy"}
      </button>
      {msg && <p role="status" className="mt-2 text-sm text-ink-2">{msg}</p>}
    </div>
  );
}

/* ---------------------------------------------------------------- inspector */
function Inspector({ project, edit, hasAudio, clipId, now, selText, onSelText, onJob }: { project: Project; edit: (fn: (p: Project) => Project, key?: string) => void; hasAudio: boolean; clipId: number; now: number; selText: string | null; onSelText: (id: string | null) => void; onJob: (id: number) => void }) {
  const { mode, cells } = project.layout;
  const setMode = (m: Mode) => edit((p) => { p.layout.mode = m; return p; });
  const seg = "flex-1 rounded-full px-3 py-2 text-sm transition";
  const names: Record<Mode, string> = { blur: "Siyah arka plan", crop: "Tek pencere", stack: "İki pencere" };
  const cellsShown = mode === "crop" ? [0] : mode === "stack" ? [0, 1] : [];
  const label = (i: number) => (mode === "crop" ? "Pencere" : i === 0 ? "Üst pencere" : "Alt pencere");
  const split = project.layout.split ?? 0.5;
  return (
    <div className="flex flex-col gap-7">
      <section>
        <h2 className="title mb-3 text-lg">Yerleşim</h2>
        <div role="radiogroup" aria-label="Yerleşim" className="flex gap-1 rounded-full bg-paper-2 p-1">
          {(Object.keys(names) as Mode[]).map((m) => (
            <button key={m} role="radio" aria-checked={mode === m} onClick={() => setMode(m)}
              className={`${seg} ${mode === m ? "bg-ink font-semibold text-paper" : "text-ink-2 hover:text-ink"}`}>{names[m]}</button>
          ))}
        </div>
        {mode === "blur" && <p className="mt-3 text-sm text-ink-2">Görüntü ortada, alt ve üstü siyah kalır.</p>}
        {mode === "stack" && (
          <div className="mt-4">
            <p className="text-sm font-medium">Üst / alt oranı</p>
            <div role="radiogroup" aria-label="Üst ve alt pencere oranı" className="mt-2 grid grid-cols-5 gap-1">
              {[0.3, 0.35, 0.4, 0.5, 0.6].map((v) => (
                <button key={v} role="radio" aria-checked={Math.abs(split - v) < 0.005} onClick={() => edit((p) => { p.layout.split = v; return p; })}
                  className={`rounded-xl border px-1 py-2 text-xs tnum transition ${Math.abs(split - v) < 0.005 ? "border-ink bg-ink font-semibold text-paper" : "border-line text-ink-2 hover:border-ink"}`}>
                  %{Math.round(v * 100)}<br />%{Math.round((1 - v) * 100)}
                </button>
              ))}
            </div>
            <div className="mt-3 flex flex-wrap gap-2">
              <button onClick={() => edit((p) => { p.layout.cells = [p.layout.cells[1], p.layout.cells[0]]; return p; })}
                className="rounded-full border border-line px-3 py-1.5 text-sm hover:border-ink">⇅ Pencereleri değiştir</button>
            </div>
            <FacePanel clipId={clipId} split={split} edit={edit} onJob={onJob} />
          </div>
        )}
        {cellsShown.map((i) => (
          <div key={i} className="mt-4">
            <div className="flex items-center justify-between">
              <label htmlFor={`z${i}`} className="text-sm font-medium">{label(i)} · yakınlık</label>
              <button onClick={() => edit((p) => { p.layout.cells[i] = { ...p.layout.cells[i], cx: 0.5, cy: 0.5, zoom: 1 }; return p; })}
                className="text-xs text-ink-2 underline underline-offset-2">Sıfırla</button>
            </div>
            <div className="mt-1 flex items-center gap-3">
              <input id={`z${i}`} type="range" min={1} max={6} step={0.05} value={cells[i].zoom} className="flex-1 accent-[var(--ink)]"
                onChange={(e) => edit((p) => { p.layout.cells[i].zoom = Number(e.target.value); return p; }, `zoom-${i}`)} />
              <span className="tnum w-10 text-right text-sm text-ink-2">{cells[i].zoom.toFixed(1)}×</span>
            </div>
            <div className="mt-2 grid grid-cols-2 gap-3">
              {(["cx", "cy"] as const).map((k) => (
                <label key={k} className="block text-xs text-ink-2">
                  {k === "cx" ? "Yatay konum" : "Dikey konum"}
                  <input type="range" min={0} max={1} step={0.005} value={cells[i][k]} className="mt-1 w-full accent-[var(--ink)]"
                    onChange={(e) => edit((p) => { p.layout.cells[i][k] = Number(e.target.value); return p; }, `${k}-${i}`)} />
                </label>
              ))}
            </div>
          </div>
        ))}
        {cellsShown.length > 0 && <p className="mt-3 text-sm text-ink-2">Önizlemede sürükleyerek kaydır.</p>}
      </section>

      <TextPanel project={project} edit={edit} now={now} selected={selText} onSelect={onSelText} />

      <section>
        <h2 className="title mb-3 text-lg">Ses</h2>
        {!hasAudio ? <p className="text-sm text-ink-2">Bu kaynakta ses yok.</p> : (
          <>
            <label htmlFor="vol" className="flex justify-between text-sm font-medium">Ses seviyesi <span className="tnum font-normal text-ink-2">%{Math.round(project.audio.volume * 100)}</span></label>
            <input id="vol" type="range" min={0} max={2} step={0.05} value={project.audio.volume} className="mt-1 w-full accent-[var(--ink)]"
              onChange={(e) => edit((p) => { p.audio.volume = Number(e.target.value); return p; }, "volume")} />
            {project.audio.volume > 1 && <p className="mt-1 text-xs text-mute">Önizleme en çok %100 çalar; dışa aktarılan videoda %{Math.round(project.audio.volume * 100)} olur.</p>}
            <label className="mt-3 flex items-start gap-2 text-sm">
              <input type="checkbox" checked={project.audio.normalize} onChange={(e) => edit((p) => { p.audio.normalize = e.target.checked; return p; })} className="mt-0.5 size-4 accent-[var(--ink)]" />
              <span>Ses seviyesini dengele <span className="block text-xs text-mute">Klipler arası ses farkını azaltır (−16 LUFS). Önizlemede duyulmaz.</span></span>
            </label>
          </>
        )}
      </section>

      <section>
        <h2 className="title mb-2 text-lg">Kırpma</h2>
        <p className="text-sm text-ink-2">Zaman çizelgesinde yeşil tutamaçları sürükle. Başlangıç ve bitiş arası <span className="tnum font-medium text-ink">{dur(project.trim.out - project.trim.in)}</span>.</p>
      </section>
      <p className="hidden" aria-hidden>{OW}×{OH}</p>
    </div>
  );
}
