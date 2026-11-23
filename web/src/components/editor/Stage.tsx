import { useCallback, useEffect, useRef, useState } from "react";
import { OW, OH, plan, type Layer, type Project } from "../../lib/layout";

/** One <video> of a layer. Registers itself on mount (master or muted copy) so the parent never sees a changing ref. */
function LayerVideo({ layer, src, onMaster, register }: {
  layer: Layer; src: string; onMaster: (v: HTMLVideoElement | null) => void; register: (key: string, v: HTMLVideoElement | null) => void;
}) {
  const ref = useRef<HTMLVideoElement>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (layer.master) { onMaster(el); return () => onMaster(null); }
    register(layer.key, el);
    return () => register(layer.key, null);
  }, [layer.master, layer.key, onMaster, register]);
  const l = layer;
  return (
    <video ref={ref} src={src} muted={!l.master} playsInline preload="auto" draggable={false}
      style={{ position: "absolute", left: l.video.x, top: l.video.y, width: l.video.w, height: l.video.h, maxWidth: "none",
        filter: l.blur ? `blur(${l.blur}px)` : undefined, transform: l.blur ? "scale(1.1)" : undefined, pointerEvents: "none" }} />
  );
}

/** The 9:16 preview: draws the project's layers with CSS, using the same geometry the export uses.
 *  The master layer plays the audio; the other layers are muted copies kept in step with it. */
export function Stage({ project, src, W, H, onMaster, onPan, children }: {
  project: Project; src: string; W: number; H: number;
  onMaster: (v: HTMLVideoElement | null) => void;
  onPan: (cell: number, dcx: number, dcy: number) => void;
  children?: React.ReactNode | ((scale: number) => React.ReactNode);   // drawn on top, in the 1080x1920 canvas space
}) {
  const wrap = useRef<HTMLDivElement>(null);
  const [scale, setScale] = useState(0.3);
  const layers = plan(project, W, H);
  const masterEl = useRef<HTMLVideoElement | null>(null);
  const slaves = useRef<Map<string, HTMLVideoElement>>(new Map());
  const setMasterEl = useCallback((v: HTMLVideoElement | null) => { masterEl.current = v; onMaster(v); }, [onMaster]);
  const register = useCallback((key: string, v: HTMLVideoElement | null) => { if (v) slaves.current.set(key, v); else slaves.current.delete(key); }, []);
  const drag = useRef<{ cell: number; x: number; y: number; k: number } | null>(null);

  useEffect(() => {
    const el = wrap.current;
    if (!el) return;
    const fit = () => setScale(Math.max(0.05, Math.min(el.clientWidth / OW, el.clientHeight / OH)));
    const ro = new ResizeObserver(fit);
    ro.observe(el);
    fit();
    return () => ro.disconnect();
  }, []);

  // keep the muted copies on the master's clock
  useEffect(() => {
    const id = window.setInterval(() => {
      const m = masterEl.current;
      if (!m) return;
      slaves.current.forEach((v) => {
        if (Math.abs(v.currentTime - m.currentTime) > 0.1) v.currentTime = m.currentTime;
        if (m.paused !== v.paused) { if (m.paused) v.pause(); else void v.play().catch(() => {}); }
      });
    }, 120);
    return () => window.clearInterval(id);
  }, []);

  const down = (e: React.PointerEvent, cell: number | undefined, k: number) => {
    if (cell == null) return;
    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
    drag.current = { cell, x: e.clientX, y: e.clientY, k };
  };
  const move = (e: React.PointerEvent) => {
    const d = drag.current;
    if (!d) return;
    const dx = (e.clientX - d.x) / scale, dy = (e.clientY - d.y) / scale;     // canvas px
    d.x = e.clientX; d.y = e.clientY;
    onPan(d.cell, -dx / d.k / W, -dy / d.k / H);                               // content follows the finger: the window moves the other way
  };
  const up = () => { drag.current = null; };

  const movable = project.layout.mode !== "blur";
  return (
    <div ref={wrap} className="grid h-full w-full place-items-center">
      <div className="relative overflow-hidden rounded-[18px] bg-black shadow-lift" style={{ width: OW * scale, height: OH * scale }}>
        <div className="absolute left-0 top-0" style={{ width: OW, height: OH, transform: `scale(${scale})`, transformOrigin: "0 0" }}>
          {layers.map((l) => (
            <div key={l.key} onPointerDown={(e) => down(e, l.cell, l.video.w / W)} onPointerMove={move} onPointerUp={up} onPointerCancel={up}
              style={{ position: "absolute", left: l.box.x, top: l.box.y, width: l.box.w, height: l.box.h, overflow: "hidden",
                cursor: movable ? "grab" : undefined, touchAction: movable ? "none" : undefined }}>
              <LayerVideo layer={l} src={src} onMaster={setMasterEl} register={register} />
            </div>
          ))}
          {typeof children === "function" ? children(scale) : children}
        </div>
      </div>
    </div>
  );
}
