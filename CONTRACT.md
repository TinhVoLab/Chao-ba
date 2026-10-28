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
  after transcription.) **Exception, opt-in only:** the optional Gemini Live voice engine (`engine=gemini`, needs Google
  credentials) streams call audio *through* the server to Google; it is relayed frame by frame and never stored (no
  audio column, no file); the page and the privacy endpoint say so.
- Python 3.14 venv at `.venv` (`.venv/bin/python`, `.venv/bin/pytest`). Installed: numpy, pandas,
  fastapi, uvicorn, pydantic, anthropic, pytest, httpx, google-genai (pinned 2.33.0; optional Gemini Live engine).
  Add deps to `requirements.txt` if you need more.
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
- `GET /api/health` → `{"ok":true,"llm":"claude"|"fallback","voice":"browser"|"gemini"}` (`voice` = default voice engine of web calls)
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
  (`sharing_paused: true`, light gray); `clinician_sharing` removes the elder from the community dashboard (`/api/community/overview`). Nothing is deleted.
- `POST /api/elders/{id}/consents/{type}/grant` re-grants; `POST /api/elders/{id}/resume` = re-grant `daily_call`.
- `GET /api/evaluation` → evaluation report JSON
- `POST /api/demo/reset[?elder=hanh]` (only while `CHAOBA_DEMO=1`, else 403) → deletes that elder's (or every elder's)
  rows and re-seeds: `{ok, reset:"hanh"|"all", elders:[...], today:{elder_id: date}}`
- `POST /api/calls` `{elder_id, channel:"web", simulated?: bool, engine?: "gemini"|"browser"}` → `{call_id, greeting_text, phase, engine,
  prompt_version, day, notice_vi, notice_en, voice}`. `engine` (request) picks the voice engine; default `CHAOBA_VOICE_ENGINE`
  (`browser`). `voice` = `{engine:"browser", requested, note_vi?, note_en?, reason?}` or, when Gemini Live is configured,
  `{engine:"gemini-live", requested:"gemini", model, voice, mode:"developer"|"vertex"|"fake", input_rate:16000, output_rate:24000,
  ws:"/ws/voice/{call_id}"}` (then the response's `engine` is `gemini-live`). Never contains a key.
- `POST /api/calls/{call_id}/turns` `{text, start, end, pauses:[...]}` → `{reply_text, phase, emergency:bool, end_call:bool, event, tier}`
  `tier` ∈ `acute` (115 advised, family alerted now, call ends; `emergency: true`) | `non_acute` (the elder's own event
  clearly in the past: one confirming question, red `health_concern` alert, no 115; a "yes" escalates to `acute`) |
  `third_party` (happened to someone else: empathy only, nothing recorded) | `null`.
  `event` ∈ `emergency, health_concern, health_concern_settled, third_party, symptom_followup, opt_out, opt_out_confirm,
  opt_out_cancelled, declined, scam, medication, diagnosis` or `null`.
- `GET /api/calls/{call_id}/simulate` (demo) → `{text, pauses, duration_sec, target_sps, simulated:true}`: pauses and
  duration are calibrated to the persona's current baseline speech rate and pause ratio; the page reports
  `start`/`end = start + duration_sec`.
- `POST /api/calls/{call_id}/end` → `{metrics: CallMetrics, analysis: CallAnalysis, today: <today shape>, day, simulated, rehearsal, voice?}`
  (`voice` only for Gemini Live calls: the stored voice metadata, see *Voice WebSocket*)
- Elder standing screen (`chaoba/server/elder_ui.py`; the web app's `/screen`; writes are the elder's self-reports, never scored):
  `GET /api/elders/{id}/screen` → `{date, day, medications:[{name, time, timed, status:"taken"|"not_yet"|null, answered_at}], messages:[to_elder notes, last 7 days], mood_today, game_plays_today, opted_out, simulated}`;
  `POST|GET /api/elders/{id}/medication_log` `{status:"taken"|"not_yet", medication?, time?}`; `POST|GET /api/elders/{id}/mood_checkin` `{mood:"happy"|"neutral"|"sad"}`;
  `POST|GET /api/elders/{id}/game_plays` `{game:"ca_dao"|"family_names", item_id, correct, choice?}` (GET `?days=14` → entries/plays + today). `source` = `elder_screen` when `X-Role: elder_self`.
  `POST /api/demo/reset` also clears these rows. The screen's video call posts a normal `POST /api/elders/{id}/contacts`.
- **Sổ ký ức (memory book) + prevention activities** (`chaoba/server/memories.py`; tables `memory_story`, `activity_log`;
  text only, no audio). Role: `X-Role: elder_self` (or `elder`) = the elder; any other role = family.
  - `GET /api/elders/{id}/memories` → `{elder_id, display_name, name_en, honorific, viewer:"elder"|"family", stories:[Story],
    themes:[{theme, label_vi, label_en, count}], shared_count, private_count, total, sharing_paused, audio:{stored:false, note_vi, note_en}, simulated}`.
    Family roles get **only shared stories** (private ones appear only in `private_count`: no title, no text); the elder gets all.
    While `family_sharing` is withdrawn, family roles get `stories: []`, `sharing_paused: true`.
    `Story = {id, day, date, question_id, theme, theme_vi, theme_en, era:{label_vi, label_en, decade}, title_vi, title_en, text_vi,
    text_en, translation:"human"|"llm"|"gist", people:[{vi,en}], places:[str], word_count, shared, consent:{answer:"yes"|"no"|"unclear"|"not_asked",
    asked_in_call, by, ts, history:[{shared, by, role?, requested_by?, confirmed_by_elder_or_proxy?, ts}]}, source:"call"|"simulated", simulated}`.
    Themes: childhood, hometown, food, work, love, wedding, family, festivals, hardship, friends.
  - `GET /api/elders/{id}/memories/export?lang=vi|en|both` → `text/html` printable memoir of the **shared** stories only: title page
    "Sổ ký ức của Bà Hạnh" / "Memory book of Mrs Hanh", one chapter per theme (era order inside), print CSS, simulated badge.
  - `POST /api/elders/{id}/memories/{mid}/share` | `/unshare`, body `{confirmed_by_elder_or_proxy?: bool, requested_by?: str}` →
    `{ok, id, shared, consent}`. Unless `X-Role` is `elder_self`, the body must carry `confirmed_by_elder_or_proxy: true`, else **400**
    `{"detail":{"error":"confirmation_required", ...}}` (same rule as consent withdrawal); 404 for an unknown story. Each change is appended
    to `consent.history` and to the access log (`share_memory` / `unshare_memory`).
  - `GET /api/elders/{id}/activities` → `{games:{played, success_rate, success_rate_first_4_weeks, success_rate_last_4_weeks, current_level (1-3),
    by_category:[{category, label_vi, label_en, played, success_rate}], trend:[{week, day_from, day_to, played, success_rate, mean_level}]},
    screen_games:{played, correct_rate, played_last_14_days, by_game} (read from elder_ui's `elder_game_play`), nudges:{delivered, by_category:[{category,
    label_vi, label_en, count}]}, life_questions:{asked, stories}, associations:[{activity, label_vi, label_en, days_with, days_without,
    next_day_mood_with, next_day_mood_without, mood_diff, next_day_poor_sleep_with, next_day_poor_sleep_without}], association_note_vi/en
    ("association, not causation"), improve:{day, date, focus, focus_labels, label_vi, label_en, plan_nudges_delivered, mood_before, mood_after,
    poor_sleep_before, poor_sleep_after} | null, narrative:{stories, words_early, words_recent, change_pct, note_vi, note_en} | null (exploratory,
    not used by the light), difficulty_rule_vi/en, simulated}`. Success rate counts a partial answer as ½. `{sharing_paused:true, simulated}` for family
    roles while `family_sharing` is withdrawn.
  - `POST /api/calls/{id}/end` additionally returns `memory_book:{story_id, shared, title_vi?, title_en?, game:{category, level, outcome}|null, nudge}`.
  - Call flow (prompt `ut-thuong-2026.10.3`; `.4` adds the family-card relay slot after consent, see below): story phase = follow-up hook (if any) → today's life-story question (no repeats) → its follow-up →
    "Bà cho con kể lại chuyện này cho chị Lan nghe được hông?" (yes → shared; no / unclear / not asked → private) → closing: optional memory game
    (2 days in 3; levels 1-3, a miss makes the next one easier, two successes harder), medication reminder, family message, one habit nudge, goodbye.
  - Seed: 11 / 11 / 8 simulated stories for hanh / tu / control (mixed shared / private), activity log over the 90 days, and Bà Hạnh's day-44
    care plan (`care_plan` row: walk + sunlight, water, regular sleep, call an old friend). `POST /api/demo/reset` re-seeds them.
- **Family coordination** (`chaoba/server/family.py`; tables `care_circle`, `care_rota`, `care_task`, `topic_asked`; family app `/family`).
  Identity: `X-Actor` is matched (case/diacritics-normalised) to a care-circle member; the effective role is the *lower* of `X-Role`
  and the member's stored role (`primary` > `viewer`), so a header cannot raise it. `X-Role: elder_self` = the elder.
  `clinician` / `health_station` → **403** `{"detail":{"error":"family_only",...}}`. Every request is written to the access log.
  Seeded circles (simulated): hanh = Lan (primary, TP.HCM), Minh (viewer, Hà Nội), Vy (viewer, Bến Tre); tu = Bà Tư (primary), Khoa, Ngân;
  control = Thảo (primary), Tâm. Weekday indices are Mon=0 … Sun=6.
  - `GET /api/elders/{id}/family` → `{viewer, members, rota, tasks, suggestions, synthesis, access, sharing_paused, simulated}` (one call for the page).
    `viewer = {member_id, name, role, permissions:{full_view, edit_rota, manage_tasks, see_access_log}}`;
    `members = [{id, name, relation, relation_vi, role:"primary"|"viewer", city}]`.
  - `GET /api/elders/{id}/family/timeline?days=14` (1–120) → `{items:[{id, kind, day, date, actor, title_vi, title_en, text_vi, text_en, redacted,
    ...}], upcoming:[appointment tasks], from_day, to_day, viewer, members, sharing_paused, simulated}`, newest first.
    `kind` ∈ `call` (morning-call summary; `light`, `rehearsal`), `note` (`to_elder`; `text_lang:"vi"`), `contact` (`contact_kind`), `alert`
    (`severity`, `alert_type`, `acknowledged`), `event` (care_event: medication change, doctor visit, re-baseline …; `event_type`), `task`
    (created / done; `task_id`, `task_kind`), `rota` (rota changed), `self_report` (the elder's own screen taps: medication taken / not yet, mood;
    `report_kind`; never scored), `gap` (nobody called for ≥ 3 days; `severity:"yellow"`).
    **Viewer filtering:** other people's notes come back with `redacted:true` and a placeholder text; alert texts have verbatim quotes replaced by
    `“…”` (`redacted:true`). While `family_sharing` is withdrawn, `call`, `alert`, `event` and `self_report` items are omitted.
  - `GET /api/elders/{id}/family/synthesis?days=7` → `{from_day, to_day, from_date, to_date, days, items:[{topic, label_vi, label_en, count, ai,
    people:[names], sources, first_day, last_day, mentions:[{source:"ai"|"note", who, date, day}], text_vi, text_en}], summary_vi, summary_en,
    contact_vi, contact_en, engine:"rules"|"claude", sharing_paused, simulated}`. Sources: symptom keys of answered day records (AI) + family notes
    (negation-aware `extract_symptoms`; `to_elder` notes skipped). Topics: pain (body part named, e.g. "đau lưng"), insomnia, dizziness, skipped_meal,
    fall, sadness, missed_medication. With a key, Claude Haiku rewording must pass `explain.postcheck` (no new numbers, no blocklisted words).
  - `GET /api/elders/{id}/family/rota` → `{week:[{weekday, weekday_vi, weekday_en, member_id, member_name}], today:{…, date, done, anyone_called},
    history:[last 7 days: {date, day, member_id, member_name, contacted, by_assignee, contacts:[{member_name, kind}], before_rota}],
    gap:{days_since, nudge, threshold:3, last}, created_day, mine?:{weekdays, your_turn, next:{date, weekday, in_days}|null}, nudge_vi, nudge_en}`.
    `your_turn` = today is the viewer's weekday and they have not logged a contact today; `gap` reuses the Today contact status (0 once anyone
    logged a contact today).
  - `POST /api/elders/{id}/family/rota` `{assignments:{"0":"lan", "6": null, …}}` → `{ok, …rota}`. Primary only (**403** `primary_only`);
    422 for a weekday outside 0–6 or an unknown member; `null` clears the day.
  - `GET /api/elders/{id}/family/tasks?include_done=true` → `{tasks:[Task], kinds, simulated}`;
    `Task = {id, kind:"appointment"|"medicine"|"visit"|"other", title_vi, title_en, assignee_id, assignee_name, due_date, overdue, done, done_by,
    done_day, created_by, created_day, simulated}` (tasks created in the app keep the typed title in both fields).
  - `POST /api/elders/{id}/family/tasks` `{kind, title, assignee_id?, due_date?: "YYYY-MM-DD"}` → `{ok, …Task}` (primary or viewer; 422 on bad kind,
    empty/long title, unknown assignee, bad date; elder_self 403).
  - `POST /api/elders/{id}/family/tasks/{task_id}` `{done?, assignee_id?, due_date?, title?}` → `{ok, …Task}`: primary any task; viewer only tasks
    assigned to or created by them (else **403** `not_allowed`); 404 unknown task. `DELETE …/tasks/{task_id}`: primary or the creator.
  - `GET /api/elders/{id}/family/suggestions` → `{suggestions:[Suggestion] (≤ 4, fresh), already_asked:[Suggestion], window_from_day, sharing_paused,
    simulated}`; `Suggestion = {key, source:"call"|"memory"|"synthesis", day, text_vi, text_en, asked_by:[{name, date, member_id, how:"asked"|"note",
    you}]}`. Keys: `care:<topic>`, `hook:<text>`, `act:<activity>`, `fact:<normalised fact>`.
  - `POST /api/elders/{id}/family/suggestions/asked` `{topic_key}` → `{ok, topic_key, member_name, day, date}` (moves the topic to `already_asked`
    for everyone for 7 days).
  - `GET /api/elders/{id}/family/access?days=7` → `{days, people:[{actor, role, label_vi, label_en, views, writes, last_ts}], simulated}` (the elder sees who looked).
    `label_*` is the display name: the member's name for family (a default `family:<role>` actor is mapped to that member
    and merged with them); the elder's own reads (`elder_self`, e.g. actor `elder:hanh`)
    are merged into one row labelled by kin ("Má (chính bà)" / "Mom (herself)").
- **Family micro-interactions "Gửi yêu thương"** (`chaoba/server/kudos.py`; table `kudos`; family app Today + `/family`,
  elder screen `/screen`). Identity as for `/family` (care circle; a header can lower, never raise a role); `X-Role:
  elder_self` = the elder; `clinician` / `health_station` → **403** `family_only`. All cards are text only.
  `Kudos = {id, day, date, kind:"checkin"|"love"|"advice"|"care_tip"|"message", template_id|null, icon, sender_id,
  sender_name, sender_relation, elder_self_vi ("má"/"bà"/"ông": how the elder names herself to this sender), text_vi,
  text_en, text_lang, custom, health, choices:[{id, vi, en}], status:"sent"|"seen"|"replied", status_vi/en, sent_at,
  sent_time ("07:20", Vietnam time), seen_at, seen_via:"screen"|"call"|null, replied_at, reply_time, reply:{choice?,
  choice_vi?, choice_en?, text?, heart?, via, at, simulated}|null, reply_hidden, reply_vi/en ("Má trả lời: Ăn rồi con ·
  07:42"), heart, redacted, folk_note, story:{id, saved, declined?}|null, simulated}`.
  - `GET /api/elders/{id}/kudos/catalog` → `{viewer, address_vi, address_en, templates:[{id, kind, icon, health, label_vi,
    label_en, text_vi, text_en, choices, folk_note}], groups, limit_per_day:6, sent_today, remaining_today, max_text:160,
    voice_note:{available:false,...}, self_report, can_send, simulated}`; texts follow the sender's relation ("Con nhớ má",
    "Cháu nhớ bà", "Ba ăn cơm chưa?"). Templates: checkin `ate|slept|feeling|meds`, love `love|miss|goodnight|thanks`,
    advice `canh_chua|cough|mai`, care_tip `water|sun|walk|rest`.
  - `POST /api/elders/{id}/kudos` `{kind, template_id? | text?, from?}` → `{ok, kudos, sent_today, remaining_today}`.
    Family only (elder_self **403** `family_sender_only`); `from` must be the caller (else **403** `not_allowed`).
    `checkin` / `love` need a template; `advice`, `care_tip`, `message` take a template or 1–160 characters of text.
    Free text passes `explain.contains_blocked`, the diagnosis-request detector and a medication / dose filter:
    **422** `{"detail":{"error":"diagnosis_words"|"medical_advice"|"money_topic", "field":"text", message_vi, message_en}}`.
    At most 6 cards per sender per day: **429** `{"detail":{"error":"daily_limit", limit, message_vi, message_en}}`.
  - `GET /api/elders/{id}/kudos?box=inbox|sent|family&days=28&pending=0|1` → `{box, items:[Kudos], viewer, date,
    micro_7d, sent_today, remaining_today, limit_per_day, sharing_paused, self_report, simulated}`. `inbox` = elder_self
    only (else **403** `elder_only`); with `pending=1` the queue (oldest first): not replied, not snoozed, and one-way cards
    not yet seen. `sent` = the caller's cards, `family` = everyone's (a `viewer` gets other people's free text as
    `redacted: true`, "Lời nhắn riêng"); lists are newest first. While `family_sharing` is withdrawn, family roles get
    check-in answers removed (`reply: null`, `reply_hidden: true`); hearts and advice stay.
  - `POST /api/elders/{id}/kudos/{kid}/seen` `{via?: "screen"|"call", snooze_minutes?: 1–1440}` (elder_self only) →
    `{ok, kudos}`. A snoozed card ("Để sau") leaves the screen queue until then; a seen card is no longer relayed in calls.
  - `POST /api/elders/{id}/kudos/{kid}/reply` `{choice? | text? | heart?, via: "screen"|"call"}` (elder_self only) →
    `{ok, kudos, can_save}`; `choice` must be one of the card's choices (advice also `call_back`), else **422**; empty → **422**.
    A heart can be added to an answered card.
  - `POST /api/elders/{id}/kudos/{kid}/save` `{confirmed_by_elder_or_proxy?, decline?}` → `{ok, id, story_id, title_vi,
    title_en}`: saves an advice answer as a **shared** memory-book story, theme `advice` ("Lời má dạy: nấu canh chua"; the
    `/memories` theme label is "Lời má dạy" / "Lời ba dạy"). Unless `X-Role` is `elder_self`, **400**
    `confirmation_required` without `confirmed_by_elder_or_proxy: true`; **409** `nothing_to_save` if the card is not an
    answered advice question; idempotent. `{decline: true}` (elder only) records "keep it private".
  - **Call relay** (prompt `ut-thuong-2026.10.4`): `build_context` adds unseen cards from the last 3 days as
    `DailyContext.relay`; right after the consent answer the call says them ("Dạ. Cháu Vy gửi thương bà nè. Chị Lan hỏi bà
    nấu canh chua sao cho ngon, bà chỉ giùm với?", ≤ 2 questions, advice first), takes the next elder turn as the reply and
    confirms "Dạ, con nhắn lại cho chị Lan liền nha." `POST /api/calls/{id}/end` additionally returns
    `kudos_relay:[{id, choice?, text?, seen?, reply?}]`; replies are stored with `via: "call"` (`simulated` on rehearsals).
  - **Never counted as calls.** `today.contact` / `contacts` / rota add `micro_7d` (cards sent in the last 7 days) but
    `days_since` and `nudge` still count only `family_contact` calls and visits. `GET /dmaic` `contact` adds
    `micro_pre_per_week`, `micro_post_per_week`, `micro_recent_per_week`, `weekly:[{day_from, day_to, date_from, date_to,
    calls_visits, micro}]` (6 weeks), `micro_note_vi/en`. The family timeline adds `kind:"kudos"` items (`kudos_id`,
    `kudos_kind`, `status`, `heart`, `icon`) titled "Lan gửi má: “Má ăn cơm chưa?”" with the reply as text.
  - Seed: simulated cards with replies for hanh (16, Lan / Minh / Vy, incl. the canh chua answer saved as "Lời má dạy"),
    tu (5), control (3); none pending. `POST /api/demo/reset` clears and re-seeds them.
- **Community dashboard** (`chaoba/server/community.py`; family app `/community`).
  `GET /api/community/overview` with `X-Role: clinician | health_station` (else **403** `{"detail":{"error":"clinician_only",...}}`) →
  `{ward:{name_vi:"Phường X, TP.HCM (mô phỏng)", name_en, elders, sharing, not_sharing, demo_personas}, as_of, counts:{red, yellow, green, gray},
  lives_alone, missed_contact, visit_list:[VisitRow], trend:[{date, red, yellow, green, gray}] (30 days), interventions:[{intervention:
  "family_calls"|"station_visit"|"clinic_visit"|"none", label_vi, label_en, episodes, open, recovered, rate|null, median_days_to_green|null, enough}],
  method:{recovery_days:21, missed_contact_days:7, checkin_no_contact_days:10, trend_days:30, cohort:{n:60, days:120, seed:2026}},
  association_note_vi/en, disclaimer_vi/en, simulated:true}`.
  `VisitRow = {pid, label:"N.T.H. · 72 · Khu phố 3", initials, age, area, light, days_in_state, since_date, reasons_vi[], reasons_en[],
  days_since_contact, missed_contact, lives_alone, demo_persona, group:"red"|"yellow"|"check_in", rank}`. Order: red, then yellow (each by days in
  state ↓, missed contact, lives alone), then `check_in` (green/gray, lives alone, no family contact ≥ 10 days). Pseudonymised: no names, ids or
  addresses. Ward = 60 elders from `generate_cohort(n=60, days=120, seed=2026)` re-dated to end yesterday + the 3 personas; only elders with active
  `clinician_sharing` consent appear. Each request logs `read_community` on every sharing persona's access log. Interventions are association
  only (assigned at random in the simulation).
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

## Voice WebSocket (optional Gemini Live engine; chaoba/server/voice.py, chaoba/agent/gemini_live.py)

Server-side proxy: browser ↔ `WS /ws/voice/{call_id}` ↔ Gemini Live (google-genai async). The browser never sees a key.
Credentials: `GEMINI_API_KEY` (Gemini Developer API) or `GOOGLE_GENAI_USE_VERTEXAI=true` + `GOOGLE_CLOUD_PROJECT`
(+ `GOOGLE_CLOUD_LOCATION`, default `us-central1`) with Application Default Credentials; `CHAOBA_GEMINI_FAKE=1` = offline fake
(tests), `=fail` = always fails (fallback demo). Settings: `CHAOBA_VOICE_ENGINE`, `CHAOBA_GEMINI_MODEL` (`gemini-3.8-live`),
`CHAOBA_GEMINI_VOICE` (`Sulafat`), `CHAOBA_GEMINI_LANGUAGE_CODE` (unset; `vi-VN` to send it), `CHAOBA_GEMINI_SILENCE_MS` (1000).

- `GET /api/voice/config` → `{default_engine, configured_default, gemini:{available, mode, reason, model, voice, input_rate, output_rate}}`
- Open the socket only for a call whose `POST /api/calls` returned `voice.engine == "gemini-live"`; otherwise the server sends
  `{"type":"error","error":"unknown_call"}` and closes (4404).
- **Browser → server**
  - binary: raw 16-bit little-endian mono PCM, 16 kHz (≈100 ms frames). Relayed to Gemini, counted, never stored.
  - `{"type":"vad","state":"speech"|"silence","t":sec}`: WebAudio VAD transitions on the page clock (seconds since call start;
    silence sent after ≥ 0.3 s). The server turns them into the elder turn's `start`/`end`/`pauses` (gaps ≥ 0.4 s).
  - `{"type":"text","text":str,"start"?:sec,"end"?:sec,"pauses"?:[sec]}`: typed or simulated elder line (no audio).
  - `{"type":"playback","state":"idle"}`: the page finished playing Út Thương's audio (silence timer starts).
  - `{"type":"end"}`: stop (the page then calls `POST /api/calls/{id}/end` as usual).
- **Server → browser**
  - binary: raw 16-bit little-endian mono PCM, 24 kHz, Út Thương's voice. Play in order; drop the queue on `interrupt`.
  - `{"type":"ready","engine":"gemini-live","model","voice","input_rate":16000,"output_rate":24000}`
  - `{"type":"transcript","who":"agent"|"elder","text","final":bool,"greeting"?:true}`: captions (Gemini input/output
    transcription, or the typed line). Interim updates replace the current caption until `final`.
  - `{"type":"turn", ...}`: same fields as `POST /turns` (`reply_text, phase, emergency, end_call, event, tier`) once the
    orchestrator has processed an elder turn (banner on `emergency`, concern note on `tier:"non_acute"`).
  - `{"type":"interrupt","reason":"barge_in"|"safety"|"correction"}`: stop playback at once.
  - `{"type":"agent_done"}`: Út Thương finished a turn (the page sends the next typed/simulated line after playback).
  - `{"type":"say","text","reason":"safety_fallback"}`: Gemini did not start the safety message in time; say it with the
    browser's own TTS (then `ended` follows).
  - `{"type":"ended","reason":"completed"|"emergency"|"client_end","end_reason"}`: drain playback, then `POST /end`.
  - `{"type":"fallback","reason","note_vi","note_en"}`: Gemini unavailable (connect failure, disconnect, no credentials):
    continue the **same call** with the browser pipeline (`POST /turns`), show the note. A closed socket means the same.
- Gemini tools (declared by the server): `next_step()` → `{mode:"exact"|"adapt"|"silent", line, phase, end_call_after}`,
  `report_answer(kind, value)`, `flag_emergency(category, quote, acute)` (layer 2, `Orchestrator.handle_flag`), `end_call()`.
  The recall answer is never sent to the model (`build_context_block(hide_recall_answer=True)`).
- Voice metadata (`call_session.voice_json`, also `voice` in `/end`): `{engine:"gemini-live", model, voice, language_code, mode,
  silence_ms, time_to_first_audio_ms, latency_ms:[per turn, end of elder speech → first audio byte], latency_p50_ms,
  latency_p90_ms, usage:{prompt_tokens, response_tokens, total_tokens, prompt_by_modality, response_by_modality}, tool_calls,
  interruptions, violations:[{match, text, t}], model_reports, missed_next_step, audio_in_bytes, audio_out_bytes,
  audio_stored:false, fallback, safety_tts_fallback, end_reason}`. `call_session.engine` = `gemini-live` (or
  `gemini-live>browser` after a fallback).

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
