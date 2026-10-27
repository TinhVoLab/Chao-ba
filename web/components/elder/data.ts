"use client";
// Elder-screen reads and writes (chaoba/server/elder_ui.py). Writes the API cannot take right now are kept on the
// device (localStorage "cb-elder-outbox") and retried when the screen loads or the network comes back, so a tap on
// "Đã uống thuốc" is never lost. Today's choices are also remembered locally so the screen works offline.

export interface MedToday {
  name: string;
  time: string;
  timed: boolean;
  status: "taken" | "not_yet" | null;
  answered_at: string | null;
}
export interface ScreenMessage {
  id?: number | string;
  author: string;
  text: string;
  date?: string | null;
}
export interface ScreenBundle {
  date: string;
  medications: MedToday[];
  messages: ScreenMessage[];
  mood_today: { mood: Mood } | null;
  game_plays_today: number;
  opted_out: boolean;
}
export type Mood = "happy" | "neutral" | "sad";

const OUTBOX = "cb-elder-outbox";

function elderHeaders(elderId: string): Record<string, string> {
  return { "Content-Type": "application/json", "X-Actor": encodeURIComponent(`elder:${elderId}`), "X-Role": "elder_self" };
}

export async function fetchScreen(apiBase: string, elderId: string): Promise<ScreenBundle | null> {
  try {
    const r = await fetch(`${apiBase}/api/elders/${encodeURIComponent(elderId)}/screen`, {
      headers: elderHeaders(elderId),
      cache: "no-store",
      signal: AbortSignal.timeout(3500),
    });
    if (!r.ok) return null;
    return (await r.json()) as ScreenBundle;
  } catch {
    return null;
  }
}

interface Pending {
  url: string;
  body: unknown;
  elderId: string;
}
function readOutbox(): Pending[] {
  try {
    const v = JSON.parse(localStorage.getItem(OUTBOX) ?? "[]") as unknown;
    return Array.isArray(v) ? (v as Pending[]) : [];
  } catch {
    return [];
  }
}
function writeOutbox(list: Pending[]) {
  try {
    if (list.length) localStorage.setItem(OUTBOX, JSON.stringify(list));
    else localStorage.removeItem(OUTBOX);
  } catch {
    /* storage blocked */
  }
}

async function send(p: Pending): Promise<"ok" | "retry" | "refused"> {
  try {
    const r = await fetch(p.url, {
      method: "POST",
      headers: elderHeaders(p.elderId),
      body: JSON.stringify(p.body),
      signal: AbortSignal.timeout(5000),
    });
    if (r.ok) return "ok";
    return r.status >= 500 ? "retry" : "refused";
  } catch {
    return "retry";
  }
}

/** POST from the elder screen. "saved" = stored on the server; "queued" = kept here and retried later. */
export async function postElder(
  apiBase: string,
  elderId: string,
  path: string,
  body: unknown,
): Promise<"saved" | "queued" | "refused"> {
  const p = { url: `${apiBase}/api/elders/${encodeURIComponent(elderId)}/${path}`, body, elderId };
  const r = await send(p);
  if (r === "ok") return "saved";
  if (r === "refused") return "refused";
  writeOutbox([...readOutbox(), p]);
  return "queued";
}

let flushing = false;
export async function flushElderOutbox(): Promise<void> {
  if (flushing) return;
  flushing = true;
  try {
    for (const item of readOutbox()) {
      const r = await send(item);
      if (r === "retry") break;
      writeOutbox(readOutbox().filter((x) => !(x.url === item.url && JSON.stringify(x.body) === JSON.stringify(item.body))));
    }
  } finally {
    flushing = false;
  }
}

/** Per-day local memory of the elder's taps (offline fallback). */
export function localDay<T>(elderId: string, key: string): T | null {
  try {
    const raw = localStorage.getItem(`cb-elder-${elderId}-${key}`);
    if (!raw) return null;
    const v = JSON.parse(raw) as { date: string; value: T };
    return v.date === new Date().toDateString() ? v.value : null;
  } catch {
    return null;
  }
}
export function saveLocalDay(elderId: string, key: string, value: unknown) {
  try {
    localStorage.setItem(`cb-elder-${elderId}-${key}`, JSON.stringify({ date: new Date().toDateString(), value }));
  } catch {
    /* ignore */
  }
}

/** Family love notes waiting for the elder ("Gửi yêu thương", kudos.py): oldest first; null when offline. */
export async function fetchKudosInbox(apiBase: string, elderId: string): Promise<import("@/lib/kudos").Kudos[] | null> {
  try {
    const r = await fetch(`${apiBase}/api/elders/${encodeURIComponent(elderId)}/kudos?box=inbox&pending=1&days=7`, {
      headers: elderHeaders(elderId),
      cache: "no-store",
      signal: AbortSignal.timeout(3500),
    });
    if (!r.ok) return null;
    return ((await r.json()) as { items: import("@/lib/kudos").Kudos[] }).items;
  } catch {
    return null;
  }
}
