"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { ChevronLeft, ChevronRight } from "lucide-react";
import type { ElderSummary } from "@/lib/types";
import { StatusShape } from "./StatusShape";
import { LIGHT_WORD } from "@/lib/format";

/**
 * Elder switcher. Each chip shows name + that elder's light (shape, not just color).
 * Phones/tablets: one row that scrolls sideways; the edge with more chips fades out and gets a chevron button, and the
 * current elder is scrolled into view. Desktop (lg): chips wrap. Long names are truncated, full name in `title`.
 */
export function ElderSwitcher({ elders, current, path }: { elders: ElderSummary[]; current: string; path: string }) {
  const ref = useRef<HTMLUListElement>(null);
  const [more, setMore] = useState({ left: false, right: false });

  const measure = useCallback(() => {
    const el = ref.current;
    if (!el) return;
    const left = el.scrollLeft > 4;
    const right = el.scrollLeft + el.clientWidth < el.scrollWidth - 4;
    setMore((m) => (m.left === left && m.right === right ? m : { left, right }));
  }, []);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    // Bring the current elder into view without moving the page vertically.
    const active = el.querySelector<HTMLElement>('[aria-current="page"]');
    if (active && el.scrollWidth > el.clientWidth) {
      const target = active.offsetLeft - (el.clientWidth - active.offsetWidth) / 2;
      el.scrollLeft = Math.max(0, target);
    }
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, [current, measure]);

  const nudge = (dir: 1 | -1) => ref.current?.scrollBy({ left: dir * ref.current.clientWidth * 0.7, behavior: "smooth" });

  return (
    <nav aria-label="Người thân / Family member" className="relative -mx-4">
      <ul
        ref={ref}
        onScroll={measure}
        data-more-left={more.left || undefined}
        data-more-right={more.right || undefined}
        className="hscroll-fade no-scrollbar flex gap-2 overflow-x-auto px-4 lg:flex-wrap"
      >
        {elders.map((e) => {
          const active = e.id === current;
          const w = LIGHT_WORD[e.light] ?? LIGHT_WORD.gray;
          return (
            <li key={e.id} className="shrink-0">
              <Link
                href={`${path}?elder=${encodeURIComponent(e.id)}`}
                aria-current={active ? "page" : undefined}
                scroll={false}
                title={e.display_name}
                className={`flex min-h-12 max-w-[13.5rem] items-center gap-2 rounded-full border py-1.5 pl-1.5 pr-4 transition-colors duration-200 ${
                  active ? "border-ink bg-ink text-bg" : "border-line bg-surface text-ink hover:border-line-strong"
                }`}
              >
                <span className={`grid size-9 shrink-0 place-items-center rounded-full ${active ? "bg-bg/15" : "bg-surface-2"}`}>
                  <StatusShape light={e.light} size={22} />
                </span>
                <span className="flex min-w-0 flex-col leading-tight">
                  <span className="truncate font-semibold">{e.display_name}</span>
                  <span className={`truncate text-xs ${active ? "opacity-80" : "text-ink-3"}`}>
                    <span className="l-vi">{w.vi}</span>
                    <span className="l-en">{w.en}</span>
                  </span>
                </span>
              </Link>
            </li>
          );
        })}
      </ul>
      {more.left && (
        <button
          type="button"
          onClick={() => nudge(-1)}
          className="absolute left-1 top-1/2 grid size-9 -translate-y-1/2 place-items-center rounded-full border border-line bg-surface text-ink-2 shadow-soft"
        >
          <ChevronLeft size={18} aria-hidden />
          <span className="sr-only">Người trước / Previous</span>
        </button>
      )}
      {more.right && (
        <button
          type="button"
          onClick={() => nudge(1)}
          className="absolute right-1 top-1/2 grid size-9 -translate-y-1/2 place-items-center rounded-full border border-line bg-surface text-ink-2 shadow-soft"
        >
          <ChevronRight size={18} aria-hidden />
          <span className="sr-only">Xem thêm người thân / More family members</span>
        </button>
      )}
    </nav>
  );
}
