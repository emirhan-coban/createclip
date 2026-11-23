import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, dur, friendlyError, normalizeUrl } from "../lib/api";
import { useJob } from "../lib/useJob";
import { Poster } from "../components/Poster";
import { Terminal } from "../components/Terminal";
import { parseTime } from "../lib/time";

const URL_RE = /^https?:\/\/\S+$/i;
const KEY = "kliparya.single";

const clock = (t: number) => `${Math.floor(t / 3600)}:${String(Math.floor((t % 3600) / 60)).padStart(2, "0")}:${String(Math.floor(t % 60)).padStart(2, "0")}`;

export default function Single() {
  const [jobId, setJobId] = useState<number | null>(() => {
    const v = Number(localStorage.getItem(KEY));
    return Number.isFinite(v) && v > 0 ? v : null;
  });
  useEffect(() => {          // a job id from before a server restart no longer exists
    if (jobId == null) return;
    api<{ jobs: { id: number; live?: boolean }[] }>("/api/state").then((s) => {
      if (!s.jobs.some((j) => j.id === jobId && j.live)) { localStorage.removeItem(KEY); setJobId(null); }
    }).catch(() => {});
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  const reset = () => { localStorage.removeItem(KEY); setJobId(null); };
  return (
    <main className="mx-auto w-full max-w-3xl px-6 pb-24">
      {jobId == null ? <Form onStart={(id) => { localStorage.setItem(KEY, String(id)); setJobId(id); }} /> : <Result jobId={jobId} onReset={reset} />}
    </main>
  );
}

function Form({ onStart }: { onStart: (id: number) => void }) {
  const [url, setUrl] = useState("");
  const [at, setAt] = useState("");
  const [len, setLen] = useState("45");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    const u = normalizeUrl(url);
    const start = parseTime(at), length = parseTime(len);
    if (!URL_RE.test(u)) return setErr("Bu bir link gibi görünmüyor. Kick ya da YouTube yayın linkini yapıştır.");
    if (start == null) return setErr("Başlangıç zamanını 1:44:50 ya da 44:50 gibi yaz.");
    if (length == null || length < 5 || length > 180) return setErr("Süre 5 ile 180 saniye arasında olmalı (örn. 45).");
    setErr(""); setBusy(true);
    try { onStart((await api<{ id: number }>("/api/run", { url: u, at: [`${clock(start)}-${clock(start + length)}`] })).id); }
    catch (x) { setErr((x as Error).message); setBusy(false); }
  };
  const field = "w-full rounded-xl border border-line bg-raised px-4 py-3 text-[1.02rem] outline-none focus:border-ink";
  return (
    <section className="pt-[clamp(2.5rem,8vh,5rem)]">
      <h1 className="display max-w-[16ch]">Tek bir klip al.</h1>
      <p className="mt-5 max-w-[48ch] text-[1.1rem] leading-relaxed text-ink-2">
        Yayın linkini, klibin başladığı zamanı ve süresini yaz. Sohbet analizi yapılmaz, yalnızca o aralık indirilip dikey klibe çevrilir.
      </p>
      <form onSubmit={submit} className="mt-8 grid gap-5">
        <label className="block">
          <span className="text-sm text-ink-2">Yayın linki</span>
          <input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="Kick ya da YouTube yayın linki" inputMode="url" autoComplete="off" spellCheck={false} className={`${field} mt-1`} />
        </label>
        <div className="grid gap-5 sm:grid-cols-2">
          <label className="block">
            <span className="text-sm text-ink-2">Başlangıç zamanı</span>
            <input value={at} onChange={(e) => setAt(e.target.value)} placeholder="1:44:50" inputMode="numeric" autoComplete="off" className={`${field} tnum mt-1`} />
            <span className="mt-1 block text-xs text-mute">Saat:dakika:saniye (ya da 44:50)</span>
          </label>
          <label className="block">
            <span className="text-sm text-ink-2">Süre (saniye)</span>
            <input value={len} onChange={(e) => setLen(e.target.value)} placeholder="45" inputMode="numeric" autoComplete="off" className={`${field} tnum mt-1`} />
            <span className="mt-1 block text-xs text-mute">5–180 sn</span>
          </label>
        </div>
        <p role="alert" className="min-h-5 text-sm text-danger">{err}</p>
        <div><button disabled={busy} className="rounded-full bg-lime px-7 py-3 font-semibold text-lime-ink transition active:scale-[0.97] disabled:opacity-60">{busy ? "Başlıyor…" : "Klibi al"}</button></div>
      </form>
    </section>
  );
}

function Result({ jobId, onReset }: { jobId: number; onReset: () => void }) {
  const job = useJob(jobId);
  const navigate = useNavigate();
  const clip = Object.values(job.clips)[0];
  const running = job.status === "running" || job.status === "waiting";
  const failed = job.status === "failed" || job.status === "blocked" || job.status === "cancelled";
  const f = failed ? friendlyError(job.status, job.error) : null;
  return (
    <section className="pt-10">
      <div className="flex items-center gap-4">
        <div className="min-w-0 flex-1">
          <p className="truncate text-lg font-semibold">{job.info?.title ?? (running ? "Yayın bulunuyor…" : "Yayın alınamadı")}</p>
          <p className="text-sm text-ink-2">{job.info ? <>{job.info.channel} · <span className="tnum">{dur(job.info.duration)}</span></> : job.status === "waiting" ? "Sırada, önceki iş bitince başlar" : ""}</p>
        </div>
        {running
          ? <button onClick={() => void api(`/api/jobs/${jobId}/cancel`, {})} className="rounded-full border border-line px-4 py-2 text-sm font-medium hover:border-ink">Durdur</button>
          : <button onClick={onReset} className="rounded-full bg-ink px-5 py-2.5 text-sm font-semibold text-paper active:scale-95">Yeni klip</button>}
      </div>

      <div className="mt-10 flex flex-wrap items-end gap-8">
        {clip?.done ? (
          <Poster id={clip.id} title={clip.title} start={clip.start} end={clip.end} onOpen={() => navigate(`/editor/${clip.id}`)} />
        ) : !failed ? (
          <div className="w-full max-w-sm" aria-busy="true">
            <p className="text-sm text-ink-2">{clip?.stage ?? "Hazırlanıyor"}</p>
            <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-paper-2"><div className="h-full rounded-full bg-lime transition-all" style={{ width: `${Math.round((clip?.frac ?? 0.03) * 100)}%` }} /></div>
          </div>
        ) : null}
        {clip?.done && (
          <div className="flex flex-col gap-2">
            <p className="text-sm text-ink-2">Hazır. Düzenlemek için klibe tıkla.</p>
            <Link to="/panel/klipler" className="rounded-full bg-lime px-5 py-2.5 text-center text-sm font-semibold text-lime-ink">Panelde aç</Link>
          </div>
        )}
      </div>

      {f && (
        <div role="alert" className="mt-8 rounded-2xl border border-line bg-raised p-5">
          <p className="font-semibold">{f.title}</p>
          <p className="mt-1 text-sm text-ink-2">{f.hint}</p>
          {job.error && job.status === "failed" && <p className="mt-3 break-words rounded-lg bg-paper-2 p-3 font-mono text-xs">{job.error}</p>}
          <button onClick={onReset} className="mt-4 rounded-full bg-lime px-5 py-2.5 text-sm font-semibold text-lime-ink active:scale-95">Tekrar dene</button>
        </div>
      )}
      <Terminal logs={job.logs} running={running} jobId={jobId} />
    </section>
  );
}
