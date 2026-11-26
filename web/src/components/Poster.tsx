import { useRef } from "react";
import { hms } from "../lib/api";

/** A finished clip as a vertical poster. Hovering plays it muted; the poster is as tall as its score deserves. */
export function Poster({ id, title, start, end, score, scale = 1, onOpen, label, pressed }: {
  id: number; title?: string; start?: number; end?: number; score?: number; scale?: number; onOpen?: () => void;
  label?: string; pressed?: boolean;
}) {
  const v = useRef<HTMLVideoElement>(null);
  return (
    <button
      type="button"
      onClick={onOpen}
      aria-pressed={pressed}
      onMouseEnter={() => { v.current?.play().catch(() => {}); }}
      onMouseLeave={() => { if (v.current) { v.current.pause(); v.current.currentTime = 0; } }}
      onFocus={() => { v.current?.play().catch(() => {}); }}
      onBlur={() => { v.current?.pause(); }}
      className="group relative block shrink-0 isolate overflow-hidden rounded-[22px] border-0 bg-black p-0 text-left shadow-lift transition-transform duration-300 hover:-translate-y-1"
      style={{ aspectRatio: "9 / 16", height: `${Math.round(340 * scale)}px` }}
      aria-label={label ?? (title ? `Klibi aç: ${title}` : "Klibi aç")}
    >
      <video ref={v} src={`/media/${id}.mp4`} poster={`/media/${id}.jpg`} muted loop playsInline preload="none"
        className="absolute inset-0 h-full w-full object-cover" />
      <span className="absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/75 to-transparent p-3.5 pt-12 text-white">
        {title && <span className="line-clamp-2 block text-[13px] font-medium leading-snug">{title}</span>}
        <span className="tnum mt-1 flex items-center justify-between text-[11px] text-white/75">
          <span>{start != null && end != null ? `${hms(start)}–${hms(end)}` : ""}</span>
          {score != null && score > 0 && <span className="rounded-full bg-lime px-2 py-0.5 font-semibold text-lime-ink">{score.toFixed(1)}</span>}
        </span>
      </span>
    </button>
  );
}
