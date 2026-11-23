// Layout geometry shared by the preview (CSS) and the export (ffmpeg, autoshorts/editor.py). Keep both in step:
// the same window maths, the same 1080x1920 canvas.
import { defaultCaptions, type Captions } from "./captions";
import type { TextLayer } from "./texts";

export const OW = 1080;
export const OH = 1920;

export type Cell = { cx: number; cy: number; zoom: number };
export type Mode = "blur" | "crop" | "stack";
export type Project = {
  version: 1;
  trim: { in: number; out: number };
  layout: { mode: Mode; cells: Cell[] };
  audio: { volume: number; normalize: boolean };
  captions: Captions;
  texts: TextLayer[];
};
export type Box = { x: number; y: number; w: number; h: number };
export type Layer = {
  key: string;
  box: Box;              // where the layer sits on the 1080x1920 canvas (overflow hidden)
  video: Box;            // the whole source frame, placed inside that box
  blur?: number;
  master?: boolean;      // the audible, authoritative video
  cell?: number;         // which cell (0/1) a drag on this layer moves
};

export const ASPECT: Record<"crop" | "stack", [number, number]> = { crop: [9, 16], stack: [9, 8] };

export function cellRect(W: number, H: number, cell: Cell, aw: number, ah: number): Box {
  const zoom = Math.max(1, cell.zoom);
  let wh = H / zoom;
  let ww = (wh * aw) / ah;
  if (ww > W) { ww = W; wh = (W * ah) / aw; }
  return {
    x: Math.min(Math.max(cell.cx * W - ww / 2, 0), W - ww),
    y: Math.min(Math.max(cell.cy * H - wh / 2, 0), H - wh),
    w: ww, h: wh,
  };
}

function cellLayer(key: string, W: number, H: number, cell: Cell, aw: number, ah: number, box: Box, idx: number, master: boolean): Layer {
  const win = cellRect(W, H, cell, aw, ah);
  const s = box.w / win.w;
  return { key, box, video: { x: -win.x * s, y: -win.y * s, w: W * s, h: H * s }, master, cell: idx };
}

/** Layers to draw for a project, given the source frame size. */
export function plan(p: Project, W: number, H: number): Layer[] {
  const { mode, cells } = p.layout;
  if (mode === "crop") return [cellLayer("c0", W, H, cells[0], 9, 16, { x: 0, y: 0, w: OW, h: OH }, 0, true)];
  if (mode === "stack") {
    return [
      cellLayer("c0", W, H, cells[0], 9, 8, { x: 0, y: 0, w: OW, h: OH / 2 }, 0, true),
      cellLayer("c1", W, H, cells[1], 9, 8, { x: 0, y: OH / 2, w: OW, h: OH / 2 }, 1, false),
    ];
  }
  const cover = Math.max(OW / W, OH / H);
  const fgH = (H * OW) / W;
  return [
    { key: "bg", box: { x: 0, y: 0, w: OW, h: OH }, video: { x: (OW - W * cover) / 2, y: (OH - H * cover) / 2, w: W * cover, h: H * cover }, blur: 36 },
    { key: "fg", box: { x: 0, y: (OH - fgH) / 2, w: OW, h: fgH }, video: { x: 0, y: 0, w: OW, h: fgH }, master: true },
  ];
}

export const defaultProject = (dur: number): Project => ({
  version: 1, trim: { in: 0, out: dur },
  layout: { mode: "blur", cells: [{ cx: 0.5, cy: 0.5, zoom: 1 }, { cx: 0.85, cy: 0.8, zoom: 3 }] },
  audio: { volume: 1, normalize: true },
  captions: defaultCaptions(),
  texts: [],
});
