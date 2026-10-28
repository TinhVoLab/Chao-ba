// Family page navigation (server-rendered): the "today" strip above the tabs, and the tabs themselves.
// Tabs are plain links driven by ?tab= so they work without JS, can be shared, and keep ?elder= and other params.
import Link from "next/link";
import { CalendarSync, HandHeart, ListChecks, MessageCircleHeart, PhoneCall, Rows3 } from "lucide-react";
import type { KudosList } from "@/lib/kudos";
import type { CareTask, Rota } from "@/lib/types";
import { shortDate } from "@/lib/format";
import { T } from "../T";

export const FAMILY_TABS = [
  { key: "checkin", vi: "Hỏi thăm", en: "Check in", Icon: MessageCircleHeart },
  { key: "care", vi: "Chia việc", en: "Share the care", Icon: CalendarSync },
  { key: "timeline", vi: "Nhật ký", en: "Timeline", Icon: Rows3 },
] as const;
export type FamilyTab = (typeof FAMILY_TABS)[number]["key"];

type Params = Record<string, string | string[] | undefined>;

export function familyTab(raw: string | string[] | undefined): FamilyTab {
  const v = Array.isArray(raw) ? raw[0] : raw;
  return FAMILY_TABS.find((t) => t.key === v)?.key ?? "checkin";
}

/** /family URL for a tab, keeping every other search param (elder, viewer, …). The default tab drops ?tab=. */
export function familyHref(sp: Params, tab: FamilyTab, hash = ""): string {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(sp)) {
    if (k === "tab" || v == null) continue;
    for (const x of Array.isArray(v) ? v : [v]) q.append(k, x);
  }
  if (tab !== "checkin") q.set("tab", tab);
  const s = q.toString();
  return `/family${s ? `?${s}` : ""}${hash}`;
}

export function FamilyTabNav({ sp, active }: { sp: Params; active: FamilyTab }) {
  return (
    <nav aria-label="Mục / Sections" className="rounded-full bg-surface-2 p-1">
      <ul className="grid grid-cols-3 gap-1">
        {FAMILY_TABS.map(({ key, vi, en, Icon }) => {
          const on = key === active;
          return (
            <li key={key} className="min-w-0">
              <Link
                href={familyHref(sp, key)}
                aria-current={on ? "page" : undefined}
                data-testid={`family-tab-${key}`}
                className={`flex min-h-11 items-center justify-center gap-1.5 rounded-full px-1.5 text-sm font-semibold transition-colors duration-150 sm:px-2 sm:text-[0.9375rem] ${
                  on ? "bg-surface text-ink shadow-sm" : "text-ink-2 hover:text-ink"
                }`}
              >
                <Icon size={17} className="hidden shrink-0 sm:block" aria-hidden />
                <span className="truncate">
                  <T vi={vi} en={en} />
                </span>
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}

const addDays = (iso: string, n: number) => {
  const d = new Date(`${iso}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + n);
  return d.toISOString().slice(0, 10);
};

type Chip = {
  key: string;
  href: string;
  Icon: typeof PhoneCall;
  tone: string;
  label: { vi: string; en: string };
  note?: { vi: string; en: string };
};

/** At most three chips: whose turn it is to call (with the overdue note), tasks due within 3 days, new replies from
 *  the elder. A chip with nothing to say is not shown; with no chips the strip disappears. */
export function TodayStrip({
  sp,
  rota,
  tasks,
  kudos,
  kinVi,
  kinEn,
}: {
  sp: Params;
  rota: Rota;
  tasks: CareTask[];
  kudos: KudosList | null;
  kinVi: string;
  kinEn: string;
}) {
  const todayIso = rota.today.date;
  const chips: Chip[] = [];
  const K = kinVi ? kinVi[0].toUpperCase() + kinVi.slice(1) : kinVi;

  // 1. Calls: whose turn, with "nobody called for N days" in the same chip.
  const t = rota.today;
  const overdue = rota.gap.nudge && !t.done;
  const days = rota.gap.days_since ?? rota.gap.threshold;
  const late = overdue ? { vi: `Đã ${days} ngày chưa ai gọi ${kinVi}`, en: `Nobody has called ${kinEn} for ${days} days` } : undefined;
  const turn = rota.mine?.your_turn
    ? { vi: `Hôm nay tới lượt bạn gọi ${kinVi}`, en: `Your turn to call ${kinEn} today` }
    : t.member_name && !t.done
      ? { vi: `Hôm nay tới lượt ${t.member_name} gọi`, en: `${t.member_name}'s turn to call today` }
      : null;
  if (turn || late) {
    chips.push({
      key: "call",
      href: familyHref(sp, "care"),
      Icon: PhoneCall,
      tone: overdue ? "bg-yellow-tint text-yellow-ink" : rota.mine?.your_turn ? "bg-accent text-accent-ink" : "bg-surface-2 text-ink-2",
      label: turn ?? late!,
      note: turn ? late : undefined,
    });
  }

  // 2. Open tasks due within 3 days (overdue ones included).
  const soon = tasks
    .filter((x) => !x.done && x.due_date && x.due_date <= addDays(todayIso, 3))
    .sort((a, b) => (a.due_date ?? "").localeCompare(b.due_date ?? ""));
  if (soon.length) {
    const first = soon[0];
    const late = soon.filter((x) => (x.due_date ?? "") < todayIso).length;
    chips.push({
      key: "tasks",
      href: familyHref(sp, "care"),
      Icon: ListChecks,
      tone: late ? "bg-red-tint text-red-ink" : "bg-surface-2 text-ink-2",
      label:
        soon.length === 1
          ? { vi: "1 việc tới hạn trong 3 ngày", en: "1 task due within 3 days" }
          : { vi: `${soon.length} việc tới hạn trong 3 ngày`, en: `${soon.length} tasks due within 3 days` },
      note: {
        vi: `${first.title_vi} · ${shortDate(first.due_date ?? "")}${late ? ` · ${late} quá hạn` : ""}`,
        en: `${first.title_en} · ${shortDate(first.due_date ?? "")}${late ? ` · ${late} overdue` : ""}`,
      },
    });
  }

  // 3. New replies from the elder to the family's love notes (since yesterday).
  const since = addDays(kudos?.date ?? todayIso, -1);
  const replies = (kudos?.items ?? [])
    .filter((k) => k.status === "replied" && (k.replied_at ?? k.reply?.at ?? "").slice(0, 10) >= since)
    .sort((a, b) => (b.replied_at ?? "").localeCompare(a.replied_at ?? ""));
  if (replies.length) {
    const r = replies[0];
    chips.push({
      key: "kudos",
      href: familyHref(sp, "checkin", "#kudos-h"),
      Icon: HandHeart,
      tone: "bg-rose-tint text-rose-ink",
      label:
        replies.length === 1
          ? { vi: `${K} trả lời ${r.sender_name}`, en: `${kinEn} replied to ${r.sender_name}` }
          : { vi: `${K} trả lời ${replies.length} lời thương`, en: `${kinEn} replied to ${replies.length} love notes` },
      note: r.reply_vi ? { vi: r.reply_vi, en: r.reply_en || r.reply_vi } : undefined,
    });
  }

  if (!chips.length) return null;
  return (
    <section aria-label="Hôm nay / Today" data-testid="family-today">
      <ul className="grid gap-2 sm:grid-cols-3">
        {chips.map((c) => (
          <li key={c.key} className="min-w-0">
            <Link
              href={c.href}
              data-testid={`family-chip-${c.key}`}
              className="flex h-full min-h-11 items-center gap-3 rounded-2xl border border-line bg-surface px-3 py-2.5 transition-colors duration-150 hover:border-line-strong"
            >
              <span className={`grid size-9 shrink-0 place-items-center rounded-full ${c.tone}`}>
                <c.Icon size={18} aria-hidden />
              </span>
              <span className="min-w-0 flex-1">
                <span className="block font-semibold leading-snug">
                  <T vi={c.label.vi} en={c.label.en} />
                </span>
                {c.note && (
                  <span className="block truncate text-sm text-ink-2">
                    <T vi={c.note.vi} en={c.note.en} />
                  </span>
                )}
              </span>
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}
