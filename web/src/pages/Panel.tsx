import { useEffect, useMemo, useState } from "react";
import { NavLink, Navigate, Route, Routes } from "react-router-dom";
import { AnimatePresence } from "motion/react";
import { api, dur, size, type Clip, type Config, type State } from "../lib/api";
import { useAppState } from "../lib/useAppState";
import { Poster } from "../components/Poster";
import { ClipDialog } from "../components/ClipDialog";

const NAV = [
  { to: "/panel", label: "Genel bakış", end: true },
  { to: "/panel/klipler", label: "Klipler" },
  { to: "/panel/kanallar", label: "Kanallar" },
  { to: "/panel/ayarlar", label: "Ayarlar" },
];

export default function Panel() {
  const { state, error, refresh } = useAppState();
  return (
    <div className="mx-auto grid w-full max-w-7xl gap-8 px-6 pb-24 pt-6 md:grid-cols-[13rem_1fr]">
      <nav aria-label="Panel" className="-mx-6 flex gap-1 overflow-x-auto px-6 md:sticky md:top-20 md:mx-0 md:h-fit md:flex-col md:overflow-visible md:px-0">
        {NAV.map((n) => (
          <NavLink key={n.to} to={n.to} end={n.end}
            className={({ isActive }) => `shrink-0 whitespace-nowrap rounded-full px-4 py-2 text-[0.95rem] transition ${isActive ? "bg-ink font-semibold text-paper" : "text-ink-2 hover:bg-paper-2"}`}>
            {n.label}
          </NavLink>
        ))}
      </nav>
      <div className="min-w-0">
        {error && <p role="alert" className="mb-4 rounded-xl border border-line bg-raised p-3 text-sm text-danger">Sunucuya ulaşılamıyor: {error}</p>}
        {!state ? <p className="text-ink-2">Yükleniyor…</p> : (
          <Routes>
            <Route index element={<Overview s={state} />} />
            <Route path="klipler" element={<Clips s={state} refresh={refresh} />} />
            <Route path="kanallar" element={<Channels s={state} refresh={refresh} />} />
            <Route path="ayarlar" element={<Settings s={state} refresh={refresh} />} />
            <Route path="*" element={<Navigate to="/panel" replace />} />
          </Routes>
        )}
      </div>
    </div>
  );
}

const live = (c: Clip) => c.status === "done" && c.has_file;

function Overview({ s }: { s: State }) {
  const clips = s.clips.filter(live);
  const running = s.jobs.filter((j) => j.status === "running" || j.status === "queued").length;
  const nums = [
    { v: clips.length, l: "klip hazır" },
    { v: s.sources.length, l: "izlenen kanal" },
    { v: running, l: "çalışan iş" },
  ];
  return (
    <div className="flex flex-col gap-12">
      <div className="flex flex-wrap gap-x-14 gap-y-6">
        {nums.map((n) => (
          <div key={n.l}>
            <div className="display tnum !text-[clamp(3rem,6vw,4.6rem)]">{n.v}</div>
            <div className="mt-1 text-ink-2">{n.l}</div>
          </div>
        ))}
      </div>
      <section aria-label="Son klipler">
        <h2 className="title mb-4 text-2xl">Son klipler</h2>
        {clips.length === 0 ? <p className="text-ink-2">Henüz klip yok. Ana sayfadan bir yayın linki yapıştır.</p> : (
          <div className="-mx-6 flex items-end gap-4 overflow-x-auto px-6 pb-4">
            {clips.slice(0, 8).map((c) => <Poster key={c.id} id={c.id} title={c.title} start={c.start} end={c.end} score={c.score} scale={0.7} />)}
          </div>
        )}
      </section>
      <section aria-label="Son işler">
        <h2 className="title mb-2 text-2xl">Son işler</h2>
        {s.jobs.length === 0 ? <p className="text-ink-2">Henüz iş çalışmadı.</p> : (
          <ul className="m-0 list-none divide-y divide-line p-0">
            {s.jobs.slice(0, 6).map((j) => (
              <li key={j.id} className="flex items-center gap-3 py-3 text-[0.95rem]">
                <span className={`size-2.5 shrink-0 rounded-full ${j.status === "done" ? "bg-lime ring-1 ring-ink/60" : j.status === "running" ? "bg-ink" : "bg-mute"}`} />
                <span className="min-w-0 flex-1 truncate">{j.url ?? "Kanal taraması"}</span>
                <span className="text-ink-2">{({ queued: "sırada", running: "çalışıyor", done: "bitti", failed: "hata", blocked: "engellendi", cancelled: "durduruldu" } as Record<string, string>)[j.status] ?? j.status}</span>
                {j.ended && j.run_started && <span className="tnum text-mute">{dur(j.ended - j.run_started)}</span>}
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}

function Clips({ s, refresh }: { s: State; refresh: () => void }) {
  const [q, setQ] = useState("");
  const [open, setOpen] = useState<number | null>(null);
  const clips = useMemo(() => s.clips.filter(live).filter((c) => `${c.title} ${c.video_title}`.toLowerCase().includes(q.toLowerCase())), [s.clips, q]);
  const cur = s.clips.find((c) => c.id === open);
  return (
    <div>
      <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
        <h1 className="title text-3xl">Klipler</h1>
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Başlıkta ara" aria-label="Başlıkta ara"
          className="w-full max-w-xs rounded-full border border-line bg-raised px-4 py-2.5 outline-none focus:border-ink" />
      </div>
      {clips.length === 0 ? <p className="text-ink-2">{q ? "Eşleşen klip yok." : "Henüz klip yok."}</p> : (
        <div className="grid grid-cols-[repeat(auto-fill,minmax(10.5rem,1fr))] gap-5">
          {clips.map((c) => (
            <div key={c.id} className="[&>button]:!h-auto [&>button]:w-full">
              <Poster id={c.id} title={c.title} start={c.start} end={c.end} score={c.score} onOpen={() => setOpen(c.id)} />
            </div>
          ))}
        </div>
      )}
      <AnimatePresence>{cur && <ClipDialog key={cur.id} clip={cur} onClose={() => setOpen(null)} onChanged={refresh} />}</AnimatePresence>
    </div>
  );
}

function Channels({ s, refresh }: { s: State; refresh: () => void }) {
  const [url, setUrl] = useState("");
  const [err, setErr] = useState("");
  const add = async (e: React.FormEvent) => {
    e.preventDefault();
    try { await api("/api/sources", { url }); setUrl(""); setErr(""); refresh(); } catch (x) { setErr((x as Error).message); }
  };
  return (
    <div className="max-w-2xl">
      <h1 className="title mb-2 text-3xl">Kanallar</h1>
      <p className="mb-6 text-ink-2">Yeni biten yayınlar taranıp klibe çevrilir. İlk eklemede en yeni 3 yayın işlenir.</p>
      <form onSubmit={add} className="flex gap-2">
        <input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="kick.com/kanal ya da youtube.com/@kanal" aria-label="Kanal linki"
          className="min-w-0 flex-1 rounded-full border border-line bg-raised px-4 py-2.5 outline-none focus:border-ink" />
        <button className="rounded-full bg-lime px-5 py-2.5 font-semibold text-lime-ink active:scale-95">Kanal ekle</button>
      </form>
      <p role="alert" className="mt-2 min-h-5 text-sm text-danger">{err}</p>
      <ul className="m-0 mt-2 list-none divide-y divide-line p-0">
        {s.sources.map((x) => (
          <li key={x.id} className="flex items-center gap-3 py-3">
            <span className="min-w-0 flex-1 truncate">{x.url.replace(/^https?:\/\/(www\.)?/, "")}</span>
            <button onClick={async () => { await api("/api/sources/delete", { url: x.url }); refresh(); }} className="text-sm text-danger hover:underline">Çıkar</button>
          </li>
        ))}
      </ul>
      {s.sources.length > 0 && <button onClick={async () => { await api("/api/scan", {}); refresh(); }} className="mt-5 rounded-full border border-line px-5 py-2.5 hover:border-ink">Şimdi tara</button>}
    </div>
  );
}

function Settings({ s, refresh }: { s: State; refresh: () => void }) {
  const c = s.config;
  const [f, setF] = useState({ ...c, hashtags: c.hashtags.join(" ") });
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const set = <K extends keyof typeof f>(k: K, v: (typeof f)[K]) => setF((x) => ({ ...x, [k]: v }));
  const save = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      const r = await api<{ config: Config }>("/api/config", { ...f, hashtags: f.hashtags.split(/\s+/).filter(Boolean) });
      setF({ ...r.config, hashtags: r.config.hashtags.join(" ") });      // show what was actually saved (e.g. "#" added)
      setMsg({ ok: true, text: "Kaydedildi" }); refresh();
    } catch (x) { setMsg({ ok: false, text: (x as Error).message }); }
    setTimeout(() => setMsg(null), 3500);
  };
  const field = "w-full rounded-xl border border-line bg-raised px-3 py-2.5 outline-none focus:border-ink";
  const num = (k: "clips_per_video" | "min_len" | "max_len" | "lead" | "skip_start_min" | "keep_source_days" | "stall_min", label: string, hint?: string) => (
    <label className="block">
      <span className="text-sm text-ink-2">{label}</span>
      <input type="number" value={f[k]} onChange={(e) => set(k, Number(e.target.value))} className={`${field} tnum mt-1`} />
      {hint && <span className="mt-1 block text-xs text-mute">{hint}</span>}
    </label>
  );
  return (
    <form onSubmit={save} className="max-w-2xl">
      <h1 className="title mb-2 text-3xl">Ayarlar</h1>
      <p className="mb-6 text-ink-2">Yeni işlerde varsayılan olarak kullanılır.</p>
      <div className="grid gap-5 sm:grid-cols-2">
        <label className="block sm:col-span-2">
          <span className="text-sm text-ink-2">An bulma yöntemi</span>
          <select value={f.engine} onChange={(e) => set("engine", e.target.value)} className={`${field} mt-1`}>
            <option value="auto">Otomatik (sohbet, olmazsa ses)</option>
            <option value="chat">Sohbet yoğunluğu</option>
            <option value="audio">Ses yüksekliği</option>
            <option value="transcript">Konuşma metni (ClipsAI, deneysel, kurulu olmalı)</option>
          </select>
        </label>
        {num("clips_per_video", "Yayın başına klip", "1–20")}
        {num("skip_start_min", "İlk kaç dakika atlansın", "Açılıştaki kalabalık sohbeti yok sayar")}
        {num("min_len", "En kısa klip (sn)")}
        {num("max_len", "En uzun klip (sn)")}
        {num("lead", "Zirveden kaç sn önce başlasın")}
        <label className="block">
          <span className="text-sm text-ink-2">Yeni kliplerin yerleşimi</span>
          <select value={f.layout} onChange={(e) => set("layout", e.target.value as Config["layout"])} className={`${field} mt-1`}>
            <option value="blur">Bulanık arka plan</option>
            <option value="face">Kamera üstte, oyun altta</option>
          </select>
          <span className="mt-1 block text-xs text-mute">Kamera yüzü bulunamazsa bulanık yerleşim kullanılır.</span>
        </label>
        <label className="block">
          <span className="text-sm text-ink-2">Kamera penceresi yüksekliği</span>
          <select value={String(f.split)} onChange={(e) => set("split", Number(e.target.value))} className={`${field} mt-1`}>
            {[0.5, 0.4, 0.35, 0.3].map((v) => <option key={v} value={v}>%{Math.round(v * 100)} kamera · %{Math.round((1 - v) * 100)} oyun</option>)}
          </select>
        </label>
        <label className="block sm:col-span-2">
          <span className="text-sm text-ink-2">Konuşmaya göre kesim</span>
          <select value={String(f.smart_cut)} onChange={(e) => set("smart_cut", e.target.value === "auto" ? "auto" : e.target.value === "true")} className={`${field} mt-1`}>
            <option value="auto">Otomatik (Whisper modeli indirilmişse)</option>
            <option value="true">Açık</option>
            <option value="false">Kapalı (yalnızca zirve anına göre)</option>
          </select>
          <span className="mt-1 block text-xs text-mute">Klibin cümle ortasında başlayıp bitmesini önler; başlık ve etiketleri konuşmadan çıkarır. Klip başına yarım dakika kadar ekler.</span>
        </label>
        {num("keep_source_days", "Kaynak görüntü kaç gün saklansın", "Düzenlenmiş klipler hariç; 0 = silme")}
        {num("stall_min", "Kaç dk ilerleme yoksa iş durdurulsun", "0 = hiç durdurma")}
        <label className="block">
          <span className="text-sm text-ink-2">Etiketler</span>
          <input value={f.hashtags} onChange={(e) => set("hashtags", e.target.value)} className={`${field} mt-1`} placeholder="#shorts #oyun" />
        </label>
        <label className="block sm:col-span-2">
          <span className="text-sm text-ink-2">Klipler şuraya kaydedilir</span>
          <input value={f.output_dir} onChange={(e) => set("output_dir", e.target.value)} className={`${field} mt-1`} />
          <span className="mt-1 block text-xs text-mute">Şu an: {s.output}</span>
        </label>
        <label className="flex items-center gap-2 sm:col-span-2">
          <input type="checkbox" checked={f.credit} onChange={(e) => set("credit", e.target.checked)} className="size-4 accent-[var(--lime)]" />
          <span>Açıklamaya kaynak yayın bağlantısını ekle</span>
        </label>
      </div>
      <div className="mt-6 flex items-center gap-3">
        <button className="rounded-full bg-lime px-6 py-2.5 font-semibold text-lime-ink active:scale-95">Kaydet</button>
        <span role="status" className={`text-sm ${msg && !msg.ok ? "text-danger" : "text-ink-2"}`}>{msg?.text}</span>
      </div>
      <Storage />
    </form>
  );
}

function Storage() {
  const [u, setU] = useState<{ files: number; bytes: number } | null>(null);
  const [note, setNote] = useState("");
  useEffect(() => { api<{ files: number; bytes: number }>("/api/storage").then(setU).catch(() => {}); }, []);
  const clean = async () => {
    if (!u || !confirm("Düzenleyici için saklanan kaynak görüntüler silinsin mi? Hazır klipler silinmez; düzenlemek istersen kaynak yeniden indirilir ve o klibin kayıtlı düzenlemesi sıfırlanır.")) return;
    const r = await api<{ files: number; bytes: number }>("/api/storage/clean", {});
    setU({ files: 0, bytes: 0 });
    setNote(`${r.files} dosya silindi, ${size(r.bytes)} boşaldı.`);
  };
  return (
    <section className="mt-10 border-t border-line pt-6" aria-label="Depolama">
      <h2 className="title text-xl">Depolama</h2>
      <p className="mt-1 text-sm text-ink-2">Düzenleyici, her klibin çevresindeki kaynak görüntüyü saklar.</p>
      <div className="mt-3 flex flex-wrap items-center gap-3">
        <span className="tnum">{u ? `${u.files} dosya · ${size(u.bytes)}` : "…"}</span>
        <button type="button" onClick={clean} disabled={!u || u.files === 0} className="rounded-full border border-line px-4 py-2 text-sm hover:border-ink disabled:opacity-40">Kaynak dosyalarını temizle</button>
        <span role="status" className="text-sm text-ink-2">{note}</span>
      </div>
    </section>
  );
}
