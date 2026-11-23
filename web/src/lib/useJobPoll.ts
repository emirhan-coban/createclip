import { useEffect, useState } from "react";
import { api, type Job, type State } from "./api";

/** Follows a background job (source download, transcription, export) through the shared state list. */
export function useJobPoll(jobId: number | null) {
  const [job, setJob] = useState<Job | null>(null);
  useEffect(() => {
    setJob(null);
    if (jobId == null) return;
    let stop = false;
    const tick = async () => {
      try {
        const s = await api<State>("/api/state");
        const j = s.jobs.find((x) => x.id === jobId) ?? null;
        if (!stop) setJob(j);
        if (j && ["done", "failed", "cancelled", "blocked"].includes(j.status)) return;
      } catch { /* keep trying */ }
      if (!stop) setTimeout(tick, 700);
    };
    void tick();
    return () => { stop = true; };
  }, [jobId]);
  return job;
}
