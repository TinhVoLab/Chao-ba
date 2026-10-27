"use client";
import type { FamilyMember } from "@/lib/types";
import { hueOf } from "./util";

/**
 * Placeholder family photo: a soft gradient portrait generated from the person's name and relation (the real
 * device shows photos the family uploads). Not a likeness of anyone.
 */
export function Portrait({ member, id, fit = "slice" }: { member: FamilyMember; id: string; fit?: "slice" | "meet" }) {
  const h = hueOf(member.name);
  const older = member.relation === "wife" || member.relation === "husband";
  const longHair = member.relation === "daughter" || member.relation === "granddaughter";
  const bun = member.relation === "wife";
  const skin = `oklch(0.8 0.06 ${55 + (h % 15)})`;
  const hair = older ? "oklch(0.78 0.01 80)" : `oklch(0.3 0.03 ${40 + (h % 30)})`;
  const shirt = `oklch(0.62 0.11 ${h})`;
  return (
    <svg viewBox={fit === "meet" ? "60 0 280 300" : "0 0 400 300"} preserveAspectRatio={fit === "meet" ? "xMidYMax slice" : "xMidYMid slice"} width="100%" height="100%" aria-hidden>
      <defs>
        <linearGradient id={`${id}-bg`} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor={`oklch(0.88 0.06 ${(h + 40) % 360})`} />
          <stop offset="1" stopColor={`oklch(0.7 0.09 ${(h + 10) % 360})`} />
        </linearGradient>
        <radialGradient id={`${id}-sun`} cx="0.78" cy="0.2" r="0.5">
          <stop offset="0" stopColor="oklch(0.97 0.05 90)" stopOpacity="0.9" />
          <stop offset="1" stopColor="oklch(0.97 0.05 90)" stopOpacity="0" />
        </radialGradient>
      </defs>
      <rect width="400" height="300" fill={`url(#${id}-bg)`} />
      <rect width="400" height="300" fill={`url(#${id}-sun)`} />
      {/* leaves at the edge, like a photo taken on the porch */}
      <g fill={`oklch(0.55 0.1 140)`} opacity="0.55">
        <ellipse cx="30" cy="60" rx="34" ry="12" transform="rotate(-30 30 60)" />
        <ellipse cx="22" cy="110" rx="30" ry="10" transform="rotate(20 22 110)" />
        <ellipse cx="380" cy="250" rx="36" ry="12" transform="rotate(-20 380 250)" />
      </g>
      <g transform="translate(200 0)">
        {longHair && <path d="M-62 120 q-6 90 18 140 h88 q24 -50 18 -140 z" fill={hair} />}
        <path d="M-120 300 q0 -86 120 -92 q120 6 120 92 z" fill={shirt} />
        <rect x="-18" y="176" width="36" height="34" rx="12" fill={skin} />
        <ellipse cx="0" cy="134" rx="54" ry="62" fill={skin} />
        {bun && <circle cx="0" cy="66" r="24" fill={hair} />}
        <path
          d={longHair ? "M-58 128 q4 -72 58 -74 q56 2 58 74 q-24 -40 -58 -42 q-36 2 -58 42z" : "M-56 120 q2 -62 56 -64 q54 2 56 64 q-10 -30 -56 -34 q-44 4 -56 34z"}
          fill={hair}
        />
        <path d="M-22 142 q6 4 12 0 M10 142 q6 4 12 0" stroke="oklch(0.3 0.03 50)" strokeWidth="3.5" fill="none" strokeLinecap="round" />
        <path d="M-14 166 q14 10 28 0" stroke="oklch(0.42 0.08 25)" strokeWidth="4" fill="none" strokeLinecap="round" />
      </g>
    </svg>
  );
}

/** Ambient scene between family photos (home at Tết). */
export function MaiScene() {
  return (
    <svg viewBox="0 0 400 300" preserveAspectRatio="xMidYMid slice" width="100%" height="100%" aria-hidden>
      <defs>
        <radialGradient id="mai-warm" cx="0.3" cy="0.3" r="0.9">
          <stop offset="0" stopColor="oklch(0.94 0.07 92)" />
          <stop offset="1" stopColor="oklch(0.8 0.11 70)" />
        </radialGradient>
      </defs>
      <rect width="400" height="300" fill="url(#mai-warm)" />
      <path d="M-10 260 Q120 200 210 150 T420 40" stroke="oklch(0.42 0.06 50)" strokeWidth="9" fill="none" strokeLinecap="round" />
      <path d="M150 182 Q170 230 230 250" stroke="oklch(0.42 0.06 50)" strokeWidth="6" fill="none" strokeLinecap="round" />
      {[
        [90, 215], [160, 175], [235, 130], [300, 95], [360, 62], [205, 240], [120, 160], [270, 160], [330, 125],
      ].map(([x, y], k) => (
        <g key={k} transform={`translate(${x} ${y})`}>
          {[0, 72, 144, 216, 288].map((a) => (
            <ellipse key={a} cx="0" cy="-12" rx="8" ry="12" fill="oklch(0.85 0.16 92)" transform={`rotate(${a})`} />
          ))}
          <circle r="5" fill="oklch(0.62 0.15 55)" />
        </g>
      ))}
    </svg>
  );
}
