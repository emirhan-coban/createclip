import { useRef } from "react";
import { FONTS, type FontKey } from "../../lib/fonts";
import type { Project } from "../../lib/layout";
import { EMOJI_PALETTE, newText, type TextLayer } from "../../lib/texts";

type Edit = (fn: (p: Project) => Project, key?: string) => void;
const clamp = (v: number, a: number, b: number) => Math.min(b, Math.max(a, v));

export function TextPanel({ project, edit, now, selected, onSelect }: {
  project: Project; edit: Edit; now: number; selected: string | null; onSelect: (id: string | null) => void;
}) {
  const layers = project.texts ?? [];
  const len = project.trim.out - project.trim.in;
  const sel = layers.find((l) => l.id === selected) ?? null;
  const area = useRef<HTMLTextAreaElement>(null);

  const add = () => {
    const id = `t${Date.now().toString(36)}`;
    const start = clamp(now, 0, Math.max(0, len - 0.5));
    const layer = newText(id, +start.toFixed(2), +Math.min(len, start + 3).toFixed(2), [0.2, 0.35, 0.5, 0.65, 0.8][layers.length % 5]);
    edit((p) => { p.texts = [...(p.texts ?? []), layer]; return p; });
    onSelect(id);
  };
  const patch = (id: string, change: Partial<TextLayer>, key: string) =>
    edit((p) => { p.texts = p.texts.map((l) => (l.id === id ? { ...l, ...change } : l)); return p; }, `${key}-${id}`);
  const remove = (id: string) => { edit((p) => { p.texts = p.texts.filter((l) => l.id !== id); return p; }); if (selected === id) onSelect(null); };
  const field = "w-full rounded-xl border border-line bg-raised px-3 py-2 outline-none focus:border-ink";
  const range = (label: string, v: number, min: number, max: number, step: number, key: "size" | "x" | "y" | "stroke", show: (n: number) => string) => (
    <label className="block text-sm">
      <span className="flex justify-between"><span>{label}</span><span className="tnum text-ink-2">{show(v)}</span></span>
      <input type="range" min={min} max={max} step={step} value={v} className="mt-1 w-full accent-[var(--ink)]"
        onChange={(e) => patch(sel!.id, { [key]: Number(e.target.value) } as Partial<TextLayer>, `t-${key}`)} />
    </label>
  );
  const insert = (emoji: string) => {
    if (!sel) return;
    const el = area.current, at = el?.selectionStart ?? sel.text.length;
    patch(sel.id, { text: sel.text.slice(0, at) + emoji + sel.text.slice(at) }, "t-text");
  };

  return (
    <section aria-label="Metin">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="title text-lg">Metin</h2>
        <button onClick={add} className="rounded-full bg-ink px-4 py-1.5 text-sm font-semibold text-paper active:scale-95">Metin ekle</button>
      </div>
      {layers.length === 0 ? (
        <p className="text-sm text-ink-2">Başlık, etiket ya da emoji ekle; istediğin aralıkta ekranda kalır. Önizlemede sürükleyerek taşırsın.</p>
      ) : (
        <ul className="m-0 flex list-none flex-col gap-1 p-0">
          {layers.map((l) => (
            <li key={l.id}>
              <button onClick={() => onSelect(l.id === selected ? null : l.id)} aria-pressed={l.id === selected}
                className={`flex w-full items-center gap-2 rounded-xl border px-3 py-2 text-left text-sm ${l.id === selected ? "border-ink bg-paper-2" : "border-line"}`}>
                <span className="min-w-0 flex-1 truncate font-medium">{l.text || "(boş)"}</span>
                <span className="tnum shrink-0 text-xs text-ink-2">{l.start.toFixed(1)}–{l.end.toFixed(1)} sn</span>
              </button>
            </li>
          ))}
        </ul>
      )}

      {sel && (
        <div className="mt-4 flex flex-col gap-4 rounded-2xl border border-line p-4">
          <div>
            <label htmlFor="t-text" className="text-sm font-medium">Metin</label>
            <textarea id="t-text" ref={area} rows={3} value={sel.text} spellCheck={false} className={`${field} mt-1 resize-y`}
              onChange={(e) => patch(sel.id, { text: e.target.value }, "t-text")} />
            <div className="mt-2 flex flex-wrap gap-1" aria-label="Emoji ekle">
              {EMOJI_PALETTE.map((e) => (
                <button key={e} type="button" onClick={() => insert(e)} className="grid size-8 place-items-center rounded-lg border border-line text-lg hover:border-ink" aria-label={`Emoji ekle ${e}`}>{e}</button>
              ))}
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <label className="block text-sm">Başlangıç (sn)
              <input type="number" min={0} max={len} step={0.1} value={sel.start} className={`${field} tnum mt-1`}
                onChange={(e) => patch(sel.id, { start: clamp(Number(e.target.value), 0, sel.end - 0.1) }, "t-start")} />
              <button type="button" onClick={() => patch(sel.id, { start: +clamp(now, 0, sel.end - 0.1).toFixed(2) }, "t-start")} className="mt-1 text-xs text-ink-2 underline underline-offset-2">Şimdiye al</button>
            </label>
            <label className="block text-sm">Bitiş (sn)
              <input type="number" min={0} max={len} step={0.1} value={sel.end} className={`${field} tnum mt-1`}
                onChange={(e) => patch(sel.id, { end: clamp(Number(e.target.value), sel.start + 0.1, len) }, "t-end")} />
              <button type="button" onClick={() => patch(sel.id, { end: +clamp(now, sel.start + 0.1, len).toFixed(2) }, "t-end")} className="mt-1 text-xs text-ink-2 underline underline-offset-2">Şimdiye al</button>
            </label>
          </div>

          <div>
            <label htmlFor="t-font" className="text-sm font-medium">Yazı tipi</label>
            <select id="t-font" value={sel.font} onChange={(e) => patch(sel.id, { font: e.target.value as FontKey }, "t-font")} className={`${field} mt-1`}>
              {(Object.keys(FONTS) as FontKey[]).map((k) => <option key={k} value={k}>{FONTS[k].label}</option>)}
            </select>
          </div>
          {range("Boyut", sel.size, 0.03, 0.18, 0.0025, "size", (v) => `${Math.round(v * 1000) / 10}`)}
          {range("Yatay konum", sel.x, 0, 1, 0.005, "x", (v) => `%${Math.round(v * 100)}`)}
          {range("Dikey konum", sel.y, 0, 1, 0.005, "y", (v) => `%${Math.round(v * 100)}`)}
          {range("Kontur", sel.stroke, 0, 3, 0.1, "stroke", (v) => v.toFixed(1))}

          <div className="grid grid-cols-2 gap-3">
            <label className="block text-sm">Renk
              <input type="color" value={sel.color} onChange={(e) => patch(sel.id, { color: e.target.value.toUpperCase() }, "t-color")} className="mt-1 block h-10 w-full cursor-pointer rounded-xl border border-line bg-raised p-1" />
            </label>
            <label className="block text-sm">Zemin rengi
              <input type="color" value={sel.bg.color} onChange={(e) => patch(sel.id, { bg: { ...sel.bg, color: e.target.value.toUpperCase() } }, "t-bgc")} className="mt-1 block h-10 w-full cursor-pointer rounded-xl border border-line bg-raised p-1" />
            </label>
          </div>
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={sel.bg.on} onChange={(e) => patch(sel.id, { bg: { ...sel.bg, on: e.target.checked } }, "t-bg")} className="size-4 accent-[var(--ink)]" />Arkasına zemin ekle
          </label>
          {sel.bg.on && (
            <label className="block text-sm">
              <span className="flex justify-between"><span>Zemin koyuluğu</span><span className="tnum text-ink-2">%{Math.round(sel.bg.opacity * 100)}</span></span>
              <input type="range" min={0.1} max={1} step={0.05} value={sel.bg.opacity} className="mt-1 w-full accent-[var(--ink)]"
                onChange={(e) => patch(sel.id, { bg: { ...sel.bg, opacity: Number(e.target.value) } }, "t-bgo")} />
            </label>
          )}
          <button onClick={() => remove(sel.id)} className="self-start text-sm text-danger underline underline-offset-2">Bu metni sil</button>
        </div>
      )}
    </section>
  );
}
