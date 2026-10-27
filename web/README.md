# Chào Bà – family app (web/)

Next.js 16 (App Router, TypeScript, Tailwind 4, Recharts) PWA for adult children, plus the 9:16 standing-screen mockup.

```bash
npm install
npm run dev                 # http://localhost:3000
npm run build && npm start  # production
NEXT_PUBLIC_API_BASE=http://localhost:8000 npm run dev   # API base (this is the default)
```

Routes: `/` Today · `/trends` · `/alerts` · `/dmaic` · `/privacy` · `/screen` (standing screen) · `/call` (opens the API's `/call?elder=<id>`).
Pick an elder with `?elder=hanh|tu|control`.

Data is read server-side from the API; if it is unreachable each page falls back to `fixtures/*.json`
(snapshots of the real API: `node scripts/snapshot-fixtures.mjs http://localhost:8000` against a freshly seeded API) and shows an "offline demo data" badge.
Icons: `node scripts/gen-icons.mjs`. Language (VI/EN) and theme are kept in localStorage.
