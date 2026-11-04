import { HeartHandshake } from "lucide-react";
import type { Connection } from "@/lib/types";
import { shortDate } from "@/lib/format";
import { T } from "./T";

/** Weekly family connection (connection.py): who was in touch, how often. Shown beside the health charts, never in the light. */
export function ConnectionCard({ c }: { c: Connection }) {
  if (c.sharing_paused || !c.weeks.length || !c.summary) return null;
  const weeks = c.weeks;
  const max = Math.max(1, ...weeks.map((w) => w.calls_visits + w.micro));
  const h = (n: number) => `${(n / max) * 100}%`;
  const now = c.summary.last_14_days;
  const prev = c.summary.previous_14_days;
  const size = c.summary.circle_size;
  const last = weeks[weeks.length - 1];
  return (
    <section aria-labelledby="conn-h" className="flex flex-col gap-3 rounded-2xl border border-line bg-surface p-4" data-testid="connection">
      <h2 id="conn-h" className="flex items-center gap-2 text-lg font-bold">
        <HeartHandshake size={20} aria-hidden className="text-rose" />
        <T vi="Kết nối gia đình" en="Family connection" />
      </h2>
      <dl className="grid grid-cols-3 gap-2">
        <Stat
          value={`${now.days_in_touch}/14`}
          vi="ngày có người nhà liên lạc"
          en="days someone was in touch"
          was={prev ? `${prev.days_in_touch}/14` : null}
        />
        <Stat value={`${last.members}/${size}`} vi="người ghé tuần này" en="family members this week" />
        <Stat value={String(now.elder_replies)} vi="lượt đáp lại (14 ngày)" en="replies back (14 days)" />
      </dl>
      <figure className="flex flex-col gap-1.5">
        <div className="flex h-28 items-end gap-1" role="img" aria-label={weeks.map((w) => `${shortDate(w.from)}: ${w.calls_visits} + ${w.micro}`).join("; ")}>
          {weeks.map((w) => (
            <div key={w.from} className="flex h-full flex-1 flex-col justify-end gap-px" title={`${shortDate(w.from)}–${shortDate(w.to)}`}>
              <span className="w-full rounded-t-sm bg-rose" style={{ height: h(w.micro) }} />
              <span className="w-full rounded-b-sm bg-accent" style={{ height: h(w.calls_visits) }} />
            </div>
          ))}
        </div>
        <figcaption className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 text-sm text-ink-2">
          <span className="tnum">
            {shortDate(weeks[0].from)} – {shortDate(last.to)}
          </span>
          <span className="flex items-center gap-3">
            <span className="flex items-center gap-1.5">
              <span aria-hidden className="size-2.5 rounded-sm bg-accent" />
              <T vi="Gọi / thăm" en="Calls / visits" />
            </span>
            <span className="flex items-center gap-1.5">
              <span aria-hidden className="size-2.5 rounded-sm bg-rose" />
              <T vi="Ảnh, thiệp yêu thương" en="Photos, love cards" />
            </span>
          </span>
        </figcaption>
      </figure>
      <p className="text-sm text-ink-3">
        <T vi={c.note_vi ?? ""} en={c.note_en ?? ""} />
      </p>
    </section>
  );
}

function Stat({ value, vi, en, was }: { value: string; vi: string; en: string; was?: string | null }) {
  return (
    <div className="flex flex-col gap-0.5 rounded-xl bg-surface-2 p-2.5">
      <dt className="order-2 text-sm leading-snug text-ink-2">
        <T vi={vi} en={en} />
      </dt>
      <dd className="order-1 text-xl font-extrabold leading-none tnum">{value}</dd>
      {was && (
        <span className="order-3 text-xs text-ink-3 tnum">
          <T vi={`2 tuần trước: ${was}`} en={`2 weeks before: ${was}`} />
        </span>
      )}
    </div>
  );
}
