"use client";
import { forwardRef } from "react";
import s from "./classes";

export type AvatarState = "idle" | "speaking" | "listening" | "thinking";

/**
 * Út Thương: a warm, non-human companion (a marigold blossom with a kind face), drawn in SVG.
 * idle = slow breathing; speaking = mouth + sound arcs; listening = open eyes and a halo that follows the mic
 * level (CSS variable --lvl set by the parent); thinking = eyes up, three soft dots.
 */
export const Avatar = forwardRef<HTMLDivElement, { state: AvatarState; label?: string; className?: string }>(
  function Avatar({ state, label, className }, ref) {
    const petals = Array.from({ length: 10 }, (_, i) => i * 36);
    return (
      <div ref={ref} className={`${s.avatar} ${className ?? ""}`} data-state={state} role="img" aria-label={label ?? "Út Thương"}>
        <svg viewBox="0 0 200 200" aria-hidden>
          <defs>
            <radialGradient id="ut-body" cx="0.42" cy="0.36" r="0.75">
              <stop offset="0" stopColor="oklch(0.95 0.08 88)" />
              <stop offset="0.6" stopColor="oklch(0.86 0.14 78)" />
              <stop offset="1" stopColor="oklch(0.74 0.16 62)" />
            </radialGradient>
          </defs>
          <circle className={s.avHalo} cx="100" cy="100" r="96" />
          <g className={s.avWaves}>
            <path d="M168 70 q14 30 0 60" />
            <path d="M182 58 q22 42 0 84" />
            <path d="M32 70 q-14 30 0 60" />
            <path d="M18 58 q-22 42 0 84" />
          </g>
          <g className={s.avPetals}>
            {petals.map((a) => (
              <ellipse key={a} cx="100" cy="42" rx="20" ry="30" transform={`rotate(${a} 100 100)`} />
            ))}
          </g>
          <g className={s.avBody}>
            <circle cx="100" cy="100" r="60" fill="url(#ut-body)" />
            <ellipse cx="72" cy="114" rx="10" ry="6" className={s.avCheek} />
            <ellipse cx="128" cy="114" rx="10" ry="6" className={s.avCheek} />
            {/* eyes: smiling arcs, or open dots while listening */}
            <g className={s.avEyesSmile}>
              <path d="M74 98 q9 -10 18 0" />
              <path d="M108 98 q9 -10 18 0" />
            </g>
            <g className={s.avEyesOpen}>
              <circle cx="83" cy="95" r="6.5" />
              <circle cx="117" cy="95" r="6.5" />
            </g>
            <path className={s.avSmile} d="M86 118 q14 13 28 0" />
            <ellipse className={s.avMouth} cx="100" cy="122" rx="11" ry="8" />
          </g>
          <g className={s.avDots}>
            <circle cx="80" cy="176" r="6" />
            <circle cx="100" cy="176" r="6" />
            <circle cx="120" cy="176" r="6" />
          </g>
        </svg>
      </div>
    );
  },
);
