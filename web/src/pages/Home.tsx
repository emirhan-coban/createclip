import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { AnimatePresence, motion } from "motion/react";
import { api, dur, friendlyError, hms, normalizeUrl, type State } from "../lib/api";
import { useJob } from "../lib/useJob";
import { Timeline } from "../components/Timeline";
import { Steps } from "../components/Steps";
import { Poster } from "../components/Poster";
import { Burst } from "../components/Burst";

const URL_RE = /^https?:\/\/\S+$/i;
const KEY = "kliparya.job";
const LAST = "kliparya.last";

export default function Home() {
  const [jobId, setJobId] = useState<number | null>(() => {
    const v = Number(localStorage.getItem(KEY));
    return Number.isFinite(v) && v > 0 ? v : null;
  });
  const job = useJob(jobId);
  // a job id from before a server restart no longer exists: start fresh instead of waiting on nothing
  useEffect(() => {
    if (jobId == null) return;
    api<{ jobs: { id: number; live?: boolean }[] }>("/api/state").then((s) => {
      if (!s.jobs.some((j) => j.id === jobId && j.live)) { localStorage.removeItem(KEY); setJobId(null); }
    }).catch(() => {});
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const start = async (url: string, n: number, skip: number) => {
    const { id } = await api<{ id: number }>("/api/run", { url, n, start_min: skip });
    localStorage.setItem(KEY, String(id));
    localStorage.setItem(LAST, JSON.stringify({ url, n, skip }));
    setJobId(id);
  };
  const reset = () => { localStorage.removeItem(KEY); setJobId(null); };
  const retry = async () => {
    try {
      const last = JSON.parse(localStorage.getItem(LAST) ?? "null") as { url: string; n: number; skip: number } | null;
      if (last) await start(last.url, last.n, last.skip); else reset();
    } catch { reset(); }
  };

  return (
    <main className="mx-auto w-full max-w-6xl px-6 pb-24">
      <AnimatePresence mode="wait">
        {jobId == null ? (
          <motion.div key="idle" exit={{ opacity: 0, y: -16 }} transition={{ duration: 0.25 }}>
            <Idle onStart={start} />
          </motion.div>
        ) : (
          <motion.div key="run" initial={{ opacity: 0, y: 24 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.5, ease: [0.2, 0.7, 0.1, 1] }}>
            <Run jobId={jobId} job={job} onReset={reset} onRetry={retry} />
          </motion.div>
        )}
      </AnimatePresence>
    </main>
  );
}

/* ------------------------------------------------------------------ before a link */
function Idle({ onStart }: { onStart: (url: string, n: number, skip: number) => Promise<void> }) {
  const [url, setUrl] = useState("");
  const [n, setN] = useState(5);
  const [skip, setSkip] = useState(0);
  useEffect(() => {       // start from the defaults saved in Settings
    api<State>("/api/state").then((s) => { setN(s.config.clips_per_video); setSkip(s.config.skip_start_min); }).catch(() => {});
  }, []);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  useEffect(() => input.current?.focus({ preventScroll: true }), []);

  const go = async (u: string) => {
    u = normalizeUrl(u);
    if (!URL_RE.test(u)) { setErr("Bu bir link gibi görünmüyor. Kick ya da YouTube yayın linkini yapıştır."); return; }
    setErr(""); setBusy(true);
    try { await onStart(u, n, skip); } catch (e) { setErr((e as Error).message); setBusy(false); }
  };

  return (
    <section className="pt-[clamp(3rem,10vh,7rem)] text-center">
      <h1 className="display mx-auto max-w-[14ch]">Uzun yayından kısa klipler.</h1>
      <p className="mx-auto mt-6 max-w-[46ch] text-[1.15rem] leading-relaxed text-ink-2">
        Yayın linkini yapıştır. Sohbetin yükseldiği anları bulur, dikey klibe çevirir.
      </p>

      <form className="mx-auto mt-10 flex max-w-2xl items-center gap-2 rounded-full border border-line bg-raised p-2 pl-6 shadow-lift focus-within:border-ink"
        onSubmit={(e) => { e.preventDefault(); void go(url); }}>
        <label htmlFor="link" className="sr-only">Yayın linki</label>
        <input id="link" ref={input} value={url} onChange={(e) => setUrl(e.target.value)}
          onPaste={(e) => { const t = normalizeUrl(e.clipboardData.getData("text")); if (URL_RE.test(t)) { e.preventDefault(); setUrl(t); void go(t); } }}
          placeholder="Kick ya da YouTube yayın linki" inputMode="url" autoComplete="off" spellCheck={false}
          className="min-w-0 flex-1 bg-transparent py-3 text-[1.02rem] outline-none placeholder:text-mute" />
        <button disabled={busy} className="rounded-full bg-lime px-6 py-3 text-[0.98rem] font-semibold text-lime-ink transition active:scale-[0.97] disabled:opacity-60">
          {busy ? "Başlıyor…" : "Klipleri bul"}
        </button>
      </form>
      <p role="alert" className="mt-3 min-h-6 text-sm text-danger">{err}</p>

      <div className="mt-2 inline-flex items-center gap-5 text-[0.95rem] text-ink-2">
        <label className="flex items-center gap-2">
          <Stepper value={n} onChange={setN} min={1} max={20} /> klip
        </label>
        <label className="flex items-center gap-2">
          ilk <input type="number" min={0} max={600} value={skip} aria-label="Atlanacak dakika" onChange={(e) => setSkip(Math.max(0, +e.target.value || 0))}
            className="tnum w-14 rounded-lg border border-line bg-raised px-2 py-1 text-center text-ink" /> dakikayı atla
        </label>
      </div>

      <div className="mx-auto mt-16 max-w-4xl">
        <Timeline duration={7200} quiet moments={[]} />
        <p className="mt-3 text-sm text-mute">Yayının zaman çizelgesi burada canlı çizilir.</p>
      </div>
    </section>
  );
}

function Stepper({ value, onChange, min, max }: { value: number; onChange: (n: number) => void; min: number; max: number }) {
  const b = "grid size-8 place-items-center rounded-full border border-line bg-raised text-lg leading-none transition active:scale-90 disabled:opacity-40";
  return (
    <span className="inline-flex items-center gap-2">
      <button type="button" className={b} aria-label="Azalt" disabled={value <= min} onClick={() => onChange(value - 1)}>−</button>
      <span className="tnum w-6 text-center font-semibold text-ink">{value}</span>
      <button type="button" className={b} aria-label="Artır" disabled={value >= max} onClick={() => onChange(value + 1)}>+</button>
    </span>
  );
}

/* ------------------------------------------------------------------ while / after a job */
function Run({ jobId, job, onReset, onRetry }: { jobId: number; job: ReturnType<typeof useJob>; onReset: () => void; onRetry: () => void }) {
  const navigate = useNavigate();
  const info = job.info;
  const duration = job.activity?.duration ?? info?.duration ?? 0;
  const running = job.status === "running" || job.status === "waiting";
  const final = !!job.activity && !job.activity.partial;
  const chatPhase = !!job.chat && !final && running;
  const scan = chatPhase && job.chat?.stage === "örnekleme" ? job.chat.frac : null;
  const [burst, setBurst] = useState(false);
  const was = useRef(job.status);
  useEffect(() => {
    if (was.current !== "done" && job.status === "done") { setBurst(true); const t = setTimeout(() => setBurst(false), 1400); return () => clearTimeout(t); }
    was.current = job.status;
  }, [job.status]);

  const ordered = useMemo(() => [...job.moments].sort((a, b) => a.rank - b.rank), [job.moments]);
  const maxScore = Math.max(1, ...ordered.map((m) => m.score));
  const cancel = () => void api(`/api/jobs/${jobId}/cancel`, {});
  const failed = job.status === "failed" || job.status === "blocked" || job.status === "cancelled";

  return (
    <div className="pt-8">
      <div className="flex items-center gap-4">
        <div className="relative grid h-14 w-24 shrink-0 place-items-center overflow-hidden rounded-xl bg-paper-2 text-xl font-semibold text-mute">
          {info?.thumbnail ? <img src={info.thumbnail} alt="" className="h-full w-full object-cover" /> : (info?.channel?.[0]?.toUpperCase() ?? "")}
        </div>
        <div className="min-w-0 flex-1">
          <p className="truncate text-lg font-semibold leading-tight">{info?.title ?? (failed ? "Yayın alınamadı" : "Yayın bulunuyor…")}</p>
          <p className="text-sm text-ink-2">
            {info ? <>{info.channel} · <span className="tnum">{dur(info.duration)}</span></> : job.status === "waiting" ? "Sırada, önceki iş bitince başlar" : ""}
          </p>
        </div>
        {running ? (
          <button onClick={cancel} className="rounded-full border border-line px-4 py-2 text-sm font-medium transition hover:border-ink">Durdur</button>
        ) : (
          <button onClick={onReset} className="rounded-full bg-ink px-5 py-2.5 text-sm font-semibold text-paper transition active:scale-95">Yeni yayın</button>
        )}
      </div>

      <div className="mt-10 grid gap-10 lg:grid-cols-[17rem_1fr]">
        <Steps job={job} />
        <div className="relative min-w-0">
          {duration > 1 && <Timeline duration={duration} blank={!job.activity} values={job.activity?.values} scan={scan} shimmer={chatPhase && job.chat?.stage !== "örnekleme"}
            moments={ordered} clips={job.clips} />}
          {burst && <Burst />}
        </div>
      </div>

      {failed && (() => {
        const f = friendlyError(job.status, job.error);
        return (
          <div role="alert" className="mt-10 rounded-2xl border border-line bg-raised p-5">
            <p className="font-semibold">{f.title}</p>
            <p className="mt-1 text-sm text-ink-2">{f.hint}</p>
            {job.error && job.status === "failed" && (
              <details className="mt-3 text-sm text-ink-2">
                <summary className="cursor-pointer select-none">Teknik ayrıntı</summary>
                <p className="mt-2 break-words rounded-lg bg-paper-2 p-3 font-mono text-xs">{job.error}</p>
              </details>
            )}
            <div className="mt-4 flex gap-2">
              <button onClick={onRetry} className="rounded-full bg-lime px-5 py-2.5 text-sm font-semibold text-lime-ink transition active:scale-95">Yeniden dene</button>
              <button onClick={onReset} className="rounded-full border border-line px-5 py-2.5 text-sm transition hover:border-ink">Başka link</button>
            </div>
          </div>
        );
      })()}

      {ordered.length > 0 && (
        <section className="mt-12" aria-label="Klipler">
          <div className="mb-5 flex items-end justify-between">
            <h2 className="title text-2xl">{job.status === "done" ? `${ordered.filter((m) => job.clips[m.rank]?.done).length} klip hazır` : "Klipler kesiliyor"}</h2>
            {job.status === "done" && <Link to="/panel/klipler" className="rounded-full bg-lime px-5 py-2.5 text-sm font-semibold text-lime-ink transition active:scale-95">Panelde aç</Link>}
          </div>
          <div className="-mx-6 flex items-end gap-5 overflow-x-auto px-6 pb-6">
            {ordered.map((m, i) => {
              const c = job.clips[m.rank];
              return (
                <motion.div key={m.rank} layout initial={{ opacity: 0, y: 24 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.15 * i, type: "spring", stiffness: 200, damping: 22 }}>
                  {c?.done ? (
                    <motion.div initial={{ rotateY: 90 }} animate={{ rotateY: 0 }} transition={{ duration: 0.5 }}>
                      <Poster id={c.id} title={c.title} start={m.start} end={m.end} score={m.score} scale={0.78 + 0.22 * (m.score / maxScore)} onOpen={() => navigate(`/editor/${c.id}`)} />
                    </motion.div>
                  ) : (
                    <Pending rank={m.rank} start={m.start} end={m.end} stage={!running && !c?.done ? "Hazırlanamadı" : c?.stage} frac={c?.frac ?? 0} scale={0.78 + 0.22 * (m.score / maxScore)} />
                  )}
                </motion.div>
              );
            })}
          </div>
        </section>
      )}
    </div>
  );
}

function Pending({ rank, start, end, stage, frac, scale }: { rank: number; start: number; end: number; stage?: string; frac: number; scale: number }) {
  return (
    <div className="relative flex shrink-0 flex-col justify-between overflow-hidden rounded-[22px] border border-dashed border-ink/40 p-4"
      style={{ aspectRatio: "9 / 16", height: `${Math.round(340 * scale)}px` }} aria-busy="true">
      <span className="tnum text-sm font-semibold">{rank}</span>
      <div>
        <p className="tnum text-xs text-ink-2">{hms(start)}–{hms(end)}</p>
        <p className="mt-1 min-h-9 text-sm leading-snug">{stage ?? "Sırada"}</p>
        <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-paper-2">
          <motion.div className="h-full rounded-full bg-lime" animate={{ width: `${Math.round(frac * 100)}%` }} transition={{ duration: 0.5 }} />
        </div>
      </div>
    </div>
  );
}
