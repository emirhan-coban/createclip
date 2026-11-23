// Captions: the same chunking, timeline and font metrics as autoshorts/captions.py (Pillow), so the preview matches
// the exported video. Word times are seconds in the source file.
export type Word = { word: string; start: number; end: number };
export type FontKey = "montserrat" | "poppins" | "gabarito";
export type CapStyle = {
  font: FontKey; size: number; ypos: number; chunk: number; color: string; active: string;
  stroke: number; upper: boolean; mask: boolean; sync: number;
};
export type Captions = { enabled: boolean; words: Word[]; style: CapStyle };
export type State = { s: number; e: number; i: number; ch: Word[] };

export const DEFAULT_STYLE: CapStyle = {
  font: "montserrat", size: 0.075, ypos: 0.62, chunk: 3, color: "#FFFFFF", active: "#FFDD00", stroke: 1, upper: true, mask: false, sync: -0.08,
};
export const FONTS: Record<FontKey, { label: string; family: string; weight: number }> = {
  montserrat: { label: "Montserrat", family: "KMontserrat", weight: 800 },
  poppins: { label: "Poppins", family: "KPoppins", weight: 700 },
  gabarito: { label: "Gabarito", family: "KGabarito", weight: 800 },
};
export const defaultCaptions = (): Captions => ({ enabled: false, words: [], style: { ...DEFAULT_STYLE } });

const SWEAR = ["sik", "amk", "amına", "amina", "orospu", "piç", "yarrak", "göt", "got", "ibne", "mına"];
const trLower = (s: string) => s.replace(/İ/g, "i").replace(/I/g, "ı").toLowerCase();
export const trUpper = (s: string) => s.replace(/i/g, "İ").replace(/ı/g, "I").toUpperCase();

export function maskWord(w: string): string {
  const core = w.replace(/[^\p{L}\p{N}_]/gu, "");
  if (core && SWEAR.some((st) => trLower(core).startsWith(st))) {
    const i = w.indexOf(core[0]);
    return w.slice(0, i + 1) + "*".repeat(core.length - 1) + w.slice(i + core.length);
  }
  return w;
}

function chunks(words: Word[], size: number): Word[][] {
  const out: Word[][] = [];
  let cur: Word[] = [];
  for (const w of words) {
    cur.push(w);
    if (cur.length === size || /[.?!,]$/.test(w.word)) { out.push(cur); cur = []; }
  }
  if (cur.length) out.push(cur);
  return out;
}

/** Strictly sequential caption states (no overlaps), like captions.build_states. `sync` shifts them in time. */
export function buildStates(words: Word[], chunk: number, sync: number): State[] {
  const raw: State[] = [];
  for (const ch of chunks(words, chunk)) {
    ch.forEach((w, i) => {
      let end = i + 1 < ch.length ? ch[i + 1].start : w.end + 0.15;
      end = Math.min(end, w.start + 1.5);
      raw.push({ s: Math.max(0, w.start + sync), e: Math.max(0, Math.max(end, w.start + 0.04) + sync), i, ch });
    });
  }
  raw.sort((a, b) => a.s - b.s);
  const out: State[] = [];
  let t = 0;
  raw.forEach((st, k) => {
    const s = Math.max(st.s, t);
    let e = st.e;
    if (k + 1 < raw.length) e = Math.min(e, Math.max(raw[k + 1].s, s + 0.04));
    e = Math.max(e, s + 0.04);
    out.push({ s, e, i: st.i, ch: st.ch });
    t = e;
  });
  return out;
}

export function stateAt(states: State[], t: number): State | null {
  let lo = 0, hi = states.length - 1;
  while (lo <= hi) {
    const m = (lo + hi) >> 1;
    if (t < states[m].s) hi = m - 1;
    else if (t >= states[m].e) lo = m + 1;
    else return states[m];
  }
  return null;
}

/** Replace the text, keep the timing. Same word count: 1:1. Otherwise re-time evenly (by length) over the same span. */
export function applyTextEdit(words: Word[], text: string): Word[] {
  const toks = text.split(/\s+/).filter(Boolean);
  if (!toks.length || !words.length) return words;
  if (toks.length === words.length) return words.map((w, i) => ({ ...w, word: toks[i] }));
  const s = words[0].start, e = words[words.length - 1].end;
  const total = toks.reduce((a, t) => a + t.length, 0) || 1;
  let cur = s;
  return toks.map((t) => { const d = ((e - s) * t.length) / total; const w = { word: t, start: +cur.toFixed(3), end: +(cur + d).toFixed(3) }; cur += d; return w; });
}

/** Draws one caption state on a 1080x1920 canvas exactly like captions.Drawer. */
export function drawCaption(ctx: CanvasRenderingContext2D, st: State, style: CapStyle, W = 1080, H = 1920) {
  ctx.clearRect(0, 0, W, H);
  const fd = FONTS[style.font];
  let texts = st.ch.map((w) => (style.mask ? maskWord(w.word) : w.word));
  if (style.upper) texts = texts.map(trUpper);
  const size = Math.floor(W * style.size);
  const setFont = (px: number) => { ctx.font = `${fd.weight} ${px}px ${fd.family}`; ctx.fontKerning = "none"; };
  const measure = () => {
    const sp = ctx.measureText(" ").width;
    return { sp, total: texts.reduce((a, t) => a + ctx.measureText(t).width, 0) + sp * (texts.length - 1) };
  };
  let px = size;
  setFont(px);
  let { sp, total } = measure();
  if (total > W * 0.92) { px = Math.max(14, Math.floor((size * W * 0.92) / total)); setFont(px); ({ sp, total } = measure()); }
  const stroke = style.stroke > 0 ? Math.max(2, Math.round((px / 11) * style.stroke)) : 0;
  const ascent = ctx.measureText("M").fontBoundingBoxAscent;
  const y = Math.floor(H * style.ypos) + ascent;          // Pillow places text by its ascender line at ypos
  ctx.textBaseline = "alphabetic";
  ctx.lineJoin = "round";
  let x = (W - total) / 2;
  texts.forEach((t, i) => {
    if (stroke) { ctx.lineWidth = stroke * 2; ctx.strokeStyle = "#000"; ctx.strokeText(t, x, y); }
    ctx.fillStyle = i === st.i ? style.active : style.color;
    ctx.fillText(t, x, y);
    x += ctx.measureText(t).width + sp;
  });
}
