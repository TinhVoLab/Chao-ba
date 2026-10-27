// Adapters from the live API's shapes to what the UI renders. Applied to live and fixture data alike.
import type { Alert, DailyRecord, Note, TimelineEvent } from "./types";

const SEVERITY: Record<string, Alert["severity"]> = {
  red: "critical",
  emergency: "critical",
  critical: "critical",
  yellow: "warning",
  warning: "warning",
  green: "info",
  gray: "info",
  info: "info",
};

export function normAlerts(list: unknown): Alert[] {
  if (!Array.isArray(list)) return [];
  return (list as Alert[])
    .map((a) => ({ ...a, id: String(a.id), severity: a.severity_level ?? SEVERITY[String(a.severity)] ?? "info" }))
    .sort((a, b) => b.day - a.day || String(b.id).localeCompare(String(a.id), undefined, { numeric: true }));
}

/** Notes carry `day` and `date` from the API; older snapshots lacked `date`, so fall back to the timeline. Newest first. */
export function normNotes(list: unknown, records: Pick<DailyRecord, "day" | "date">[]): Note[] {
  if (!Array.isArray(list)) return [];
  const dateOf = new Map(records.map((r) => [r.day, r.date]));
  return (list as Note[])
    .map((n) => ({ ...n, date: n.date ?? (n.day != null ? dateOf.get(n.day) : undefined) }))
    .sort((a, b) => (b.day ?? 0) - (a.day ?? 0) || Number(b.id ?? 0) - Number(a.id ?? 0));
}

/** Timeline events worth a marker on charts (lights already show alert/recovery days). */
const MARKER_TYPES = new Set(["medication_change", "doctor_visit", "care_plan", "rebaseline", "new_baseline", "symptom_report", "hospital", "fall"]);
export function chartEvents(events: TimelineEvent[] | undefined): TimelineEvent[] {
  const rank = (t: string) => ["medication_change", "symptom_report", "fall", "hospital", "doctor_visit", "care_plan"].indexOf(t);
  return (events ?? []).filter((e) => MARKER_TYPES.has(e.type)).sort((a, b) => a.day - b.day || rank(a.type) - rank(b.type));
}
export const isRebaseline = (e: TimelineEvent) => e.type === "rebaseline" || e.type === "new_baseline";
