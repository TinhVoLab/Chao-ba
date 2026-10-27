// Class names for the elder screen's stylesheet (elder.css): s.photo -> "es-photo".
// (A plain prefixed stylesheet rather than a CSS module: this app's Turbopack CSS rule runs every *.css file
// through the Tailwind loader, which does not emit CSS-module class maps.)
export const s: Record<string, string> = new Proxy({} as Record<string, string>, {
  get: (_t, k) => (typeof k === "string" ? `es-${k}` : undefined),
});
export default s;
