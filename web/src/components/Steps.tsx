import { motion } from "motion/react";
import type { JobView } from "../lib/useJob";
import { Counter } from "./Counter";

type State = "todo" | "now" | "done" | "stopped";

export function Steps({ job }: { job: JobView }) {
  const doneClips = Object.values(job.clips).filter((c) => c.done).length;
  const total = job.moments.length;
  const audio = job.activity?.source === "audio";
  const final = !!job.activity && !job.activity.partial;
  const finished = job.status === "done";
  const halted = job.status === "failed" || job.status === "cancelled" || job.status === "blocked";
  const raw: { name: string; state: State; live: React.ReactNode }[] = [
    { name: "Yayını tanı", state: job.info ? "done" : "now", live: job.info ? job.info.title : "Bilgiler alınıyor" },
    {
      name: audio ? "Sesi dinle" : "Sohbeti oku",
      state: final ? "done" : job.info ? "now" : "todo",
      live: final
        ? audio ? "Ses seviyesi çıkarıldı" : <><Counter value={job.activity!.messages} /> mesaj okundu</>
        : job.chat ? <><Counter value={job.chat.messages} /> mesaj · {job.chat.stage}</> : "Sırada",
    },
    { name: "Anları bul", state: total ? "done" : final ? "now" : "todo",
      live: total ? `${total} an, en yükseği ${Math.max(...job.moments.map((m) => m.score)).toFixed(1)}` : "Zirveler aranıyor" },
    { name: "Klipleri kes", state: finished ? "done" : total ? "now" : "todo",
      live: total ? `${doneClips} / ${total} hazır` : "Sırada" },
  ];

  // when the job stopped, the step that was in progress shows as stopped instead of pulsing forever
  const steps = raw.map((s) => (halted && s.state === "now" ? { ...s, state: "stopped" as State } : s));

  return (
    <ol className="relative m-0 flex list-none flex-col gap-1 p-0">
      {steps.map((s, i) => (
        <li key={s.name} className="relative flex gap-3.5 pb-5 last:pb-0">
          {i < steps.length - 1 && <span aria-hidden className="absolute left-[11px] top-7 h-[calc(100%-28px)] w-px bg-line" />}
          <span className="relative mt-0.5 grid size-6 shrink-0 place-items-center rounded-full border border-ink/80"
            style={{ background: s.state === "done" ? "var(--lime)" : "var(--paper)" }}>
            {s.state === "done" && (
              <svg viewBox="0 0 16 16" className="size-3.5"><path d="M3.5 8.5l3 3 6-7" fill="none" stroke="var(--ink)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" /></svg>
            )}
            {s.state === "stopped" && (
              <svg viewBox="0 0 16 16" className="size-3.5"><path d="M4.5 4.5l7 7M11.5 4.5l-7 7" fill="none" stroke="var(--ink)" strokeWidth="2" strokeLinecap="round" /></svg>
            )}
            {s.state === "now" && <motion.span className="size-2 rounded-full bg-ink" animate={{ scale: [1, 1.7, 1], opacity: [1, 0.4, 1] }} transition={{ duration: 1.4, repeat: Infinity }} />}
          </span>
          <span className="min-w-0">
            <span className={`block text-[15px] font-semibold leading-6 ${s.state === "todo" ? "text-mute" : ""}`}>{s.name}</span>
            <span className="line-clamp-2 block text-[13px] leading-snug text-ink-2">{s.live}</span>
          </span>
        </li>
      ))}
    </ol>
  );
}
