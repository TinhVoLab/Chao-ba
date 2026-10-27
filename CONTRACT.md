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
def generate_persona(key: Literal["hanh","tu","control"], days: int = 90, seed: int = 7) -> dict
    # -> {"elder": {...profile...}, "records": [DailyRecord as dict], "notes": [...], "events": [...],
    #     "dmaic": {...}, "simulated": True}
def generate_cohort(n: int = 200, days: int = 120, seed: int = 11) -> list[dict]
    # each item like generate_persona plus "truth": {"decline": bool, "onset_day": int|None, "type": str}

# dmaic.py
def compute_cycle(records, lights, define: dict, intervention_day: int, pre_days=14, post_days=14) -> dict
    # -> {"phases": [{"phase":"define|measure|analyze|improve|control","day_from","day_to","summary_vi","summary_en"}],
    #     "effect": {metric: {"pre": x, "post": y, "change_pct": z}}, "new_baseline_day": int|None}

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
- `GET /api/health` → `{"ok":true,"llm":"claude"|"fallback"}`
- `GET /api/elders` → `[{id, display_name, name_en, age, province, light, simulated}]`
- `GET /api/elders/{id}` → elder profile
- `GET /api/elders/{id}/today` → `{date, day, light, reasons, explanation_vi, explanation_en, summary_vi, summary_en, answered, mood, simulated}`
- `GET /api/elders/{id}/timeline?days=90` → `{records:[DailyRecord], lights:[DailyLight], baseline:{metric:{center,scale}}, events:[{day,type,label_vi,label_en}]}`
- `GET /api/elders/{id}/alerts` → `[{id, day, date, type, severity, explanation_vi, explanation_en, acknowledged}]`
- `POST /api/elders/{id}/alerts/{alert_id}/ack`
- `GET /api/elders/{id}/dmaic` → compute_cycle output
- `GET /api/elders/{id}/notes`, `POST /api/elders/{id}/notes` `{author, text}`
- `GET /api/elders/{id}/privacy` → `{consents:[...], access_log:[...], data_retention:{audio:"not stored", transcript_days:7}}`
- `GET /api/evaluation` → evaluation report JSON
- `POST /api/calls` `{elder_id, channel:"web"}` → `{call_id, greeting_text, phase}`
- `POST /api/calls/{call_id}/turns` `{text, start, end, pauses:[...]}` → `{reply_text, phase, emergency:bool, end_call:bool}`
- `POST /api/calls/{call_id}/end` → `{metrics: CallMetrics, analysis: CallAnalysis, today: <today shape>}`
- Static elder call page: `GET /call?elder=hanh` (big single button, Web Speech API vi-VN for STT/TTS, WebAudio VAD for timings).

Seed: on startup the server loads personas `hanh`, `tu`, `control` from `chaoba.core.synth` (90 days). A real
web call appends day 91 for that elder (channel `web`, `simulated:false`) using the simulated baseline.
