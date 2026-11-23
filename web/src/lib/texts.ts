// Text layers: same wrapping, block geometry and baselines as autoshorts/texts.py (Pillow). Times are seconds from the
// clip's start. Change both files together.
import { FONTS, type FontKey } from "./fonts";

export type TextLayer = {
  id: string; text: string; start: number; end: number; x: number; y: number; size: number;
  font: FontKey; color: string; stroke: number; bg: { on: boolean; color: string; opacity: number };
};
export const OW = 1080;
export const OH = 1920;
const LINE = 1.25, BASE = 1.0, EMOJI_ADV = 1.2, EMOJI_PX = 1.15, MAX_W = 0.88;
const EMOJI_SPLIT = /([\u{1F300}-\u{1FAFF}\u{2300}-\u{23FF}\u{2600}-\u{27BF}\u{2B00}-\u{2BFF}])/u;
const EMOJI_ONE = /^[\u{1F300}-\u{1FAFF}\u{2300}-\u{23FF}\u{2600}-\u{27BF}\u{2B00}-\u{2BFF}]$/u;
export const EMOJI_PALETTE = ["😂", "🔥", "😮", "💀", "👀", "👏", "👍", "🎮", "💥", "🤯"];

export const newText = (id: string, start: number, end: number, y: number): TextLayer => ({
  id, text: "Metnini yaz", start, end, x: 0.5, y, size: 0.07, font: "montserrat", color: "#FFFFFF", stroke: 1,
  bg: { on: false, color: "#000000", opacity: 0.55 },
});

export const runs = (s: string): [boolean, string][] =>
  s.replace(/️/g, "").split(EMOJI_SPLIT).filter(Boolean).map((p) => [EMOJI_ONE.test(p), p] as [boolean, string]);

export type Geometry = {
  px: number; lines: string[][]; widths: number[]; lh: number; pad: [number, number]; padbg: [number, number];
  block: [number, number]; size: [number, number]; origin: [number, number]; sp: number; adv: number; stroke: number;
};

export function setFont(ctx: CanvasRenderingContext2D, layer: TextLayer, px: number) {
  const f = FONTS[layer.font];
  ctx.font = `${f.weight} ${px}px ${f.family}`;
  ctx.fontKerning = "none";
}

export function geometry(ctx: CanvasRenderingContext2D, l: TextLayer): Geometry {
  const px = Math.floor(OW * l.size);
  setFont(ctx, l, px);
  const sp = ctx.measureText(" ").width, adv = px * EMOJI_ADV;
  const wordW = (w: string) => runs(w).reduce((a, [e, t]) => a + (e ? adv : ctx.measureText(t).width), 0);
  const lines: string[][] = [];
  for (const raw of l.text.split("\n")) {
    let cur: string[] = [], cw = 0;
    for (const w of raw.split(" ")) {
      if (w === "") continue;
      const ww = wordW(w), add = cur.length ? sp + ww : ww;
      if (cur.length && cw + add > OW * MAX_W) { lines.push(cur); cur = [w]; cw = ww; }
      else { cur.push(w); cw += add; }
    }
    lines.push(cur);
  }
  const widths = lines.map((ln) => ln.reduce((a, w) => a + wordW(w), 0) + sp * Math.max(0, ln.length - 1));
  const blockW = Math.max(1, ...widths), lh = px * LINE, blockH = lh * lines.length;
  const stroke = l.stroke > 0 ? Math.max(2, Math.round((px / 11) * l.stroke)) : 0;
  const padbg: [number, number] = l.bg.on ? [px * 0.4, px * 0.22] : [0, 0];
  const pad: [number, number] = [padbg[0] + stroke + 2, padbg[1] + stroke + 2];
  const w = blockW + 2 * pad[0], h = blockH + 2 * pad[1];
  return { px, lines, widths, lh, pad, padbg, block: [blockW, blockH], size: [w, h], origin: [l.x * OW - w / 2, l.y * OH - h / 2], sp, adv, stroke };
}

export function drawText(ctx: CanvasRenderingContext2D, l: TextLayer): Geometry {
  const g = geometry(ctx, l);
  const [ox, oy] = g.origin, [padX, padY] = g.pad;
  if (l.bg.on) {
    const [bx, by] = g.padbg;
    const hex = l.bg.color.replace("#", "");
    ctx.fillStyle = `rgba(${parseInt(hex.slice(0, 2), 16)},${parseInt(hex.slice(2, 4), 16)},${parseInt(hex.slice(4, 6), 16)},${l.bg.opacity})`;
    ctx.beginPath();
    ctx.roundRect(ox + padX - bx, oy + padY - by, g.block[0] + 2 * bx, g.block[1] + 2 * by, g.px * 0.35);
    ctx.fill();
  }
  ctx.textBaseline = "alphabetic";
  ctx.textAlign = "left";
  ctx.lineJoin = "round";
  g.lines.forEach((ln, i) => {
    let x = ox + padX + (g.block[0] - g.widths[i]) / 2;
    const base = oy + padY + i * g.lh + g.px * BASE;
    ln.forEach((w, wi) => {
      for (const [emoji, t] of runs(w)) {
        if (emoji) {
          const size = g.px * EMOJI_PX;
          ctx.save();
          ctx.font = `${size / 1.17}px "Apple Color Emoji", sans-serif`;
          ctx.textAlign = "center";
          ctx.fillStyle = "#000";
          ctx.fillText(t, x + g.adv / 2, base - size * 0.85 + size * 0.86);
          ctx.restore();
          x += g.adv;
        } else {
          setFont(ctx, l, g.px);
          if (g.stroke) { ctx.lineWidth = g.stroke * 2; ctx.strokeStyle = "#000"; ctx.strokeText(t, x, base); }
          ctx.fillStyle = l.color;
          ctx.fillText(t, x, base);
          x += ctx.measureText(t).width;
        }
      }
      if (wi + 1 < ln.length) x += g.sp;
    });
  });
  return g;
}
