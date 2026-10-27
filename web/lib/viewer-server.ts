// Server-side half of lib/viewer.ts: reads the "Viewing as" choice from the request cookie.
import { cookies } from "next/headers";
import { VIEWER_COOKIE, parseViewerCookie, viewerFor } from "./viewer";

export async function serverViewerId(elderId: string): Promise<string | undefined> {
  const store = await cookies();
  return parseViewerCookie(store.get(VIEWER_COOKIE)?.value)[elderId];
}

export async function serverViewer(elderId: string) {
  return viewerFor(elderId, await serverViewerId(elderId));
}
