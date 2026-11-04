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
  /** True when the family_sharing consent is withdrawn: the API withholds the light and summary. */
  sharing_paused?: boolean;
  contact?: ContactStatus;
  /** True when `date` is the server's today (the record is this morning's call). */
  is_today?: boolean;
  /** Heading for the call section, e.g. "Cuộc gọi sáng nay" or "Cuộc gọi gần nhất (12/10)". */
  label_vi?: string;
  label_en?: string;
  simulated: boolean;
}

export interface FamilyContact {
  id?: number;
  day: number;
  date: string;
  member_id?: string | null;
  member_name?: string | null;
  kind: "call" | "visit" | "message" | string;
  duration_min?: number | null;
  source?: string;
  simulated?: boolean;
}

/** Last family call/visit relative to the latest call day; `nudge` when nobody called for `nudge_after_days`. */
export interface ContactStatus {
  last: FamilyContact | null;
  days_since: number | null;
  nudge: boolean;
  nudge_after_days: number;
  /** Love notes / check-in cards the family sent in the last 7 days (kudos.py); never counted as calls. */
  micro_7d?: number;
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

export interface BaselineSegment {
  /** First day judged against this baseline. */
  from_day: number;
  to_day: number;
  /** Days the baseline was estimated from. */
  window: [number, number];
  metrics: Partial<Record<Metric, { center: number; scale: number }>>;
}

export interface Timeline {
  records: DailyRecord[];
  lights: DailyLight[];
  /** Baseline in force now (kept for compatibility); `baselines` has the full history. */
  baseline: Partial<Record<Metric, { center: number; scale: number }>>;
  baselines?: BaselineSegment[];
  sharing_paused?: boolean;
  events: TimelineEvent[];
  simulated?: boolean;
}

export interface Alert {
  id: string | number;
  day: number;
  date: string;
  type: string;
  /** Light colour as stored ("yellow" | "red"); normalised to info | warning | critical from `severity_level`. */
  severity: "info" | "warning" | "critical" | string;
  severity_level?: "info" | "warning" | "critical";
  explanation_vi: string;
  explanation_en: string;
  acknowledged: boolean;
  /** Red alerts wait for a clinician / health-station review (care_review.py); null until reviewed. */
  review?: AlertReview | null;
  needs_review?: boolean;
}

/** Review outcomes accepted by care_review.py OUTCOMES (follow-up close to home, then referral). */
export type ReviewOutcome =
  | "no_action"
  | "family_follow_up"
  | "phone_check"
  | "home_visit"
  | "repeat_assessment"
  | "gp_referral"
  | "geriatrics"
  | "neurology"
  | "mental_health"
  | "emergency";

export interface AlertReview {
  /** A ReviewOutcome; kept as string so an older or newer server value still renders. */
  outcome: ReviewOutcome | string;
  outcome_vi: string;
  outcome_en: string;
  note: string;
  by: string;
  role: string;
  at: string;
  day: number | null;
}

export interface ReviewRow {
  elder_ref: string;
  label: string;
  alert_id: number;
  day: number;
  date: string;
  type: string;
  needs_review: boolean;
  review: AlertReview | null;
}

/** Weekly family-connection series (connection.py). Never part of the light. */
export interface ConnectionWeek {
  from: string;
  to: string;
  calls_visits: number;
  micro: number;
  members: number;
  days_in_touch: number;
  elder_replies: number;
}
export interface Connection {
  weeks: ConnectionWeek[];
  summary: {
    last_14_days: Omit<ConnectionWeek, "from" | "to" | "members">;
    previous_14_days: Omit<ConnectionWeek, "from" | "to" | "members"> | null;
    circle_size: number;
  } | null;
  in_light?: false;
  note_vi?: string;
  note_en?: string;
  sharing_paused: boolean;
  simulated: boolean;
}

/** One signal beside the light (brain_context.py). Fields depend on `key`; `available: false` carries a `reason`. */
export interface BrainContextItem {
  key: "recall" | "speech_rate" | "sleep" | "mood" | "symptoms" | "medication" | "connection" | "games";
  /** Whether a rule of the daily light already uses this signal (connection, games and medication taps never do). */
  in_light: boolean;
  available: boolean;
  reason?: "no_baseline" | "no_calls" | "voice_metrics_off" | "no_medications" | "not_logged" | "no_data";
  /** "baseline" = vs the person's own usual; "previous" = vs the period of the same length before. */
  compare?: "baseline" | "previous";
  flagged_days?: number;
  free?: number;
  asked?: number;
  usual?: number | null;
  mean?: number;
  change_pct?: number | null;
  direction?: "slower" | "faster";
  calls?: number;
  days?: number;
  prev?: number | null;
  low_days?: number;
  checkins?: { happy: number; neutral: number; sad: number } | null;
  top?: { symptom: string; days: number; label_vi: string; label_en: string }[];
  concerns?: number;
  taken_days?: number;
  answered_days?: number;
  prev_taken_days?: number | null;
  days_in_touch?: number;
  calls_visits?: number;
  plays?: number;
  days_played?: number;
}
export interface BrainContext {
  days: 14 | 28;
  from?: string;
  to?: string;
  light: { counts: Record<"green" | "yellow" | "red" | "gray", number>; latest: Light | null } | null;
  items: BrainContextItem[];
  sharing_paused: boolean;
  simulated: boolean;
  note_vi: string;
  note_en: string;
  future_vi: string;
  future_en: string;
}

export type PhaseKey = "define" | "measure" | "analyze" | "improve" | "control";
export type PhaseStatus = "done" | "current" | "not_started";
export interface DmaicPhase {
  phase: PhaseKey;
  status?: PhaseStatus;
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
  /** Family calls + visits per week: before / after the intervention and in the last 14 days. */
  /** True when the effect table comes from a scripted persona (illustration, not a measured outcome). */
  effect_illustrative?: boolean;
  effect_note_vi?: string;
  effect_note_en?: string;
  contact?: {
    pre_per_week?: number | null;
    post_per_week?: number | null;
    recent_per_week?: number | null;
    pre_window?: [number, number];
    post_window?: [number, number];
    recent_window?: [number, number];
    /** Micro-contacts (love notes, check-in cards; kudos.py) per week: a separate series, never counted as calls. */
    micro_pre_per_week?: number | null;
    micro_post_per_week?: number | null;
    micro_recent_per_week?: number | null;
    weekly?: { day_from: number; day_to: number; date_from: string | null; date_to: string | null; calls_visits: number; micro: number }[];
    micro_note_vi?: string;
    micro_note_en?: string;
  } | null;
  sharing_paused?: boolean;
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
  /** Reads collapsed into this row (one row per actor, action and resource per day). */
  count?: number;
  last_ts?: string;
  [k: string]: unknown;
}
export interface Privacy {
  /** Current state per consent purpose (`status`: active | withdrawn | declined). */
  consents: RawConsent[];
  consent_history?: RawConsent[];
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

// ---------------------------------------------------------------- family coordination (/api/elders/{id}/family)
export interface FamilyMemberRow {
  id: string;
  name: string;
  relation: string;
  relation_vi: string;
  role: "primary" | "viewer";
  city: string | null;
}

export interface FamilyViewer {
  member_id: string | null;
  name: string;
  role: "primary" | "viewer" | "elder_self";
  permissions: { full_view: boolean; edit_rota: boolean; manage_tasks: boolean; see_access_log: boolean };
}

export interface RotaSlot {
  weekday: number;
  weekday_vi: string;
  weekday_en: string;
  member_id: string | null;
  member_name: string | null;
}

export interface Rota {
  week: RotaSlot[];
  today: RotaSlot & { date: string; done: boolean; anyone_called: boolean };
  history: (RotaSlot & {
    date: string;
    day: number | null;
    contacted: boolean;
    by_assignee: boolean;
    contacts: { member_name: string; kind: string }[];
    before_rota: boolean;
  })[];
  gap: { days_since: number | null; nudge: boolean; threshold: number; last: FamilyContact | null };
  created_day: number | null;
  mine?: { weekdays: number[]; your_turn: boolean; next: { date: string; weekday: number; in_days: number } | null };
  nudge_vi: string | null;
  nudge_en: string | null;
}

export type TaskKind = "appointment" | "medicine" | "visit" | "other";

export interface CareTask {
  id: number;
  kind: TaskKind;
  title_vi: string;
  title_en: string;
  assignee_id: string | null;
  assignee_name: string | null;
  due_date: string | null;
  overdue: boolean;
  done: boolean;
  done_by: string | null;
  done_day: number | null;
  created_by: string | null;
  created_day: number | null;
  simulated: boolean;
}

export interface AskedBy {
  name: string;
  date: string | null;
  member_id: string | null;
  how: "asked" | "note";
  you?: boolean;
}

export interface Suggestion {
  key: string;
  source: "call" | "memory" | "synthesis";
  day: number | null;
  text_vi: string;
  text_en: string;
  asked_by: AskedBy[];
}

export interface Suggestions {
  suggestions: Suggestion[];
  already_asked: Suggestion[];
  window_from_day: number;
  sharing_paused: boolean;
  simulated: boolean;
}

export interface SynthesisItem {
  topic: string;
  label_vi: string;
  label_en: string;
  count: number;
  ai: number;
  people: string[];
  sources: number;
  first_day: number;
  last_day: number;
  mentions: { source: "ai" | "note"; who: string; date: string; day: number }[];
  text_vi: string;
  text_en: string;
}

export interface Synthesis {
  from_day: number;
  to_day: number;
  from_date: string;
  to_date: string;
  days: number;
  items: SynthesisItem[];
  summary_vi: string;
  summary_en: string;
  contact_vi: string;
  contact_en: string;
  engine: "rules" | "claude";
  sharing_paused: boolean;
  simulated: boolean;
}

export interface AccessPerson {
  actor: string;
  role: string;
  /** Display name (family.py `access`): the actor, or the elder's kin name for `elder_self` ("Má (chính bà)"). */
  label_vi?: string;
  label_en?: string;
  views: number;
  writes: number;
  last_ts: string;
}

export interface FamilyOverview {
  viewer: FamilyViewer;
  members: FamilyMemberRow[];
  rota: Rota;
  tasks: CareTask[];
  suggestions: Suggestions;
  synthesis: Synthesis;
  access: { days: number; people: AccessPerson[] };
  sharing_paused: boolean;
  simulated: boolean;
}

export type FeedKind = "call" | "note" | "contact" | "alert" | "task" | "event" | "rota" | "gap" | "self_report" | "kudos";

export interface FeedItem {
  id: string;
  kind: FeedKind;
  day: number | null;
  date: string | null;
  actor: string | null;
  title_vi: string;
  title_en: string;
  text_vi: string;
  text_en: string;
  redacted: boolean;
  light?: Light | null;
  severity?: "yellow" | "red";
  rehearsal?: boolean;
  to_elder?: boolean;
  simulated?: boolean;
  text_lang?: "vi";
  /** kind "kudos" (family love notes, kudos.py) */
  kudos_id?: number;
  kudos_kind?: string;
  status?: "sent" | "seen" | "replied";
  heart?: boolean;
}

export interface FamilyTimeline {
  items: FeedItem[];
  upcoming: CareTask[];
  from_day: number;
  to_day: number;
  viewer: FamilyViewer;
  members: FamilyMemberRow[];
  sharing_paused: boolean;
  simulated: boolean;
}

// ---------------------------------------------------------------- community dashboard (/api/community/overview)
export interface VisitRow {
  pid: string;
  label: string;
  initials: string;
  age: number;
  area: string;
  light: Light;
  days_in_state: number;
  since_date: string | null;
  reasons_vi: string[];
  reasons_en: string[];
  days_since_contact: number | null;
  missed_contact: boolean;
  lives_alone: boolean;
  demo_persona: boolean;
  group: "red" | "yellow" | "check_in";
  rank: number;
}

export interface InterventionRow {
  intervention: string;
  label_vi: string;
  label_en: string;
  episodes: number;
  open: number;
  recovered: number;
  rate: number | null;
  median_days_to_green: number | null;
  enough: boolean;
}

export interface Community {
  ward: { name_vi: string; name_en: string; elders: number; sharing: number; not_sharing: number; demo_personas: number };
  as_of: string;
  counts: Record<Light, number>;
  lives_alone: number;
  missed_contact: number;
  visit_list: VisitRow[];
  /** Red alerts of sharing elders: waiting for review first (older snapshots lack it). */
  review_queue?: ReviewRow[];
  trend: ({ date: string } & Record<Light, number>)[];
  interventions: InterventionRow[];
  method: {
    recovery_days: number;
    missed_contact_days: number;
    checkin_no_contact_days: number;
    trend_days: number;
    cohort: { n: number; days: number; seed: number };
  };
  association_note_vi: string;
  association_note_en: string;
  disclaimer_vi: string;
  disclaimer_en: string;
  simulated: boolean;
}
