# Chào Bà: Challenge Fit

Future Health Digital Innovation Challenge 2026. This page maps the six judging criteria (no weights published) to concrete evidence in the repository. All performance numbers are from **simulated data**.

## 1. Judging criteria → evidence

| # | Criterion | What we claim (and don't) | Evidence: file / screen / number |
|---|---|---|---|
| 1 | **Health impact & clinical relevance** | Earlier family awareness of a *sustained change relative to the person's own baseline* in speech, recall, symptoms, mood and engagement, followed by a human action. No diagnostic claim. | Problem sizing: 14.2 M aged 60+ (2024), 20.9 M by 2034 ([TECHNICAL_DOCUMENTATION §1](TECHNICAL_DOCUMENTATION.md#1-problem-and-health-impact)). Bà Hạnh story: yellow day 38 → red day 43 → doctor visit day 44 → green day 56, speech rate 4.18 → 4.61 syll/s (+10.2 %; *illustrative*: written into the scripted persona, not a measured effect) (`data/synth/hanh.json`, family app `/dmaic?elder=hanh`). Emergency spotter → 115 instruction + red alert (`chaoba/agent/emergency.py`). Validation plan vs MoCA and clinician frailty assessment (§13). |
| 2 | **Technical depth & architecture** | Explicit, auditable signal definitions; robust personal baseline; EWMA with variance inflation; rule engine with hysteresis; layered agent safety; LLM optional. | Metric formulas (§4, `chaoba/core/metrics.py`); control chart λ = 0.3, limits 2.5/3.5, k ≈ 1.40–1.47 (§5, `chaoba/core/control_chart.py`); Mermaid architecture and sequence diagrams (§3); prompt caching + strict tool + structured output (`chaoba/agent/orchestrator.py`, `analysis.py`); **119 passing tests** (`.venv/bin/pytest -q`). |
| 3 | **Working solution & demo quality** | End-to-end runnable with no API keys: web call → metrics → light → family app. | `http://localhost:8000/call?elder=hanh&sim=1` (hands-free call); family app screens Today / Trends / Alerts / DMAIC / Privacy, plus the standing screen (a phase-2 concept mockup, not in scope); [DEMO_GUIDE](DEMO_GUIDE.md) 3-minute script; a live call appends day 91 with a computed light. |
| 4 | **Responsible AI, safety & data governance** | No raw audio; consent per purpose (withdrawable from the app, which stops that processing) plus daily verbal consent; opt-out honoured; never diagnostic; human in the loop; false alarms reported openly; subgroup results. | No audio column + server test `test_no_audio_anywhere`; 7-day transcript expiry (`chaoba/server/db.py`); RLS for primary/viewer/clinician/elder_self (`chaoba/server/schema.sql`); access log (`/privacy`, de-duplicated per person/page/day); consent withdraw/grant API; guardrails for scam / medication / diagnosis (`guardrails.py`); blocklist + number post-check (`chaoba/core/explain.py`); fairness tables by dialect/channel and false alarms **0.19 (95 % CI 0.16–0.22) per person-month** on a held-out simulated cohort; chance-corrected sensitivity **64.9 % (57.1–72.5)**, and an earlier inflated "92 %" figure withdrawn and explained (`data/eval/report.md`, operating curve `data/eval/operating_curve.svg`); scripted pre/post effects flagged `effect_illustrative` in the DMAIC API; PDPL 91/2025/QH15, Decree 356/2025/ND-CP, Decree 98/2021 (§11.5); candid Limitations (§15). |
| 5 | **Scalability & deployment readiness** | Same orchestrator behind a browser today and LiveKit SIP tomorrow; production Postgres schema with RLS; containerised stack; stateless analytics. We do not claim a production deployment: the API still uses SQLite and the SIP adapter is untested. | `docker compose up --build` (API + family app + Postgres loading `schema.sql`; `Dockerfile`, `web/Dockerfile` standalone, `docker-compose.yml`); RLS smoke test `deploy/rls_test.sql` + `tests/deploy/` (skips without Docker; **not yet run in the build environment**, daemon was off); env `CHAOBA_CORS_ORIGINS`, `NEXT_PUBLIC_API_BASE`, `CHAOBA_API_INTERNAL`; family-app writes kept on the device and retried when the API is unreachable; `chaoba/agent/livekit_agent.py` (sketch, **untested**); load estimate ≈ 330 concurrent calls per 10,000 elders over a 2-hour morning window ([TECHNICAL_DOCUMENTATION §12](TECHNICAL_DOCUMENTATION.md#12-scalability-and-deployment)). |
| 6 | **Commercial viability & path to pilot** | B2C subscription for adult children; B2G commune health stations; B2B insurers/hospitals (post-discharge). The < 100k VND per person-month target is met on the web channel; on the phone only at 5 calls/week or with telephony ≤ ≈ 500 VND/min. All supplier prices are labelled assumptions, not quotes. | Reproducible per-call cost model `deploy/cost_model.py` (tokens per phase measured from a scripted call; §12.3): web + Haiku ≈ 45,000 VND/person-month; domestic SIP + Sonnet + Opus ≈ 241,000; domestic SIP + Haiku + domestic STT/TTS ≈ 137,000 daily / ≈ 99,500 at 5 calls/week. Price hypotheses and margins §13; competitors (ElliQ, Winterlight Labs, Sonde Health; public product descriptions, verify); staged pilot: usability (10–20 families) → validation (50–100 elders, HCMC geriatrics, STARD/TRIPOD) → service pilot. |

## 2. Focus-area fit

| Focus area | Challenge wording | How Chào Bà fits |
|---|---|---|
| **Wellbeing** | "help people understand changes in their health and wellbeing, sustain healthier behaviours, access more personalised support over time" | Daily light + plain explanation of *what changed vs her own usual*. Goals from the Define step (sleep 6 h, take BP medication on time). Daily medication reminder. Memory book and family messages to keep engagement. Personal baseline that is re-set after an intervention (DMAIC Control). |
| **Population Health** | "identify emerging health risks, strengthen prevention and screening, support timely action across communities" | Passive, low-cost screening of change across many older adults over ordinary phones. Event rules for falls, repeated symptoms and missed calls. B2G view for commune health stations (aggregate share of yellow/red, outreach list; roadmap). Validation plan with STARD/TRIPOD reporting. Subgroup (dialect/channel) monitoring. |

## 3. Mapping to the chosen challenge statement

The exact challenge statements are visible only after login on Hack2skill and none has been chosen yet. When one is chosen:

- [ ] Paste the statement's key requirements (target users, setting, required outputs, data constraints, deliverables) into a table below the pre-filled mapping for its focus area.
- [ ] For each requirement, point to one piece of evidence (file, screen, number) from §1, or write the gap and next step. Do not stretch: an unmet requirement is listed as a gap.
- [ ] Check wording against the statement's own terms (e.g. "screening", "prevention", "personalised support") and keep the no-diagnosis rule: Chào Bà reports change against the person's own baseline.
- [ ] Re-check that every number quoted is labelled simulated, and that cost figures cite §12.3 assumptions.
- [ ] Update the README headline and the demo script (DEMO_GUIDE) to lead with the statement's main requirement.

### 3.1 Pre-filled: Wellbeing

Published focus-area description: "help people understand changes in their health and wellbeing, sustain healthier behaviours, access more personalised support over time".

| Phrase | Chào Bà response | Evidence | Gap / next step |
|---|---|---|---|
| understand changes in their health and wellbeing | Daily light with a plain VI/EN explanation of what changed against the person's own usual; trends with the usual range drawn | Family app Today and Trends (`/`, `/trends`); `chaoba/core/explain.py` | Explanations go to the family; an elder-facing summary is only in the phase-2 standing-screen concept |
| sustain healthier behaviours | Goals set in the Define step (sleep 6 h, blood-pressure medication on time); medication reminder read from the profile at the end of every call; family contact rhythm counted before/after a care plan | `/dmaic`; `chaoba/agent/orchestrator.py` (closing); contact log | Behaviour change is not measured beyond self-report and family contacts |
| access more personalised support over time | Personal baseline re-set after an intervention; memory book and follow-up hooks personalise each call; family notes passed on in the next call | §5, §6, §7 of the technical documentation | Long-term engagement is untested (pilot metric: call completion and opt-out over 4–6 weeks) |

### 3.2 Pre-filled: Population Health

Published focus-area description: "identify emerging health risks, strengthen prevention and screening, support timely action across communities".

| Phrase | Chào Bà response | Evidence | Gap / next step |
|---|---|---|---|
| identify emerging health risks | Sustained change in speech, recall, symptoms, mood and engagement, judged against each person's baseline; event rules for falls, repeated symptoms and missed calls | §5 light rules; alert types in `CONTRACT.md`; simulated cohort results (`data/eval/report.md`) | Signals are not clinically validated; validation study vs MoCA and clinician frailty assessment (§13) |
| strengthen prevention and screening | Passive, low-cost daily check over ordinary phones (production path) for people who would not use an app | Cost model §12.3 (phone ≈ 99,500 VND/person-month at 5 calls/week, assumptions labelled) | "Screening" for a named condition would bring medical-device rules (Decree 98/2021); we claim change detection only |
| support timely action across communities | Red/yellow alerts with a next step for the family; DMAIC loop records the action and checks its effect; B2G outreach list for commune health stations (roadmap) | `/alerts`, `/dmaic`; §13 segments | Population dashboard and commune workflow are not built; needs a B2G pilot site and data-sharing agreement |
