# Chào Bà: Challenge Fit

Future Health Digital Innovation Challenge 2026. This page maps the six judging criteria (no weights published) to concrete evidence in the repository. All performance numbers are from **simulated data**.

## 1. Judging criteria → evidence

| # | Criterion | What we claim (and don't) | Evidence: file / screen / number |
|---|---|---|---|
| 1 | **Health impact & clinical relevance** | Earlier family awareness of a *sustained change relative to the person's own baseline* in speech, recall, symptoms, mood and engagement, followed by a human action. No diagnostic claim. | Problem sizing: 14.2 M aged 60+ (2024), 20.9 M by 2034 ([TECHNICAL_DOCUMENTATION §1](TECHNICAL_DOCUMENTATION.md#1-problem-and-health-impact)). Bà Hạnh story: yellow day 38 → red day 43 → doctor visit day 44 → green day 56, speech rate 4.18 → 4.61 syll/s (+10.2 %) (`data/synth/hanh.json`, family app `/dmaic?elder=hanh`). Emergency spotter → 115 instruction + red alert (`chaoba/agent/emergency.py`). Validation plan vs MoCA and clinician frailty assessment (§13). |
| 2 | **Technical depth & architecture** | Explicit, auditable signal definitions; robust personal baseline; EWMA with variance inflation; rule engine with hysteresis; layered agent safety; LLM optional. | Metric formulas (§4, `chaoba/core/metrics.py`); control chart λ = 0.3, limits 2.5/3.5, k ≈ 1.40–1.47 (§5, `chaoba/core/control_chart.py`); Mermaid architecture and sequence diagrams (§3); prompt caching + strict tool + structured output (`chaoba/agent/orchestrator.py`, `analysis.py`); **119 passing tests** (`.venv/bin/pytest -q`). |
| 3 | **Working solution & demo quality** | End-to-end runnable with no API keys: web call → metrics → light → family app. | `http://localhost:8000/call?elder=hanh&sim=1` (hands-free call); family app screens Today / Trends / Alerts / DMAIC / Privacy / Standing screen; [DEMO_GUIDE](DEMO_GUIDE.md) 3-minute script; a live call appends day 91 with a computed light. |
| 4 | **Responsible AI, safety & data governance** | No raw audio; consent per purpose (withdrawable from the app, which stops that processing) plus daily verbal consent; opt-out honoured; never diagnostic; human in the loop; false alarms reported openly; subgroup results. | No audio column + server test `test_no_audio_anywhere`; 7-day transcript expiry (`chaoba/server/db.py`); RLS for primary/viewer/clinician/elder_self (`chaoba/server/schema.sql`); access log (`/privacy`, de-duplicated per person/page/day); consent withdraw/grant API; guardrails for scam / medication / diagnosis (`guardrails.py`); blocklist + number post-check (`chaoba/core/explain.py`); fairness tables by dialect/channel and false alarms **0.29 per person-month** (`data/eval/report.md`); PDPL 91/2025/QH15, Decree 356/2025/ND-CP, Decree 98/2021 (§11.5); candid Limitations (§15). |
| 5 | **Scalability & deployment readiness** | Same orchestrator behind a browser today and LiveKit SIP tomorrow; Postgres/Supabase schema ready; stateless analytics. | `chaoba/agent/livekit_agent.py` (sketch, **untested**); `schema.sql` (Postgres + RLS + pg_cron purge); load estimate ≈ 330 concurrent calls per 10,000 elders spread over a 2-hour morning window; cost model §12.2. |
| 6 | **Commercial viability & path to pilot** | B2C subscription for adult children; B2G commune health stations; B2B insurers/hospitals (post-discharge). Cost per PSTN person-month must fall from ~US$6–14 to < 100k VND. | §12.2 cost model, §13 segments, competitors (ElliQ, Winterlight Labs, Sonde Health; based on public product descriptions, verify), staged pilot: usability (10–20 families) → validation (50–100 elders, HCMC geriatrics, STARD/TRIPOD) → service pilot. |

## 2. Focus-area fit

| Focus area | Challenge wording | How Chào Bà fits |
|---|---|---|
| **Wellbeing** | "help people understand changes in their health and wellbeing, sustain healthier behaviours, access more personalised support over time" | Daily light + plain explanation of *what changed vs her own usual*. Goals from the Define step (sleep 6 h, take BP medication on time). Daily medication reminder. Memory book and family messages to keep engagement. Personal baseline that is re-set after an intervention (DMAIC Control). |
| **Population Health** | "identify emerging health risks, strengthen prevention and screening, support timely action across communities" | Passive, low-cost screening of change across many older adults over ordinary phones. Event rules for falls, repeated symptoms and missed calls. B2G view for commune health stations (aggregate share of yellow/red, outreach list; roadmap). Validation plan with STARD/TRIPOD reporting. Subgroup (dialect/channel) monitoring. |

## 3. Challenge statement mapping (fill in once the statement is chosen)

The exact challenge statements are visible only after login on Hack2skill. When the team has chosen one, paste its key phrases into the left column and point each to evidence.

| Challenge statement requirement (paste) | Chào Bà response | Evidence (file / screen / number) | Gap / next step |
|---|---|---|---|
| _TODO: requirement 1_ | | | |
| _TODO: requirement 2_ | | | |
| _TODO: requirement 3_ | | | |
| _TODO: target users / setting_ | older adults 60+ in Vietnam and their adult children; commune health stations; post-discharge programmes | §1, §13 | |
| _TODO: data / privacy constraints_ | no raw audio, consent per purpose, 7-day transcripts, RLS, PDPL 91/2025/QH15 | §11 | cross-border LLM use (§11.5) |
| _TODO: deliverables_ | working prototype + technical documentation + assumptions + limitations | `README.md`, `docs/` | |
