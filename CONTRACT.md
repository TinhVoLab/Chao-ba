# Chào Bà – build contract (shared by all workstreams)

Prototype for the Future Health Digital Innovation Challenge 2026 (prototype due **20 Nov 2026**).
Judging criteria: health impact & clinical relevance · technical depth & architecture · working solution &
demo quality · responsible AI, safety & data governance · scalability & deployment readiness · commercial
viability & path to pilot. Every workstream should make its part demonstrable against these.

## Hard rules
- Runs with **no API keys**: every LLM call has a deterministic fallback. If `ANTHROPIC_API_KEY` is set,
  use Claude: conversation `claude-sonnet-5-5` (fallback `claude-haiku-5-5`), post-call analysis
  `claude-opus-5-5` (structured output), explanation rewording `claude-haiku-5-5`.
- Never claim diagnosis. Wording: "change relative to the person's own baseline", never "dementia",
  "sa sút trí tuệ", "trầm cảm" as a finding. All simulated data is flagged `simulated: true` and shown as
  "Dữ liệu mô phỏng / Simulated data" in the UI.
- No raw audio is stored anywhere. The browser sends only text + VAD timings.
- Python 3.14 venv at `.venv` (`.venv/bin/python`, `.venv/bin/pytest`). Installed: numpy, pandas,
  fastapi, uvicorn, pydantic, anthropic, pytest, httpx. Add deps to `requirements.txt` if you need more.
- Stay inside your own directories (ownership below). Shared types live in `chaoba/core/models.py`
  (owned by the lead; ask before changing).

## Layout and ownership
| Path | Owner | Contents |
|---|---|---|
| `chaoba/core/` | core-analytics | metrics, control chart, explanation, synthetic data, DMAIC, evaluation |
| `tests/core/` | core-analytics | pytest |
| `scripts/` | core-analytics | `gen_synth.py`, `run_eval.py` → write to `data/` |
| `data/` | generated | `data/synth/*.json`, `data/eval/report.json`, `data/eval/report.md` |
| `chaoba/agent/` | voice-agent | conversation engine, persona/prompts, emergency spotter, post-call analysis, LiveKit adapter |
| `chaoba/server/` | voice-agent | FastAPI app, SQLite store, REST API, static elder web-call page |
| `tests/server/`, `tests/agent/` | voice-agent | pytest |
| `web/` | family-app | Next.js PWA (family app + 9:16 standing-screen mockup) |
| `docs/` | docs | English technical documentation for submission |

## Core API (chaoba/core) — signatures other workstreams import
```python
# metrics.py
def count_syllables(text: str) -> int
def compute_call_metrics(turns: list[Turn], min_elder_sec: float = 45.0) -> CallMetrics

# control_chart.py
@dataclass class ControlConfig:  # defaults: baseline_days=21, min_valid=14, lam=0.3, L_yellow=2.0, L_red=3.0,
                                 # yellow_days=3, red_days=5, recover_days=3, sigma_floor (per metric dict)
def evaluate_series(records: list[DailyRecord], cfg: ControlConfig | None = None,
                    rebaseline_days: list[int] | None = None) -> list[DailyLight]

# explain.py
def explain(light: DailyLight, elder_name_vi: str, elder_name_en: str, use_llm: bool = False) -> tuple[str, str]  # (vi, en)

# synth.py
def generate_persona(key: Literal["hanh","tu","control"], days: int = 90, seed: int = 7,
                     end_date: date | None = None) -> dict
    # -> {"elder": {...profile...}, "records": [DailyRecord as dict], "notes": [...], "events": [...],
    #     "contacts": [family calls/visits], "dmaic": {...}, "simulated": True}
    # end_date re-labels dates so day `days` falls on it; values never depend on the calendar anchor.
def generate_cohort(n: int = 200, days: int = 120, seed: int = 11) -> list[dict]
    # each item like generate_persona plus "truth": {"decline": bool, "onset_day": int|None, "type": str}

# dmaic.py
def compute_cycle(records, lights, define: dict, intervention_day: int, pre_days=14, post_days=14,
                  contacts: list | None = None, contact_window=28) -> dict
    # -> {"phases": [{"phase":"define|measure|analyze|improve|control", "status":"done|current|not_started",
    #                 "day_from","day_to","summary_vi","summary_en"}],   # not_started -> day_from/day_to None
    #     "effect": {metric: {"pre": x, "post": y, "change_pct": z}}, "new_baseline_day": int|None,
    #     "contact": {"pre_per_week","post_per_week","recent_per_week", *_window} | None}

# evaluation.py
def run_evaluation(cohort: list[dict], cfg=None) -> dict  # sensitivity, specificity, median detection delay,
    # false alarms per person-month, breakdown by dialect and channel; also writes markdown via report_md()
```

## Elder profile shape (`elder` object)
```json
{"id":"hanh","display_name":"Bà Hạnh","name_en":"Mrs Hanh","honorific":"bà","self_ref":"con",
 "age":72,"province":"Bến Tre","dialect":"south","lives_alone":true,"channel_pref":"pstn",
 "conditions":["hypertension"],"medications":[{"name":"Amlodipine 5mg","time":"07:00"}],
 "family":[{"id":"lan","name":"Lan","relation":"daughter","role":"primary"}],
 "goals":["Ngủ đủ 6 tiếng","Uống thuốc huyết áp đúng giờ","Giữ trí nhớ ổn định"],
 "memory_facts":["Cây mai trước nhà sắp ra nụ"]}
```

## REST API (chaoba/server, default http://localhost:8000, CORS open for localhost:3000)
All responses JSON; every elder-scoped response includes `"simulated": bool`.
Identity (no login in the prototype): the app sends `X-Actor` (percent-encoded name, e.g. `Lan`) and `X-Role`
(`primary`); defaults `family:primary` / `primary`. Reads are logged once per actor / action / resource / day with a
counter (`count`, `last_ts`); writes always get their own row.
- `GET /api/health` → `{"ok":true,"llm":"claude"|"fallback"}`
- `GET /api/elders` → `[{id, display_name, name_en, age, province, light, simulated}]`
- `GET /api/elders/{id}` → elder profile
- `GET /api/elders/{id}/today` → `{date, day, light, reasons, explanation_vi, explanation_en, summary_vi, summary_en, answered, mood, sharing_paused, contact:{last, days_since, nudge, nudge_after_days}, simulated}`
  (`contact.days_since` = latest call day − last family call/visit day; `nudge` when ≥ 3)
- `GET /api/elders/{id}/timeline?days=90` → `{records:[DailyRecord], lights:[DailyLight], baseline:{metric:{center,scale}}, baselines:[{from_day, to_day, window:[a,b], metrics:{metric:{center,scale}}}], events:[{day,type,label_vi,label_en}]}`
  (`baseline` = the one in force now, kept for compatibility; `baselines` = history: `from_day` first day judged against it, `window` days it was estimated from)
- `GET /api/elders/{id}/alerts` → `[{id, day, date, type, severity, severity_level, explanation_vi, explanation_en, acknowledged}]` (see *Alert types and severities*)
- `POST /api/elders/{id}/alerts/{alert_id}/ack`
- `GET /api/elders/{id}/dmaic` → compute_cycle output (phases carry `status`; `contact` = family calls/visits per week before/after the intervention and in the last 14 days)
- `GET /api/elders/{id}/notes` → `[{id, day, date, author, text, to_elder, simulated, created_at}]`, `POST /api/elders/{id}/notes` `{author, text, to_elder?}`
- `GET /api/elders/{id}/contacts?days=90` → `{contacts:[{id, day, date, member_id, member_name, kind, duration_min, source, simulated}], last, days_since, nudge, per_week_last_14_days}`
- `POST /api/elders/{id}/contacts` `{kind:"call"|"visit"|"message", member_id?, member_name?, duration_min?}` (the app posts `call` when the family taps "Gọi má")
- `GET /api/elders/{id}/privacy` → `{consents:[{kind, status:"active"|"withdrawn"|"declined", granted, granted_by, changed_by, ts, scope_vi, scope_en,...}], consent_history:[...], access_log:[{actor, role, action, resource, ts, count, last_ts}], data_retention:{audio:"not stored", transcript_days:7}, scheduling_active}`
- `POST /api/elders/{id}/consents/{type}/withdraw` (type ∈ daily_call, voice_metrics, family_sharing, clinician_sharing, research_use) → `{ok, kind, granted:false, status:"withdrawn", scheduling_active}`.
  Processing for that purpose stops at once: `daily_call` pauses scheduling exactly like an in-call opt-out (`POST /api/calls` → 409);
  `voice_metrics` stores no speech metrics for later calls; `family_sharing` makes today/timeline/alerts/dmaic return no health data
  (`sharing_paused: true`, light gray); `clinician_sharing` has no clinician view to stop in the prototype. Nothing is deleted.
- `POST /api/elders/{id}/consents/{type}/grant` re-grants; `POST /api/elders/{id}/resume` = re-grant `daily_call`.
- `GET /api/evaluation` → evaluation report JSON
- `POST /api/calls` `{elder_id, channel:"web"}` → `{call_id, greeting_text, phase}`
- `POST /api/calls/{call_id}/turns` `{text, start, end, pauses:[...]}` → `{reply_text, phase, emergency:bool, end_call:bool}`
- `POST /api/calls/{call_id}/end` → `{metrics: CallMetrics, analysis: CallAnalysis, today: <today shape>}`
- Static elder call page: `GET /call?elder=hanh` (big single button, Web Speech API vi-VN for STT/TTS, WebAudio VAD for timings).

Seed: on startup the server loads personas `hanh`, `tu`, `control` from `chaoba.core.synth` (90 days) plus their
simulated family contact logs. **Calendar:** day indices are fixed; dates are anchored at seed time so that day 90 =
the day before the server's current date (override with `CHAOBA_END_DATE=YYYY-MM-DD`). A web call appends day 91
dated today (channel `web`; `simulated:false` only if a person spoke or typed). Notes/contacts posted from the app
get today's day index on the elder's calendar.

## Alert types and severities
`severity` is the light colour (`yellow` | `red`); `severity_level` maps it for clients: `red` → `critical`,
`yellow` → `warning` (anything else → `info`). `type` is:

| type | source | severity |
|---|---|---|
| `metric_trend` | one signal's EWMA beyond the yellow limit for ≥ 3 consecutive valid days | yellow |
| `metric_shift` | one signal beyond the red limit for ≥ 5 days | red |
| `multi_metric` | ≥ 2 signals in the yellow state for ≥ 5 days | red |
| `symptom_repeat` | same symptom mentioned ≥ 2× in 7 days | yellow |
| `multi_symptom` | ≥ 3 different symptoms in 7 days | red |
| `fall` | a fall reported in today's call (outside the emergency path) | red |
| `unanswered` | consecutive unanswered calls (yellow 2 days, red 3+) | yellow / red |
| `low_mood` | mood ≤ 2 on ≥ 3 of the last 7 days | yellow |
| `light_yellow` / `light_red` | light rose without a specific reason code | yellow / red |
| `emergency` | emergency spotter fired during a call (115 advised) | red |
| `opt_out` | elder asked in a call to stop the daily calls | yellow |
| `scam_topic` | elder mentioned money / bank / OTP requests | yellow |

Light-rise alerts take the first non-`recovering` reason code of the day the light rose.
