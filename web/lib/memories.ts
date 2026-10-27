// Sổ ký ức (memory book) + prevention activities: types and server-side reads.
// Live API first (as the "Viewing as" family member, so only shared stories come back), bundled fixtures offline.
import { serverApiBase } from "./config";
import { actorHeaders } from "./viewer";
import { serverViewerId } from "./viewer-server";
import type { Loaded } from "./types";
import hanhMem from "@/fixtures/memories/hanh.json";
import tuMem from "@/fixtures/memories/tu.json";
import controlMem from "@/fixtures/memories/control.json";

export interface Era {
  label_vi?: string;
  label_en?: string;
  decade?: number | null;
}

export interface Story {
  id: number;
  day: number | null;
  date: string | null;
  question_id: string | null;
  theme: string;
  theme_vi: string;
  theme_en: string;
  era: Era;
  title_vi: string;
  title_en: string;
  text_vi: string;
  text_en: string;
  translation: "human" | "llm" | "gist" | string;
  people: { vi: string; en: string }[];
  places: string[];
  word_count: number | null;
  shared: boolean;
  source: string;
  simulated: boolean;
}

export interface Memories {
  elder_id: string;
  display_name?: string;
  name_en?: string;
  honorific?: string;
  viewer: "family" | "elder";
  stories: Story[];
  themes: { theme: string; label_vi: string; label_en: string; count: number }[];
  shared_count: number;
  private_count: number;
  total: number;
  sharing_paused: boolean;
  audio: { stored: boolean; note_vi: string; note_en: string };
  simulated: boolean;
}

export interface Rated {
  category: string;
  label_vi: string;
  label_en: string;
  played?: number;
  count?: number;
  success_rate?: number | null;
}

export interface Activities {
  sharing_paused?: boolean;
  games?: {
    played: number;
    success_rate: number | null;
    success_rate_first_4_weeks: number | null;
    success_rate_last_4_weeks: number | null;
    current_level: number;
    by_category: Rated[];
    trend: { week: number; day_from: number; day_to: number; played: number; success_rate: number | null; mean_level: number | null }[];
  };
  screen_games?: { played: number; correct_rate: number | null; played_last_14_days: number } | null;
  nudges?: { delivered: number; by_category: Rated[] };
  life_questions?: { asked: number; stories: number };
  associations?: {
    activity: string;
    label_vi: string;
    label_en: string;
    days_with: number;
    days_without: number;
    next_day_mood_with: number | null;
    next_day_mood_without: number | null;
    mood_diff: number;
    next_day_poor_sleep_with: number | null;
    next_day_poor_sleep_without: number | null;
  }[];
  association_note_vi?: string;
  association_note_en?: string;
  improve?: {
    day: number;
    date: string | null;
    focus_labels: Rated[];
    label_vi?: string;
    label_en?: string;
    plan_nudges_delivered: number;
    mood_before: number | null;
    mood_after: number | null;
    poor_sleep_before: number | null;
    poor_sleep_after: number | null;
  } | null;
  narrative?: { stories: number; words_early: number | null; words_recent: number | null; change_pct: number | null; note_vi: string; note_en: string } | null;
  difficulty_rule_vi?: string;
  difficulty_rule_en?: string;
  simulated?: boolean;
}

interface Bundle {
  memories: Memories;
  activities: Activities;
}
const FIX = { hanh: hanhMem, tu: tuMem, control: controlMem } as unknown as Record<string, Bundle>;
const fixture = (id: string): Bundle => FIX[id] ?? FIX.hanh;

async function get<T>(path: string, fallback: () => T, elderId: string): Promise<Loaded<T>> {
  try {
    const res = await fetch(`${serverApiBase()}${path}`, {
      cache: "no-store",
      signal: AbortSignal.timeout(3000),
      headers: actorHeaders(elderId, await serverViewerId(elderId)),
    });
    if (!res.ok) throw new Error(`${res.status}`);
    return { data: (await res.json()) as T, live: true };
  } catch {
    return { data: fallback(), live: false };
  }
}

const e = encodeURIComponent;
export const getMemories = (id: string) => get<Memories>(`/api/elders/${e(id)}/memories`, () => fixture(id).memories, id);
export const getActivities = (id: string) =>
  get<Activities>(`/api/elders/${e(id)}/activities`, () => fixture(id).activities, id);

export { exportUrl, pct } from "./memories-shared";
