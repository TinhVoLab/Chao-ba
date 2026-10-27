# Chào Bà: Demo Guide

How to run the prototype and a **3-minute demo script** mapped to the judging criteria.
All seeded data is **simulated** and labelled "Dữ liệu mô phỏng / Simulated data" in the UI. No step needs an API key.

---

## 1. Run it

Prerequisites: Python 3.14, Node.js 20+ (tested with 22.14), and Chrome or Edge (Web Speech API with vi-VN). For spoken output, a Vietnamese system voice should be installed (macOS ships "Linh"). Without one, the call still runs with on-screen captions.

```bash
# from the repo root
python3.14 -m venv .venv && .venv/bin/pip install -r requirements.txt

# Terminal 1: API + elder call page (http://localhost:8000)
.venv/bin/uvicorn chaoba.server.app:app --port 8000

# Terminal 2: family app (http://localhost:3000)
cd web && npm install && npm run dev
```

Check:

```bash
curl -s localhost:8000/api/health      # {"ok":true,"llm":"fallback"}  (or "claude" with a key)
.venv/bin/pytest -q                     # all pass (174 at the time of writing; Postgres RLS tests skip without Docker)
```

On first start the server seeds three simulated elders (90 days each, plus a simulated family call/visit log) into `data/runtime/chaoba.db`:

| id | Elder | Story | Light on day 90 | Family contact |
|---|---|---|---|---|
| `hanh` | Bà Hạnh, 72, Bến Tre, lives alone | BP medication change (day 30) → yellow day 38 → red day 43 → doctor visit day 44 → green day 56 → new baseline day 77 | green | Lan ~1×/week → 3×/week after day 44 → fades; last call day 85, so Today shows "5 days since anyone called" |
| `tu` | Ông Tư, 76, HCMC | slow recall / word-use drift → yellow from day 65 | yellow | son calls ~2×/week (no nudge) |
| `control` | Ông Bảy, 69, Cần Thơ | stable control | green | daughter calls / visits often (no nudge) |

**Dates.** Day numbers are fixed; dates are set when the database is seeded: **day 90 = the day before the server's date**. A call is always filed under **today's date** on the elder's calendar (day 91 on the seeding day, day 92 if the server is still running tomorrow, and so on). **Several calls on the same date are sub-calls of one day**: the day's record is updated in place (the last valid call wins for speech metrics; symptoms, emergency and "answered" are combined; `calls` counts them). A call never creates a date after today. `/today` returns `is_today` and a ready-made heading (`label_vi` "Cuộc gọi sáng nay" / "Cuộc gọi hôm qua (26/10)"). To pin dates (e.g. for screenshots), start uvicorn with `CHAOBA_END_DATE=2026-11-19`; if that date is in the future, live calls merge into the last seeded day rather than creating a later one. The offline fixtures in `web/fixtures/` carry the calendar of the day they were snapshotted.

**Reset the demo** (removes live calls, rehearsals, notes, alerts and contact logs, and re-seeds):

```bash
curl -X POST localhost:8000/api/demo/reset              # all three elders
curl -X POST 'localhost:8000/api/demo/reset?elder=hanh'  # just Bà Hạnh
```

The endpoint exists only while `CHAOBA_DEMO=1` (the default for the prototype); start uvicorn with `CHAOBA_DEMO=0` to disable it (it then returns 403). The old way still works: stop uvicorn, `rm data/runtime/chaoba.db`, start again. To use a throw-away database: `CHAOBA_DB=/tmp/chaoba-demo.db .venv/bin/uvicorn chaoba.server.app:app --port 8000`.

**CORS.** By default the API accepts browser requests from `localhost`, `127.0.0.1` or `[::1]` on **any port** (so the web app also works on :3001 or a Vite port). For a deployed app set `CHAOBA_CORS_ORIGINS="https://app.example.vn,https://demo.example.vn"`; only those exact origins are then allowed.

### No-key mode vs Claude mode

| | No key (default) | `ANTHROPIC_API_KEY` set |
|---|---|---|
| Start | as above | `export ANTHROPIC_API_KEY=sk-ant-...` in Terminal 1 before `uvicorn` |
| `/api/health` | `"llm":"fallback"` | `"llm":"claude"` |
| Conversation | `ScriptedEngine`: deterministic, phase-aware Southern Vietnamese with keyword reactions | `claude-sonnet-5-5` (cached persona prompt), fallback `claude-haiku-5-5`, then scripted |
| Emergency detection | Layer 1 keyword spotter | Layer 1 + Layer 2 `flag_emergency` tool |
| Post-call analysis | rule-based (lexicons, recall keywords, mood heuristic) | `claude-opus-5-5` structured output, rule-based fallback |
| Family explanation | templates | templates; newest light reworded by `claude-haiku-5-5` only if the post-check passes |
| Data leaving the server | none from the Chào Bà server (but see "Speech recognition" below) | transcript + per-call context sent to the Anthropic API |

**Speech recognition.** The elder call page uses the browser's Web Speech API. In Chrome and Edge this **streams the microphone audio to the browser vendor's cloud (Google for Chrome)**; the Chào Bà server itself never receives or stores audio, only text and pause timings. The page says this in its footer. Use typed mode ("Gõ chữ") or sim mode if that matters for your audience. Production calls go over the phone to a self-hosted Vietnamese ASR (PhoWhisper/Whisper) that discards audio after transcription.

Every safety layer (spotter, guardrails, output scrub, blocklist) runs in both modes. The response of `POST /api/calls` contains `engine` (`scripted` / `claude`). If a Claude request fails, the call silently continues on the scripted engine, and the engine actually used is stored with the call. **The Claude path has been tested only with a fake client, not against the live API.**

---

## 2. Screens

| URL | What it shows |
|---|---|
| `http://localhost:8000/call?elder=hanh` | **Elder web call page**: one big green button "Nghe", live captions, "Không lưu ghi âm" notice (the server stores no audio) and a footer explaining that speech recognition is the browser's (Google) service, typed-answer mode ("Gõ chữ"), demo toggle "Giả lập người nói (demo)", result card after the call (heading, light, summary, explanation, metrics) |
| `http://localhost:8000/call?elder=hanh&sim=1` | Same page in **hands-free rehearsal**: a scripted elder answers each question (spoken by the browser TTS in a lower voice and marked "(giả lập)"). Its timings are calibrated to the persona's own baseline speech rate and pause ratio. A rehearsal is stored and shown but **not scored**: the light stays what it was, with the reason "rehearsal, not scored" |
| `http://localhost:3000/?elder=hanh` | Family app **Today**: light, plain explanation, this morning's call summary, mood, symptoms mentioned, "Gọi má" (logs a call) / quick note, contact nudge "No one has called Mom for 5 days", last 14 days |
| `/trends?elder=hanh` | 90 days by default (30-day option): each signal vs the person's usual range (baseline ± 1 SD, the real baseline history from the API so the band steps at the day-77 re-baseline), 7-day average, the yellow/red period shaded behind every chart, numbered markers for medication change (1), doctor visit / care plan (2) and new baseline (3), table view |
| `/alerts?elder=hanh` | Alerts with explanations; "Seen, I'm on it" acknowledgement |
| `/dmaic?elder=hanh` | Define → Measure → Analyze → Improve → Control (status from the API: done / current / not started), family calls+visits per week before / after / last 14 days, cycle on the timeline, intervention effect (14 days before / after) |
| `/privacy?elder=hanh` | Data retention; consents per purpose with **Withdraw** (confirm dialog; really stops processing via `POST /api/elders/{id}/consents/{type}/withdraw`) and **Turn back on**; "who viewed" access log (one row per person, page and day, with a count) |
| `/screen?elder=hanh` | 9:16 standing-screen mockup for the elder's home |
| `/call` | Links to the elder call page for each elder |
| `http://localhost:8000/api/evaluation` | Simulated-cohort evaluation JSON (`data/eval/report.md` for the readable version) |

Switch elders with `?elder=hanh|tu|control` or the elder switcher. The VI/EN toggle is in the header.

---

## 3. Three-minute demo script

Before you start: both servers running and a freshly seeded DB. Open two Chrome windows side by side: (A) `localhost:3000/dmaic?elder=hanh` and (B) `localhost:8000/call?elder=hanh&sim=1`. Turn the volume up. Set the family app to EN if the audience is English-speaking.

| Time | Do (click) | Say | Criterion |
|---|---|---|---|
| 0:00–0:20 | Window A on **Today** for Bà Hạnh (green; point at the yellow "5 days since anyone called Mom" nudge) | "Vietnam has 14.2 million people over 60, heading to 20.9 million by 2034. Their children often live far away. Chào Bà is a 4-minute morning call from Út Thương, a Southern-Vietnamese AI companion, over the phone or the web. It watches for **change relative to the person's own baseline** and tells the family in plain words. It never diagnoses." | 1 Health impact |
| 0:20–1:20 | Window B: click **Nghe**. Let the simulated call run (about 60 s; you can talk over it) | "She opens with a message from the daughter, says she's a virtual assistant, that nothing is recorded, and asks for consent. Then sleep, food, how she feels. Now the recall game: yesterday's story. The simulated elder fails free recall, so Út Thương gives one cue. That's a recall score of 1 out of 3. When she mentions her back, Út Thương asks how long it has been. Then a life story for the memory book, and it closes with the exact medication reminder and the daughter's message. Our server only receives text and pause timings, never audio." | 3 Working demo · 4 Responsible AI |
| 1:20–1:35 | Point at the **result card** ("Cuộc gọi sáng nay": light, summary, metrics, tag "Diễn tập mô phỏng – không tính điểm") | "Per call we compute syllables per second, pause ratio, filler rate, MATTR vocabulary diversity, recall 0–3, symptoms and mood. Calls with under 45 seconds of speech don't count. And this was a rehearsal with a scripted voice, so it is shown but never scored: rehearsing cannot change her light." | 2 Technical depth |
| 1:35–2:15 | Window A: **Trends**, then **DMAIC** for Bà Hạnh | "Here's 90 days of simulated data; the shaded band is the yellow and red period. After a blood-pressure medication change, marker 1, she mentions dizziness. Yellow on day 38, then her speech slows and pauses grow: red on day 43. The family took her to the doctor on day 44, marker 2, and Lan started calling three times a week. That's the Improve step, and both parts are measured: speech rate recovered from 4.18 to 4.61 syllables per second, family calls went from 1.2 to 3 a week, and she was back to green on day 56. On day 77 the stable period becomes her new baseline, marker 3. Control keeps watching: calls have dropped back to once a week, which is why Today showed the nudge." | 1 Clinical relevance · 2 Technical depth |
| 2:15–2:35 | Switch elder to **Ông Tư** (Today → yellow) | "Different pattern: a slow drift in story recall. Yellow from day 65. The cycle is at Analyze; Improve hasn't started and carries a recommendation: take him to a doctor and bring this trend report. No diagnosis, no specialty named." | 1 · 4 |
| 2:35–2:50 | Show `data/eval/report.md` or a slide with the ablation table | "On a **simulated** cohort of 200 elders: 92 % of injected declines flagged, median 19 days, 0.29 false alarms per person-month. With one population norm instead of a personal baseline, sensitivity drops to 76 % and 38 of 112 stable people would be in near-permanent alarm. Simulated, not clinical. Next comes a 50–100 person validation against MoCA with a geriatrics department in Ho Chi Minh City." | 2 · 4 Fairness |
| 2:50–3:00 | **Privacy** tab | "Consent per purpose, and each can be withdrawn here; that really stops the processing. A family member withdrawing on the elder's behalf has to confirm the elder agreed. Transcripts expire after 7 days, quoted words in alerts after 30, every family view is logged, and our server never stores audio. Families pay by subscription; commune health stations and post-discharge programmes are the B2G and B2B path. Production calls go over ordinary phones via LiveKit SIP." | 4 · 5 Scalability · 6 Commercial |

### Optional extras (if time or questions allow)

- **Emergency tiers (≈ 40 s).** Use Ông Bảy so Bà Hạnh's story stays clean. Open `localhost:8000/call?elder=control`, click **Gõ chữ**, then **Nghe**, type `Dạ được con` → Enter, then one of:
  - **Acute:** `Tui té hổng dậy được` or `Đang đau ngực`. Út Thương calmly says to call 115 or a neighbour and that "chị Thảo" is being told. A red banner with a "Gọi 115" link appears, the call ends, and the family app **Alerts** shows a red `emergency` alert quoting him. Today stays red after later calls the same day (the emergency is stored on the day's record).
  - **Non-acute (past event):** `Tui bị ngã cầu thang hôm qua` or `Hôm qua tui hơi tức ngực`. No 115. Út Thương asks one question: "Giờ ông có đang đau hay chảy máu gì hông ông?". Answer `Dạ hổng có` → she reassures him and says she'll ask the family to check in; the family gets a red `health_concern` alert "please check in today". Answer `Dạ có, còn đau lắm` instead → it escalates to the acute path (115).
  - **Someone else:** `Hôm qua thằng cháu té xe trầy chân`. Út Thương sympathises and carries on; no alert, nothing recorded against Ông Bảy.
  - Negations and idioms do not fire: `Hổng có té gì hết`, `Té ra hôm qua là chủ nhật`.
  - Reset afterwards with `curl -X POST 'localhost:8000/api/demo/reset?elder=control'`.
- **Guardrails.** In typed mode: `Con ơi chuyển khoản giùm bà` (scam: refuses, warns about OTP, family gets a `scam_topic` alert), `Bà bỏ thuốc huyết áp được hông?` (medication: "ask the doctor"), `Tui bị bệnh tiểu đường hả con?` or `Vậy là bệnh gì?` (diagnosis: "I'm a virtual assistant, I can't examine; ask the doctor or chị Lan"), `Sáng nay hơi mỏi cái lưng` (follow-up: "bà mỏi cái lưng từ hồi nào vậy bà, có đỡ chưa?").
- **Opt-out.** `Thôi đừng gọi nữa` → confirmation → `Dạ đúng` → calls stop; a new `POST /api/calls` for that elder returns 409; the family gets an alert; the Privacy screen shows "Daily calls are paused" with **Resume calls** (`POST /api/elders/{id}/resume`).
- **Consent withdrawal from the app.** Privacy (use Ông Bảy) → **Withdraw** next to "Share daily light and summaries with family" → confirm that Ông Bảy (or his legal proxy) agreed (the API refuses a family withdrawal without `confirmed_by_elder_or_proxy: true`) → Today shows "Paused" and hides the light, summary, trends and alerts. **Turn back on** restores it. Withdrawing "Receive daily check-in calls" pauses calls exactly like the in-call opt-out.
- **Contact log.** On Today for Bà Hạnh, tap **Gọi má** (on a laptop the `tel:` link does nothing visible): the call is logged, the nudge disappears on reload and "You called Mom today" shows.
- **Real speech.** Open `/call?elder=hanh` without `sim=1`, allow the microphone, and answer in Vietnamese. Speech is recognised by the browser (Chrome/Edge); pauses are measured by an in-page VAD.

### Caveats to state honestly if asked

- In **sim mode** the "speech" is scripted text with timings modelled on the persona's own baseline, not a person. Such a call is a **rehearsal**: stored as `simulated: true` (channel `web`) with the event "Web call (simulated rehearsal, not scored)", shown on the timeline, and **excluded from the control chart**. Running it many times cannot turn anyone yellow. A real (spoken or typed) call on the same day replaces the rehearsal data for that day.
- Speech recognition on the web page is the browser vendor's cloud service (Google in Chrome), not ours. Our server stores no audio.
- PSTN/LiveKit is architected and sketched but **not demonstrated**.
- There is no login in the prototype. The app identifies itself as the primary carer (Lan for Bà Hạnh) through `X-Actor` / `X-Role` headers, which is what the access log shows.
- Typed answers ("Gõ chữ") carry no real speech timing, so a typed call is stored as a too-short (invalid) day: summary, mood and symptoms count, speech metrics do not. Use it for the safety demos, not for metrics.
