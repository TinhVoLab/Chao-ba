"use client";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { Light } from "@/lib/types";
import { LIGHT_WORD, shortDate } from "@/lib/format";
import { useLang } from "@/lib/useLang";
import { StatusShape } from "../StatusShape";
import { T } from "../T";

type Row = { date: string } & Record<Light, number>;
// Status colours (reserved for the light) in severity order, bottom to top.
const ORDER: Light[] = ["red", "yellow", "green", "gray"];
const FILL: Record<Light, string> = { red: "var(--red)", yellow: "var(--yellow)", green: "var(--green)", gray: "var(--gray)" };

/** Ward lights per day, stacked (30 days). Legend uses the light shapes, so identity is never colour alone. */
export function WardTrend({ rows }: { rows: Row[] }) {
  const lang = useLang();
  const first = rows[0];
  const last = rows.at(-1);
  return (
    <figure className="flex flex-col gap-2">
      <ul className="flex flex-wrap gap-x-4 gap-y-1 text-sm text-ink-2" aria-label={lang === "en" ? "Legend" : "Chú giải"}>
        {ORDER.map((l) => (
          <li key={l} className="inline-flex items-center gap-1.5">
            <StatusShape light={l} size={14} />
            <T vi={LIGHT_WORD[l].vi} en={LIGHT_WORD[l].en} />
          </li>
        ))}
      </ul>
      <div className="h-56 w-full" role="img" aria-label={lang === "en" ? "Ward lights per day, last 30 days" : "Số người theo màu đèn mỗi ngày, 30 ngày qua"}>
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={rows} margin={{ top: 4, right: 4, bottom: 0, left: -18 }} barCategoryGap={2}>
            <CartesianGrid vertical={false} stroke="var(--line)" />
            <XAxis
              dataKey="date"
              tickFormatter={shortDate}
              tick={{ fill: "var(--ink-3)", fontSize: 12 }}
              tickLine={false}
              axisLine={{ stroke: "var(--line-strong)" }}
              interval="preserveStartEnd"
              minTickGap={24}
            />
            <YAxis domain={[0, "dataMax"]} tick={{ fill: "var(--ink-3)", fontSize: 12 }} tickLine={false} axisLine={false} allowDecimals={false} width={44} />
            <Tooltip
              cursor={{ fill: "var(--band)" }}
              content={({ active, payload, label }) =>
                active && payload?.length ? (
                  <div className="rounded-xl border border-line bg-surface px-3 py-2 text-sm shadow-soft">
                    <p className="font-semibold">{shortDate(String(label))}</p>
                    {ORDER.map((l) => {
                      const v = (payload[0].payload as Row)[l];
                      return (
                        <p key={l} className="flex items-center gap-1.5 text-ink-2 tnum">
                          <StatusShape light={l} size={12} />
                          {lang === "en" ? LIGHT_WORD[l].en : LIGHT_WORD[l].vi}: <span className="font-semibold text-ink">{v}</span>
                        </p>
                      );
                    })}
                  </div>
                ) : null
              }
            />
            {ORDER.map((l, i) => (
              <Bar
                key={l}
                dataKey={l}
                stackId="w"
                fill={FILL[l]}
                stroke="var(--surface)"
                strokeWidth={1}
                radius={i === ORDER.length - 1 ? [3, 3, 0, 0] : 0}
                isAnimationActive={false}
              />
            ))}
          </BarChart>
        </ResponsiveContainer>
      </div>
      {first && last && (
        <figcaption className="text-sm text-ink-3">
          <T
            vi={`Đỏ: ${first.red} → ${last.red} người, vàng: ${first.yellow} → ${last.yellow} người (${shortDate(first.date)} → ${shortDate(last.date)}).`}
            en={`Red: ${first.red} → ${last.red}, yellow: ${first.yellow} → ${last.yellow} (${shortDate(first.date)} → ${shortDate(last.date)}).`}
          />
        </figcaption>
      )}
    </figure>
  );
}
