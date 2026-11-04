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
curl -s localhost:8000/api/health      # {"ok":true,"llm":"fallback","voice":"browser"}  (or "claude" with a key)
.venv/bin/pytest -q                     # 294 passed (the 3 Postgres RLS tests also run when Docker is available)
```

On first start the server seeds three simulated elders (90 days each, plus a simulated family call/visit log) into `data/runtime/chaoba.db`:

| id | Elder | Story | Light on day 90 | Family contact |
|---|---|---|---|---|
| `hanh` | Bà Hạnh, 72, Bến Tre, lives alone | BP medication change (day 30) → yellow day 38 → red day 43 → doctor visit day 44 → green day 53 → new baseline day 77 | green | Lan ~1×/week → 3×/week after day 44 → fades; last call day 85, so Today shows "5 days since anyone called" |
| `tu` | Ông Tư, 76, HCMC | slow recall / word-use drift → yellow from day 70 | yellow | son Khoa calls or visits ~2–3×/week (no nudge) |
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

### Optional: Gemini Live voice engine (`engine=gemini`)

An optional voice engine for the `/call` page and the `/screen` talk view: Gemini Live hears and speaks (full duplex, the elder can interrupt), our orchestrator still decides every line and runs every safety check on the live transcripts (TECHNICAL_DOCUMENTATION.md §7.4). Audio goes **through our server to Google** and is never stored. Off by default; the browser voice stays the fallback.

1. Credentials, either mode (never put them in the web app; only the API server reads them):

   ```bash
   # (a) Gemini Developer API
   export GEMINI_API_KEY=...                      # from Google AI Studio

   # (b) Vertex AI with Application Default Credentials
   gcloud auth application-default login          # or GOOGLE_APPLICATION_CREDENTIALS=/path/sa.json
   export GOOGLE_GENAI_USE_VERTEXAI=true GOOGLE_CLOUD_PROJECT=<project-id> GOOGLE_CLOUD_LOCATION=us-central1
   ```

   Optional: `CHAOBA_VOICE_ENGINE=gemini` (default for every web call), `CHAOBA_GEMINI_MODEL` (default `gemini-3.8-live`), `CHAOBA_GEMINI_VOICE` (default `Sulafat`), `CHAOBA_GEMINI_LANGUAGE_CODE=vi-VN`, `CHAOBA_GEMINI_SILENCE_MS` (default 1000).
2. Start the API as usual in the same terminal, then check `curl -s localhost:8000/api/voice/config` → `"gemini":{"available":true,"mode":"developer"|"vertex",...}`.
3. Open http://localhost:8000/call?elder=hanh&engine=gemini (or `/screen?elder=hanh&engine=gemini` in the web app) and press **Nghe**. The badge reads **"Giọng: Gemini Live · đã kết nối"**; speak, and interrupt Út Thương to hear her stop. If Gemini cannot be reached the badge switches to "Giọng: trình duyệt · dự phòng" and the same call continues on the browser voice.
4. Go/no-go numbers (latency p50/p90, time to first audio, what Gemini said for each safety probe, token usage, cost per 4-minute call): `.venv/bin/python scripts/voice_bench.py --calls 3` → `data/runtime/voice_bench.json`. Without credentials it exits with instructions; `--fake` dry-runs it.

**Not yet verified with real credentials** (none on the build machine): everything is tested against an offline fake session (`CHAOBA_GEMINI_FAKE=1`) and in a muted browser (`web/scripts/voice-e2e.mjs`). Whether the voice sounds right to Southern elders must be judged by people. Tell the audience that with this engine on, call audio is processed by Google outside Vietnam.

**Muted rehearsal without a key** (no sound, no network): `CHAOBA_GEMINI_FAKE=1 .venv/bin/uvicorn chaoba.server.app:app --port 8000`, then `http://localhost:8000/call?elder=hanh&engine=gemini&sim=1&mute=1` shows the Gemini badge and runs a whole call on the fake (digital-silence audio frames + transcripts). `CHAOBA_GEMINI_FAKE=fail` demonstrates the fallback.

---

## 2. Screens

| URL | What it shows |
|---|---|
| `http://localhost:8000/call?elder=hanh` | **Elder web call page**: one big green button "Nghe", live captions, "Không lưu ghi âm" notice (the server stores no audio) and a footer explaining that speech recognition is the browser's (Google) service, typed-answer mode ("Gõ chữ"), demo toggle "Giả lập người nói (demo)", result card after the call (heading, light, summary, explanation, metrics) |
| `http://localhost:8000/call?elder=hanh&sim=1` | Same page in **hands-free rehearsal**: a scripted elder answers each question (spoken by the browser TTS in a lower voice and marked "(giả lập)"). Its timings are calibrated to the persona's own baseline speech rate and pause ratio. A rehearsal is stored and shown but **not scored**: the light stays what it was, with the reason "rehearsal, not scored" |
| `http://localhost:3000/?elder=hanh` | Family app **Today**: light, plain explanation, this morning's call summary, mood, symptoms mentioned, "Gọi má" (logs a call) / quick note, contact nudge "No one has called Mom for 5 days", **Gửi yêu thương / Send some love** (one-tap cards with Đã gửi → Má đã xem → Má đã trả lời and the reply inline), last 14 days |
| `/trends?elder=hanh` | 90 days by default (30-day option): each signal vs the person's usual range (baseline ± 1 SD, the real baseline history from the API so the band steps at the day-77 re-baseline), 7-day average, the yellow/red period shaded behind every chart, numbered markers for medication change (1), doctor visit / care plan (2) and new baseline (3), table view |
| `/alerts?elder=hanh` | Alerts with explanations; "Seen, I'm on it" acknowledgement |
| `/dmaic?elder=hanh` | Define → Measure → Analyze → Improve → Control (status from the API: done / current / not started), family calls+visits per week before / after / last 14 days, cycle on the timeline, intervention effect (14 days before / after) |
| `/memories?elder=hanh` | **Sổ ký ức / Memory book**: shared life stories as chapters by theme (era, people, places; VI/EN), "3 chuyện bà giữ riêng" (count only, no content), **Xuất sổ ký ức** opens the printable memoir `localhost:8000/api/elders/hanh/memories/export?lang=vi` (shared stories only). Linked from Today. The DMAIC page has a **Hoạt động phòng ngừa / Prevention activities** section (memory games with adaptive difficulty, habit nudges, Bà Hạnh's day-44 care plan, "association, not causation") |
| `/family?elder=hanh` | **Gia đình / Family**: weekly synthesis "Tuần này má nhắc đau lưng 3 lần, với 2 người trong nhà (Lan, Minh) và với Út Thương", before-you-call topics (what a sibling already asked is set aside), call rota (whose turn today, last 7 days, "5 days since anyone called"), care tasks, the shared timeline (filters: All / Family / Út Thương / Self-reported) and "who looked at Mom's information". Switch **Đang xem với tư cách / Viewing as** (under the elder switcher, on every page) between Lan (primary, full view), Minh and Vy (summary view: other people's notes are hidden, quotes removed) |
| `/community` | **Bảng trạm y tế / Health-station board** (under **Thêm / More**): simulated ward "Phường X, TP.HCM" (60 generated elders + the 3 personas), counts by light, prioritised visit list (red → yellow → check-in; pseudonymised initials · age · area), 30-day ward trend, "which actions coincided with recovery" (association only). Read with `X-Role: health_station` |
| `/privacy?elder=hanh` | Data retention; consents per purpose with **Withdraw** (confirm dialog; really stops processing via `POST /api/elders/{id}/consents/{type}/withdraw`) and **Turn back on**; "who viewed" access log (one row per person, page and day, with a count) |
| `/screen?elder=hanh` | **Elder standing screen** (interactive 9:16 web prototype; hardware is phase 2). On a desktop it shows the screen in a device frame with a "Hướng dẫn demo" panel; on a portrait tablet/phone, or with `?kiosk=1`, it fills the screen. Flags: `sim=1` hands-free rehearsal, `typed=1` typed answers, `tts=0` captions only (silent), `lang=en` English, `elder=tu|control`. See *Standing screen* below |
| `/call` | Links to the elder call page for each elder |
| `http://localhost:8000/api/evaluation` | Simulated-cohort evaluation JSON (`data/eval/report.md` for the readable version) |

Switch elders with `?elder=hanh|tu|control` or the elder switcher. The VI/EN toggle is in the header. On a phone the bottom bar has **Hôm nay · Xu hướng · Gia đình · DMAIC · Thêm**; **Thêm / More** opens Cảnh báo (with an unread badge, also shown as a banner on Today), Sổ ký ức, Riêng tư and Cộng đồng. On a desktop all of them are in the side rail.

---

## 3. Three-minute demo script

Before you start: both servers running and a freshly seeded DB. Open two Chrome windows side by side: (A) `localhost:3000/dmaic?elder=hanh` and (B) `localhost:8000/call?elder=hanh&sim=1`. Turn the volume up. Set the family app to EN if the audience is English-speaking.

| Time | Do (click) | Say | Criterion |
|---|---|---|---|
| 0:00–0:20 | Window A on **Today** for Bà Hạnh (green; point at the yellow "5 days since anyone called Mom" nudge) | "Vietnam has 14.2 million people over 60, heading to 20.9 million by 2034. Their children often live far away. Chào Bà is a 4-minute morning call from Út Thương, a Southern-Vietnamese AI companion, over the phone or the web. It watches for **change relative to the person's own baseline** and tells the family in plain words. It never diagnoses." | 1 Health impact |
| 0:20–1:20 | Window B: click **Nghe**. Let the simulated call run (about 60 s; you can talk over it) | "She opens with a message from the daughter, says she's a virtual assistant, that nothing is recorded, and asks for consent. Then sleep, food, how she feels. Now the recall game: yesterday's story. The simulated elder fails free recall, so Út Thương gives one cue. That's a recall score of 1 out of 3. When she mentions her back, Út Thương asks how long it has been. Then a life story for the memory book, and it closes with the exact medication reminder and the daughter's message. Our server only receives text and pause timings, never audio." | 3 Working demo · 4 Responsible AI |
| 1:20–1:35 | Point at the **result card** ("Cuộc gọi sáng nay": light, summary, metrics, tag "Diễn tập mô phỏng – không tính điểm") | "Per call we compute syllables per second, pause ratio, filler rate, MATTR vocabulary diversity, recall 0–3, symptoms and mood. Calls with under 45 seconds of speech don't count. And this was a rehearsal with a scripted voice, so it is shown but never scored: rehearsing cannot change her light." | 2 Technical depth |
| 1:35–2:15 | Window A: **Trends**, then **DMAIC** for Bà Hạnh | "Here's 90 days of simulated data; the shaded band is the yellow and red period. After a blood-pressure medication change, marker 1, she mentions dizziness. Yellow on day 38, then her speech slows, fillers increase and she mentions poor sleep and skipped meals: red on day 43. The family took her to the doctor on day 44, marker 2, and Lan started calling three times a week. That's the Improve step, and both parts are measured: speech rate recovered from 4.18 to 4.61 syllables per second, family calls went from 1.2 to 3 a week, and she was back to green on day 53. On day 77 the stable period becomes her new baseline, marker 3. Control keeps watching: calls have dropped back to once a week, which is why Today showed the nudge." | 1 Clinical relevance · 2 Technical depth |
| 2:15–2:35 | Switch elder to **Ông Tư** (Today → yellow) | "Different pattern: a slow drift in story recall. Yellow from day 70: he recalled yesterday's story fully on none of his last 7 calls, against 7 of 7 normally. The cycle is at Analyze; Improve hasn't started and carries a recommendation: call and talk with him more often, and if it persists, bring this trend report to his next check-up. No diagnosis, no specialty named." | 1 · 4 |
| 2:35–2:50 | Show `data/eval/report.md` or a slide with the ablation table | "On a **simulated** held-out cohort of 400 elders, with the threshold chosen on a separate cohort: 80 % of clinical-type declines were flagged by a matching rule within 45 days, but 15 % of stable people would be 'flagged' by chance in the same window, so the honest number is 65 % beyond chance. Median delay 24 days, 0.19 false alarms per person-month. With one population norm instead of a personal baseline, the beyond-chance figure falls to 40 % and 43 of 227 stable people would be in alarm most of the time. Simulated, not clinical. Next comes a 50–100 person validation against MoCA with a geriatrics department in Ho Chi Minh City." | 2 · 4 Fairness |
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

### Family coordination and the health-station board (≈ 60 s, optional)

- **/family?elder=hanh as Lan**: "Each child hears one fragment. Lan heard about Mom's back on the phone, Minh by Zalo,
  and Út Thương in a morning call. Nobody had the picture; the weekly synthesis puts it together: back pain 3 times, from
  three sources, ask whether it's better, and if it lasts, a check-up." Point at the rota: "It's Lan's turn today, and
  nobody has called for 5 days."
- Switch **Viewing as → Minh**: the notice says he sees the summary view; Lan's and Vy's notes show a lock; the rota says
  his next turn. The topic "Cây mai sắp ra nụ" sits under "Already covered this week: Lan asked 22/10", so Mom isn't asked
  the same thing three times. Tick his task "Về thăm má cuối tuần"; it shows as done for everyone.
- **Thêm → Cộng đồng**: "For a commune health station: 61 people who agreed to share, pseudonymised. Red first, longest
  first, then those with no family contact and living alone. The recovery table is association only; in this simulation
  the actions are random, and the page says so." This is the B2G path.
- Reset: `curl -X POST localhost:8000/api/demo/reset` (also re-seeds the family data).

### Memory book and prevention activities (≈ 45 s, optional)

- In the simulated call (`/call?elder=hanh&sim=1`, or add `&tts=0` for captions only), after the recall game Út Thương asks
  **one life-story question** (never repeated; e.g. "Hồi nhỏ má của bà hay dạy bà điều gì vậy bà?") and its follow-up, then:
  *"Bà cho con kể lại chuyện này cho chị Lan nghe được hông bà?"* The simulated elder says yes or "con giữ riêng giùm bà";
  either way Út Thương confirms it. On two days out of three a short **game** follows (finish a ca dao line, name a few
  fruits), offered as play; the closing ends with one **habit nudge** (water, morning walk, bedtime, call an old friend…).
- Say: "Each story becomes a page of a memoir for the grandchildren, but only if she says yes; private stories stay hers.
  Text only, no voice is kept; keeping a voice clip would be a future opt-in, clip by clip."
- Open **/memories?elder=hanh**: the new story is there if shared (otherwise the private count went up). Click **Xuất sổ ký
  ức** for the printable book. Switch to **Ông Tư**: his later stories are shorter and less specific, in line with his drift.
  It is shown as data, not scored.
- **DMAIC → Hoạt động phòng ngừa**: games played, recall rate first vs last 4 weeks (Ông Tư 84 % → 58 %, difficulty
  settled at level 1, so the game stays easy and never feels like a test), nudges by kind, Bà Hạnh's care plan from day 44
  with mood / poor-sleep before and after, and which activities were followed by better next days, labelled
  **association, not causation**.
- Elder-side view (all stories, incl. private): `curl -H 'X-Role: elder_self' localhost:8000/api/elders/hanh/memories`.

### Gửi yêu thương: family love notes (≈ 30 s, optional)

Two windows side by side: (A) family app `localhost:3000/?elder=hanh` (Today) and (B) `localhost:3000/screen?elder=hanh&tts=0`
(add `&typed=1` to type the advice answer instead of speaking it).

| Time | Do | Say |
|---|---|---|
| 0:00–0:08 | A: under **Gọi má**, point at the yellow nudge "Đã 5 ngày chưa ai gọi má. Má đã nhận 5 lời thương tuần này, gọi má một cuộc nữa nha", then tap **Má ăn cơm chưa?** | "Not every day allows a call. One tap sends Mom a small card. But look: the nudge still counts only real calls. Love notes never replace a call." |
| 0:08–0:18 | B: within ~10 s the card slides in: Lan's photo with a soft ring (no sound), "Con Lan gửi: Má ăn cơm chưa?". Tap **Ăn rồi** | "Huge buttons, readable from her chair. Her answer is a self-report: the family sees it, the light never uses it." |
| 0:18–0:24 | A: the row turns "Má đã trả lời" with "Má trả lời: Ăn rồi con · 07:42" (reload if needed). Tap **Hỏi ý má → Trồng mai sao cho ra nụ đúng Tết?** | "And this one makes her feel needed: ask for her know-how." |
| 0:24–0:30 | B: **Nói câu trả lời** (or type), **Gửi cho con Lan**, then "Lưu lời má dạy vào Sổ ký ức?" → **Lưu lại** | "With her yes, the answer becomes a 'Lời má dạy' page in the memory book. On an ordinary phone, Út Thương relays the same cards in the morning call: 'Chị Lan hỏi bà nấu canh chua sao cho ngon?', and passes the answer back." |

- Phone-only relay: send a card, then run `localhost:8000/call?elder=hanh&sim=1&tts=0` → the first line after consent relays it;
  the reply appears on Today with "(qua cuộc gọi sáng)". A card already seen on the screen is not relayed.
- Free text with a dose (`Má uống thêm 1 viên thuốc`) is refused kindly; a sender can send 6 cards a day.
- DMAIC shows micro-contacts per week as a separate series next to calls and visits.
- Automated check (silent: `--mute-audio`, `tts=0`, speech synthesis stubbed, typed advice):
  `WEB=http://localhost:3000 API=http://localhost:8000 node web/scripts/kudos-e2e.mjs` (resets Bà Hạnh; writes
  `docs/screenshots/kudos-*.png`).

### Standing screen (≈ 60 s, optional)

Open `localhost:3000/screen?elder=hanh` (desktop: device frame + demo guide; tablet in portrait or `&kiosk=1`: full screen).

- **Idle:** big clock and date, rotating family photos (generated placeholders), Lan's message from the family app (`to_elder` notes), today's 07:00 medication with **Đã uống thuốc ✓ / Chưa**, a water reminder. Nothing moves on its own except the slow photo fade and Út Thương breathing.
- **Nói chuyện với Út Thương:** a real call on the same API as `/call` (`POST /api/calls`, `/turns`, `/end`). Add `&sim=1` for a hands-free rehearsal or `&typed=1` to type. The avatar breathes, speaks and listens; "Đang nghe…" shows when the mic is open; big **Kết thúc** ends at once (speech is cancelled, the mic released). After the call, `/today` shows today's day updated.
- **Emergency:** with `&typed=1`, type `tôi bị tức ngực` → calm full-screen red: "Đã báo cho chị Lan", **Gọi 115** (`tel:115`); the family app gets the red `emergency` alert.
- **Gọi con Lan:** a clearly labelled *simulated* video call; on connect it posts `POST /api/elders/hanh/contacts` (kind `call`, Lan), so Today's "days since anyone called" resets.
- **Đã uống thuốc / Hôm nay thấy sao? / Trò chơi ca dao:** stored via `POST /api/elders/{id}/medication_log`, `/mood_checkin`, `/game_plays` (GET returns the history). These are the elder's self-reports: not scored, not diagnostic, and they never change the light. If the API is unreachable, taps are kept on the device and sent later.
- Sound: in real use Út Thương speaks (vi-VN, rate 0.9) and stops instantly when the call ends or the page is hidden. Add `&tts=0` for captions only.
- Automated check (silent: `--mute-audio`, `tts=0`, sim/typed modes): `WEB=http://localhost:3000 API=http://localhost:8000 node web/scripts/screen-e2e.mjs` (resets Bà Hạnh, writes `docs/screenshots/screen-*.png`).

### Caveats to state honestly if asked

- In **sim mode** the "speech" is scripted text with timings modelled on the persona's own baseline, not a person. Such a call is a **rehearsal**: stored as `simulated: true` (channel `web`) with the event "Web call (simulated rehearsal, not scored)", shown on the timeline, and **excluded from the control chart**. Running it many times cannot turn anyone yellow. A real (spoken or typed) call on the same day replaces the rehearsal data for that day.
- Speech recognition on the web page is the browser vendor's cloud service (Google in Chrome), not ours. Our server stores no audio.
- PSTN/LiveKit is architected and sketched but **not demonstrated**.
- There is no login in the prototype. The app identifies itself as the primary carer (Lan for Bà Hạnh) through `X-Actor` / `X-Role` headers, which is what the access log shows.
- Typed answers ("Gõ chữ") carry no real speech timing, so a typed call is stored as a too-short (invalid) day: summary, mood and symptoms count, speech metrics do not. Use it for the safety demos, not for metrics.
