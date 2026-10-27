import { Brain, Footprints, Info, Sparkles } from "lucide-react";
import type { Activities } from "@/lib/memories";
import { pct } from "@/lib/memories";
import { T } from "@/components/T";

const LEVEL = { 1: { vi: "dễ", en: "easy" }, 2: { vi: "vừa", en: "medium" }, 3: { vi: "khó hơn", en: "harder" } } as const;

function Stat({ value, vi, en }: { value: string; vi: string; en: string }) {
  return (
    <div className="flex flex-col rounded-2xl bg-surface-2 px-4 py-3">
      <span className="text-[1.5rem] font-extrabold leading-tight tnum">{value}</span>
      <span className="text-sm text-ink-2">
        <T vi={vi} en={en} />
      </span>
    </div>
  );
}

/** "Hoạt động phòng ngừa": memory games woven into the calls, habit nudges, and what coincided with better days. */
export function PreventionActivities({ a, elderVi, elderEn }: { a: Activities; elderVi: string; elderEn: string }) {
  if (a.sharing_paused) {
    return (
      <p className="text-ink-2">
        <T vi="Đang ẩn vì chia sẻ với gia đình đã tạm dừng." en="Hidden while sharing with the family is paused." />
      </p>
    );
  }
  const g = a.games;
  const trend = g?.trend ?? [];
  const lvl = LEVEL[(g?.current_level ?? 2) as 1 | 2 | 3] ?? LEVEL[2];
  const assoc = (a.associations ?? []).slice(0, 3);
  const imp = a.improve;
  return (
    <div className="flex flex-col gap-5">
      <p className="max-w-[65ch] text-ink-2">
        <T
          vi={`Trong mỗi cuộc gọi, Út Thương lồng một trò chơi trí nhớ nhỏ (nối câu ca dao, kể tên) và một lời nhắc thói quen tốt. Trò chơi tự đổi độ khó để ${elderVi[0].toLowerCase()}${elderVi.slice(1)} không thấy như bị kiểm tra.`}
          en={`Each call weaves in one small memory game (finish a folk verse, name a few things) and one healthy-habit nudge. The game adjusts its difficulty so ${elderEn} never feels tested.`}
        />
      </p>

      {g && (
        <section aria-labelledby="games-h" className="flex flex-col gap-3">
          <h3 id="games-h" className="flex items-center gap-2 font-bold">
            <Brain size={18} className="text-accent" aria-hidden />
            <T vi="Trò chơi trí nhớ" en="Memory games" />
          </h3>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            <Stat value={String(g.played)} vi="lượt chơi" en="games played" />
            <Stat value={pct(g.success_rate_first_4_weeks)} vi="nhớ được, 4 tuần đầu" en="recalled, first 4 weeks" />
            <Stat value={pct(g.success_rate_last_4_weeks)} vi="nhớ được, 4 tuần gần đây" en="recalled, last 4 weeks" />
            <Stat value={`${g.current_level}/3`} vi={`độ khó hiện tại (${lvl.vi})`} en={`current level (${lvl.en})`} />
          </div>
          {trend.length > 1 && (
            <figure className="flex flex-col gap-1">
              <div className="flex h-20 items-end gap-1" role="img" aria-label="Tỉ lệ nhớ được theo tuần / Weekly recall rate">
                {trend.map((w) => (
                  <div
                    key={w.week}
                    className="flex-1 rounded-t-md bg-accent/70"
                    style={{ height: `${Math.max(6, Math.round((w.success_rate ?? 0) * 100))}%` }}
                    title={`Tuần ${w.week} / Week ${w.week}: ${pct(w.success_rate)} · mức ${w.mean_level ?? "–"}`}
                  />
                ))}
              </div>
              <figcaption className="flex justify-between text-xs text-ink-3">
                <span>
                  <T vi="Tuần 1" en="Week 1" />
                </span>
                <span>
                  <T vi="Tỉ lệ nhớ được mỗi tuần" en="Share recalled each week" />
                </span>
                <span>
                  <T vi={`Tuần ${trend.at(-1)?.week}`} en={`Week ${trend.at(-1)?.week}`} />
                </span>
              </figcaption>
            </figure>
          )}
          <p className="text-sm text-ink-3">
            <T vi={a.difficulty_rule_vi ?? ""} en={a.difficulty_rule_en ?? ""} />
            {a.screen_games && a.screen_games.played > 0 && (
              <>
                {" "}
                <T
                  vi={`Thêm ${a.screen_games.played} lượt tự chơi trên màn hình (${pct(a.screen_games.correct_rate)} đúng).`}
                  en={`Plus ${a.screen_games.played} plays on the standing screen (${pct(a.screen_games.correct_rate)} correct).`}
                />
              </>
            )}
          </p>
        </section>
      )}

      {a.nudges && a.nudges.delivered > 0 && (
        <section aria-labelledby="nudges-h" className="flex flex-col gap-3">
          <h3 id="nudges-h" className="flex items-center gap-2 font-bold">
            <Footprints size={18} className="text-accent" aria-hidden />
            <T vi={`Lời nhắc thói quen (${a.nudges.delivered})`} en={`Habit nudges (${a.nudges.delivered})`} />
          </h3>
          <ul className="flex flex-wrap gap-2">
            {a.nudges.by_category.map((n) => (
              <li key={n.category} className="rounded-full border border-line bg-surface px-3 py-1.5 text-sm">
                <T vi={n.label_vi} en={n.label_en} /> <span className="font-semibold tnum">{n.count}</span>
              </li>
            ))}
          </ul>
        </section>
      )}

      {imp && (
        <section aria-labelledby="improve-h" className="flex flex-col gap-2 rounded-2xl bg-accent-tint/60 p-4">
          <h3 id="improve-h" className="flex items-center gap-2 font-bold">
            <Sparkles size={18} className="text-accent" aria-hidden />
            <T vi="Bước Cải thiện: hoạt động trong kế hoạch" en="Improve step: activities in the plan" />
          </h3>
          <p className="text-[0.9375rem]">
            <T vi={imp.label_vi ?? ""} en={imp.label_en ?? ""} />
          </p>
          <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-sm text-ink-2 tnum">
            <dt><T vi="Lời nhắc theo kế hoạch" en="Plan nudges delivered" /></dt>
            <dd className="font-semibold text-ink">{imp.plan_nudges_delivered}</dd>
            <dt><T vi="Tâm trạng TB trước / sau" en="Mean mood before / after" /></dt>
            <dd className="font-semibold text-ink">{imp.mood_before ?? "–"} → {imp.mood_after ?? "–"} /5</dd>
            <dt><T vi="Ngày kể khó ngủ trước / sau" en="Poor-sleep days before / after" /></dt>
            <dd className="font-semibold text-ink">{pct(imp.poor_sleep_before)} → {pct(imp.poor_sleep_after)}</dd>
          </dl>
        </section>
      )}

      {assoc.length > 0 && (
        <section aria-labelledby="assoc-h" className="flex flex-col gap-2">
          <h3 id="assoc-h" className="font-bold">
            <T vi="Đi kèm với ngày hôm sau tốt hơn?" en="Followed by a better next day?" />
          </h3>
          <ul className="flex flex-col divide-y divide-line rounded-2xl border border-line bg-surface">
            {assoc.map((x) => (
              <li key={x.activity} className="flex items-center justify-between gap-3 px-4 py-2.5 text-[0.9375rem]">
                <span>
                  <T vi={x.label_vi} en={x.label_en} />
                  <span className="block text-xs text-ink-3 tnum">
                    <T vi={`${x.days_with} ngày có / ${x.days_without} ngày không`} en={`${x.days_with} days with / ${x.days_without} without`} />
                  </span>
                </span>
                <span className="shrink-0 text-right text-sm tnum">
                  <T vi="tâm trạng hôm sau" en="next-day mood" />{" "}
                  <span className="font-semibold">
                    {x.mood_diff > 0 ? "+" : ""}
                    {x.mood_diff.toFixed(2)}
                  </span>
                </span>
              </li>
            ))}
          </ul>
          <p className="flex items-start gap-2 text-sm text-ink-3">
            <Info size={15} className="mt-0.5 shrink-0" aria-hidden />
            <T vi={a.association_note_vi ?? ""} en={a.association_note_en ?? ""} />
          </p>
        </section>
      )}
    </div>
  );
}
