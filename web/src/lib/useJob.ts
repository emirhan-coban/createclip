import { useEffect, useReducer } from "react";

export type Moment = { rank: number; start: number; end: number; score: number };
export type ClipLive = { rank: number; id: number; stage: string; frac: number; done?: boolean; title?: string; start?: number; end?: number; score?: number };
export type LogLine = { t: number; level: "info" | "step" | "cmd" | "ok" | "warn" | "err"; text: string };
export type JobView = {
  status: "waiting" | "running" | "done" | "failed" | "cancelled" | "blocked";
  error?: string;
  info?: { title: string; duration: number; platform: string; channel: string; thumbnail: string; url: string };
  chat?: { frac: number; messages: number; stage: string };
  activity?: { values: number[]; bin_sec: number; duration: number; messages: number; source: string; partial: boolean };
  audio?: { phase: "download" | "measure"; frac: number; text: string };
  fallback?: string;                      // why the chat could not be used (we listened to the audio instead)
  startedAt?: number;                     // server time of the first event, seconds
  lastAt?: number;                        // server time of the latest event
  moments: Moment[];
  clips: Record<number, ClipLive>;
  logs: LogLine[];                        // the terminal
};

type Ev = { kind: string; [k: string]: unknown };
const empty: JobView = { status: "waiting", moments: [], clips: {}, logs: [] };

function reduce(s: JobView, e: Ev | "reset"): JobView {
  if (e === "reset") return empty;
  const t = typeof e.t === "number" ? e.t : undefined;
  s = { ...s, startedAt: s.startedAt ?? t, lastAt: t ?? s.lastAt };
  switch (e.kind) {
    case "log": return { ...s, logs: [...s.logs, { t: t ?? 0, level: e.level as LogLine["level"], text: String(e.text ?? "") }].slice(-800) };
    case "audio": return { ...s, status: "running", audio: e as unknown as JobView["audio"] };
    case "fallback": return { ...s, fallback: String(e.reason ?? "") };
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
