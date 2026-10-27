// "Gửi yêu thương": family micro-interactions (chaoba/server/kudos.py). Types, client reads (as the "Viewing as"
// member) and writes through the outbox, so a card only shows "Đã gửi" once the API stored it.
import { API_BASE } from "./config";
import { postWrite } from "./outbox";
import { actorHeaders } from "./viewer";

export type KudosKind = "checkin" | "love" | "advice" | "care_tip" | "message";

export interface KudosChoice {
  id: string;
  vi: string;
  en: string;
}

export interface KudosTemplate {
  id: string;
  kind: KudosKind;
  icon: string;
  health: boolean;
  label_vi: string;
  label_en: string;
  text_vi: string;
  text_en: string;
  choices: KudosChoice[];
  folk_note: boolean;
}

export interface KudosCatalog {
  viewer: { member_id: string | null; name: string; role: string };
  address_vi: string;
  address_en: string;
  templates: KudosTemplate[];
  groups: { kind: KudosKind; label_vi: string; label_en: string }[];
  limit_per_day: number;
  sent_today: number;
  remaining_today: number;
  max_text: number;
  voice_note: { available: boolean; note_vi: string; note_en: string };
  self_report: { note_vi: string; note_en: string };
  can_send: boolean;
  simulated: boolean;
}

export interface KudosReply {
  choice?: string;
  choice_vi?: string;
  choice_en?: string;
  text?: string;
  heart?: boolean;
  via?: "screen" | "call";
  at?: string;
  simulated?: boolean;
}

export interface Kudos {
  id: number;
  day: number | null;
  date: string;
  kind: KudosKind;
  template_id: string | null;
  icon: string;
  sender_id: string | null;
  sender_name: string;
  sender_relation: string | null;
  elder_self_vi: string;
  text_vi: string;
  text_en: string;
  text_lang: "vi" | null;
  custom: boolean;
  health: boolean;
  choices: KudosChoice[];
  status: "sent" | "seen" | "replied";
  status_vi: string;
  status_en: string;
  sent_at: string;
  sent_time: string;
  seen_at: string | null;
  seen_via: "screen" | "call" | null;
  replied_at: string | null;
  reply_time: string;
  reply: KudosReply | null;
  reply_hidden: boolean;
  reply_vi: string;
  reply_en: string;
  heart: boolean;
  redacted: boolean;
  folk_note: boolean;
  story: { id: number | null; saved: boolean; declined?: boolean } | null;
  simulated: boolean;
}

export interface KudosList {
  box: "inbox" | "sent" | "family";
  items: Kudos[];
  date: string;
  micro_7d: number;
  sent_today: number;
  remaining_today: number;
  limit_per_day: number;
  sharing_paused: boolean;
  self_report: { note_vi: string; note_en: string };
  simulated: boolean;
}

const e = encodeURIComponent;

export async function fetchKudos(elderId: string, box: "sent" | "family", days = 28): Promise<KudosList | null> {
  try {
    const r = await fetch(`${API_BASE}/api/elders/${e(elderId)}/kudos?box=${box}&days=${days}`, {
      headers: actorHeaders(elderId),
      cache: "no-store",
      signal: AbortSignal.timeout(4000),
    });
    return r.ok ? ((await r.json()) as KudosList) : null;
  } catch {
    return null;
  }
}

export async function fetchCatalog(elderId: string): Promise<KudosCatalog | null> {
  try {
    const r = await fetch(`${API_BASE}/api/elders/${e(elderId)}/kudos/catalog`, {
      headers: actorHeaders(elderId),
      cache: "no-store",
      signal: AbortSignal.timeout(4000),
    });
    return r.ok ? ((await r.json()) as KudosCatalog) : null;
  } catch {
    return null;
  }
}

/** The server's friendly refusal (free-text post-check, daily limit) from a rejected write's detail. */
export function refusalMessage(detail: string): { vi: string; en: string } | null {
  try {
    const d = JSON.parse(detail) as { message_vi?: string; message_en?: string };
    if (d && d.message_vi) return { vi: d.message_vi, en: d.message_en ?? d.message_vi };
  } catch {
    /* plain text */
  }
  return null;
}

export type SendOutcome =
  | { state: "saved"; kudos: Kudos; remaining: number }
  | { state: "queued" }
  | { state: "refused"; message: { vi: string; en: string } | null; detail: string };

export async function sendKudos(
  elderId: string,
  body: { kind: KudosKind; template_id?: string; text?: string },
): Promise<SendOutcome> {
  const r = await postWrite("kudos", elderId, `/api/elders/${e(elderId)}/kudos`, body, { meta: { body } });
  if (r.state === "saved") {
    const j = r.json as { kudos: Kudos; remaining_today: number };
    return { state: "saved", kudos: j.kudos, remaining: j.remaining_today };
  }
  if (r.state === "queued") return { state: "queued" };
  return { state: "refused", message: refusalMessage(r.detail), detail: r.detail };
}

export async function saveAdviceToMemory(elderId: string, kid: number) {
  return postWrite("kudos_save", elderId, `/api/elders/${e(elderId)}/kudos/${kid}/save`, { confirmed_by_elder_or_proxy: true }, { queue: false });
}
