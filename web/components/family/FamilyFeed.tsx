"use client";
import { useState } from "react";
import { Bell, Bot, CalendarDays, HandHeart, CalendarSync, ListChecks, Lock, NotebookPen, PhoneCall, PhoneOff, Rows3 } from "lucide-react";
import type { FeedItem, FeedKind } from "@/lib/types";
import { longDate } from "@/lib/format";
import { StatusShape } from "../StatusShape";
import { T } from "../T";

const ICON: Record<FeedKind, typeof Bell> = {
  call: Bot,
  note: NotebookPen,
  contact: PhoneCall,
  alert: Bell,
  task: ListChecks,
  event: CalendarDays,
  rota: CalendarSync,
  gap: PhoneOff,
  self_report: HandHeart,
};

const FILTERS: { key: string; vi: string; en: string; kinds: FeedKind[] | null }[] = [
  { key: "all", vi: "Tất cả", en: "All", kinds: null },
  { key: "people", vi: "Cả nhà", en: "Family", kinds: ["note", "contact", "task", "rota", "gap"] },
  { key: "ai", vi: "Út Thương", en: "Út Thương", kinds: ["call", "alert", "event"] },
  { key: "self", vi: "Tự báo", en: "Self-reported", kinds: ["self_report"] },
];

/** "Dòng thời gian chung": AI summaries, notes, calls/visits, alerts, tasks and care events in one feed. */
export function FamilyFeed({ items, fromDate }: { items: FeedItem[]; fromDate: string | null }) {
  const [filter, setFilter] = useState("all");
  const [allDays, setAllDays] = useState(false);
  const kinds = FILTERS.find((f) => f.key === filter)?.kinds;
  const shown = kinds ? items.filter((i) => kinds.includes(i.kind)) : items;
  const byDate = new Map<string, FeedItem[]>();
  for (const it of shown) {
    const k = it.date ?? "";
    byDate.set(k, [...(byDate.get(k) ?? []), it]);
  }

  return (
    <section aria-labelledby="feed-h" className="flex flex-col gap-3">
      <h2 id="feed-h" className="flex items-center gap-2 text-sm font-bold uppercase tracking-wide text-ink-3">
        <Rows3 size={16} aria-hidden />
        <T vi="Dòng thời gian chung" en="Shared timeline" />
      </h2>
      <div role="group" aria-label="Lọc / Filter" className="flex flex-wrap gap-2">
        {FILTERS.map((f) => (
          <button
            key={f.key}
            type="button"
            aria-pressed={filter === f.key}
            onClick={() => setFilter(f.key)}
            className={`min-h-11 rounded-full border px-4 text-[0.9375rem] font-semibold transition-colors duration-150 ${
              filter === f.key ? "border-ink bg-ink text-bg" : "border-line-strong bg-surface text-ink-2 hover:border-ink"
            }`}
          >
            <T vi={f.vi} en={f.en} />
          </button>
        ))}
      </div>
      <ol className="flex flex-col gap-5">
        {[...byDate.entries()].slice(0, allDays ? undefined : 3).map(([date, list]) => {
          const d = longDate(date);
          return (
            <li key={date}>
              <h3 className="mb-1.5 text-sm font-semibold text-ink-2">
                <T vi={d.vi} en={d.en} />
              </h3>
              <ul className="flex flex-col divide-y divide-line rounded-2xl border border-line bg-surface">
                {list.map((it) => (
                  <FeedRow key={it.id} it={it} />
                ))}
              </ul>
            </li>
          );
        })}
      </ol>
      {!allDays && byDate.size > 3 && (
        <button
          type="button"
          onClick={() => setAllDays(true)}
          className="min-h-11 self-start rounded-full border border-line-strong px-4 font-semibold text-ink-2 transition-colors duration-150 hover:border-ink hover:text-ink"
        >
          <T vi={`Xem thêm ${byDate.size - 3} ngày`} en={`Show ${byDate.size - 3} more days`} />
        </button>
      )}
      {allDays && fromDate && (
        <p className="text-sm text-ink-3">
          <T vi={`Hiển thị từ ${longDate(fromDate).vi}.`} en={`Showing from ${longDate(fromDate).en}.`} />
        </p>
      )}
    </section>
  );
}

function FeedRow({ it }: { it: FeedItem }) {
  const Icon = ICON[it.kind] ?? CalendarDays;
  const tone =
    it.kind === "gap" || it.severity === "yellow"
      ? "bg-yellow-tint text-yellow-ink"
      : it.severity === "red"
        ? "bg-red-tint text-red-ink"
        : it.kind === "call"
          ? "bg-accent-tint text-accent"
          : "bg-surface-2 text-ink-2";
  return (
    <li className="flex gap-3 px-3.5 py-3">
      <span className={`grid size-9 shrink-0 place-items-center rounded-full ${tone}`}>
        <Icon size={17} aria-hidden />
      </span>
      <div className="min-w-0 flex-1">
        <p className="flex flex-wrap items-center gap-x-2 font-semibold leading-snug">
          <T vi={it.title_vi} en={it.title_en} />
          {it.kind === "call" && it.light && it.light !== "gray" && <StatusShape light={it.light} size={16} />}
          {it.rehearsal && (
            <span className="rounded-full bg-surface-2 px-2 text-xs font-semibold text-ink-3">
              <T vi="diễn tập" en="rehearsal" />
            </span>
          )}
        </p>
        {(it.text_vi || it.text_en) && (
          <p className={`mt-0.5 text-[0.9375rem] leading-snug ${it.redacted && it.kind === "note" ? "italic text-ink-3" : "text-ink-2"}`}>
            {it.redacted && <Lock size={13} className="mr-1 inline align-[-1px]" aria-hidden />}
            {it.text_lang === "vi" ? (
              <span lang="vi">{it.text_vi}</span>
            ) : (
              <T vi={it.text_vi} en={it.text_en} />
            )}
          </p>
        )}
      </div>
    </li>
  );
}
