// Mirrors chaoba/core/models.py and the REST shapes in CONTRACT.md.
export type Light = "green" | "yellow" | "red" | "gray";
export type Channel = "web" | "pstn" | "sim";
export const METRICS = ["speech_rate_sps", "pause_ratio", "filled_pause_rate", "mattr", "recall_score"] as const;
export type Metric = (typeof METRICS)[number];
export const BAD_DIRECTION: Record<Metric, 1 | -1> = {
  speech_rate_sps: -1,
  pause_ratio: 1,
  filled_pause_rate: 1,
  mattr: -1,
  recall_score: -1,
};

export interface ElderSummary {
  id: string;
  display_name: string;
  name_en: string;
  age: number;
  province: string;
  light: Light;
  opted_out?: boolean;
  simulated: boolean;
}

export interface FamilyMember {
  id: string;
  name: string;
  relation: string;
  role: string;
  phone?: string;
}

export interface ElderProfile {
  id: string;
  display_name: string;
  name_en: string;
  honorific: string;
  self_ref?: string;
  age: number;
  province: string;
  dialect?: string;
  lives_alone?: boolean;
  channel_pref?: string;
  conditions?: string[];
  medications?: { name: string; time: string }[];
  family?: FamilyMember[];
  goals?: string[];
  memory_facts?: string[];
  phone?: string;
  simulated?: boolean;
}

export interface Reason {
  code: string;
  metric?: Metric;
  days?: number;
  change_pct?: number;
  symptom?: string;
  [k: string]: unknown;
}

export interface Today {
  date: string;
  day: number;
  light: Light;
  reasons: Reason[];
  explanation_vi: string;
  explanation_en: string;
  summary_vi: string;
  summary_en: string;
  answered: boolean;
  mood: number | null;
  channel?: Channel;
  simulated: boolean;
}

export interface DailyRecord {
  elder_id: string;
  day: number;
  date: string;
  channel: Channel;
  answered: boolean;
  valid: boolean;
  speech_rate_sps: number | null;
  pause_ratio: number | null;
  filled_pause_rate: number | null;
  mattr: number | null;
  recall_score: number | null;
  mood: number | null;
  symptoms: Record<string, number>;
  summary_vi: string;
  summary_en: string;
  simulated: boolean;
}

export interface DailyLight {
  elder_id: string;
  day: number;
  date: string;
  light: Light;
  reasons: Reason[];
  z: Partial<Record<Metric, number | null>>;
  baseline_ready: boolean;
  explanation_vi: string;
  explanation_en: string;
}

export interface TimelineEvent {
  day: number;
  type: string;
  label_vi: string;
  label_en: string;
}

export interface Timeline {
  records: DailyRecord[];
  lights: DailyLight[];
  baseline: Partial<Record<Metric, { center: number; scale: number }>>;
  events: TimelineEvent[];
  simulated?: boolean;
}

export interface Alert {
  id: string | number;
  day: number;
  date: string;
  type: string;
  /** API sends the light level ("yellow" | "red"); normalised to info | warning | critical. */
  severity: "info" | "warning" | "critical" | string;
  explanation_vi: string;
  explanation_en: string;
  acknowledged: boolean;
}

export type PhaseKey = "define" | "measure" | "analyze" | "improve" | "control";
export interface DmaicPhase {
  phase: PhaseKey;
  day_from: number | null;
  day_to: number | null;
  summary_vi: string;
  summary_en: string;
}
export interface Dmaic {
  phases: DmaicPhase[];
  effect: Partial<Record<Metric, { pre: number | null; post: number | null; change_pct: number | null }>>;
  new_baseline_day: number | null;
  first_alert_day?: number | null;
  peak_light?: Light | null;
  intervention_day?: number | null;
  green_day?: number | null;
  days_to_green?: number | null;
  simulated?: boolean;
}

export interface Note {
  id?: string | number;
  day?: number;
  date?: string;
  created_at?: string;
  author: string;
  text: string;
  to_elder?: boolean;
  simulated?: boolean;
}

/** Consent as the API sends it. */
export interface RawConsent {
  type?: string;
  kind?: string;
  id?: string;
  granted?: boolean;
  status?: string;
  by?: string;
  granted_by?: string;
  witness?: string;
  scope_vi?: string;
  scope_en?: string;
  label_vi?: string;
  label_en?: string;
  date?: string;
  granted_at?: string;
  ts?: string;
  [k: string]: unknown;
}
/** Access log entry as the API sends it. */
export interface RawAccess {
  actor?: string;
  who?: string;
  role?: string;
  action: string;
  resource?: string;
  ts?: string;
  at?: string;
  [k: string]: unknown;
}
export interface Privacy {
  consents: RawConsent[];
  access_log: RawAccess[];
  data_retention: { audio: string; transcript_days: number; [k: string]: unknown };
  scheduling_active?: boolean;
  simulated?: boolean;
}

/** Result of a data read: `live` is false when the bundled fixture was used. */
export interface Loaded<T> {
  data: T;
  live: boolean;
}
