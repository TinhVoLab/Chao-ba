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
- No raw audio is stored anywhere, and the Chào Bà server never receives audio: the call page sends only text + VAD
  timings. (The web prototype's speech recognition is the browser's Web Speech API, which in Chrome/Edge streams the
  microphone to the vendor's cloud; the page says so. Production: self-hosted PhoWhisper/Whisper, audio discarded
  after transcription.)
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
@dataclass class ControlConfig:  # defaults: baseline_days=21, min_valid=14, lam=0.3, L_yellow=3.0, L_red=4.0,
                                 # yellow_days=3, red_days=5, recover_days=3, sigma_floor (per metric dict)
def evaluate_series(records: list[DailyRecord], cfg: ControlConfig | None = None,
                    rebaseline_days: list[int] | None = None) -> list[DailyLight]
    # event rules (no baseline needed): record.emergency -> red, reason {"code":"emergency","day"};
    # symptoms key "concern:<category>" -> red, reason {"code":"health_concern","symptom":<category>,"day"}
    # ("concern:" keys are not counted as symptoms). Callers exclude rehearsal days before calling (see server).

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
 "family":[{"id":"lan","name":"Lan","relation":"daughter","role":"primary","honorific":"chị"}],
 "goals":["Ngủ đủ 6 tiếng","Uống thuốc huyết áp đúng giờ","Giữ trí nhớ ổn định"],
 "memory_facts":["Cây mai trước nhà sắp ra nụ"]}
```

`family[].honorific` (anh/chị/cô/chú/bà/ông, or "" = name only) is how Út Thương names the member ("chị Lan",
"bà Tư"). Synth profiles do not carry it; the server fills it in at seed time from `relation` (daughter→chị,
son→anh, wife→bà, husband→ông, …; a name that already starts with an honorific, e.g. "Bà Tư", keeps it), see
`chaoba/agent/persona.py`.

## REST API (chaoba/server, default http://localhost:8000)
CORS: `CHAOBA_CORS_ORIGINS` = comma-separated list of allowed origins; unset → any port on localhost / 127.0.0.1 /
[::1] (development). `CHAOBA_DEMO` = `1` (default) enables demo-only endpoints; `0` disables them.
All responses JSON; every elder-scoped response includes `"simulated": bool`.
Identity (no login in the prototype): the app sends `X-Actor` (percent-encoded name, e.g. `Lan`) and `X-Role`
(`primary`); defaults `family:primary` / `primary`. Reads are logged once per actor / action / resource / day with a
counter (`count`, `last_ts`); writes always get their own row.
- `GET /api/health` → `{"ok":true,"llm":"claude"|"fallback"}`
- `GET /api/elders` → `[{id, display_name, name_en, age, province, light, simulated}]`
- `GET /api/elders/{id}` → elder profile
- `GET /api/elders/{id}/today` → `{date, day, is_today, label_vi, label_en, calls, rehearsal, emergency, light, reasons, explanation_vi, explanation_en, summary_vi, summary_en, answered, mood, channel, sharing_paused, contact:{last, days_since, nudge, nudge_after_days}, simulated}`
  (`contact.days_since` = latest call day − last family call/visit day; `nudge` when ≥ 3.
  `is_today` = the latest record is dated today; `label_vi`/`label_en` = "Cuộc gọi sáng nay"/"This morning's call",
  "Cuộc gọi hôm qua (26/10)"/"Yesterday's call (26 Oct)", else "Cuộc gọi ngày 24/10"/"Call on 24 Oct".
  `calls` = number of calls merged into that day; `rehearsal` = that day is a simulated web call (not scored);
  `emergency` = an acute emergency happened in a call that day.)
- `GET /api/elders/{id}/timeline?days=90` → `{records:[DailyRecord], lights:[DailyLight], baseline:{metric:{center,scale}}, baselines:[{from_day, to_day, window:[a,b], metrics:{metric:{center,scale}}}], events:[{day,type,label_vi,label_en}]}`
  (`baseline` = the one in force now, kept for compatibility; `baselines` = history: `from_day` first day judged against it, `window` days it was estimated from.
  Records may carry `emergency: bool` and `calls: int`; symptom keys `concern:<category>` mark a non-acute health concern.
  **Rehearsal days** (`simulated: true` and `channel: "web"`) are returned but not scored: their light is the light of
  the last scored day, with the extra reason `{"code":"rehearsal_not_scored","level":"info","scored_day":d}`.)
- `GET /api/elders/{id}/alerts` → `[{id, day, date, type, severity, severity_level, explanation_vi, explanation_en, acknowledged}]` (see *Alert types and severities*)
- `POST /api/elders/{id}/alerts/{alert_id}/ack`
- `GET /api/elders/{id}/dmaic` → compute_cycle output (phases carry `status`; `contact` = family calls/visits per week before/after the intervention and in the last 14 days)
- `GET /api/elders/{id}/notes` → `[{id, day, date, author, text, to_elder, simulated, created_at}]`, `POST /api/elders/{id}/notes` `{author, text, to_elder?}`
- `GET /api/elders/{id}/contacts?days=90` → `{contacts:[{id, day, date, member_id, member_name, kind, duration_min, source, simulated}], last, days_since, nudge, per_week_last_14_days}`
- `POST /api/elders/{id}/contacts` `{kind:"call"|"visit"|"message", member_id?, member_name?, duration_min?}` (the app posts `call` when the family taps "Gọi má")
- `GET /api/elders/{id}/privacy` → `{consents:[{kind, status:"active"|"withdrawn"|"declined", granted, granted_by, changed_by, requested_by, confirmed_by_elder_or_proxy, ts, scope_vi, scope_en,...}], consent_history:[...], access_log:[{actor, role, action, resource, ts, count, last_ts}], data_retention:{audio:"not stored", transcript_days:7, quote_days:30, speech_recognition, metrics, llm_processing}, scheduling_active}`
- `POST /api/elders/{id}/consents/{type}/withdraw` (type ∈ daily_call, voice_metrics, family_sharing, clinician_sharing, research_use),
  body `{confirmed_by_elder_or_proxy: bool, requested_by?: str, reason?: str}` → `{ok, kind, granted:false, status:"withdrawn", requested_by, confirmed_by_elder_or_proxy, scheduling_active}`.
  The consent is the elder's: unless `X-Role` is `elder_self`, the body must have `confirmed_by_elder_or_proxy: true`, else
  **400** `{"detail":{"error":"confirmation_required","field":"confirmed_by_elder_or_proxy","message_en","message_vi"}}`.
  `requested_by` defaults to the `X-Actor` name; both are stored on the consent row.
  Processing for that purpose stops at once: `daily_call` pauses scheduling exactly like an in-call opt-out (`POST /api/calls` → 409);
  `voice_metrics` stores no speech metrics for later calls; `family_sharing` makes today/timeline/alerts/dmaic return no health data
  (`sharing_paused: true`, light gray); `clinician_sharing` has no clinician view to stop in the prototype. Nothing is deleted.
- `POST /api/elders/{id}/consents/{type}/grant` re-grants; `POST /api/elders/{id}/resume` = re-grant `daily_call`.
- `GET /api/evaluation` → evaluation report JSON
- `POST /api/demo/reset[?elder=hanh]` (only while `CHAOBA_DEMO=1`, else 403) → deletes that elder's (or every elder's)
  rows and re-seeds: `{ok, reset:"hanh"|"all", elders:[...], today:{elder_id: date}}`
- `POST /api/calls` `{elder_id, channel:"web", simulated?: bool}` → `{call_id, greeting_text, phase, engine, prompt_version, day, notice_vi, notice_en}`
- `POST /api/calls/{call_id}/turns` `{text, start, end, pauses:[...]}` → `{reply_text, phase, emergency:bool, end_call:bool, event, tier}`
  `tier` ∈ `acute` (115 advised, family alerted now, call ends; `emergency: true`) | `non_acute` (the elder's own event
  clearly in the past: one confirming question, red `health_concern` alert, no 115; a "yes" escalates to `acute`) |
  `third_party` (happened to someone else: empathy only, nothing recorded) | `null`.
  `event` ∈ `emergency, health_concern, health_concern_settled, third_party, symptom_followup, opt_out, opt_out_confirm,
  opt_out_cancelled, declined, scam, medication, diagnosis` or `null`.
- `GET /api/calls/{call_id}/simulate` (demo) → `{text, pauses, duration_sec, target_sps, simulated:true}`: pauses and
  duration are calibrated to the persona's current baseline speech rate and pause ratio; the page reports
  `start`/`end = start + duration_sec`.
- `POST /api/calls/{call_id}/end` → `{metrics: CallMetrics, analysis: CallAnalysis, today: <today shape>, day, simulated, rehearsal}`
- Static elder call page: `GET /call?elder=hanh` (big single button, Web Speech API vi-VN for STT/TTS, WebAudio VAD for timings).

Seed: on startup the server loads personas `hanh`, `tu`, `control` from `chaoba.core.synth` (90 days) plus their
simulated family contact logs. **Calendar:** day indices are fixed; dates are anchored at seed time so that day 90 =
the day before the server's current date (override with `CHAOBA_END_DATE=YYYY-MM-DD`). A web call is filed under
**today's** day index and date (day 91 on the seeding day); it never creates a date after today. Several calls on one
date are **sub-calls of that day** and are merged into one record: the last valid call wins for the speech metrics,
recall/mood come from the last call that has them, `answered`/`valid`/`emergency` are OR-ed, symptom counts are a
union (max per symptom), `calls` counts them. A rehearsal (`simulated:true`, channel `web`) never overwrites a day
that has real or seeded data, and a real call replaces a rehearsal-only day. `simulated:false` only if a person spoke
or typed. Notes/contacts posted from the app get today's day index on the elder's calendar.

**Retention:** transcripts 7 days; verbatim quotes in alerts (“…”) and in stored call analyses (symptom quotes,
follow-up hooks, new-fact sentences) are replaced by "[đã xoá sau 30 ngày]" after 30 days (purged on startup and after
every call).

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
| `health_concern` | non-acute tier: the elder's own past episode (e.g. "hôm qua tui hơi tức ngực", "tui bị ngã cầu thang hôm qua"); "please check in today", no 115 | red |
| `unanswered` | consecutive unanswered calls (yellow 2 days, red 3+) | yellow / red |
| `low_mood` | mood ≤ 2 on ≥ 3 of the last 7 days | yellow |
| `light_yellow` / `light_red` | light rose without a specific reason code | yellow / red |
| `emergency` | acute tier of the emergency spotter during a call (115 advised); persisted as `DailyRecord.emergency` so the day stays red after later calls | red |
| `opt_out` | elder asked in a call to stop the daily calls | yellow |
| `scam_topic` | elder mentioned money / bank / OTP requests | yellow |

Light-rise alerts take the first non-`recovering` reason code of the day the light rose. A call that already raised
an `emergency` or `health_concern` alert raises no extra light-rise alert. Events about someone else (third-party tier)
raise no alert. Reason codes added by the server: `emergency`, `health_concern`, `rehearsal_not_scored`.
