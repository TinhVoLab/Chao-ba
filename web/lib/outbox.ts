"use client";
// Family-app writes (contact log, notes, alert acks, consent withdrawals) go through here so the UI only says
// "saved" when the API actually stored the row. Failed writes are kept in localStorage ("outbox") and retried
// later: when the app mounts, when the browser comes back online, and every 30 s while something is pending.
// Client errors (4xx) are not retried: the server understood the request and refused it.
import { useEffect, useSyncExternalStore } from "react";
import { API_BASE } from "./config";
import { actorHeaders } from "./viewer";
import { writeLocal } from "./useLang";

export type WriteKind = "contact" | "note" | "ack" | "withdraw";

export interface PendingWrite {
  id: string;
  kind: WriteKind;
  elderId: string;
  path: string;
  body: unknown;
  headers: Record<string, string>;
  createdAt: string;
  tries: number;
  /** localStorage key set to `createdAt` once the write reaches the server (e.g. "you called today"). */
  markKey?: string;
  /** What the UI needs to show the item while pending (note text, alert id, consent kind). */
  meta?: Record<string, unknown>;
}

export type WriteOutcome =
  | { state: "saved"; json: unknown }
  | { state: "queued" }
  | { state: "rejected"; status: number; detail: string };

const KEY = "cb-outbox";
const EVENT = "cb-outbox";
export const SENT_EVENT = "cb-outbox-sent";

function read(): PendingWrite[] {
  try {
    const raw = localStorage.getItem(KEY);
    const v = raw ? (JSON.parse(raw) as unknown) : [];
    return Array.isArray(v) ? (v as PendingWrite[]) : [];
  } catch {
    return [];
  }
}

let cacheRaw: string | null | undefined;
let cacheList: PendingWrite[] = [];
function snapshot(): PendingWrite[] {
  let raw: string | null = null;
  try {
    raw = localStorage.getItem(KEY);
  } catch {
    raw = null;
  }
  if (raw !== cacheRaw) {
    cacheRaw = raw;
    cacheList = read();
  }
  return cacheList;
}

/** Returns false when the browser blocks storage (the caller must then say the write is lost, not kept). */
function save(list: PendingWrite[]): boolean {
  let ok = true;
  try {
    if (list.length) localStorage.setItem(KEY, JSON.stringify(list));
    else localStorage.removeItem(KEY);
  } catch {
    ok = false;
  }
  window.dispatchEvent(new Event(EVENT));
  return ok;
}

type Attempt = { ok: true; json: unknown } | { ok: false; retry: boolean; status: number; detail: string };

async function attempt(path: string, body: unknown, headers: Record<string, string>): Promise<Attempt> {
  try {
    const res = await fetch(`${API_BASE}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...headers },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: AbortSignal.timeout(5000),
    });
    const json = (await res.json().catch(() => null)) as unknown;
    if (res.ok) return { ok: true, json };
    const detail =
      json && typeof json === "object" && "detail" in json
        ? typeof (json as { detail: unknown }).detail === "string"
          ? String((json as { detail: unknown }).detail)
          : JSON.stringify((json as { detail: unknown }).detail)
        : res.statusText;
    // 408 / 429 / 5xx are transient; other 4xx are a refusal and will not succeed on retry.
    const retry = res.status >= 500 || res.status === 408 || res.status === 429;
    return { ok: false, retry, status: res.status, detail };
  } catch {
    return { ok: false, retry: true, status: 0, detail: "network" };
  }
}

function onSent(item: PendingWrite, json: unknown) {
  if (item.markKey) writeLocal(item.markKey, item.createdAt);
  window.dispatchEvent(new CustomEvent(SENT_EVENT, { detail: { item, json } }));
}

/**
 * POST a family write. "saved" only when the API answered 2xx; "queued" when it could not be reached (kept on
 * this device, retried later); "rejected" when the API refused it (4xx, not retried).
 */
export async function postWrite(
  kind: WriteKind,
  elderId: string,
  path: string,
  body?: unknown,
  opts: { markKey?: string; meta?: Record<string, unknown>; queue?: boolean } = {},
): Promise<WriteOutcome> {
  const headers = actorHeaders(elderId);
  const createdAt = new Date().toISOString();
  const r = await attempt(path, body, headers);
  if (r.ok) {
    if (opts.markKey) writeLocal(opts.markKey, createdAt);
    return { state: "saved", json: r.json };
  }
  if (!r.retry || opts.queue === false) return { state: "rejected", status: r.status, detail: r.detail };
  const item: PendingWrite = {
    id: `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`,
    kind,
    elderId,
    path,
    body,
    headers,
    createdAt,
    tries: 1,
    markKey: opts.markKey,
    meta: opts.meta,
  };
  if (!save([...read(), item])) return { state: "rejected", status: 0, detail: "storage" };
  return { state: "queued" };
}

let flushing = false;
/** Retry every pending write in order. Stops at the first network failure (the server is still unreachable). */
export async function flushOutbox(): Promise<void> {
  if (flushing || typeof window === "undefined") return;
  flushing = true;
  try {
    for (const item of read()) {
      const r = await attempt(item.path, item.body, item.headers);
      if (r.ok) {
        save(read().filter((x) => x.id !== item.id));
        onSent(item, r.json);
      } else if (!r.retry) {
        // Refused now (e.g. the alert no longer exists): drop it rather than retry forever.
        save(read().filter((x) => x.id !== item.id));
      } else {
        save(read().map((x) => (x.id === item.id ? { ...x, tries: x.tries + 1 } : x)));
        if (r.status === 0) break;
      }
    }
  } finally {
    flushing = false;
  }
}

function subscribe(cb: () => void) {
  window.addEventListener(EVENT, cb);
  window.addEventListener("storage", cb);
  return () => {
    window.removeEventListener(EVENT, cb);
    window.removeEventListener("storage", cb);
  };
}

const EMPTY: PendingWrite[] = [];

/** Pending writes (optionally for one elder) and a background retry loop while any are pending. */
export function useOutbox(elderId?: string): PendingWrite[] {
  const all = useSyncExternalStore(subscribe, snapshot, () => EMPTY);
  const any = all.length > 0;
  useEffect(() => {
    if (!any) return;
    flushOutbox();
    const t = setInterval(flushOutbox, 30_000);
    window.addEventListener("online", flushOutbox);
    return () => {
      clearInterval(t);
      window.removeEventListener("online", flushOutbox);
    };
  }, [any]);
  return elderId ? all.filter((x) => x.elderId === elderId) : all;
}
