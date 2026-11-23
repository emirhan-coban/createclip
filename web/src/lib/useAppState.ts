import { useCallback, useEffect, useRef, useState } from "react";
import { api, type State } from "./api";

/** Polls /api/state: every 2 s while a job runs, every 6 s otherwise. `refresh` forces an immediate reload. */
export function useAppState() {
  const [state, setState] = useState<State | null>(null);
  const [error, setError] = useState<string | null>(null);
  const timer = useRef<number>(0);

  const load = useCallback(async () => {
    window.clearTimeout(timer.current);
    let busy = false;
    try {
      const s = await api<State>("/api/state");
      setState(s); setError(null);
      busy = s.jobs.some((j) => j.status === "running" || j.status === "queued");
    } catch (e) { setError((e as Error).message); }
    timer.current = window.setTimeout(load, busy ? 2000 : 6000);
  }, []);

  useEffect(() => { void load(); return () => window.clearTimeout(timer.current); }, [load]);
  return { state, error, refresh: load };
}
