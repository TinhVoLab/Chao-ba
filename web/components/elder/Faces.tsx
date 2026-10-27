import type { Mood } from "./data";

/** Big, friendly mood faces (self-report only). */
export function Face({ mood }: { mood: Mood }) {
  const fill = mood === "happy" ? "oklch(0.86 0.14 85)" : mood === "neutral" ? "oklch(0.84 0.06 220)" : "oklch(0.8 0.06 280)";
  const mouth = mood === "happy" ? "M34 62 q16 16 32 0" : mood === "neutral" ? "M36 66 h28" : "M34 70 q16 -12 32 0";
  return (
    <svg viewBox="0 0 100 100" aria-hidden width="100%" height="100%">
      <circle cx="50" cy="50" r="46" fill={fill} />
      <circle cx="36" cy="42" r="5.5" fill="oklch(0.26 0.03 60)" />
      <circle cx="64" cy="42" r="5.5" fill="oklch(0.26 0.03 60)" />
      <path d={mouth} stroke="oklch(0.26 0.03 60)" strokeWidth="5.5" fill="none" strokeLinecap="round" />
    </svg>
  );
}
