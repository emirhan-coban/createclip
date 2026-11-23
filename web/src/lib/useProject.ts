import { useCallback, useEffect, useRef, useState } from "react";
import type { Project } from "./layout";

type Hist = { present: Project; past: Project[]; future: Project[] };

/** The edit project with undo/redo and debounced autosave. Edits sharing a `key` within 800 ms become one undo step
 *  (so dragging a slider or a handle is a single step, not hundreds). */
export function useProject(clipId: number, initial: Project | null) {
  const [h, setH] = useState<Hist | null>(initial ? { present: initial, past: [], future: [] } : null);
  const [saving, setSaving] = useState<"saved" | "saving" | "error">("saved");
  const last = useRef<{ key: string; t: number }>({ key: "", t: 0 });
  const dirty = useRef(false);

  useEffect(() => { setH(initial ? { present: initial, past: [], future: [] } : null); dirty.current = false; }, [initial, clipId]);

  const edit = useCallback((fn: (p: Project) => Project, key = "") => {
    setH((cur) => {
      if (!cur) return cur;
      const next = fn(structuredClone(cur.present));
      const now = Date.now();
      const merge = key !== "" && last.current.key === key && now - last.current.t < 800;
      last.current = { key, t: now };
      dirty.current = true;
      return { present: next, past: merge ? cur.past : [...cur.past, cur.present].slice(-100), future: [] };
    });
  }, []);
  const undo = useCallback(() => setH((c) => { if (!c || !c.past.length) return c; dirty.current = true; last.current = { key: "", t: 0 };
    return { present: c.past[c.past.length - 1], past: c.past.slice(0, -1), future: [c.present, ...c.future] }; }), []);
  const redo = useCallback(() => setH((c) => { if (!c || !c.future.length) return c; dirty.current = true; last.current = { key: "", t: 0 };
    return { present: c.future[0], past: [...c.past, c.present], future: c.future.slice(1) }; }), []);

  const present = h?.present;
  // leaving the page (or closing the tab) within the 700 ms autosave delay must not lose the last edit
  const latest = useRef<Project | null>(null);
  latest.current = present ?? null;
  useEffect(() => {
    const flush = () => {
      if (!dirty.current || !latest.current) return;
      dirty.current = false;
      void fetch(`/api/clips/${clipId}/project`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(latest.current), keepalive: true });
    };
    window.addEventListener("pagehide", flush);
    return () => { window.removeEventListener("pagehide", flush); flush(); };
  }, [clipId]);
  useEffect(() => {
    if (!present || !dirty.current) return;
    setSaving("saving");
    const t = setTimeout(() => {
      fetch(`/api/clips/${clipId}/project`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(present) })
        .then((r) => { if (r.ok) dirty.current = false; setSaving(r.ok ? "saved" : "error"); })
        .catch(() => setSaving("error"));
    }, 700);
    return () => clearTimeout(t);
  }, [present, clipId]);

  return { project: present ?? null, edit, undo, redo, canUndo: !!h?.past.length, canRedo: !!h?.future.length, saving };
}
