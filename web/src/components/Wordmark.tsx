export function Wordmark({ size = 28 }: { size?: number }) {
  return (
    <span className="inline-flex items-center gap-2.5">
      <img src="/logo.svg" alt="" width={size} height={size} />
      <span className="title text-[1.1rem]">Kliparya</span>
    </span>
  );
}
