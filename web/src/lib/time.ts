/** "1:44:50", "44:50", "6290" or "1sa44dk50sn" -> seconds; null when it is not a time. */
export function parseTime(s: string): number | null {
  s = s.trim().toLowerCase().replace(/\s+/g, "");
  if (!s) return null;
  const parts = s.match(/^(?:(\d+)(?:sa|h))?(?:(\d+)(?:dk|m))?(?:(\d+)(?:sn|s)?)?$/);
  if (/[a-z]/.test(s) && parts && (parts[1] || parts[2] || parts[3])) return Number(parts[1] ?? 0) * 3600 + Number(parts[2] ?? 0) * 60 + Number(parts[3] ?? 0);
  if (!/^\d+(:\d{1,2}){0,2}$/.test(s)) return null;
  return s.split(":").reduce((a, p) => a * 60 + Number(p), 0);
}
