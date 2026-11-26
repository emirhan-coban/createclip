import { useEffect, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { api, type Stats } from "../lib/api";

const PERIODS = [{ d: 7, l: "7 gün" }, { d: 28, l: "28 gün" }, { d: 90, l: "90 gün" }, { d: 0, l: "Tümü" }];
const num = (n: number) => n.toLocaleString("tr-TR");
const pct = (n: number) => `%${n.toLocaleString("tr-TR", { maximumFractionDigits: 1 })}`;
const day = (t: number) => new Date(t * 1000).toLocaleDateString("tr-TR", { day: "numeric", month: "short" });

function Table({ label, head, rows }: { label: string; head: string[]; rows: { key: string | number; cells: ReactNode[] }[] }) {
  return (
    <section aria-label={label} className="mt-8">
      <h2 className="title mb-2 text-xl">{label}</h2>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[34rem] border-collapse text-sm">
          <thead>
            <tr className="border-b border-line text-ink-2">
              {head.map((h, i) => <th key={h} scope="col" className={`py-2 font-medium ${i ? "pl-4 text-right" : "text-left"}`}>{h}</th>)}
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {rows.map((r) => (
              <tr key={r.key}>
                {r.cells.map((c, i) => <td key={i} className={`py-2.5 ${i ? "tnum whitespace-nowrap pl-4 text-right" : "max-w-[18rem]"}`}>{c}</td>)}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

/** YouTube numbers of the clips uploaded from the panel, per streamer and per video. */
export function Analytics() {
  const [days, setDays] = useState(28);
  const [data, setData] = useState<Stats | null>(null);
  const [err, setErr] = useState("");
  useEffect(() => {
    let stale = false;
    setData(null); setErr("");
    api<Stats>(`/api/youtube/stats?days=${days}`).then((s) => { if (!stale) setData(s); }).catch((x) => { if (!stale) setErr((x as Error).message); });
    return () => { stale = true; };
  }, [days]);

  const status = { waiting: "henüz veri yok", scheduled: "yayın bekliyor" };
  return (
    <div>
      <h1 className="title mb-2 text-3xl">Analiz</h1>
      <p className="mb-4 max-w-2xl text-ink-2">Panelden YouTube'a yüklediğin videolar. YouTube bu verileri 2–3 gün gecikmeyle verir.</p>
      <div role="group" aria-label="Dönem" className="flex flex-wrap gap-2">
        {PERIODS.map((p) => (
          <button key={p.d} type="button" onClick={() => setDays(p.d)} aria-pressed={days === p.d}
            className={`rounded-full px-4 py-2 text-sm ${days === p.d ? "bg-ink font-semibold text-paper" : "border border-line hover:border-ink"}`}>{p.l}</button>
        ))}
      </div>

      {err ? <p role="alert" className="mt-6 text-sm text-danger">{err} <Link to="/panel/ayarlar" className="underline underline-offset-2">Ayarlar</Link></p>
        : !data ? <p role="status" className="mt-6 text-ink-2">YouTube'dan alınıyor…</p>
        : data.videos.length === 0 ? <p className="mt-6 text-ink-2">Panelden henüz video yüklenmedi. Klipler'den bir klip yükleyince burada görünür.</p>
        : (
          <>
            <div className="mt-8 flex flex-wrap gap-x-12 gap-y-5">
              {[{ v: data.totals.views, l: "izlenme" }, { v: data.totals.engaged, l: "etkin izlenme" }, { v: data.totals.subs, l: "kazanılan abone" }].map((n) => (
                <div key={n.l}>
                  <div className="display tnum !text-[clamp(2.2rem,4.5vw,3.4rem)]">{num(n.v)}</div>
                  <div className="mt-1 text-ink-2">{n.l}</div>
                </div>
              ))}
            </div>
            <p className="mt-3 max-w-2xl text-xs text-mute">Etkin izlenme: ilk karede bırakmayıp izlemeye devam edenler. Karşılaştırmak için izlenmeden daha güvenilir.</p>

            {data.streamers.length > 0 && (
              <Table label="Yayıncılar" head={["Yayıncı", "Video", "Video başı izlenme", "Ort. izlenme yüzdesi", "Abone"]}
                rows={data.streamers.map((s) => ({ key: s.streamer, cells: [s.streamer, num(s.videos), num(s.avg_views), pct(s.view_pct), num(s.subs)] }))} />
            )}
            <Table label="Videolar" head={["Video", "İzlenme", "Etkin", "Ort. yüzde", "Abone", "Beğeni"]}
              rows={data.videos.map((v) => ({
                key: v.clip_id,
                cells: [
                  <>
                    <a href={`https://youtube.com/shorts/${v.yt_id}`} target="_blank" rel="noopener noreferrer" className="line-clamp-2 hover:underline">{v.title || v.yt_id}</a>
                    <span className="text-mute">{v.streamer}{v.published ? ` · ${day(v.published)}` : ""}{v.state !== "data" ? ` · ${status[v.state]}` : ""}</span>
                  </>,
                  ...(v.state === "data" ? [num(v.views), num(v.engaged), pct(v.view_pct), num(v.subs), num(v.likes)] : ["–", "–", "–", "–", "–"]),
                ],
              }))} />
            <p className="mt-4 text-xs text-mute">
              {data.other > 0 ? `Panel dışından yüklenmiş ${data.other} video bu listede yok. ` : ""}
              {data.truncated ? "YouTube yalnızca en çok izlenen 200 videoyu veriyor; az izlenenler “henüz veri yok” görünebilir." : ""}
            </p>
          </>
        )}
    </div>
  );
}
