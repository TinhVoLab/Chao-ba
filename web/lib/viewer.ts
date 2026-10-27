// Who is using the family app. The prototype has no login, so the app identifies the demo viewer to the API with
// X-Actor / X-Role headers (the access log records them). Each elder has a small care circle (mirrors
// CIRCLES in chaoba/server/family.py): one primary carer who sees everything, and viewers who see summaries.
// The "Đang xem với tư cách / Viewing as" switcher stores the chosen member per elder in the `cb-viewer` cookie
// ("hanh:minh,tu:khoa"), so server-side reads and client-side writes use the same identity.
// Header values must be ASCII, so the name is percent-encoded (the API decodes it).

export type ViewerRole = "primary" | "viewer";

export interface CircleMember {
  id: string;
  name: string;
  role: ViewerRole;
  relVi: string;
  relEn: string;
  city: string;
}

export const CIRCLES: Record<string, CircleMember[]> = {
  hanh: [
    { id: "lan", name: "Lan", role: "primary", relVi: "con gái", relEn: "daughter", city: "TP.HCM" },
    { id: "minh", name: "Minh", role: "viewer", relVi: "con trai", relEn: "son", city: "Hà Nội" },
    { id: "vy", name: "Vy", role: "viewer", relVi: "cháu gái", relEn: "granddaughter", city: "Bến Tre" },
  ],
  tu: [
    { id: "ba_tu", name: "Bà Tư", role: "primary", relVi: "vợ", relEn: "wife", city: "TP.HCM" },
    { id: "khoa", name: "Khoa", role: "viewer", relVi: "con trai", relEn: "son", city: "TP.HCM" },
    { id: "ngan", name: "Ngân", role: "viewer", relVi: "con gái", relEn: "daughter", city: "Đà Nẵng" },
  ],
  control: [
    { id: "thao", name: "Thảo", role: "primary", relVi: "con gái", relEn: "daughter", city: "Cần Thơ" },
    { id: "tam", name: "Tâm", role: "viewer", relVi: "con trai", relEn: "son", city: "TP.HCM" },
  ],
};

export const VIEWER_COOKIE = "cb-viewer";

/** "hanh:minh,tu:khoa" -> { hanh: "minh", tu: "khoa" } */
export function parseViewerCookie(raw: string | undefined | null): Record<string, string> {
  const out: Record<string, string> = {};
  for (const part of decodeURIComponent(raw ?? "").split(",")) {
    const [e, m] = part.split(":");
    if (e && m) out[e.trim()] = m.trim();
  }
  return out;
}

export function serializeViewerCookie(map: Record<string, string>): string {
  return encodeURIComponent(
    Object.entries(map)
      .map(([e, m]) => `${e}:${m}`)
      .join(","),
  );
}

export function circleFor(elderId?: string): CircleMember[] {
  return CIRCLES[elderId ?? ""] ?? CIRCLES.hanh;
}

/** The chosen member for this elder (default: the primary carer). */
export function viewerFor(elderId?: string, memberId?: string | null) {
  const c = circleFor(elderId);
  const m = c.find((x) => x.id === memberId) ?? c.find((x) => x.role === "primary") ?? c[0];
  return { name: m.name, role: m.role, memberId: m.id, member: m };
}

/** Client only: the viewer chosen in the switcher (use in event handlers, not during render). */
export function currentViewer(elderId: string) {
  return viewerFor(elderId, clientViewerId(elderId));
}

/** Client only: the member chosen in the switcher for this elder (reads the cookie). */
export function clientViewerId(elderId: string): string | undefined {
  if (typeof document === "undefined") return undefined;
  const raw = document.cookie
    .split(";")
    .map((s) => s.trim())
    .find((s) => s.startsWith(`${VIEWER_COOKIE}=`));
  return parseViewerCookie(raw?.slice(VIEWER_COOKIE.length + 1))[elderId];
}

export function setClientViewer(elderId: string, memberId: string) {
  const raw = document.cookie
    .split(";")
    .map((s) => s.trim())
    .find((s) => s.startsWith(`${VIEWER_COOKIE}=`));
  const map = parseViewerCookie(raw?.slice(VIEWER_COOKIE.length + 1));
  map[elderId] = memberId;
  document.cookie = `${VIEWER_COOKIE}=${serializeViewerCookie(map)}; path=/; max-age=31536000; samesite=lax`;
}

/**
 * Identity headers for the API. On the server pass the member id read from the cookie (lib/viewer-server.ts);
 * in the browser it is read from the cookie when not given.
 */
export function actorHeaders(elderId?: string, memberId?: string | null): Record<string, string> {
  const v = viewerFor(elderId, memberId ?? (elderId ? clientViewerId(elderId) : undefined));
  return { "X-Actor": encodeURIComponent(v.name), "X-Role": v.role };
}

/** The community dashboard is read as the ward health station (a non-family role). */
export const STATION_ACTOR = { name: "Trạm Y tế Phường X", role: "health_station" };
export const stationHeaders = (): Record<string, string> => ({
  "X-Actor": encodeURIComponent(STATION_ACTOR.name),
  "X-Role": STATION_ACTOR.role,
});
