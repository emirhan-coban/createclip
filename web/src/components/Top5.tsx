import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, hms, type Clip, type State } from "../lib/api";
import { useJobPoll } from "../lib/useJobPoll";
import { Poster } from "./Poster";

const MIN = 2, MAX = 5, LIMIT = 180;
const HEADINGS: Record<number, string> = { 2: "HAFTANIN TOP 2'Sİ", 3: "HAFTANIN TOP 3'Ü", 4: "HAFTANIN TOP 4'Ü", 5: "HAFTANIN TOP 5'İ" };

type Item = { clip_id: number; credit: string; note: string };

const field = "w-full rounded-xl border border-line bg-raised px-3 py-2 text-sm outline-none focus:border-ink";
const small = "grid size-8 shrink-0 place-items-center rounded-full border border-line text-sm hover:border-ink disabled:opacity-30";

/** Pick 2-5 finished clips, rank them, write a comment for each, and render one countdown video. */
export function Top5({ s, refresh }: { s: State; refresh: () => void }) {
  const [items, setItems] = useState<Item[]>([]);
  const [heading, setHeading] = useState<string | null>(null);   // null = follow the number of clips
  const [jobId, setJobId] = useState<number | null>(null);
  const [err, setErr] = useState("");
  const job = useJobPoll(jobId);
  const busy = jobId != null && !["done", "failed", "cancelled", "blocked"].includes(job?.status ?? "queued");
  useEffect(() => { if (job?.status === "done") refresh(); }, [job?.status]); // eslint-disable-line react-hooks/exhaustive-deps

  const clips = s.clips.filter((c) => c.status === "done" && c.has_file && c.engine !== "top5");
  const byId = new Map(clips.map((c) => [c.id, c]));
  const chosen = items.filter((i) => byId.has(i.clip_id));       // a clip deleted meanwhile drops out
  const total = chosen.reduce((n, i) => { const c = byId.get(i.clip_id)!; return n + (c.end - c.start); }, 0);
  const title = heading ?? HEADINGS[chosen.length] ?? HEADINGS[MAX];

  const toggle = (c: Clip) => setItems(chosen.some((i) => i.clip_id === c.id) ? chosen.filter((i) => i.clip_id !== c.id)
    : chosen.length < MAX ? [...chosen, { clip_id: c.id, credit: c.channel, note: "" }] : chosen);
  const patch = (id: number, p: Partial<Item>) => setItems(chosen.map((i) => (i.clip_id === id ? { ...i, ...p } : i)));
  const move = (from: number, to: number) => { const next = [...chosen]; next.splice(to, 0, ...next.splice(from, 1)); setItems(next); };
  const create = async () => {
    try { setErr(""); setJobId((await api<{ id: number }>("/api/top5", { heading: title, items: chosen })).id); }
    catch (x) { setErr((x as Error).message); }
  };

  return (
    <div>
      <h1 className="title mb-2 text-3xl">Haftanın Top 5'i</h1>
      <p className="mb-6 max-w-2xl text-ink-2">
        {MIN}–{MAX} klip seç ve sırala. Video son sıradan 1 numaraya doğru oynar; her bölümde sıra, yayıncı adı ve senin yorumun görünür.
      </p>

      {chosen.length > 0 && (
        <section aria-label="Sıralama" className="mb-8 max-w-2xl">
          <label className="block">
            <span className="text-sm text-ink-2">Videonun başlığı</span>
            <input value={title} maxLength={60} onChange={(e) => setHeading(e.target.value)} className={`${field} mt-1 font-semibold`} />
          </label>
          <ol className="m-0 mt-4 list-none divide-y divide-line p-0">
            {chosen.map((i, n) => {
              const c = byId.get(i.clip_id)!;
              return (
                <li key={i.clip_id} className="flex gap-3 py-3">
                  <span className="display tnum w-12 shrink-0 !text-3xl">#{n + 1}</span>
                  <img src={`/media/${c.id}.jpg`} alt="" className="h-24 w-[3.4rem] shrink-0 rounded-lg bg-black object-cover" />
                  <div className="flex min-w-0 flex-1 flex-col gap-1.5">
                    <p className="truncate text-sm text-ink-2">{c.title} · <span className="tnum">{hms(c.end - c.start)}</span></p>
                    <input value={i.note} maxLength={120} onChange={(e) => patch(c.id, { note: e.target.value })} aria-label={`${n + 1}. klip yorumu`}
                      placeholder="Ekranda görünecek yorumun (boş olabilir)" className={field} />
                    <input value={i.credit} maxLength={40} onChange={(e) => patch(c.id, { credit: e.target.value })} aria-label={`${n + 1}. klip yayıncı adı`}
                      placeholder="Yayıncı adı" className={field} />
                  </div>
                  <div className="flex flex-col gap-1">
                    <button type="button" className={small} disabled={n === 0} onClick={() => move(n, n - 1)} aria-label="Yukarı taşı">↑</button>
                    <button type="button" className={small} disabled={n === chosen.length - 1} onClick={() => move(n, n + 1)} aria-label="Aşağı taşı">↓</button>
                    <button type="button" className={small} onClick={() => toggle(c)} aria-label="Listeden çıkar">×</button>
                  </div>
                </li>
              );
            })}
          </ol>
          <div className="mt-3 flex flex-wrap items-center gap-3">
            <button onClick={create} disabled={busy || chosen.length < MIN || total > LIMIT}
              className="rounded-full bg-lime px-6 py-2.5 font-semibold text-lime-ink active:scale-95 disabled:opacity-40">Montajı oluştur</button>
            <span className={`tnum text-sm ${total > LIMIT ? "text-danger" : "text-ink-2"}`}>
              Toplam {hms(total)} / {hms(LIMIT)}{total > LIMIT ? " · kısalt ya da bir klip çıkar" : ""}
            </span>
          </div>
          <p role="status" className="mt-2 text-sm text-ink-2">
            {busy ? `${job?.status === "running" ? job.msg || "Hazırlanıyor" : "Sırada bekliyor"}${job?.frac ? ` · %${Math.round(job.frac * 100)}` : ""}` : ""}
            {job?.status === "done" && <>Montaj hazır. <Link to="/panel/klipler" className="underline underline-offset-2">Klipler'de izle ve yükle</Link>.</>}
          </p>
          {(err || job?.status === "failed") && <p role="alert" className="mt-1 text-sm text-danger">{err || job?.error}</p>}
        </section>
      )}

      {clips.length < MIN ? <p className="text-ink-2">Montaj için en az {MIN} hazır klip gerekli.</p> : (
        <div className="grid grid-cols-[repeat(auto-fill,minmax(10.5rem,1fr))] gap-5">
          {clips.map((c) => {
            const rank = chosen.findIndex((i) => i.clip_id === c.id) + 1;
            return (
              <div key={c.id} className={`relative rounded-[22px] [&>button]:!h-auto [&>button]:w-full ${rank ? "ring-4 ring-lime" : ""}`}>
                <Poster id={c.id} title={c.title} start={c.start} end={c.end} score={c.score} onOpen={() => toggle(c)}
                  pressed={rank > 0} label={`Montaja ${rank ? "ekli, çıkar" : "ekle"}: ${c.title}`} />
                {rank > 0 && <span className="tnum pointer-events-none absolute left-2 top-2 z-10 rounded-full bg-lime px-2.5 py-1 text-sm font-semibold text-lime-ink">#{rank}</span>}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
