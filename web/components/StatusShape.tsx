import type { Light } from "@/lib/types";
import { LIGHT_WORD } from "@/lib/format";
import { T } from "./T";

const FILL: Record<Light, string> = {
  green: "var(--green)",
  yellow: "var(--yellow)",
  red: "var(--red)",
  gray: "var(--gray-tint)",
};
const GLYPH: Record<Light, string> = {
  green: "var(--on-green)",
  yellow: "var(--on-yellow)",
  red: "var(--on-red)",
  gray: "var(--gray-ink)",
};

/**
 * The daily light. Never color alone: each state has its own shape and glyph
 * (circle + check, triangle + !, octagon + !!, dashed circle + …).
 */
export function StatusShape({ light, size = 96, className = "" }: { light: Light; size?: number; className?: string }) {
  const g = GLYPH[light];
  return (
    <svg width={size} height={size} viewBox="0 0 100 100" aria-hidden="true" className={className}>
      {light === "green" && (
        <>
          <circle cx="50" cy="50" r="46" fill={FILL.green} />
          <path d="M30 51 L44 65 L71 37" fill="none" stroke={g} strokeWidth="9" strokeLinecap="round" strokeLinejoin="round" />
        </>
      )}
      {light === "yellow" && (
        <>
          <path d="M50 8 Q54 8 56.5 12.5 L94 80 Q96.5 86 90 88 H10 Q3.5 86 6 80 L43.5 12.5 Q46 8 50 8Z" fill={FILL.yellow} />
          <path d="M50 34 V60" stroke={g} strokeWidth="9" strokeLinecap="round" />
          <circle cx="50" cy="74" r="5.5" fill={g} />
        </>
      )}
      {light === "red" && (
        <>
          <path d="M31 5 H69 L95 31 V69 L69 95 H31 L5 69 V31Z" fill={FILL.red} strokeLinejoin="round" />
          <path d="M39 27 V56 M61 27 V56" stroke={g} strokeWidth="9" strokeLinecap="round" />
          <circle cx="39" cy="71" r="5.5" fill={g} />
          <circle cx="61" cy="71" r="5.5" fill={g} />
        </>
      )}
      {light === "gray" && (
        <>
          <circle cx="50" cy="50" r="44" fill={FILL.gray} stroke="var(--gray)" strokeWidth="4" strokeDasharray="10 8" />
          <circle cx="32" cy="50" r="5.5" fill={g} />
          <circle cx="50" cy="50" r="5.5" fill={g} />
          <circle cx="68" cy="50" r="5.5" fill={g} />
        </>
      )}
    </svg>
  );
}

const TEXT: Record<Light, string> = {
  green: "text-green-ink",
  yellow: "text-yellow-ink",
  red: "text-red-ink",
  gray: "text-gray-ink",
};
const TINT: Record<Light, string> = {
  green: "bg-green-tint",
  yellow: "bg-yellow-tint",
  red: "bg-red-tint",
  gray: "bg-gray-tint",
};
export const lightText = (l: Light) => TEXT[l] ?? TEXT.gray;
export const lightTint = (l: Light) => TINT[l] ?? TINT.gray;

/** Compact light chip: shape + word. */
export function LightChip({ light, className = "" }: { light: Light; className?: string }) {
  const w = LIGHT_WORD[light] ?? LIGHT_WORD.gray;
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-sm font-semibold ${lightTint(light)} ${lightText(light)} ${className}`}>
      <StatusShape light={light} size={16} />
      <T vi={w.vi} en={w.en} />
    </span>
  );
}
