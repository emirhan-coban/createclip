import { useEffect, useRef, useState } from "react";
import { dur } from "../../lib/api";

type Strip = { n: number; step: number; thumb_h: number };
const clamp = (v: number, a: number, b: number) => Math.min(b, Math.max(a, v));
const stamp = (s: number) => {
  s = Math.max(0, Math.floor(s));
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60);
  return `${h ? h + ":" + String(m).padStart(2, "0") : m}:${String(s % 60).padStart(2, "0")}`;
};

/** Filmstrip + waveform with draggable trim handles and a playhead. Times are seconds in the source file. */
export type Bar = { id: string; start: number; end: number; label: string };

export function EditTimeline({ duration, offset, trim, time, strip, stripUrl, wave, onSeek, onTrim, bars = [], selectedBar = null, onBarSelect, onBarMove }: {
  duration: number; offset: number; trim: { in: number; out: number }; time: number;
  strip: Strip | null; stripUrl: string; wave: number[] | null;
  onSeek: (t: number) => void; onTrim: (which: "in" | "out", t: number) => void;
  bars?: Bar[];                       // text layers, in source seconds
  selectedBar?: string | null;
  onBarSelect?: (id: string) => void; onBarMove?: (id: string, newStart: number) => void;
}) {
  const box = useRef<HTMLDivElement>(null);
  const [w, setW] = useState(800);
  useEffect(() => {
    const el = box.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setW(el.clientWidth || 800));
    ro.observe(el);
    setW(el.clientWidth || 800);
    return () => ro.disconnect();
  }, []);
  const x = (t: number) => (t / duration) * w;
  const at = (clientX: number) => {
    const r = box.current!.getBoundingClientRect();
    return clamp(((clientX - r.left) / r.width) * duration, 0, duration);
  };
  const snap = (t: number) => Math.round(t * 20) / 20;
  const mode = useRef<"seek" | "in" | "out" | null>(null);

  const down = (e: React.PointerEvent, m: "seek" | "in" | "out") => {
    e.stopPropagation();
    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
    mode.current = m;
    if (m === "seek") onSeek(at(e.clientX));
  };
  const move = (e: React.PointerEvent) => {
    const m = mode.current;
    if (!m) return;
    const t = at(e.clientX);
    if (m === "seek") onSeek(t);
    else if (m === "in") onTrim("in", snap(Math.min(t, trim.out - 1)));
    else onTrim("out", snap(Math.max(t, trim.in + 1)));
  };
  const up = () => { mode.current = null; };

  // label spacing: the smallest "nice" step that leaves at least 72 px between labels
  const step = [1, 2, 5, 10, 15, 30, 60, 120, 300].find((s) => (s / duration) * w >= 72) ?? 600;
  const ticks = Array.from({ length: Math.floor(duration / step) + 1 }, (_, i) => i * step);
  const tileW = strip ? w / strip.n : 0;
  const H = 64;

  return (
    <div className="select-none">
      <div ref={box} className="relative" style={{ height: 22 + H + 34 + (bars.length ? 20 : 0) }}>
        {/* ruler */}
        <div className="absolute inset-x-0 top-0 h-[22px]">
          {ticks.map((t) => (
            <span key={t} className="tnum absolute top-0 -translate-x-1/2 text-[11px] text-mute" style={{ left: x(t) }}>
              {stamp(offset + t)}
              <i className="mx-auto mt-0.5 block h-1.5 w-px bg-line" />
            </span>
          ))}
        </div>

        {/* track */}
        <div className="absolute inset-x-0 overflow-hidden rounded-xl bg-paper-2" style={{ top: 22, height: H }}
          onPointerDown={(e) => down(e, "seek")} onPointerMove={move} onPointerUp={up} onPointerCancel={up}>
          {strip && Array.from({ length: strip.n }, (_, i) => (
            <div key={i} className="absolute top-0 h-full" style={{
              left: i * tileW, width: tileW + 0.5, backgroundImage: `url(${stripUrl})`, backgroundRepeat: "no-repeat",
              backgroundSize: `${strip.n * (H * 16 / 9)}px ${H}px`, backgroundPosition: `${-i * (H * 16 / 9) - ((H * 16 / 9) - tileW) / 2}px 0`,
            }} />
          ))}
          {wave && (
            <svg className="pointer-events-none absolute inset-x-0 bottom-0" height={H * 0.55} width={w} viewBox={`0 0 ${wave.length} 100`} preserveAspectRatio="none" aria-hidden>
              <path d={`M0 100 ${wave.map((v, i) => `L${i} ${100 - v * 100}`).join(" ")} L${wave.length} 100 Z`} fill="var(--ink)" opacity="0.5" />
            </svg>
          )}
          {/* outside the trim: dimmed */}
          <div className="pointer-events-none absolute inset-y-0 left-0 bg-paper/70" style={{ width: x(trim.in) }} />
          <div className="pointer-events-none absolute inset-y-0 right-0 bg-paper/70" style={{ width: w - x(trim.out) }} />
          <div className="pointer-events-none absolute inset-y-0 rounded-md border-y-[3px] border-lime" style={{ left: x(trim.in), width: x(trim.out) - x(trim.in) }} />
        </div>

        {/* trim handles */}
        {(["in", "out"] as const).map((k) => {
          const t = trim[k];
          return (
            <div key={k} role="slider" tabIndex={0} aria-label={k === "in" ? "Klip başlangıcı" : "Klip bitişi"}
              aria-valuemin={0} aria-valuemax={duration} aria-valuenow={t} aria-valuetext={stamp(offset + t)}
              onPointerDown={(e) => down(e, k)} onPointerMove={move} onPointerUp={up} onPointerCancel={up}
              onKeyDown={(e) => {
                const d = (e.shiftKey ? 1 : 0.1) * (e.key === "ArrowLeft" ? -1 : e.key === "ArrowRight" ? 1 : 0);
                if (d) { e.preventDefault(); onTrim(k, snap(k === "in" ? Math.min(t + d, trim.out - 1) : Math.max(t + d, trim.in + 1))); }
              }}
              className="absolute grid cursor-ew-resize place-items-center rounded-md bg-lime shadow-sm outline-offset-2"
              style={{ top: 22 - 2, height: H + 4, width: 16, left: x(t) - (k === "in" ? 16 : 0), touchAction: "none" }}>
              <i className="h-5 w-0.5 rounded bg-lime-ink/70" />
            </div>
          );
        })}

        {/* playhead */}
        <div className="pointer-events-none absolute z-10" style={{ left: x(time) - 1, top: 18, height: H + 8, width: 2, background: "var(--ink)" }}>
          <i className="absolute -top-1 left-1/2 size-3 -translate-x-1/2 rotate-45 rounded-[3px] bg-ink" />
        </div>

        {/* text layers: one bar each, drag to move in time */}
        {bars.map((b) => (
          <div key={b.id} role="button" tabIndex={0} aria-label={`Metin: ${b.label}`} aria-pressed={b.id === selectedBar}
            onPointerDown={(e) => {
              e.stopPropagation(); (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId); onBarSelect?.(b.id);
              (e.currentTarget as HTMLElement).dataset.x = String(e.clientX);
            }}
            onPointerMove={(e) => {
              const el = e.currentTarget as HTMLElement;
              if (!el.dataset.x) return;
              const dt = ((e.clientX - Number(el.dataset.x)) / w) * duration;
              el.dataset.x = String(e.clientX);
              onBarMove?.(b.id, b.start + dt);
            }}
            onPointerUp={(e) => { delete (e.currentTarget as HTMLElement).dataset.x; }} onPointerCancel={(e) => { delete (e.currentTarget as HTMLElement).dataset.x; }}
            className={`absolute flex cursor-grab items-center overflow-hidden rounded-md px-1.5 text-[11px] font-medium ${b.id === selectedBar ? "bg-lime text-lime-ink ring-2 ring-ink" : "bg-paper-2 text-ink ring-1 ring-ink/40"}`}
            style={{ left: x(b.start), width: Math.max(14, x(b.end) - x(b.start)), top: 22 + H + 4, height: 16, touchAction: "none" }}>
            <span className="truncate">{b.label}</span>
          </div>
        ))}

        {/* duration of the selection */}
        <div className="pointer-events-none absolute -translate-x-1/2 rounded-full bg-ink px-3 py-1 text-xs font-semibold text-paper tnum"
          style={{ left: (x(trim.in) + x(trim.out)) / 2, top: 22 + H + 8 + (bars.length ? 20 : 0) }}>
          {dur(trim.out - trim.in)}
        </div>
      </div>
    </div>
  );
}
