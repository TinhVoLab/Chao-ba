# Chào Bà – family app (web/)

Next.js 16 (App Router, TypeScript, Tailwind 4, Recharts) PWA for adult children, plus a 9:16 standing-screen mockup (phase-2 concept, not in the prototype's scope).

```bash
npm install
npm run dev                 # http://localhost:3000
npm run build && npm start  # production
NEXT_PUBLIC_API_BASE=http://localhost:8000 npm run dev   # API base for the browser (this is the default)
CHAOBA_API_INTERNAL=http://api:8000 npm start             # optional: API base for server-side reads (Docker)
docker build -t chaoba-web --build-arg NEXT_PUBLIC_API_BASE=http://localhost:8000 .   # standalone image
```

Routes: `/` Today · `/trends` · `/alerts` · `/dmaic` · `/privacy` · `/screen` (standing screen, phase-2 concept) · `/call` (opens the API's `/call?elder=<id>`).
Pick an elder with `?elder=hanh|tu|control`.

Data is read server-side from the API; if it is unreachable each page falls back to `fixtures/*.json`
(snapshots of the real API: `node scripts/snapshot-fixtures.mjs http://localhost:8000` against a freshly seeded API) and shows an "offline demo data" badge.
Icons: `node scripts/gen-icons.mjs`. Language (VI/EN) and theme are kept in localStorage.

Writes (family call log, notes, alert acknowledgements, consent withdrawals) go through `lib/outbox.ts`: the UI shows
"saved" only after the API answers 2xx. If the API cannot be reached the write is kept in localStorage, shown as
"Chưa lưu được — đã giữ trên máy này / Not saved — kept on this device", and retried on load, when the browser comes
back online and every 30 s. A request the API refuses (4xx) is not retried and is shown as refused. Re-enabling a consent
is never queued: it must happen while the elder's agreement is current.
