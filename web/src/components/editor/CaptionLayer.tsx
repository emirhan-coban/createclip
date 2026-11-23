import { useEffect, useMemo, useRef, useState } from "react";
import { FONTS, buildStates, drawCaption, stateAt, type Captions } from "../../lib/captions";

/** Caption overlay of the preview: a 1080x1920 canvas inside the stage's scaled canvas, drawn like the exporter does. */
export function CaptionLayer({ captions, time, trim }: { captions: Captions; time: number; trim: { in: number; out: number } }) {
  const ref = useRef<HTMLCanvasElement>(null);
  const [fontReady, setFontReady] = useState(false);
  const fd = FONTS[captions.style.font];
  useEffect(() => {
    let live = true;
    setFontReady(false);
    document.fonts.load(`${fd.weight} 64px ${fd.family}`, "ÇĞİÖŞÜ").then(() => live && setFontReady(true));
    return () => { live = false; };
  }, [fd.family, fd.weight]);

  // like the exporter: only the words inside the cut, on the clip's own timeline (so chunks start where the clip starts)
  const states = useMemo(() => {
    const len = trim.out - trim.in;
    const words = captions.words
      .filter((w) => w.end > trim.in && w.start < trim.out)
      .map((w) => ({ word: w.word, start: Math.max(0, w.start - trim.in), end: Math.min(len, w.end - trim.in) }));
    return buildStates(words, captions.style.chunk, captions.style.sync);
  }, [captions.words, captions.style.chunk, captions.style.sync, trim.in, trim.out]);
  useEffect(() => {
    const c = ref.current, ctx = c?.getContext("2d");
    if (!c || !ctx || !fontReady) return;
    const st = captions.enabled ? stateAt(states, time - trim.in) : null;
    if (st) drawCaption(ctx, st, captions.style);
    else ctx.clearRect(0, 0, c.width, c.height);
  }, [states, time, captions.enabled, captions.style, fontReady]);

  return <canvas ref={ref} width={1080} height={1920} aria-hidden style={{ position: "absolute", left: 0, top: 0, width: 1080, height: 1920, pointerEvents: "none" }} />;
}
