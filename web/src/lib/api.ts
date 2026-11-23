export type Clip = {
  id: number; status: string; score: number; start: number; end: number; title: string; description: string;
  video_title: string; video_url: string; engine: string; error: string | null; has_file: boolean; file: string; created: number;
};
export type Job = {
  id: number; kind: string; status: string; url?: string; frac?: number; msg?: string; error?: string; cancelling?: boolean;
  started: number; run_started?: number; ended?: number; updated?: number; log: string[]; events: number; live?: boolean;
};
export type Source = { id: number; url: string; name: string; added: number; backfill: number };
export type Config = { engine: string; clips_per_video: number; min_len: number; max_len: number; lead: number;
  skip_start_min: number; output_dir: string; hashtags: string[]; credit: boolean;
  smart_cut: "auto" | boolean; layout: "blur" | "face"; split: number; keep_source_days: number; stall_min: number };
export type State = { now: number; jobs: Job[]; clips: Clip[]; sources: Source[]; output: string; config: Config };

export async function api<T = unknown>(path: string, body?: unknown): Promise<T> {
  const r = await fetch(path, body === undefined ? {} : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error((j as { detail?: string; error?: string }).detail || (j as { error?: string }).error || `HTTP ${r.status}`);
  return j as T;
}

export const hms = (s: number) => {
  s = Math.max(0, Math.floor(s));
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
  return (h ? `${h}:${String(m).padStart(2, "0")}` : `${m}`) + `:${String(sec).padStart(2, "0")}`;
};
export const dur = (s: number) => {
  s = Math.max(0, Math.round(s));
  if (s < 60) return `${s} sn`;
  if (s < 3600) return `${Math.floor(s / 60)} dk ${String(s % 60).padStart(2, "0")} sn`;
  return `${Math.floor(s / 3600)} sa ${Math.floor((s % 3600) / 60)} dk`;
};

/** Turns the pipeline's raw error text into something a person can act on; the raw text stays available as detail. */
export function friendlyError(status: string, raw?: string): { title: string; hint: string } {
  const e = raw ?? "";
  if (status === "blocked") return { title: "Platform şu an isteklerimizi engelliyor", hint: "Birkaç saat bekleyip tekrar dene; sık denemek süreyi uzatır." };
  if (status === "cancelled") return { title: "Durduruldu", hint: "Aynı linki yeniden denersen indirilen sohbet saklandığı için kaldığı yerden devam eder." };
  if (/canlı|is_live|live/i.test(e)) return { title: "Bu yayın henüz bitmemiş", hint: "Yayın bittikten sonra tekrar dene; sürerken klip kesilemez." };
  if (/Belirgin bir an/i.test(e)) return { title: "Belirgin bir an bulunamadı", hint: "“İlk X dakikayı atla” değerini düşür ya da yayında sohbet çok azsa ses yüksekliğiyle dene." };
  if (/Unsupported URL|Unable to download webpage|404|Geçerli bir Kick|bilgisi alınamadı/i.test(e))
    return { title: "Bu linkten bir yayın alınamadı", hint: "Kick yayın kaydı (kick.com/kanal/videos/…) ya da bitmiş bir YouTube yayını linki olmalı." };
  return { title: "Bir şey ters gitti", hint: "Aşağıdaki ayrıntıyı kontrol et; sorun sürerse terminalde `autoshorts doctor` çalıştır." };
}

/** Adds https:// to links people paste without it (kick.com/…, youtube.com/…, youtu.be/…). */
export function normalizeUrl(u: string): string {
  u = u.trim();
  return /^(www\.)?(kick\.com|youtube\.com|youtu\.be|m\.youtube\.com)\//i.test(u) ? `https://${u}` : u;
}

export const size = (b: number) => (b >= 1e9 ? `${(b / 1e9).toFixed(1)} GB` : `${Math.max(1, Math.round(b / 1e6))} MB`);
