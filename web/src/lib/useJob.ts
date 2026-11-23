import { useEffect, useReducer } from "react";

export type Moment = { rank: number; start: number; end: number; score: number };
export type ClipLive = { rank: number; id: number; stage: string; frac: number; done?: boolean; title?: string; start?: number; end?: number; score?: number };
export type JobView = {
  status: "waiting" | "running" | "done" | "failed" | "cancelled" | "blocked";
  error?: string;
  info?: { title: string; duration: number; platform: string; channel: string; thumbnail: string; url: string };
  chat?: { frac: number; messages: number; stage: string };
  activity?: { values: number[]; bin_sec: number; duration: number; messages: number; source: string; partial: boolean };
  moments: Moment[];
  clips: Record<number, ClipLive>;
};

type Ev = { kind: string; [k: string]: unknown };
const empty: JobView = { status: "waiting", moments: [], clips: {} };

function reduce(s: JobView, e: Ev | "reset"): JobView {
  if (e === "reset") return empty;
  switch (e.kind) {
    case "info": return { ...s, status: "running", info: e as unknown as JobView["info"] };
    case "chat": return { ...s, status: "running", chat: e as unknown as JobView["chat"] };
    case "activity": return { ...s, activity: e as unknown as JobView["activity"] };
    case "moments": return { ...s, moments: e.moments as Moment[] };
    case "clip": {
      const c = e as unknown as ClipLive;
      return { ...s, clips: { ...s.clips, [c.rank]: { ...s.clips[c.rank], ...c } } };
    }
    case "end": {
      const st = e.status as string;
      return { ...s, status: (st === "done" ? "done" : st) as JobView["status"], error: (e.error as string) || undefined };
    }
    default: return s;
  }
}

/** Follows a job's server-sent event log (replayed from the start, so a refreshed page rebuilds the whole story). */
export function useJob(jobId: number | null): JobView {
  const [view, dispatch] = useReducer(reduce, empty);
  useEffect(() => {
    dispatch("reset");
    if (jobId == null) return;
    const es = new EventSource(`/api/jobs/${jobId}/events`);
    es.onmessage = (m) => {
      const ev = JSON.parse(m.data) as Ev;
      dispatch(ev);
      if (ev.kind === "end") es.close();
    };
    return () => es.close();
  }, [jobId]);
  return view;
}
