import { useEffect, useRef, useState } from "react";
import { motion } from "motion/react";
import { hms } from "../lib/api";
import type { ClipLive, Moment } from "../lib/useJob";

const W = 1000, TOP = 34, BASE = 176;

function ghost(): number[] {
  // deterministic, calm-looking stand-in shown before a link is pasted
  let seed = 7;
  const rnd = () => ((seed = (seed * 16807) % 2147483647) / 2147483647);
  return Array.from({ length: 120 }, (_, i) => {
    const bump = (c: number, w: number, h: number) => h * Math.exp(-((i - c) ** 2) / (2 * w * w));
    return 0.12 + rnd() * 0.1 + bump(24, 2.5, 0.55) + bump(63, 3, 0.9) + bump(97, 2, 0.45);
  });
}

function build(values: number[]) {
  const max = Math.max(...values, 1e-6);
  const pts = values.map((v, i) => [(i / Math.max(values.length - 1, 1)) * W, BASE - (v / max) * (BASE - TOP)] as const);
  const line = pts.map(([x, y], i) => `${i ? "L" : "M"}${x.toFixed(1)} ${y.toFixed(1)}`).join(" ");
  return { pts, line, area: `${line} L${W} ${BASE} L0 ${BASE} Z` };
}

export function Timeline({ duration, values, scan, shimmer, moments = [], clips = {}, quiet, blank }: {
  duration: number; values?: number[]; scan?: number | null; shimmer?: boolean; moments?: Moment[];
  clips?: Record<number, ClipLive>; quiet?: boolean; blank?: boolean;
}) {
  const box = useRef<HTMLDivElement>(null);
  const [px, setPx] = useState(1000);                 // rendered width in CSS pixels
  useEffect(() => {
    const el = box.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setPx(el.clientWidth || 1000));
    ro.observe(el);
    setPx(el.clientWidth || 1000);
    return () => ro.disconnect();
  }, []);
  const k = Math.max(1, W / px);                      // user units per CSS pixel: keeps text and dots legible on phones
  const narrow = px < 560;

  const data = values && values.length ? values : ghost();
  const { pts, line, area } = build(data);
  const real = !!(values && values.length);
  const hasDuration = duration > 1;
  const yAt = (t: number) => pts[Math.min(pts.length - 1, Math.max(0, Math.round((t / duration) * (pts.length - 1))))][1];
  const ticks = narrow ? [0, 0.5, 1] : [0, 0.2, 0.4, 0.6, 0.8, 1];
  const dot = Math.max(12, 9 * k), fs = 11.5 * k;

  // bubbles that would overlap an earlier one (same peak area) stack upward instead of hiding each other
  const placed = moments.map((m, i) => {
    const x1 = (m.start / duration) * W, w = Math.max(10 * k, ((m.end - m.start) / duration) * W), cx = x1 + w / 2;
    const crowd = moments.slice(0, i).filter((o) => Math.abs(((o.start + o.end) / 2 - (m.start + m.end) / 2) / duration * W) < dot * 2.1).length;
    const y = Math.max(TOP + 6, yAt(m.start + (m.end - m.start) / 2) - 22 * k) - crowd * dot * 2.2;
    return { m, i, x1, w, cx, y, c: clips[m.rank] };
  });
  const top = Math.min(0, ...placed.map((p) => p.y - dot - 4));

  return (
    <div ref={box}>
      <svg viewBox={`0 ${top} ${W} ${232 - top}`} className="block h-auto w-full overflow-visible" role="img"
        aria-label="Yayın zaman çizelgesi: sohbet yoğunluğu ve bulunan anlar">
        <defs>
          <linearGradient id="fillA" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stopColor="var(--ink)" stopOpacity={quiet ? 0.1 : 0.2} />
            <stop offset="1" stopColor="var(--ink)" stopOpacity="0" />
          </linearGradient>
          <linearGradient id="shim" x1="0" x2="1">
            <stop offset="0" stopColor="var(--lime)" stopOpacity="0" />
            <stop offset="0.5" stopColor="var(--lime)" stopOpacity="0.55" />
            <stop offset="1" stopColor="var(--lime)" stopOpacity="0" />
          </linearGradient>
          <clipPath id="plot"><rect x="0" y="0" width={W} height="232" /></clipPath>
          <clipPath id="reveal">
            <motion.rect x="0" y="0" height="232" initial={{ width: real ? 0 : W }} animate={{ width: W }}
              transition={{ duration: real ? 1.4 : 0, ease: [0.2, 0.7, 0.1, 1] }} key={real ? "r" : "g"} />
          </clipPath>
        </defs>

        <line x1="0" x2={W} y1={BASE} y2={BASE} stroke="var(--line)" strokeWidth="1" vectorEffect="non-scaling-stroke" />
        {hasDuration && ticks.map((p) => (
          <g key={p} transform={`translate(${p * W} 0)`}>
            <line y1={BASE} y2={BASE + 5 * k} stroke="var(--line)" vectorEffect="non-scaling-stroke" />
            <text y={BASE + 18 * k} textAnchor={p === 0 ? "start" : p === 1 ? "end" : "middle"} fontSize={fs} fill="var(--mute)" className="tnum">
              {hms(p * duration)}
            </text>
          </g>
        ))}

        {!blank && (
          <g clipPath="url(#reveal)" opacity={real || !quiet ? 1 : 0.8}>
            <path d={area} fill="url(#fillA)" />
            <path d={line} fill="none" stroke="var(--ink)" strokeWidth="1.6" strokeLinejoin="round" vectorEffect="non-scaling-stroke" opacity={real ? 1 : 0.35} />
          </g>
        )}

        {shimmer && (
          <g clipPath="url(#plot)">
            <motion.rect y={TOP - 10} height={BASE - TOP + 10} width="180" fill="url(#shim)" initial={{ x: -180 }}
              animate={{ x: W }} transition={{ duration: 1.8, repeat: Infinity, ease: "linear" }} />
          </g>
        )}

        {scan != null && (
          <g>
            <motion.line y1={TOP - 14} y2={BASE} stroke="var(--lime)" strokeWidth="3" strokeLinecap="round" vectorEffect="non-scaling-stroke"
              animate={{ x1: scan * W, x2: scan * W }} transition={{ duration: 0.4 }} />
            <motion.circle r={6 * k} cy={TOP - 14} fill="var(--lime)" stroke="var(--ink)" strokeWidth="1.5" vectorEffect="non-scaling-stroke"
              animate={{ cx: scan * W }} transition={{ duration: 0.4 }} />
          </g>
        )}

        {placed.map(({ m, i, x1, w, cx, y, c }) => {
          return (
            <motion.g key={m.rank} initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }}
              transition={{ type: "spring", stiffness: 260, damping: 18, delay: 0.5 + i * 0.12 }}>
              <line x1={cx} x2={cx} y1={y + dot} y2={BASE + 1} stroke="var(--ink)" strokeWidth="1" strokeDasharray="2 3" opacity="0.4" vectorEffect="non-scaling-stroke" />
              <rect x={x1} y={BASE - 3 * k} width={w} height={9 * k} rx={4.5 * k} fill="var(--paper-2)" stroke="var(--ink)" strokeWidth="1.2" vectorEffect="non-scaling-stroke" />
              <motion.rect x={x1} y={BASE - 3 * k} height={9 * k} rx={4.5 * k} fill="var(--lime)" initial={{ width: 0 }}
                animate={{ width: w * (c?.done ? 1 : (c?.frac ?? 0)) }} transition={{ duration: 0.5 }} />
              <circle cx={cx} cy={y} r={dot} fill={c?.done ? "var(--lime)" : "var(--raised)"} stroke="var(--ink)" strokeWidth="1.6" vectorEffect="non-scaling-stroke" />
              <text x={cx} y={y + fs * 0.36} textAnchor="middle" fontSize={fs} fontWeight="650" fill="var(--ink)" className="tnum">{m.rank}</text>
            </motion.g>
          );
        })}
      </svg>
    </div>
  );
}
