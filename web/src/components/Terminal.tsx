import { useEffect, useLayoutEffect, useRef, useState } from "react";
import type { LogLine } from "../lib/useJob";

const KEY = "kliparya.terminal";
const COLOR: Record<LogLine["level"], string> = {
  info: "#d8dacf", step: "#f4f5ee", cmd: "#8d9382", ok: "#a6e34f", warn: "#e8b04a", err: "#ff7b72",
};
const hhmmss = (t: number) => new Date(t * 1000).toLocaleTimeString("tr-TR", { hour12: false });

/** Docked terminal: what the job is doing right now (steps, every command it runs, results). Always dark. */
export function Terminal({ logs, running, jobId }: { logs: LogLine[]; running: boolean; jobId: number }) {
  const [open, setOpen] = useState(() => { try { return localStorage.getItem(KEY) !== "closed"; } catch { return true; } });
  const [follow, setFollow] = useState(true);
  const [copied, setCopied] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  const toggle = () => setOpen((o) => { try { localStorage.setItem(KEY, o ? "closed" : "open"); } catch { /* private mode */ } return !o; });

  useLayoutEffect(() => {
    const el = box.current;
    if (open && follow && el) el.scrollTop = el.scrollHeight;
  }, [logs.length, open, follow]);
  useEffect(() => { if (!copied) return; const t = setTimeout(() => setCopied(false), 1400); return () => clearTimeout(t); }, [copied]);

  const onScroll = () => {
    const el = box.current;
    if (el) setFollow(el.scrollHeight - el.scrollTop - el.clientHeight < 28);       // scrolled up = stop following
  };
  const last = logs[logs.length - 1];
  const H = 300;

  return (
    <>
      <div aria-hidden style={{ height: open ? H + 24 : 68 }} />
      <section aria-label="Terminal" className="fixed inset-x-0 bottom-0 z-30 px-3 sm:px-6">
        <div className="mx-auto max-w-6xl overflow-hidden rounded-t-2xl border border-b-0 border-white/10 bg-[#0b0c0a] text-[#d8dacf] shadow-[0_-12px_40px_-12px_rgba(0,0,0,0.55)]">
          <div className="flex h-11 items-center gap-3 px-4">
            <span aria-hidden className="flex gap-1.5"><i className="size-2.5 rounded-full bg-[#ff5f57]" /><i className="size-2.5 rounded-full bg-[#febc2e]" /><i className="size-2.5 rounded-full bg-[#28c840]" /></span>
            <button onClick={toggle} aria-expanded={open} aria-controls="terminal-body" className="flex min-w-0 flex-1 items-center gap-2 text-left font-mono text-[12.5px]">
              <span className="shrink-0 text-[#8d9382]">terminal · iş #{jobId}</span>
              {running && <i aria-label="çalışıyor" className="size-2 shrink-0 animate-pulse rounded-full bg-[#bff453]" />}
              {!open && last && <span className="truncate" style={{ color: COLOR[last.level] }}>{last.text}</span>}
            </button>
            {open && !follow && (
              <button onClick={() => { setFollow(true); }} className="rounded-md border border-white/15 px-2 py-0.5 font-mono text-[11px] text-[#bff453] hover:bg-white/5">sona git ↓</button>
            )}
            <button
              onClick={() => { void navigator.clipboard.writeText(logs.map((l) => `${hhmmss(l.t)} ${l.text}`).join("\n")).then(() => setCopied(true)); }}
              className="rounded-md border border-white/15 px-2 py-0.5 font-mono text-[11px] text-[#d8dacf] hover:bg-white/5">{copied ? "kopyalandı" : "kopyala"}</button>
            <button onClick={toggle} aria-label={open ? "Terminali küçült" : "Terminali aç"} className="grid size-7 place-items-center rounded-md text-[#8d9382] hover:bg-white/5">
              <svg viewBox="0 0 16 16" className={`size-3.5 transition-transform ${open ? "" : "rotate-180"}`}><path d="M3 6l5 5 5-5" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" /></svg>
            </button>
          </div>
          {open && (
            <div id="terminal-body" ref={box} onScroll={onScroll} role="log" aria-label="İşlem günlüğü" tabIndex={0}
              className="overflow-y-auto border-t border-white/10 px-4 py-3 font-mono text-[12.5px] leading-[1.65]" style={{ height: H }}>
              {logs.length === 0 && <p className="m-0 text-[#6f7268]">Bekleniyor…</p>}
              {logs.map((l, i) => (
                <div key={i} className="flex gap-3">
                  <span className="shrink-0 select-none text-[#5f625a] tnum">{hhmmss(l.t)}</span>
                  <span className="min-w-0 break-words" style={{ color: COLOR[l.level], fontWeight: l.level === "step" ? 600 : 400 }}>{l.text}</span>
                </div>
              ))}
              {running && <div className="mt-1 flex gap-3"><span className="w-[4.2rem] shrink-0" /><span aria-hidden className="inline-block h-4 w-2 animate-pulse bg-[#bff453]" /></div>}
            </div>
          )}
        </div>
      </section>
    </>
  );
}
