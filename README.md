# Chào Bà

**A 4-minute morning call that notices when an older adult is changing, and tells the family in plain words.**
Prototype for the Future Health Digital Innovation Challenge 2026.

Út Thương, a warm Southern-Vietnamese AI companion, calls an older adult each morning over the web (prototype) or an ordinary phone (production path). From the conversation's **text and pause timings only (no audio is stored)** it tracks speech rate, pauses, filler words, vocabulary diversity, recall of yesterday's story, and self-reported symptoms and mood. After a 21-day **personal baseline**, an EWMA control chart turns these into a daily **green / yellow / red** light with a plain explanation for the adult children. A DMAIC care loop then checks whether the family's or doctor's action worked. Chào Bà reports **change relative to the person's own baseline**. It does not diagnose.

> All seeded data and all evaluation numbers are **simulated** ("Dữ liệu mô phỏng / Simulated data").
> On a simulated cohort of 200 elders: 92.0 % of injected declines flagged, median 19 days after onset,
> 0.29 false alarms per person-month. With a population norm instead of a personal baseline, sensitivity is 76.1 %. These are not clinical results.

## Quickstart

Requires Python 3.14, Node.js 20+, and Chrome or Edge for the voice call page.

```bash
python3.14 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn chaoba.server.app:app --port 8000      # API + elder call page
cd web && npm install && npm run dev                      # family app (second terminal)
```

- Elder call (hands-free simulation): http://localhost:8000/call?elder=hanh&sim=1, then press **Nghe**
- Elder call (speak Vietnamese yourself): http://localhost:8000/call?elder=hanh
- Family app: http://localhost:3000/?elder=hanh (Today · Trends · Alerts · DMAIC · Privacy · `/screen`)
- Health check: `curl localhost:8000/api/health` → `{"ok":true,"llm":"fallback"}`

**No API key needed.** Every LLM step has a deterministic fallback. Set `ANTHROPIC_API_KEY` before starting uvicorn to use Claude (conversation, post-call analysis, wording). Reset demo data with `rm data/runtime/chaoba.db` (re-seeded on start).

## Tests and data

```bash
.venv/bin/pytest -q                        # 107 tests
.venv/bin/python scripts/gen_synth.py      # regenerate data/synth/{hanh,tu,control}.json (simulated personas)
.venv/bin/python scripts/run_eval.py       # regenerate data/eval/report.{json,md} (simulated cohort, < 1 s)
```

## Repository map

| Path | Contents |
|---|---|
| `chaoba/core/` | metrics (M1–M3), personal-baseline control chart and light rules, VI/EN explanations, DMAIC cycle, synthetic data, evaluation |
| `chaoba/agent/` | Út Thương persona and prompts, call orchestrator (scripted + Claude engines), emergency spotter, guardrails, post-call analysis, demo elder simulator, LiveKit SIP adapter (untested sketch) |
| `chaoba/server/` | FastAPI app, SQLite store, Postgres/Supabase production schema with RLS (`schema.sql`), static elder call page (`static/call.html`) |
| `web/` | Next.js family app (PWA) and 9:16 standing-screen mockup |
| `data/synth/`, `data/eval/` | generated simulated personas and evaluation report |
| `scripts/` | data generation and evaluation |
| `tests/` | pytest suites for core, agent, server |
| `CONTRACT.md` | internal build contract (types, REST API) |

## Documentation

- [docs/TECHNICAL_DOCUMENTATION.md](docs/TECHNICAL_DOCUMENTATION.md): architecture, signal definitions, control-chart method, DMAIC example, evaluation, responsible AI and data governance, deployment, commercial model, **Assumptions**, **Limitations**
- [docs/DEMO_GUIDE.md](docs/DEMO_GUIDE.md): how to run it, plus a 3-minute demo script mapped to the judging criteria
- [docs/CHALLENGE_FIT.md](docs/CHALLENGE_FIT.md): judging criteria → evidence; focus-area fit
- [data/eval/report.md](data/eval/report.md): full simulated evaluation report
