import { useEffect, useRef, useState } from "react";
import { FONTS } from "../../lib/captions";
import { OH, OW, drawText, geometry, type TextLayer as Layer } from "../../lib/texts";

/** Text overlay of the preview: all visible layers on one canvas, plus a draggable box around the selected one. */
export function TextLayer({ layers, time, selected, scale, onMove, onSelect }: {
  layers: Layer[]; time: number; selected: string | null; scale: number;
  onMove: (id: string, x: number, y: number) => void; onSelect: (id: string | null) => void;
}) {
  const ref = useRef<HTMLCanvasElement>(null);
  const [ready, setReady] = useState(false);
  const fontKey = layers.map((l) => l.font).sort().join(",");
  useEffect(() => {
    let live = true;
    setReady(false);
    const fams = [...new Set(layers.map((l) => FONTS[l.font]))];
    Promise.all(fams.map((f) => document.fonts.load(`${f.weight} 64px ${f.family}`, "ÇĞİÖŞÜ"))).then(() => live && setReady(true));
    return () => { live = false; };
  }, [fontKey]); // eslint-disable-line react-hooks/exhaustive-deps

  const visible = layers.filter((l) => time >= l.start && time < l.end && l.text.trim());
  const boxes = useRef<Record<string, { x: number; y: number; w: number; h: number }>>({});
  const [, force] = useState(0);
  useEffect(() => {
    const c = ref.current, ctx = c?.getContext("2d");
    if (!c || !ctx || !ready) return;
    ctx.clearRect(0, 0, OW, OH);
    const next: typeof boxes.current = {};
    for (const l of visible) {
      const g = drawText(ctx, l);
      next[l.id] = { x: g.origin[0], y: g.origin[1], w: g.size[0], h: g.size[1] };
    }
    const changed = JSON.stringify(next) !== JSON.stringify(boxes.current);
    boxes.current = next;
    if (changed) force((n) => n + 1);
  }); // every frame: cheap, and the text must follow time and edits

  const drag = useRef<{ x: number; y: number } | null>(null);
  const sel = selected ? layers.find((l) => l.id === selected) : null;
  const box = sel ? boxes.current[sel.id] ?? (ready ? (() => { const c = ref.current?.getContext("2d"); if (!c) return undefined; const g = geometry(c, sel); return { x: g.origin[0], y: g.origin[1], w: g.size[0], h: g.size[1] }; })() : undefined) : undefined;
  void OH;
  return (
    <>
      <canvas ref={ref} width={OW} height={OH} aria-hidden style={{ position: "absolute", left: 0, top: 0, width: OW, height: OH, pointerEvents: "none" }} />
      {sel && box && (
        <div
          role="button" tabIndex={0} aria-label="Metni sürükleyerek taşı"
          onPointerDown={(e) => { e.stopPropagation(); (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId); drag.current = { x: e.clientX, y: e.clientY }; onSelect(sel.id); }}
          onPointerMove={(e) => {
            const d = drag.current;
            if (!d) return;
            const dx = (e.clientX - d.x) / scale, dy = (e.clientY - d.y) / scale;
            d.x = e.clientX; d.y = e.clientY;
            onMove(sel.id, Math.min(1, Math.max(0, sel.x + dx / OW)), Math.min(1, Math.max(0, sel.y + dy / OH)));
          }}
          onPointerUp={() => { drag.current = null; }} onPointerCancel={() => { drag.current = null; }}
          style={{ position: "absolute", left: box.x - 6, top: box.y - 6, width: box.w + 12, height: box.h + 12, border: `${3 / scale}px dashed #BFF453`,
            borderRadius: 12 / scale, cursor: "move", touchAction: "none", outline: "none" }}
        />
      )}
    </>
  );
}
