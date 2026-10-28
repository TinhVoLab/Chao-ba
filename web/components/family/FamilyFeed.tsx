"use client";
import { useState } from "react";
import { Bell, Bot, CalendarDays, ChevronDown, HandHeart, CalendarSync, Heart, ListChecks, Lock, NotebookPen, PhoneCall, PhoneOff, Rows3 } from "lucide-react";
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
  kudos: Heart,
};

const FILTERS: { key: string; vi: string; en: string; kinds: FeedKind[] | null }[] = [
  { key: "all", vi: "Tất cả", en: "All", kinds: null },
  { key: "people", vi: "Cả nhà", en: "Family", kinds: ["note", "contact", "kudos", "task", "rota", "gap"] },
  { key: "ai", vi: "Út Thương", en: "Út Thương", kinds: ["call", "alert", "event"] },
  { key: "self", vi: "Tự báo", en: "Self-reported", kinds: ["self_report"] },
];

type Entry = { kind: "item"; it: FeedItem } | { kind: "kudos"; actor: string; items: FeedItem[] };

/** Within one day, love notes from the same sender become one row (“Lan gửi má 5 lời thương · má trả lời 3”), placed
 *  where the newest one was. A single note stays a normal row. */
function groupKudos(list: FeedItem[]): Entry[] {
  const out: Entry[] = [];
  const at = new Map<string, number>();
  for (const it of list) {
    if (it.kind !== "kudos" || !it.actor) {
      out.push({ kind: "item", it });
      continue;
    }
    const i = at.get(it.actor);
    if (i == null) {
      at.set(it.actor, out.length);
      out.push({ kind: "kudos", actor: it.actor, items: [it] });
    } else (out[i] as Extract<Entry, { kind: "kudos" }>).items.push(it);
  }
  return out.map((e) => (e.kind === "kudos" && e.items.length === 1 ? { kind: "item", it: e.items[0] } : e));
}

/** "Dòng thời gian chung": AI summaries, notes, calls/visits, alerts, tasks and care events in one feed. */
export function FamilyFeed({ items, fromDate, kinVi, kinEn }: { items: FeedItem[]; fromDate: string | null; kinVi: string; kinEn: string }) {
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
                {groupKudos(list).map((e) =>
                  e.kind === "item" ? (
                    <FeedRow key={e.it.id} it={e.it} />
                  ) : (
                    <KudosGroup key={`kg-${date}-${e.actor}`} actor={e.actor} items={e.items} kinVi={kinVi} kinEn={kinEn} />
                  ),
                )}
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

function KudosGroup({ actor, items, kinVi, kinEn }: { actor: string; items: FeedItem[]; kinVi: string; kinEn: string }) {
  const [open, setOpen] = useState(false);
  const replied = items.filter((i) => i.status === "replied").length;
  const id = `kg-${items[0].id}`;
  return (
    <li data-testid="feed-kudos-group">
      <div className="flex gap-3 px-3.5 py-3">
        <span className="grid size-9 shrink-0 place-items-center rounded-full bg-rose-tint text-rose-ink">
          <Heart size={17} aria-hidden />
        </span>
        <div className="min-w-0 flex-1">
          <p className="font-semibold leading-snug">
            <T
              vi={`${actor} gửi ${kinVi} ${items.length} lời thương${replied ? ` · ${kinVi} trả lời ${replied}` : ""}`}
              en={`${actor} sent ${kinEn} ${items.length} love notes${replied ? ` · ${kinEn} replied to ${replied}` : ""}`}
            />
          </p>
          <button
            type="button"
            aria-expanded={open}
            aria-controls={id}
            onClick={() => setOpen((o) => !o)}
            className="-ml-1 mt-0.5 inline-flex min-h-11 items-center gap-1 rounded-full px-1 text-sm font-semibold text-accent"
          >
            <ChevronDown size={16} className={`transition-transform duration-150 ${open ? "rotate-180" : ""}`} aria-hidden />
            {open ? <T vi="Thu gọn" en="Show less" /> : <T vi="Xem từng lời" en="Show each" />}
          </button>
        </div>
      </div>
      {open && (
        <ul id={id} className="fade-in ml-[3.75rem] mb-2 mr-2 flex flex-col divide-y divide-line rounded-xl bg-surface-2">
          {items.map((it) => (
            <FeedRow key={it.id} it={it} />
          ))}
        </ul>
      )}
    </li>
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
          : it.kind === "kudos"
            ? "bg-rose-tint text-rose-ink"
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
