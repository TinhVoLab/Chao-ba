import Link from "next/link";
import type { ReactNode } from "react";
import { AudioLines, BookOpen, Brain, HeartHandshake, Moon, Pill, Plug, Puzzle, Smile, Stethoscope } from "lucide-react";
import type { BrainContext, BrainContextItem, Light } from "@/lib/types";
import { shortDate } from "@/lib/format";
import { StatusShape } from "./StatusShape";
import { T } from "./T";

type Copy = { vi: string; en: string };
const LABEL: Record<BrainContextItem["key"], Copy> = {
  recall: { vi: "Nhớ lại chuyện đã kể", en: "Story recall" },
  speech_rate: { vi: "Tốc độ nói", en: "Speech rate" },
  sleep: { vi: "Kể ngủ không ngon", en: "Poor sleep mentioned" },
  mood: { vi: "Nghe buồn, mệt", en: "Sounded low or tired" },
  symptoms: { vi: "Kể chuyện sức khỏe", en: "Symptoms mentioned" },
  medication: { vi: "Uống thuốc (bấm trên màn hình)", en: "Medication (screen taps)" },
  connection: { vi: "Kết nối gia đình", en: "Family connection" },
  games: { vi: "Trò chơi trí nhớ", en: "Memory games" },
};
const ICON: Record<BrainContextItem["key"], typeof Brain> = {
  recall: BookOpen,
  speech_rate: AudioLines,
  sleep: Moon,
  mood: Smile,
  symptoms: Stethoscope,
  medication: Pill,
  connection: HeartHandshake,
  games: Puzzle,
};
const MISSING: Record<NonNullable<BrainContextItem["reason"]>, Copy> = {
  no_baseline: { vi: "Chưa đủ cuộc gọi để biết mức thường ngày.", en: "Not enough calls yet to know the usual level." },
  no_calls: { vi: "Chưa có cuộc gọi trong khoảng này.", en: "No calls in this period." },
  voice_metrics_off: { vi: "Đo giọng nói đang tắt (quyền riêng tư).", en: "Speech measures are switched off (privacy)." },
  no_medications: { vi: "Hồ sơ chưa có thuốc nào.", en: "No medication in the profile." },
  not_logged: { vi: "Chưa có lần bấm nào trên màn hình trong khoảng này.", en: "No taps on the screen in this period." },
  no_data: { vi: "Chưa có dữ liệu.", en: "No data yet." },
};
const LIGHT_NAME: Record<Light, Copy> = {
  green: { vi: "xanh", en: "green" },
  yellow: { vi: "vàng", en: "yellow" },
  red: { vi: "đỏ", en: "red" },
  gray: { vi: "xám", en: "gray" },
};

/** What the item shows: a headline value, a comparison line and (for chart signals) whether the light flagged it. */
function describe(it: BrainContextItem, n: number): { value: Copy; compare?: Copy; status?: Copy & { flagged: boolean } } {
  const before = (x: number | null | undefined, unit: Copy): Copy | undefined =>
    x == null ? undefined : { vi: `${n} ngày trước đó: ${x} ${unit.vi}`, en: `${n} days before: ${x} ${unit.en}` };
  const flagged = (d?: number) =>
    d
      ? { vi: `Đèn đã báo thay đổi ${d} ngày`, en: `The light flagged a change on ${d} day${d > 1 ? "s" : ""}`, flagged: true }
      : { vi: "Trong mức thường ngày", en: "Within the usual range", flagged: false };
  const days: Copy = { vi: "ngày", en: "days" };
  switch (it.key) {
    case "recall":
      return {
        value: { vi: `${it.free}/${it.asked} cuộc gọi nhớ đầy đủ`, en: `${it.free} of ${it.asked} calls with full recall` },
        compare:
          it.usual == null
            ? undefined
            : { vi: `Thường khoảng ${it.usual}/${it.asked}, không cần gợi ý`, en: `Usually about ${it.usual} of ${it.asked}, without hints` },
        status: flagged(it.flagged_days),
      };
    case "speech_rate": {
      const pct = it.change_pct ?? 0;
      return {
        value:
          pct === 0
            ? { vi: "Như thường ngày", en: "Same as usual" }
            : it.direction === "slower"
              ? { vi: `Chậm hơn ${pct}%`, en: `${pct}% slower` }
              : { vi: `Nhanh hơn ${pct}%`, en: `${pct}% faster` },
        compare: {
          vi: `${it.mean} âm tiết/giây, thường ngày ${it.usual}`,
          en: `${it.mean} syllables/s, usual ${it.usual}`,
        },
        status: flagged(it.flagged_days),
      };
    }
    case "sleep":
      return { value: { vi: `${it.days} ngày`, en: `${it.days} day${it.days === 1 ? "" : "s"}` }, compare: before(it.prev, days) };
    case "mood": {
      const c = it.checkins;
      const self: Copy | undefined = c
        ? { vi: ` · Tự chọn: vui ${c.happy}, bình thường ${c.neutral}, buồn ${c.sad}`, en: ` · Self check-ins: happy ${c.happy}, okay ${c.neutral}, sad ${c.sad}` }
        : undefined;
      const b = before(it.prev, days);
      return {
        value: { vi: `${it.low_days} ngày`, en: `${it.low_days} day${it.low_days === 1 ? "" : "s"}` },
        compare: b || self ? { vi: `${b?.vi ?? ""}${self?.vi ?? ""}`.replace(/^ · /, ""), en: `${b?.en ?? ""}${self?.en ?? ""}`.replace(/^ · /, "") } : undefined,
      };
    }
    case "symptoms": {
      const top = it.top ?? [];
      const names: Copy = { vi: top.map((s) => s.label_vi).join(", "), en: top.map((s) => s.label_en).join(", ") };
      const b = before(it.prev, days);
      return {
        value: { vi: `${it.days} ngày`, en: `${it.days} day${it.days === 1 ? "" : "s"}` },
        compare: top.length
          ? { vi: `${names.vi}${b ? ` · ${b.vi}` : ""}`, en: `${names.en}${b ? ` · ${b.en}` : ""}` }
          : b,
      };
    }
    case "medication":
      return {
        value: { vi: `${it.taken_days}/${it.answered_days} ngày đã uống`, en: `Taken on ${it.taken_days} of ${it.answered_days} days` },
        compare: before(it.prev_taken_days, { vi: "ngày đã uống", en: "days taken" }),
      };
    case "connection":
      return {
        value: { vi: `${it.days_in_touch}/${n} ngày có người nhà liên lạc`, en: `Someone in touch on ${it.days_in_touch} of ${n} days` },
        compare: before(it.prev, days),
      };
    case "games":
      return {
        value: { vi: `${it.plays} lượt · ${it.days_played} ngày`, en: `${it.plays} plays · ${it.days_played} days` },
        compare: { vi: "Để vui, không chấm điểm", en: "For fun, never scored" },
      };
  }
}

/**
 * Brain-health context (brain_context.py): the signals Chào Bà already records, beside the light, for 14 or 28 days.
 * Not a score and not a diagnosis; each row says whether the light uses it. Hidden while sharing is paused.
 */
export function BrainContextCard({ c, elderId }: { c: BrainContext; elderId: string }) {
  if (c.sharing_paused || !c.items.length) return null;
  const n = c.days;
  const tab = (d: 14 | 28): ReactNode => (
    <Link
      key={d}
      href={`/trends?elder=${encodeURIComponent(elderId)}&window=${d}`}
      scroll={false}
      aria-current={d === n ? "true" : undefined}
      className={`inline-flex min-h-11 items-center rounded-xl px-3.5 text-[0.9375rem] font-semibold ${
        d === n ? "bg-ink text-bg" : "border border-line-strong bg-surface text-ink"
      }`}
    >
      <T vi={`${d} ngày`} en={`${d} days`} />
    </Link>
  );
  return (
    <section aria-labelledby="brain-h" className="flex flex-col gap-3 rounded-2xl border border-line bg-surface p-4" data-testid="brain-context">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 id="brain-h" className="flex items-center gap-2 text-lg font-bold">
          <Brain size={20} aria-hidden className="text-accent" />
          <T vi="Bối cảnh sức khỏe não bộ" en="Brain-health context" />
        </h2>
        <nav aria-label="Khoảng thời gian / Period" className="flex gap-2">
          {tab(14)}
          {tab(28)}
        </nav>
      </div>
      {c.light && (
        <div className="flex flex-col gap-1.5 rounded-xl bg-surface-2 p-3">
          <p className="text-sm text-ink-2">
            <T
              vi={`Đèn tín hiệu ${n} ngày qua${c.from && c.to ? ` (${shortDate(c.from)} – ${shortDate(c.to)})` : ""}`}
              en={`Daily light, last ${n} days${c.from && c.to ? ` (${shortDate(c.from)} – ${shortDate(c.to)})` : ""}`}
            />
          </p>
          <ul className="flex flex-wrap gap-x-4 gap-y-1">
            {(["green", "yellow", "red", "gray"] as const).map((l) => (
              <li key={l} className="flex items-center gap-1.5 text-[0.9375rem] tnum">
                <StatusShape light={l} size={18} />
                <span className="font-bold">{c.light!.counts[l]}</span>
                <T vi={`ngày ${LIGHT_NAME[l].vi}`} en={`${LIGHT_NAME[l].en} day${c.light!.counts[l] === 1 ? "" : "s"}`} />
              </li>
            ))}
          </ul>
        </div>
      )}
      <ul className="grid grid-cols-1 gap-2 sm:grid-cols-2">
        {c.items.map((it) => {
          const Icon = ICON[it.key];
          const d = it.available ? describe(it, n) : null;
          return (
            <li key={it.key} className="flex flex-col gap-1 rounded-xl bg-surface-2 p-3" data-testid={`brain-${it.key}`}>
              <div className="flex items-start justify-between gap-2">
                <span className="flex items-center gap-2 font-semibold">
                  <Icon size={18} aria-hidden className="shrink-0 text-ink-3" />
                  <T vi={LABEL[it.key].vi} en={LABEL[it.key].en} />
                </span>
                <span className="shrink-0 rounded-full border border-line px-2 py-0.5 text-xs text-ink-3">
                  {it.in_light ? <T vi="Đèn có dùng" en="Used by the light" /> : <T vi="Không tính vào đèn" en="Not in the light" />}
                </span>
              </div>
              {d ? (
                <>
                  <p className="text-base font-bold tnum">
                    <T vi={d.value.vi} en={d.value.en} />
                  </p>
                  {d.compare && (
                    <p className="text-sm text-ink-2 tnum">
                      <T vi={d.compare.vi} en={d.compare.en} />
                    </p>
                  )}
                  {d.status && (
                    <p className={`text-sm ${d.status.flagged ? "font-semibold text-ink" : "text-ink-3"}`}>
                      <T vi={d.status.vi} en={d.status.en} />
                    </p>
                  )}
                </>
              ) : (
                <p className="text-sm text-ink-3">
                  <T vi={MISSING[it.reason ?? "no_data"].vi} en={MISSING[it.reason ?? "no_data"].en} />
                </p>
              )}
            </li>
          );
        })}
      </ul>
      <p className="text-sm text-ink-3">
        <T vi={c.note_vi} en={c.note_en} />
      </p>
      <p className="flex items-start gap-2 border-t border-line pt-3 text-sm text-ink-2" data-testid="brain-future">
        <Plug size={16} aria-hidden className="mt-0.5 shrink-0" />
        <T vi={c.future_vi} en={c.future_en} />
      </p>
    </section>
  );
}
