/** API address the browser uses (inlined at build time). */
export const API_BASE = (process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000").replace(/\/$/, "");

/**
 * API address for server-side reads. In Docker the Next server reaches the API by its service name
 * (CHAOBA_API_INTERNAL=http://api:8000) while the browser still uses NEXT_PUBLIC_API_BASE. Read at request time.
 */
export function serverApiBase(): string {
  return (process.env.CHAOBA_API_INTERNAL || API_BASE).replace(/\/$/, "");
}
