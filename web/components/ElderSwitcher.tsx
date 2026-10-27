import Link from "next/link";
import type { ElderSummary } from "@/lib/types";
import { StatusShape } from "./StatusShape";
import { LIGHT_WORD } from "@/lib/format";

/** Horizontal elder switcher. Each chip shows name + that elder's light (shape, not just color). */
export function ElderSwitcher({ elders, current, path }: { elders: ElderSummary[]; current: string; path: string }) {
  return (
    <nav aria-label="Người thân / Family member" className="-mx-4 overflow-x-auto px-4 no-scrollbar">
      <ul className="flex gap-2">
        {elders.map((e) => {
          const active = e.id === current;
          const w = LIGHT_WORD[e.light] ?? LIGHT_WORD.gray;
          return (
            <li key={e.id} className="shrink-0">
              <Link
                href={`${path}?elder=${encodeURIComponent(e.id)}`}
                aria-current={active ? "page" : undefined}
                scroll={false}
                className={`flex min-h-12 items-center gap-2 rounded-full border py-1.5 pl-1.5 pr-4 transition-colors duration-200 ${
                  active
                    ? "border-ink bg-ink text-bg"
                    : "border-line bg-surface text-ink hover:border-line-strong"
                }`}
              >
                <span className={`grid size-9 place-items-center rounded-full ${active ? "bg-bg/15" : "bg-surface-2"}`}>
                  <StatusShape light={e.light} size={22} />
                </span>
                <span className="flex flex-col leading-tight">
                  <span className="font-semibold">{e.display_name}</span>
                  <span className={`text-xs ${active ? "opacity-80" : "text-ink-3"}`}>
                    <span className="l-vi">{w.vi}</span>
                    <span className="l-en">{w.en}</span>
                  </span>
                </span>
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
