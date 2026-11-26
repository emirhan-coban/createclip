import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, type Clip, type YouTube } from "../lib/api";
import { useJobPoll } from "../lib/useJobPoll";

const when = (t: number) => new Date(t * 1000).toLocaleString("tr-TR", { day: "numeric", month: "long", hour: "2-digit", minute: "2-digit" });
/** Epoch seconds <-> the local "YYYY-MM-DDTHH:mm" of a datetime-local input. */
const toInput = (t: number) => new Date(t * 1000 - new Date(t * 1000).getTimezoneOffset() * 60000).toISOString().slice(0, 16);

const btn = "rounded-full border border-line px-4 py-2 text-sm hover:border-ink disabled:opacity-40";

/** The upload row of a clip: nothing goes to YouTube without one of these buttons and a confirmation. */
export function ClipUpload({ clip, beforeUpload, onChanged }: { clip: Clip; beforeUpload: () => Promise<void>; onChanged: () => void }) {
  const [yt, setYt] = useState<YouTube | null>(null);
  const [at, setAt] = useState("");
  const [jobId, setJobId] = useState<number | null>(null);
  const [err, setErr] = useState("");
  const job = useJobPoll(jobId);
  const busy = jobId != null && !["done", "failed", "cancelled", "blocked"].includes(job?.status ?? "queued");
  useEffect(() => { api<YouTube>("/api/youtube").then(setYt).catch(() => {}); }, []);
  useEffect(() => { if (job?.status === "done") onChanged(); }, [job?.status]); // eslint-disable-line react-hooks/exhaustive-deps

  const upload = async (mode: "now" | "later") => {
    const picked = mode === "now" ? "now" : at ? new Date(at).getTime() / 1000 : "slot";
    const text = picked === "now" ? "hemen herkese açık yayınlanacak" : picked === "slot"
      ? `sıradaki boş saatte yayınlanacak${yt?.next_slot ? ` (${when(yt.next_slot)})` : ""}` : `${when(picked)} saatinde yayınlanacak`;
    if (!confirm(`Bu klip YouTube'a yüklenecek ve ${text}.\n"Çocuklara özel değil" olarak işaretlenir. Devam edilsin mi?`)) return;
    try {
      setErr("");
      await beforeUpload();
      const r = await api<{ id: number }>(`/api/clips/${clip.id}/upload`, { when: picked });
      setJobId(r.id);
    } catch (x) { setErr((x as Error).message); }
  };

  if (clip.yt_id) return (
    <p className="text-sm">
      YouTube: <a className="underline underline-offset-2" href={`https://youtube.com/shorts/${clip.yt_id}`} target="_blank" rel="noopener noreferrer">yüklendi</a>
      {clip.yt_publish_at ? ` · yayın ${when(clip.yt_publish_at)}` : ""}
    </p>
  );
  if (!yt) return null;
  if (!yt.connected) return <p className="text-sm text-ink-2">YouTube'a yüklemek için <Link to="/panel/ayarlar" className="underline underline-offset-2">Ayarlar'dan bağlan</Link>.</p>;
  return (
    <div className="flex flex-wrap items-center gap-2 border-t border-line pt-3">
      <label className="text-sm text-ink-2" htmlFor="yt-at">Yayın zamanı</label>
      <input id="yt-at" type="datetime-local" value={at} min={toInput(Date.now() / 1000)} onChange={(e) => setAt(e.target.value)}
        className="rounded-xl border border-line bg-raised px-3 py-1.5 text-sm outline-none focus:border-ink" />
      <button onClick={() => upload("later")} disabled={busy} className="rounded-full bg-ink px-4 py-2 text-sm font-semibold text-paper disabled:opacity-40">
        {at ? "Bu saate yükle" : "Sıraya al"}
      </button>
      <button onClick={() => upload("now")} disabled={busy} className={btn}>Şimdi yayınla</button>
      <span className="basis-full text-xs text-mute">Zaman boşsa sıradaki boş saat kullanılır{yt.next_slot ? `: ${when(yt.next_slot)}` : ""}.</span>
      <span role="status" className="basis-full text-sm text-ink-2">
        {busy ? `${job?.status === "running" ? job.msg || "Yükleniyor" : "Sırada bekliyor"}${job?.frac ? ` · %${Math.round(job.frac * 100)}` : ""}` : ""}
      </span>
      {(err || job?.status === "failed") && <span role="alert" className="basis-full text-sm text-danger">{err || job?.error}</span>}
    </div>
  );
}

export function YouTubeSettings() {
  const [yt, setYt] = useState<YouTube | null>(null);
  const [err, setErr] = useState("");
  useEffect(() => {
    const load = () => { api<YouTube>("/api/youtube").then(setYt).catch(() => {}); };
    load();
    window.addEventListener("focus", load);              // consent happens in another tab
    return () => window.removeEventListener("focus", load);
  }, []);
  const connect = async () => {
    try { setErr(""); window.location.href = (await api<{ url: string }>("/api/youtube/connect", {})).url; }
    catch (x) { setErr((x as Error).message); }
  };
  const disconnect = async () => { await api("/api/youtube/disconnect", {}); setYt(await api<YouTube>("/api/youtube")); };
  return (
    <section className="mt-10 border-t border-line pt-6" aria-label="YouTube">
      <h2 className="title text-xl">YouTube</h2>
      {!yt ? <p className="mt-1 text-sm text-ink-2">…</p> : !yt.configured ? (
        <p className="mt-1 text-sm text-ink-2">
          Google Cloud'dan indirdiğin "Masaüstü uygulaması" istemci dosyasını şuraya koy, sonra bu sayfaya dön:
          <code className="mt-1 block break-all">{yt.client_secret}</code>
          Adımlar README'nin "YouTube'a yükleme" bölümünde.
        </p>
      ) : (
        <div className="mt-3 flex flex-wrap items-center gap-3">
          <span>{yt.connected ? `Bağlı${yt.channel ? `: ${yt.channel}` : ""}` : "Bağlı değil"}</span>
          {yt.connected
            ? <button type="button" onClick={disconnect} className={btn}>Bağlantıyı kes</button>
            : <button type="button" onClick={connect} className={btn}>YouTube'a bağlan</button>}
        </div>
      )}
      {err && <p role="alert" className="mt-2 text-sm text-danger">{err}</p>}
    </section>
  );
}
