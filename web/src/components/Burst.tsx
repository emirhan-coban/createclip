import { motion } from "motion/react";

/** One-off lime burst that plays when a job completes. Decorative: hidden from assistive tech. */
export function Burst() {
  const parts = Array.from({ length: 28 }, (_, i) => {
    const a = (i / 28) * Math.PI * 2 + (i % 3) * 0.2, d = 120 + ((i * 53) % 120);
    return { x: Math.cos(a) * d, y: Math.sin(a) * d * 0.7, r: 3 + (i % 4) * 1.5, delay: (i % 5) * 0.02 };
  });
  return (
    <div aria-hidden className="pointer-events-none absolute inset-0 grid place-items-center">
      {parts.map((p, i) => (
        <motion.span key={i} className="absolute rounded-full bg-lime ring-1 ring-ink/70" style={{ width: p.r * 2, height: p.r * 2 }}
          initial={{ x: 0, y: 0, opacity: 1, scale: 0.4 }} animate={{ x: p.x, y: p.y, opacity: 0, scale: 1 }}
          transition={{ duration: 1.1, delay: p.delay, ease: [0.1, 0.8, 0.2, 1] }} />
      ))}
    </div>
  );
}
