"use client";
import { useMemo, useState } from "react";
import {
  Area,
  CartesianGrid,
  ComposedChart,
  Line,
  ReferenceArea,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { MessageCircle, Pill, RotateCcw, Stethoscope, CalendarDays, HeartHandshake } from "lucide-react";
import type { DailyLight, Light, Metric, Timeline, TimelineEvent } from "@/lib/types";
import { BAD_DIRECTION } from "@/lib/types";
import { LIGHT_WORD, METRIC_META, longDate, shortDate } from "@/lib/format";
import { useLang } from "@/lib/useLang";
import { chartEvents, isRebaseline } from "@/lib/normalize";
import { StatusShape } from "./StatusShape";
import { T } from "./T";

const CHART_METRICS: Metric[] = ["speech_rate_sps", "pause_ratio", "mattr", "recall_score"];
const Y_W = 44;
const M_RIGHT = 12;
const SCALE_FLOOR: Record<Metric, number> = {
  speech_rate_sps: 0.15,
  pause_ratio: 0.015,
  filled_pause_rate: 0.006,
  mattr: 0.015,
  recall_score: 0.35,
};

const EVENT_ICON: Record<string, typeof Pill> = {
  medication_change: Pill,
  doctor_visit: Stethoscope,
  care_plan: HeartHandshake,
  rebaseline: RotateCcw,
  new_baseline: RotateCcw,
  symptom_report: MessageCircle,
};

type Band = { center: number; scale: number };

function stats(values: number[], m: Metric): Band | null {
  if (values.length < 5) return null;
  const mean = values.reduce((a, b) => a + b, 0) / values.length;
  const sd = Math.sqrt(values.reduce((a, b) => a + (b - mean) ** 2, 0) / Math.max(1, values.length - 1));
  return { center: mean, scale: Math.max(sd, SCALE_FLOOR[m]) };
}

interface Row {
  day: number;
  date: string;
  light: Light | null;
  value: number | null;
  avg: number | null;
  band: [number, number] | null;
  center: number | null;
}

type Run = { from: number; to: number; light: "yellow" | "red" };
const LIGHT_EVENT_TYPES = new Set(["alert_yellow", "alert_red", "recovered"]);
const LIGHT_OF_EVENT: Record<string, Light> = { alert_yellow: "yellow", alert_red: "red", recovered: "green" };

export function TrendsView({ timeline }: { timeline: Timeline }) {
  const lang = useLang();
  // 90 days by default: the whole story (change, action, recovery, new baseline) is visible at once.
  const [range, setRange] = useState<30 | 90>(90);
  const records = useMemo(() => [...(timeline.records ?? [])].sort((a, b) => a.day - b.day), [timeline.records]);
  const lightByDay = useMemo(() => {
    const m = new Map<number, DailyLight>();
    for (const l of timeline.lights ?? []) m.set(l.day, l);
    return m;
  }, [timeline.lights]);
  const events = useMemo(() => chartEvents(timeline.events), [timeline.events]);
  const rebaseDay = events.filter(isRebaseline).at(-1)?.day ?? null;
  // Contiguous yellow / red runs, shaded behind every chart so the alert period reads at a glance.
  const runs = useMemo(() => {
    const out: Run[] = [];
    for (const l of [...(timeline.lights ?? [])].sort((a, b) => a.day - b.day)) {
      if (l.light !== "yellow" && l.light !== "red") continue;
      const last = out.at(-1);
      if (last && last.light === l.light && l.day === last.to + 1) last.to = l.day;
      else out.push({ from: l.day, to: l.day, light: l.light });
    }
    return out;
  }, [timeline.lights]);

  const maxDay = records.at(-1)?.day ?? 0;
  const minDay = Math.max(records[0]?.day ?? 1, maxDay - range + 1);
  const shown = records.filter((r) => r.day >= minDay);
  const shownEvents = events.filter((e) => e.day >= minDay && e.day <= maxDay);
  const shownRuns = runs.filter((r) => r.to >= minDay).map((r) => ({ ...r, from: Math.max(r.from, minDay) }));
  const lightEvents = (timeline.events ?? []).filter((e) => LIGHT_EVENT_TYPES.has(e.type) && e.day >= minDay && e.day <= maxDay);
  const listed = [...shownEvents, ...lightEvents].sort((a, b) => a.day - b.day || (LIGHT_EVENT_TYPES.has(a.type) ? 1 : -1));
  // one number per day within the visible range: events on the same day share a marker
  const shownDays = [...new Set(shownEvents.map((e) => e.day))];
  const eventNo = new Map(shownEvents.map((e) => [e, shownDays.indexOf(e.day) + 1]));

  const dateOf = useMemo(() => new Map(records.map((r) => [r.day, r.date])), [records]);

  // Baselines: the API's history (`baselines`) says which baseline judged each day. The first one also covers the
  // days it was estimated from. Older snapshots without the history fall back to a client-side estimate.
  const segs = useMemo(() => timeline.baselines ?? [], [timeline.baselines]);
  const bands = useMemo(() => {
    const out = {} as Record<Metric, { early: Band | null; current: Band | null }>;
    for (const m of CHART_METRICS) {
      const api = timeline.baseline?.[m];
      const early = stats(
        records.filter((r) => r.day <= (records[0]?.day ?? 1) + 20).map((r) => r[m]).filter((v): v is number => v != null),
        m,
      );
      out[m] = { early: rebaseDay ? early : api ?? early, current: api ?? early };
    }
    return out;
  }, [records, timeline.baseline, rebaseDay]);

  const series = useMemo(() => {
    const out = {} as Record<Metric, Row[]>;
    for (const m of CHART_METRICS) {
      const rows: Row[] = [];
      for (const r of records) {
        const win = records.filter((x) => x.day > r.day - 7 && x.day <= r.day && x[m] != null).map((x) => x[m] as number);
        let b: Band | null;
        if (segs.length) {
          const sg = segs.find((x) => r.day >= x.from_day && r.day <= x.to_day) ?? (r.day < segs[0].from_day ? segs[0] : segs.at(-1));
          b = sg?.metrics?.[m] ?? null;
        } else {
          b = rebaseDay && r.day < rebaseDay ? bands[m].early : bands[m].current;
        }
        rows.push({
          day: r.day,
          date: r.date,
          light: lightByDay.get(r.day)?.light ?? null,
          value: r[m],
          avg: win.length >= 3 ? win.reduce((a, c) => a + c, 0) / win.length : null,
          band: b ? [b.center - b.scale, b.center + b.scale] : null,
          center: b ? b.center : null,
        });
      }
      out[m] = rows;
    }
    return out;
  }, [records, bands, lightByDay, rebaseDay, segs]);

  // Recall is a 0–3 score, so it is summarised as counts of days, never as a percentage change:
  // "recalled without a cue on 2 of the last 7 measured days (usually 6/7)".
  const recall = useMemo(() => {
    const isFree = (v: number | null) => v != null && v >= 3;
    const recent = records.filter((r) => r.day > maxDay - 7 && r.recall_score != null);
    if (!recent.length) return null;
    const win = segs.at(-1)?.window ?? [records[0]?.day ?? 1, (records[0]?.day ?? 1) + 20];
    const base = records.filter((r) => r.day >= win[0] && r.day <= win[1] && r.recall_score != null);
    const n = recent.length;
    return {
      hits: recent.filter((r) => isFree(r.recall_score)).length,
      n,
      usual: base.length >= 5 ? Math.round((base.filter((r) => isFree(r.recall_score)).length / base.length) * n) : null,
    };
  }, [records, segs, maxDay]);

  const ticks = useMemo(() => {
    const step = range === 30 ? 7 : 21;
    const t: number[] = [];
    for (let d = maxDay; d >= minDay; d -= step) t.unshift(d);
    return t;
  }, [range, minDay, maxDay]);

  if (!records.length) {
    return (
      <p className="rounded-2xl bg-surface-2 p-5 text-ink-2">
        <T vi="Chưa có cuộc gọi nào để vẽ xu hướng. Sau cuộc gọi đầu tiên, biểu đồ sẽ hiện ở đây." en="No calls yet. Trends appear here after the first call." />
      </p>
    );
  }

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div role="radiogroup" aria-label={lang === "en" ? "Time range" : "Khoảng thời gian"} className="inline-flex rounded-full border border-line-strong bg-surface p-1">
          {([30, 90] as const).map((r) => (
            <button
              key={r}
              type="button"
              role="radio"
              aria-checked={range === r}
              onClick={() => setRange(r)}
              className={`min-h-10 rounded-full px-4 text-[0.9375rem] font-semibold transition-colors duration-150 ${
                range === r ? "bg-ink text-bg" : "text-ink-2 hover:text-ink"
              }`}
            >
              <T vi={`${r} ngày`} en={`${r} days`} />
            </button>
          ))}
        </div>
        <Legend />
      </div>

      {listed.length > 0 && (
        <ol className="flex flex-col gap-1.5 text-[0.9375rem]" aria-label={lang === "en" ? "What happened" : "Diễn biến"}>
          {listed.map((e) => {
            const lightEv = LIGHT_OF_EVENT[e.type];
            const Icon = EVENT_ICON[e.type] ?? CalendarDays;
            return (
              <li key={`${e.day}-${e.type}`} className="flex items-center gap-2.5">
                {lightEv ? (
                  <span className="grid size-6 shrink-0 place-items-center">
                    <StatusShape light={lightEv} size={16} />
                  </span>
                ) : (
                  <span className="grid size-6 shrink-0 place-items-center rounded-full border border-ink-2 text-xs font-bold tnum">{eventNo.get(e)}</span>
                )}
                {lightEv ? <span className="w-4 shrink-0" aria-hidden /> : <Icon size={16} className="shrink-0 text-ink-3" aria-hidden />}
                <span className="w-11 shrink-0 text-ink-3 tnum">{shortDate(dateOf.get(e.day) ?? "")}</span>
                <span className={lightEv ? "text-ink-2" : "font-medium"}>
                  <T vi={e.label_vi} en={e.label_en} />
                </span>
              </li>
            );
          })}
        </ol>
      )}

      <div className="grid gap-x-8 gap-y-8 lg:grid-cols-2">
        {CHART_METRICS.map((m) => (
          <MetricChart
            key={m}
            metric={m}
            rows={series[m].filter((r) => r.day >= minDay)}
            minDay={minDay}
            maxDay={maxDay}
            ticks={ticks}
            events={shownEvents}
            runs={shownRuns}
            eventNo={eventNo}
            dateOf={dateOf}
            lang={lang}
            recall={m === "recall_score" ? recall : null}
          />
        ))}
      </div>

      <details className="group rounded-2xl border border-line bg-surface">
        <summary className="flex min-h-12 cursor-pointer items-center px-4 font-semibold">
          <T vi="Xem dạng bảng" en="View as table" />
        </summary>
        <div className="max-h-96 overflow-auto border-t border-line">
          <table className="w-full text-sm tnum">
            <thead className="sticky top-0 bg-surface text-left text-ink-3">
              <tr>
                <th className="px-3 py-2 font-semibold"><T vi="Ngày" en="Date" /></th>
                <th className="px-3 py-2 font-semibold"><T vi="Đèn" en="Light" /></th>
                {CHART_METRICS.map((m) => (
                  <th key={m} className="px-3 py-2 font-semibold">
                    <T vi={METRIC_META[m].vi} en={METRIC_META[m].en} />
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {[...shown].reverse().map((r) => {
                const l = lightByDay.get(r.day)?.light ?? "gray";
                return (
                  <tr key={r.day} className="border-t border-line">
                    <td className="px-3 py-1.5">{shortDate(r.date)}</td>
                    <td className="px-3 py-1.5">
                      <span className="inline-flex items-center gap-1.5">
                        <StatusShape light={l} size={14} />
                        <T vi={LIGHT_WORD[l].vi} en={LIGHT_WORD[l].en} />
                      </span>
                    </td>
                    {CHART_METRICS.map((m) => (
                      <td key={m} className="px-3 py-1.5">
                        {r[m] != null ? METRIC_META[m].fmt(r[m] as number) : !r.answered ? <T vi="không bắt máy" en="no answer" /> : "–"}
                      </td>
                    ))}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </details>
    </div>
  );
}

function Legend() {
  return (
    <ul className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[0.8125rem] text-ink-2">
      <li className="flex items-center gap-1.5">
        <svg width="22" height="10" aria-hidden>
          <line x1="0" y1="5" x2="22" y2="5" stroke="var(--ink)" strokeWidth="2" />
        </svg>
        <T vi="Trung bình 7 ngày" en="7-day average" />
      </li>
      <li className="flex items-center gap-1.5">
        <svg width="10" height="10" aria-hidden>
          <circle cx="5" cy="5" r="2.5" fill="var(--ink-3)" />
        </svg>
        <T vi="Từng ngày" en="Daily" />
      </li>
      <li className="flex items-center gap-1.5">
        <span className="inline-block h-3 w-5 rounded-sm" style={{ background: "var(--band)" }} aria-hidden />
        <T vi="Khoảng thường ngày (nền ± 1 độ lệch)" en="Usual range (baseline ± 1 SD)" />
      </li>
      <li className="flex items-center gap-1.5">
        <span className="inline-flex h-3 w-5 overflow-hidden rounded-sm" aria-hidden>
          <span className="flex-1" style={{ background: "var(--yellow)", opacity: 0.45 }} />
          <span className="flex-1" style={{ background: "var(--red)", opacity: 0.4 }} />
        </span>
        <T vi="Giai đoạn đèn vàng / đỏ" en="Yellow / red period" />
      </li>
    </ul>
  );
}

function MetricChart({
  metric,
  rows,
  minDay,
  maxDay,
  ticks,
  events,
  runs,
  eventNo,
  dateOf,
  lang,
  recall,
}: {
  metric: Metric;
  rows: Row[];
  minDay: number;
  maxDay: number;
  ticks: number[];
  events: TimelineEvent[];
  runs: Run[];
  eventNo: Map<TimelineEvent, number>;
  dateOf: Map<number, string>;
  lang: "vi" | "en";
  recall?: { hits: number; n: number; usual: number | null } | null;
}) {
  const meta = METRIC_META[metric];
  const vals: number[] = [];
  for (const r of rows) {
    if (r.value != null) vals.push(r.value);
    if (r.band) vals.push(r.band[0], r.band[1]);
  }
  let lo = Math.min(...vals);
  let hi = Math.max(...vals);
  const pad = (hi - lo) * 0.12 || 0.1;
  lo -= pad;
  hi += pad;
  if (metric === "recall_score") {
    lo = -0.2;
    hi = 3.2;
  }

  // Headline: last 7-day average vs. baseline, in plain words.
  const last = [...rows].reverse().find((r) => r.avg != null);
  let delta: { pct: number; outside: boolean } | null = null;
  if (last?.avg != null && last.center) {
    const pct = ((last.avg - last.center) / last.center) * 100;
    const outside = last.band ? last.avg < last.band[0] || last.avg > last.band[1] : false;
    delta = { pct, outside };
  }
  const worse = delta ? Math.sign(delta.pct) === BAD_DIRECTION[metric] : false;

  return (
    <figure className="flex min-w-0 flex-col gap-2">
      <figcaption className="flex flex-col gap-0.5">
        <div className="flex flex-wrap items-baseline justify-between gap-x-3">
          <h2 className="text-lg font-bold">
            <T vi={meta.vi} en={meta.en} />
          </h2>
          {recall ? (
            <p
              className={`text-[0.9375rem] font-semibold tnum ${recall.usual != null && recall.hits < recall.usual - 1 ? "text-red-ink" : "text-ink-2"}`}
            >
              <T
                vi={`Nhớ chuyện không cần gợi ý: ${recall.hits}/${recall.n} ngày gần đây${recall.usual != null ? ` (thường ${recall.usual}/${recall.n})` : ""}`}
                en={`Recalled without a cue: ${recall.hits} of the last ${recall.n} days${recall.usual != null ? ` (usually ${recall.usual}/${recall.n})` : ""}`}
              />
            </p>
          ) : delta && metric !== "recall_score" && (
            <p className={`text-[0.9375rem] font-semibold tnum ${delta.outside && worse ? "text-red-ink" : "text-ink-2"}`}>
              {Math.abs(delta.pct) < 1 ? (
                <T vi="Như mức thường ngày" en="At usual level" />
              ) : (
                <T
                  vi={`${delta.pct > 0 ? "Cao" : "Thấp"} hơn thường ngày ${Math.abs(delta.pct).toFixed(0)}%`}
                  en={`${Math.abs(delta.pct).toFixed(0)}% ${delta.pct > 0 ? "above" : "below"} usual`}
                />
              )}
              {delta.outside && worse && (
                <span className="font-normal">
                  {" · "}
                  <T vi="ngoài khoảng" en="outside range" />
                </span>
              )}
            </p>
          )}
        </div>
        <p className="text-sm text-ink-3">
          <T vi={meta.descVi} en={meta.descEn} />
        </p>
      </figcaption>
      <div className="h-48 w-full" role="img" aria-label={`${lang === "en" ? meta.en : meta.vi}: ${lang === "en" ? meta.descEn : meta.descVi}`}>
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={rows} margin={{ top: 20, right: M_RIGHT, bottom: 0, left: 0 }}>
            <CartesianGrid vertical={false} stroke="var(--line)" />
            <XAxis
              dataKey="day"
              type="number"
              domain={[minDay - 0.5, maxDay + 0.5]}
              ticks={ticks}
              tickFormatter={(d: number) => shortDate(dateOf.get(d) ?? "")}
              tick={{ fill: "var(--ink-3)", fontSize: 12 }}
              axisLine={{ stroke: "var(--line-strong)" }}
              tickLine={false}
              allowDataOverflow
            />
            <YAxis
              width={Y_W}
              domain={[lo, hi]}
              ticks={metric === "recall_score" ? [0, 1, 2, 3] : undefined}
              tickCount={4}
              tickFormatter={(v: number) => meta.fmt(v)}
              tick={{ fill: "var(--ink-3)", fontSize: 12 }}
              axisLine={false}
              tickLine={false}
              allowDataOverflow
            />
            {runs.map((r) => (
              <ReferenceArea
                key={`${r.light}-${r.from}`}
                x1={r.from - 0.5}
                x2={r.to + 0.5}
                fill={r.light === "red" ? "var(--red)" : "var(--yellow)"}
                fillOpacity={r.light === "red" ? 0.16 : 0.2}
                stroke="none"
                ifOverflow="hidden"
              />
            ))}
            <Area dataKey="band" type="stepAfter" stroke="none" fill="var(--band)" fillOpacity={1} isAnimationActive={false} connectNulls activeDot={false} />
            <Line dataKey="center" type="stepAfter" stroke="var(--accent)" strokeOpacity={0.55} strokeDasharray="4 4" strokeWidth={1} dot={false} activeDot={false} isAnimationActive={false} />
            <Line dataKey="value" stroke="none" dot={{ r: 2.5, fill: "var(--ink-3)", stroke: "none" }} activeDot={{ r: 5, fill: "var(--ink)", stroke: "var(--surface)", strokeWidth: 2 }} isAnimationActive={false} />
            <Line dataKey="avg" type="monotone" stroke="var(--ink)" strokeWidth={2} dot={false} activeDot={false} connectNulls isAnimationActive={false} />
            {events.filter((e, i) => events.findIndex((x) => x.day === e.day) === i).map((e) => (
              <ReferenceLine
                key={`${e.day}-${e.type}`}
                x={e.day}
                stroke="var(--ink-2)"
                strokeDasharray="2 3"
                label={(p: { viewBox?: { x?: number; y?: number } }) => <EventMark x={p.viewBox?.x ?? 0} y={p.viewBox?.y ?? 0} n={eventNo.get(e) ?? 0} />}
              />
            ))}
            <Tooltip content={<Tip metric={metric} lang={lang} />} cursor={{ stroke: "var(--ink-3)", strokeWidth: 1 }} isAnimationActive={false} />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
      <LightStrip rows={rows} minDay={minDay} maxDay={maxDay} />
    </figure>
  );
}

function EventMark({ x, y, n }: { x: number; y: number; n: number }) {
  return (
    <g>
      <circle cx={x} cy={y - 10} r={9} fill="var(--surface)" stroke="var(--ink-2)" strokeWidth={1.5} />
      <text x={x} y={y - 10} textAnchor="middle" dominantBaseline="central" fontSize={11} fontWeight={700} fill="var(--ink)">
        {n}
      </text>
    </g>
  );
}

const STRIP_H: Record<Light, number> = { gray: 4, green: 6, yellow: 11, red: 16 };
const STRIP_C: Record<Light, string> = { gray: "var(--gray)", green: "var(--green)", yellow: "var(--yellow)", red: "var(--red)" };

/** Daily light strip aligned to the chart's plot area. Height also encodes severity (not color alone). */
function LightStrip({ rows, minDay, maxDay }: { rows: Row[]; minDay: number; maxDay: number }) {
  const byDay = new Map(rows.map((r) => [r.day, r]));
  const cells = [];
  for (let d = minDay; d <= maxDay; d++) cells.push(byDay.get(d));
  return (
    <div className="flex h-4 items-end gap-px" style={{ paddingLeft: Y_W, paddingRight: M_RIGHT }} aria-hidden>
      {cells.map((r, i) => {
        const l = r?.light ?? null;
        return (
          <div
            key={i}
            className="flex-1 rounded-[2px]"
            style={{ height: l ? STRIP_H[l] : 2, background: l ? STRIP_C[l] : "var(--line)" }}
            title={r ? `${shortDate(r.date)}: ${LIGHT_WORD[l ?? "gray"].vi} / ${LIGHT_WORD[l ?? "gray"].en}` : undefined}
          />
        );
      })}
    </div>
  );
}

function Tip({
  active,
  payload,
  metric,
  lang,
}: {
  active?: boolean;
  payload?: ReadonlyArray<{ payload?: Row }>;
  metric: Metric;
  lang: "vi" | "en";
}) {
  const row = payload?.[0]?.payload;
  if (!active || !row) return null;
  const meta = METRIC_META[metric];
  const l = row.light ?? "gray";
  const d = longDate(row.date);
  const unit = lang === "en" ? meta.unitEn : meta.unitVi;
  const u = unit && unit !== "%" && unit !== "/3" ? ` ${unit}` : "";
  return (
    <div className="min-w-44 rounded-xl border border-line bg-surface px-3 py-2 text-sm shadow-soft">
      <p className="font-semibold">{lang === "en" ? d.en : d.vi}</p>
      <p className="mt-1 flex items-center gap-1.5 text-ink-2">
        <StatusShape light={l} size={14} />
        {lang === "en" ? LIGHT_WORD[l].en : LIGHT_WORD[l].vi}
      </p>
      <dl className="mt-1.5 grid grid-cols-[auto_auto] gap-x-3 gap-y-0.5 tnum">
        <dt className="text-ink-3">{lang === "en" ? "That day" : "Ngày đó"}</dt>
        <dd className="text-right font-semibold">{row.value != null ? `${meta.fmt(row.value)}${u}` : lang === "en" ? "not measured" : "không đo được"}</dd>
        <dt className="text-ink-3">{lang === "en" ? "7-day avg" : "TB 7 ngày"}</dt>
        <dd className="text-right">{row.avg != null ? meta.fmt(row.avg) : "–"}</dd>
        <dt className="text-ink-3">{lang === "en" ? "Usual" : "Thường ngày"}</dt>
        <dd className="text-right">{row.band ? `${meta.fmt(row.band[0])}–${meta.fmt(row.band[1])}` : "–"}</dd>
      </dl>
    </div>
  );
}
