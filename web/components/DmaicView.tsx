"use client";
import { useState } from "react";
import { ArrowDownRight, ArrowUpRight, Minus } from "lucide-react";
import type { DailyLight, Dmaic, DmaicPhase, Light, Metric, PhaseKey } from "@/lib/types";
import { BAD_DIRECTION, METRICS } from "@/lib/types";
import { LIGHT_WORD, METRIC_META, shortDate } from "@/lib/format";
import { T } from "./T";

const PHASES: { key: PhaseKey; letter: string; vi: string; en: string; whatVi: string; whatEn: string }[] = [
  { key: "define", letter: "D", vi: "Xác định", en: "Define", whatVi: "Điều gì thay đổi, mục tiêu là gì", whatEn: "What changed and what the goal is" },
  { key: "measure", letter: "M", vi: "Đo lường", en: "Measure", whatVi: "Xem lại dữ liệu trước và sau", whatEn: "Review the data before and after" },
  { key: "analyze", letter: "A", vi: "Phân tích", en: "Analyze", whatVi: "Tìm nguyên do có thể", whatEn: "Look for likely causes" },
  { key: "improve", letter: "I", vi: "Cải thiện", en: "Improve", whatVi: "Thử một thay đổi cùng bác sĩ, gia đình", whatEn: "Try a change with doctor and family" },
  { key: "control", letter: "C", vi: "Kiểm soát", en: "Control", whatVi: "Giữ kết quả, lập mức nền mới", whatEn: "Hold the gain, set a new baseline" },
];

type Status = "done" | "current" | "upcoming";

const STRIP_C: Record<Light, string> = { gray: "var(--gray)", green: "var(--green)", yellow: "var(--yellow)", red: "var(--red)" };
const STRIP_H: Record<Light, number> = { gray: 4, green: 6, yellow: 11, red: 16 };

export function DmaicView({
  dmaic,
  lights,
  dates,
  elderVi,
  elderEn,
}: {
  dmaic: Dmaic;
  lights: DailyLight[];
  dates: Record<number, string>;
  elderVi: string;
  elderEn: string;
}) {
  const byKey = new Map<PhaseKey, DmaicPhase>((dmaic.phases ?? []).map((p) => [p.phase, p]));
  const has = byKey.size > 0;
  const sortedLights = [...lights].sort((a, b) => a.day - b.day);
  const date = (d: number | null | undefined) => (d != null && dates[d] ? shortDate(dates[d]) : d != null ? `#${d}` : "");

  // Key dates: prefer the API's fields, derive from lights/phases when absent.
  const iv = dmaic.intervention_day ?? null;
  const firstAlert =
    dmaic.first_alert_day ?? sortedLights.find((l) => l.baseline_ready && (l.light === "yellow" || l.light === "red"))?.day ?? null;
  const firstGreen = dmaic.green_day ?? (iv != null ? sortedLights.find((l) => l.day >= iv && l.light === "green")?.day ?? null : null);
  const daysBack = dmaic.days_to_green ?? (iv != null && firstGreen != null ? firstGreen - iv : null);
  const firstOff = firstAlert;

  // Where the loop stands: intervention -> improve/control; alert only -> analyze; otherwise monitoring (control).
  const currentKey: PhaseKey | null = !has
    ? null
    : iv != null
      ? firstGreen != null
        ? "control"
        : "improve"
      : firstAlert != null
        ? "analyze"
        : "control";
  const curIdx = currentKey ? PHASES.findIndex((p) => p.key === currentKey) : -1;
  const status = (i: number): Status => {
    if (!has) return "upcoming";
    const k = PHASES[i].key;
    if (i === curIdx) return "current";
    if (currentKey === "control" && iv == null && k === "improve") return "upcoming"; // nothing needed to improve
    return i < curIdx ? "done" : "upcoming";
  };
  const [sel, setSel] = useState<number>(Math.max(0, curIdx));

  const maxDay = sortedLights.at(-1)?.day ?? 90;
  const minDay = sortedLights[0]?.day ?? 1;
  const span = Math.max(1, maxDay - minDay + 1);
  const effects = METRICS.filter((m) => dmaic.effect?.[m]);
  const selPhase = PHASES[sel];
  const selData = byKey.get(selPhase.key);

  return (
    <div className="flex flex-col gap-8">
      {/* Stepper / loop */}
      <section aria-label="Chu trình DMAIC / DMAIC cycle">
        <ol className="relative grid grid-cols-5">
          {PHASES.map((p, i) => {
            const st = status(i);
            const active = sel === i;
            return (
              <li key={p.key} className="relative flex flex-col items-center">
                {i > 0 && (
                  <span
                    aria-hidden
                    className={`absolute right-1/2 top-7 h-[3px] w-full -translate-y-1/2 ${st === "upcoming" ? "bg-line" : "bg-ink"}`}
                  />
                )}
                <button
                  type="button"
                  onClick={() => setSel(i)}
                  aria-pressed={active}
                  className="relative z-10 flex min-h-11 flex-col items-center gap-1.5 rounded-xl px-1 pb-1"
                >
                  <span
                    className={`grid size-14 place-items-center rounded-full border-[3px] text-xl font-extrabold transition-all duration-200 ${
                      st === "done"
                        ? "border-ink bg-ink text-bg"
                        : st === "current"
                          ? "border-accent bg-accent text-accent-ink"
                          : "border-dashed border-line-strong bg-bg text-ink-3"
                    } ${active ? "ring-4 ring-accent-tint ring-offset-2 ring-offset-bg" : ""}`}
                  >
                    {p.letter}
                  </span>
                  <span className={`text-[0.8125rem] font-semibold leading-tight ${active ? "text-ink" : "text-ink-2"}`}>
                    <T vi={p.vi} en={p.en} />
                  </span>
                  <span className="text-[0.75rem] text-ink-3 tnum">
                    {st === "upcoming" ? <T vi="chưa cần" en="not yet" /> : byKey.get(p.key) ? date(byKey.get(p.key)?.day_from) : ""}
                  </span>
                </button>
              </li>
            );
          })}
        </ol>
        {/* loop-back arrow: Control feeds a new Define when the next change appears */}
        <svg viewBox="0 0 500 34" className="-mt-1 h-8 w-full" preserveAspectRatio="none" aria-hidden>
          <path d="M450 2 V16 Q450 28 438 28 H62 Q50 28 50 16 V8" fill="none" stroke="var(--line-strong)" strokeWidth="2" strokeDasharray="5 5" vectorEffect="non-scaling-stroke" />
          <path d="M44 12 L50 3 L56 12" fill="none" stroke="var(--line-strong)" strokeWidth="2" vectorEffect="non-scaling-stroke" />
        </svg>
        <p className="-mt-1 text-center text-[0.8125rem] text-ink-3">
          <T vi="Vòng lặp: khi có thay đổi mới, chu trình bắt đầu lại từ D" en="A loop: a new change restarts the cycle at D" />
        </p>
      </section>

      {/* Selected phase detail */}
      <section key={sel} className="fade-in rounded-2xl border border-line bg-surface p-5" aria-live="polite">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h2 className="text-xl font-bold">
            <span className="mr-2 text-accent">{selPhase.letter}</span>
            <T vi={selPhase.vi} en={selPhase.en} />
          </h2>
          {selData && status(sel) !== "upcoming" && (
            <span className="text-sm font-medium text-ink-2 tnum">
              <T vi="Ngày" en="Day" /> {selData.day_from ?? "?"}
              {selData.day_to != null && selData.day_to !== selData.day_from ? `–${selData.day_to}` : ""} ·{" "}
              {date(selData.day_from)}
              {selData.day_to != null && selData.day_to !== selData.day_from ? `–${date(selData.day_to)}` : ""}
            </span>
          )}
        </div>
        <p className="mt-1 text-sm text-ink-3">
          <T vi={selPhase.whatVi} en={selPhase.whatEn} />
        </p>
        <p className="mt-3 max-w-[65ch] text-[1.0625rem] leading-relaxed">
          {selData ? (
            <T vi={selData.summary_vi || "–"} en={selData.summary_en || selData.summary_vi || "–"} />
          ) : has ? (
            <T vi="Giai đoạn này chưa bắt đầu." en="This phase hasn't started yet." />
          ) : (
            <T
              vi={`${elderVi} chưa cần chu trình cải thiện nào: đèn vẫn trong khoảng thường ngày. Chu trình tự mở khi đèn vàng kéo dài.`}
              en={`${elderEn} hasn't needed an improvement cycle: the light has stayed within the usual range. A cycle opens automatically when yellow persists.`}
            />
          )}
        </p>
      </section>

      {/* Outcome */}
      {daysBack != null && (
        <section className="flex flex-col gap-1" aria-labelledby="back-h">
          <h2 id="back-h" className="text-sm font-bold uppercase tracking-wide text-ink-3">
            <T vi="Kết quả" en="Outcome" />
          </h2>
          <p className="text-xl leading-snug">
            <T
              vi={
                <>
                  Trở lại <strong className="text-green-ink">xanh</strong> sau{" "}
                  <strong className="text-[2.25rem] font-extrabold tnum">{daysBack}</strong> ngày kể từ khi bắt đầu cải thiện
                </>
              }
              en={
                <>
                  Back to <strong className="text-green-ink">green</strong>{" "}
                  <strong className="text-[2.25rem] font-extrabold tnum">{daysBack}</strong> days after the improvement began
                </>
              }
            />
          </p>
          {firstOff != null && firstGreen != null && (
            <p className="text-ink-2 tnum">
              <T
                vi={`Tổng cộng ${firstGreen - firstOff} ngày không xanh (từ ${date(firstOff)} đến ${date(firstGreen)}). Mức nền mới: ${dmaic.new_baseline_day ? `ngày ${dmaic.new_baseline_day} (${date(dmaic.new_baseline_day)})` : "chưa lập"}.`}
                en={`${firstGreen - firstOff} days off green in total (${date(firstOff)} to ${date(firstGreen)}). New baseline: ${dmaic.new_baseline_day ? `day ${dmaic.new_baseline_day} (${date(dmaic.new_baseline_day)})` : "not yet set"}.`}
              />
            </p>
          )}
        </section>
      )}

      {/* Timeline (Gantt) */}
      {has && (
        <section aria-labelledby="tl-h" className="flex flex-col gap-2">
          <h2 id="tl-h" className="text-sm font-bold uppercase tracking-wide text-ink-3">
            <T vi="Chu trình trên dòng thời gian" en="The cycle on the timeline" />
          </h2>
          <div className="flex flex-col gap-1.5">
            {PHASES.map((p, i) => {
              const ph = byKey.get(p.key);
              const from = ph?.day_from ?? null;
              const to = ph?.day_to ?? from;
              return (
                <div key={p.key} className="grid grid-cols-[5.5rem_1fr] items-center gap-2 text-sm">
                  <span className="font-semibold text-ink-2">
                    <T vi={p.vi} en={p.en} />
                  </span>
                  <div className="relative h-5 rounded bg-surface-2">
                    {from != null && to != null && status(i) !== "upcoming" && (
                      <span
                        className={`absolute inset-y-0 rounded ${status(i) === "current" ? "bg-accent" : "bg-ink"}`}
                        style={{
                          left: `${((from - minDay) / span) * 100}%`,
                          width: `${Math.max(1.2, ((to - from + 1) / span) * 100)}%`,
                        }}
                        title={`${date(from)}–${date(to)}`}
                      />
                    )}
                  </div>
                </div>
              );
            })}
            <div className="grid grid-cols-[5.5rem_1fr] items-end gap-2">
              <span className="text-xs text-ink-3">
                <T vi="Đèn" en="Light" />
              </span>
              <div className="flex h-4 items-end gap-px" aria-hidden>
                {sortedLights.map((l) => (
                  <div key={l.day} className="flex-1 rounded-[1px]" style={{ height: STRIP_H[l.light], background: STRIP_C[l.light] }} title={`${shortDate(l.date)}: ${LIGHT_WORD[l.light].vi}`} />
                ))}
              </div>
            </div>
            <div className="grid grid-cols-[5.5rem_1fr] gap-2 text-xs text-ink-3 tnum">
              <span />
              <div className="flex justify-between">
                <span>{date(minDay)}</span>
                <span>{date(maxDay)}</span>
              </div>
            </div>
          </div>
        </section>
      )}

      {/* Effect table */}
      {effects.length > 0 && (
        <section aria-labelledby="eff-h" className="flex flex-col gap-2">
          <h2 id="eff-h" className="text-sm font-bold uppercase tracking-wide text-ink-3">
            {(() => {
              const f = dmaic.effect[effects[0]] as { pre_window?: [number, number]; post_window?: [number, number] } | undefined;
              const pw = f?.pre_window;
              const qw = f?.post_window;
              return pw && qw ? (
                <T
                  vi={`Hiệu quả can thiệp · trước: ngày ${pw[0]}–${pw[1]}, sau: ngày ${qw[0]}–${qw[1]}`}
                  en={`Intervention effect · pre: days ${pw[0]}–${pw[1]}, post: days ${qw[0]}–${qw[1]}`}
                />
              ) : (
                <T vi="Hiệu quả can thiệp (trước / sau)" en="Intervention effect (pre / post)" />
              );
            })()}
          </h2>
          <div className="overflow-x-auto rounded-2xl border border-line bg-surface">
            <table className="w-full min-w-[22rem] text-[0.9375rem] tnum">
              <thead>
                <tr className="text-left text-sm text-ink-3">
                  <th className="px-4 py-2.5 font-semibold"><T vi="Chỉ số" en="Signal" /></th>
                  <th className="px-2 py-2.5 text-right font-semibold"><T vi="Trước" en="Pre" /></th>
                  <th className="px-2 py-2.5 text-right font-semibold"><T vi="Sau" en="Post" /></th>
                  <th className="px-4 py-2.5 text-right font-semibold"><T vi="Thay đổi" en="Change" /></th>
                </tr>
              </thead>
              <tbody>
                {effects.map((m) => (
                  <EffectRow key={m} m={m} e={dmaic.effect[m]!} />
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </div>
  );
}

function EffectRow({ m, e }: { m: Metric; e: { pre: number | null; post: number | null; change_pct: number | null } }) {
  const meta = METRIC_META[m];
  const pct = e.change_pct;
  const better = pct != null && Math.abs(pct) >= 1 ? Math.sign(pct) === -BAD_DIRECTION[m] : null;
  const Icon = pct == null || Math.abs(pct) < 1 ? Minus : pct > 0 ? ArrowUpRight : ArrowDownRight;
  return (
    <tr className="border-t border-line">
      <th scope="row" className="px-4 py-2.5 text-left font-semibold">
        <T vi={meta.vi} en={meta.en} />
      </th>
      <td className="px-2 py-2.5 text-right text-ink-2">{e.pre != null ? meta.fmt(e.pre) : "–"}</td>
      <td className="px-2 py-2.5 text-right">{e.post != null ? meta.fmt(e.post) : "–"}</td>
      <td className="px-4 py-2.5 text-right">
        <span className={`inline-flex items-center gap-1 font-bold ${better === true ? "text-green-ink" : better === false ? "text-red-ink" : "text-ink-2"}`}>
          <Icon size={16} aria-hidden />
          {pct != null ? `${pct > 0 ? "+" : ""}${pct.toFixed(1)}%` : "–"}
        </span>
        <span className="block text-xs font-medium text-ink-3">
          {better === true ? <T vi="tốt hơn" en="better" /> : better === false ? <T vi="kém hơn" en="worse" /> : <T vi="như cũ" en="unchanged" />}
        </span>
      </td>
    </tr>
  );
}
