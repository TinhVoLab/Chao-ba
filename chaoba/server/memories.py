"""Sổ ký ức (memory book) + prevention activities: storage, call hooks, REST endpoints, printable export.

Wiring (kept out of service.py on purpose): ``install(svc)`` wraps ``Service.build_context`` (adds today's life-story
question, game and nudge to the DailyContext) and ``Service.end_call`` (extracts the story, records its per-story
consent, logs the game / nudge / question). ``seed_all(svc)`` adds the simulated stories and activity log for the demo
personas. ``register(app)`` adds the endpoints below. Tables: ``memory_story``, ``activity_log`` (db.py).

Privacy rules
- Stories are text only. No audio is stored (keeping a voice clip would be a future, per-clip opt-in).
- A story is private (``shared=false``) unless the elder said yes to "Bà cho con kể lại chuyện này cho chị Lan nghe
  được hông?". An unclear answer or no answer keeps it private.
- Family roles see only shared stories plus a count of private ones (no titles, no content). ``X-Role: elder_self``
  sees everything. While ``family_sharing`` is withdrawn, family roles see no stories and no activity summary.
- Sharing / unsharing a story is the elder's decision: ``elder_self``, or a family member who states that the elder
  (or their legal proxy) confirmed it (``confirmed_by_elder_or_proxy: true``), as for consent withdrawal.

Endpoints
  GET  /api/elders/{id}/memories                       stories visible to the caller + theme counts + private count
  GET  /api/elders/{id}/memories/export?lang=vi|en|both printable HTML memoir of the SHARED stories
  POST /api/elders/{id}/memories/{mid}/share | unshare  per-story consent change
  GET  /api/elders/{id}/activities                     games, success-rate trend, nudges, associations (not causation)
"""
from __future__ import annotations

import functools
import html
import json
import logging
from datetime import date as Date
from urllib.parse import unquote

from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from chaoba.agent import activities as act
from chaoba.agent import lifestory as ls

from .db import now_iso
from . import memory_seed

log = logging.getLogger("chaoba.memories")

ELDER_ROLES = ("elder_self", "elder")
SEED_KEYS = ("hanh", "tu", "control")
AUDIO_NOTE = {"stored": False,
              "note_vi": "Chỉ lưu chữ, không lưu giọng nói. Giữ lại đoạn ghi âm giọng kể là tính năng tương lai, "
                         "chỉ khi người cao tuổi đồng ý cho từng đoạn.",
              "note_en": "Text only; no voice is stored. Keeping a voice clip of a story is a future feature, only with "
                         "the elder's consent for each clip."}


# ============================================================================================ storage
def add_story(store, elder_id: str, story: dict, day: int | None, date: str | None, *, shared: bool, consent: dict,
              source: str, simulated: bool, call_id: str | None = None) -> int:
    return store.x(
        "INSERT INTO memory_story(elder_id, day, date, call_id, question_id, theme, era_json, title_vi, title_en, "
        "text_vi, text_en, people_json, places_json, word_count, translation, shared, consent_json, source, simulated, "
        "created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (elder_id, day, date, call_id, story.get("question_id"), story.get("theme"),
         json.dumps(story.get("era") or {}, ensure_ascii=False), story.get("title_vi"), story.get("title_en"),
         story["text_vi"], story.get("text_en"), json.dumps(story.get("people") or [], ensure_ascii=False),
         json.dumps(story.get("places") or [], ensure_ascii=False), story.get("word_count"),
         story.get("translation", "gist"), 1 if shared else 0, json.dumps(consent, ensure_ascii=False), source,
         1 if simulated else 0, now_iso(), now_iso()))


def _story_row(r) -> dict:
    theme = r["theme"] or "childhood"
    tvi, ten = ls.THEMES.get(theme, (theme, theme))
    return {"id": r["id"], "day": r["day"], "date": r["date"], "question_id": r["question_id"], "theme": theme,
            "theme_vi": tvi, "theme_en": ten, "era": json.loads(r["era_json"] or "{}"),
            "title_vi": r["title_vi"], "title_en": r["title_en"], "text_vi": r["text_vi"], "text_en": r["text_en"],
            "translation": r["translation"], "people": json.loads(r["people_json"] or "[]"),
            "places": json.loads(r["places_json"] or "[]"), "word_count": r["word_count"], "shared": bool(r["shared"]),
            "consent": json.loads(r["consent_json"] or "{}"), "source": r["source"], "simulated": bool(r["simulated"])}


def all_stories(store, elder_id: str) -> list[dict]:
    return [_story_row(r) for r in store.q("SELECT * FROM memory_story WHERE elder_id=? ORDER BY day, id", (elder_id,))]


def log_activity(store, elder_id: str, day: int | None, date: str | None, kind: str, activity_id: str | None,
                 category: str | None, level: int | None, outcome: str | None, detail: dict | None = None,
                 simulated: bool = False, call_id: str | None = None) -> int:
    return store.x("INSERT INTO activity_log(elder_id, day, date, call_id, kind, activity_id, category, level, outcome, "
                   "detail_json, simulated, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                   (elder_id, day, date, call_id, kind, activity_id, category, level, outcome,
                    json.dumps(detail or {}, ensure_ascii=False), 1 if simulated else 0, now_iso()))


def activity_rows(store, elder_id: str, kind: str | None = None) -> list[dict]:
    sql = "SELECT * FROM activity_log WHERE elder_id=?" + (" AND kind=?" if kind else "") + " ORDER BY day, id"
    rows = store.q(sql, (elder_id, kind) if kind else (elder_id,))
    out = []
    for r in rows:
        d = dict(r)
        d["detail"] = json.loads(d.pop("detail_json") or "{}")
        d["simulated"] = bool(d["simulated"])
        out.append(d)
    return out


def asked_question_ids(store, elder_id: str) -> list[str]:
    ids = [r["activity_id"] for r in activity_rows(store, elder_id, "life_question") if r["activity_id"]]
    for s in all_stories(store, elder_id):          # stories seeded without a question log still count as asked
        if s["question_id"] and s["question_id"] not in ids:
            ids.insert(0, s["question_id"])
    return ids


def care_plan_focus(store, elder_id: str) -> list[str]:
    plans = activity_rows(store, elder_id, "care_plan")
    return list(plans[-1]["detail"].get("focus") or []) if plans else []


# ============================================================================================ call hooks
def enrich_context(svc, ctx) -> None:
    """Today's life-story question, game (2 days in 3) and nudge, adapted to the elder and their history."""
    store = svc.store
    prof = ctx.profile
    eid = ctx.elder.id
    recs = store.records(eid)
    moods = [r["mood"] for r in recs[-5:] if r.get("mood") is not None]
    try:
        ctx.life_question = ls.choose_question(prof, asked_question_ids(store, eid), moods, ctx.day)
        games = activity_rows(store, eid, "game")
        ctx.game = act.choose_game(prof, games, ctx.day) if act.plays_game_today(ctx.day) else None
        nudges = [r["category"] for r in activity_rows(store, eid, "nudge")]
        ctx.nudge = act.choose_nudge(prof, nudges, recs[-7:], ctx.day, care_plan_focus(store, eid))
    except Exception as e:  # never block a call on the memory book
        log.warning("memory book context failed: %s", e)


def on_call_end(svc, state, result: dict) -> dict:
    """Store the story (with its per-story consent) and log the question, game and nudge of a finished call."""
    store = svc.store
    eid = state.ctx.elder.id
    out: dict = {"story_id": None, "shared": None, "game": None, "nudge": None}
    if state.emergency or state.opted_out or state.declined:
        return out
    day = result.get("day")
    if day is None:
        day, date = svc.call_day(eid)
    else:
        date = store.date_of_day(eid, day) or svc.call_day(eid)[1]
    sim = bool(result.get("simulated"))
    lq = state.ctx.life_question
    if lq is not None and state.life_q_asked:
        log_activity(store, eid, day, date, "life_question", lq.id, lq.theme, None,
                     "answered" if state.story_texts else "not_answered", simulated=sim, call_id=state.call_id)
        story = ls.extract_story(lq, state.story_texts, state.ctx.profile) if state.story_texts else None
        if story:
            answer = state.share_answer or "not_asked"
            consent = {"answer": answer, "asked_in_call": state.share_stage == "done", "by": "elder (in call)",
                       "ts": now_iso(), "history": [{"shared": answer == "yes", "by": "elder (in call)",
                                                     "ts": now_iso()}]}
            sid = add_story(store, eid, story, day, date, shared=answer == "yes", consent=consent, source="call",
                            simulated=sim, call_id=state.call_id)
            out.update(story_id=sid, shared=answer == "yes", title_vi=story["title_vi"], title_en=story["title_en"])
    g = state.ctx.game
    if g is not None and state.game_stage == "done":
        log_activity(store, eid, day, date, "game", g.id, g.category, g.level, state.game_outcome,
                     {"label_vi": g.label_vi, "label_en": g.label_en}, simulated=sim, call_id=state.call_id)
        out["game"] = {"category": g.category, "level": g.level, "outcome": state.game_outcome}
    n = state.ctx.nudge
    if n is not None and state.nudge_said:
        focus = care_plan_focus(store, eid)
        log_activity(store, eid, day, date, "nudge", n.id, n.category, None, "delivered",
                     {"care_plan": n.category in focus}, simulated=sim, call_id=state.call_id)
        out["nudge"] = n.category
    return out


def install(svc) -> None:
    """Wrap the service's context builder and call finaliser (idempotent)."""
    if getattr(svc, "_memories_installed", False):
        return
    orig_ctx, orig_end = svc.build_context, svc.end_call

    @functools.wraps(orig_ctx)
    def build_context(elder_id: str):
        ctx = orig_ctx(elder_id)
        enrich_context(svc, ctx)
        return ctx

    @functools.wraps(orig_end)
    def end_call(call_id: str):
        fresh = call_id not in svc.results
        state = svc.active.get(call_id)
        result = orig_end(call_id)
        if fresh and state is not None:
            try:
                result["memory_book"] = on_call_end(svc, state, result)
            except Exception as e:  # pragma: no cover - never fail the call end
                log.warning("memory book end-of-call failed: %s", e)
        return result

    svc.build_context, svc.end_call = build_context, end_call
    svc._memories_installed = True


# ============================================================================================ seed
def seed_all(svc) -> None:
    """Simulated stories + activity log for the demo personas that have none yet."""
    store = svc.store
    for key in SEED_KEYS:
        prof = store.elder(key)
        if not prof or store.one("SELECT 1 FROM activity_log WHERE elder_id=? LIMIT 1", (key,)):
            continue
        _seed_persona(store, key, prof)


def _seed_persona(store, key: str, prof: dict) -> None:
    recs = store.records(key)
    if not recs:
        return
    end = Date.fromisoformat(recs[-1]["date"])
    by_day = {r["day"]: r for r in recs}
    for day, qid, shared, vi, en, people, places in memory_seed.STORIES.get(key, []):
        q = ls.render(ls.BANK_BY_ID[qid], prof)
        story = {"question_id": qid, "theme": q.theme, "title_vi": q.title_vi, "title_en": q.title_en,
                 "text_vi": vi, "text_en": en, "people": [{"vi": a, "en": b} for a, b in people], "places": places,
                 "era": ls.era_of(vi, q.era_hint, prof.get("age"), end), "word_count": len(vi.split()),
                 "translation": "human"}
        date = store.date_of_day(key, day)
        consent = {"answer": "yes" if shared else "no", "asked_in_call": True, "by": "elder (in call, simulated)",
                   "ts": date, "history": [{"shared": shared, "by": "elder (in call, simulated)", "ts": date}]}
        add_story(store, key, story, day, date, shared=shared, consent=consent, source="simulated", simulated=True)
        log_activity(store, key, day, date, "life_question", qid, q.theme, None, "answered", simulated=True)
    plan = memory_seed.CARE_PLANS.get(key)
    if plan:
        log_activity(store, key, plan["day"], store.date_of_day(key, plan["day"]), "care_plan", "improve", "plan",
                     None, "started", {"focus": plan["focus"], "label_vi": plan["label_vi"],
                                       "label_en": plan["label_en"]}, simulated=True)
    games: list[dict] = []
    nudges: list[str] = []
    rows = []
    for d in sorted(by_day):
        r = by_day[d]
        if not r.get("answered"):
            continue
        date = r["date"]
        if act.plays_game_today(d):
            g = act.choose_game(prof, games, d)
            if g is not None:
                p = memory_seed.game_success_p(key, d, g.level or 2)
                x = memory_seed.rng_for(key, d, "game").random()
                outcome = "success" if x < p else ("partial" if x < p + 0.1 else "miss")
                games.append({"outcome": outcome, "category": g.category, "activity_id": g.id})
                rows.append((key, d, date, None, "game", g.id, g.category, g.level, outcome,
                             json.dumps({"label_vi": g.label_vi, "label_en": g.label_en}, ensure_ascii=False)))
        focus = plan["focus"] if plan and d >= plan["day"] else []
        n = act.choose_nudge(prof, nudges, [by_day[x] for x in range(d - 6, d) if x in by_day], d, focus)
        nudges.append(n.category)
        rows.append((key, d, date, None, "nudge", n.id, n.category, None, "delivered",
                     json.dumps({"care_plan": n.category in focus}, ensure_ascii=False)))
    store.xmany("INSERT INTO activity_log(elder_id, day, date, call_id, kind, activity_id, category, level, outcome, "
                "detail_json, simulated, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,1,'" + now_iso() + "')", rows)


# ============================================================================================ views
def _is_elder(role: str) -> bool:
    return role in ELDER_ROLES


def memories_view(svc, elder_id: str, role: str) -> dict:
    stories = all_stories(svc.store, elder_id)
    elder_view = _is_elder(role)
    paused = svc.sharing_paused(elder_id) and not elder_view
    visible = stories if elder_view else ([] if paused else [s for s in stories if s["shared"]])
    private_n = sum(1 for s in stories if not s["shared"])
    themes = []
    for t in ls.THEME_ORDER:
        n = sum(1 for s in visible if s["theme"] == t)
        if n:
            themes.append({"theme": t, "label_vi": ls.THEMES[t][0], "label_en": ls.THEMES[t][1], "count": n})
    prof = svc.store.elder(elder_id) or {}
    return {"elder_id": elder_id, "display_name": prof.get("display_name"), "name_en": prof.get("name_en"),
            "honorific": (prof.get("honorific") or "bà").lower(),
            "viewer": "elder" if elder_view else "family", "stories": visible, "themes": themes,
            "shared_count": sum(1 for s in stories if s["shared"]), "private_count": private_n,
            "total": len(stories), "sharing_paused": paused, "audio": AUDIO_NOTE,
            "simulated": any(s["simulated"] for s in stories) or svc.is_simulated(elder_id)}


def set_shared(svc, elder_id: str, story_id: int, shared: bool, actor: str, role: str,
               confirmed: bool, requested_by: str | None) -> dict | None:
    r = svc.store.one("SELECT * FROM memory_story WHERE elder_id=? AND id=?", (elder_id, story_id))
    if not r:
        return None
    consent = json.loads(r["consent_json"] or "{}")
    entry = {"shared": shared, "by": actor, "role": role, "requested_by": requested_by or actor,
             "confirmed_by_elder_or_proxy": confirmed or _is_elder(role), "ts": now_iso()}
    consent.setdefault("history", []).append(entry)
    consent.update({"answer": "yes" if shared else "no", "changed_by": actor, "changed_at": entry["ts"],
                    "confirmed_by_elder_or_proxy": entry["confirmed_by_elder_or_proxy"]})
    svc.store.x("UPDATE memory_story SET shared=?, consent_json=?, updated_at=? WHERE id=?",
                (1 if shared else 0, json.dumps(consent, ensure_ascii=False), now_iso(), story_id))
    return {"ok": True, "id": story_id, "shared": shared, "consent": consent}


# ---------------------------------------------------------------------------------------------- export
_E = html.escape


def export_html(svc, elder_id: str, lang: str = "vi") -> str:
    """Printable memoir of the shared stories, grouped into chapters by theme (era order inside a chapter)."""
    prof = svc.store.elder(elder_id) or {}
    stories = [s for s in all_stories(svc.store, elder_id) if s["shared"]]
    if svc.sharing_paused(elder_id):
        stories = []
    lang = lang if lang in ("vi", "en", "both") else "vi"
    vi_first = lang != "en"
    name_vi, name_en = prof.get("display_name", ""), prof.get("name_en", "")
    title = f"Sổ ký ức của {name_vi}" if vi_first else f"Memory book of {name_en}"
    subtitle_vi = (f"Những câu chuyện {name_vi[:1].lower() + name_vi[1:]} kể với Út Thương trong các cuộc gọi buổi "
                   f"sáng, và đồng ý kể lại cho con cháu.")
    subtitle_en = (f"Stories {name_en} told Út Thương on the morning calls, and agreed to share with the family.")
    simulated = any(s["simulated"] for s in stories) or svc.is_simulated(elder_id)
    dates = [s["date"] for s in stories if s["date"]]
    span = f"{_fmt_date(min(dates))} – {_fmt_date(max(dates))}" if dates else ""

    def era_key(s):
        return (s["era"].get("decade") or 9999, s["day"] or 0)

    chapters = []
    n = 0
    for t in ls.THEME_ORDER:
        items = sorted([s for s in stories if s["theme"] == t], key=era_key)
        if not items:
            continue
        n += 1
        tvi, ten = ls.THEMES[t]
        body = []
        for s in items:
            era = s["era"].get("label_vi" if vi_first else "label_en") or ""
            people = ", ".join(p.get("vi" if vi_first else "en", "") for p in s["people"])
            places = ", ".join(s["places"])
            meta = " · ".join(x for x in (era, places) if x)
            primary = s["text_vi"] if vi_first else (s["text_en"] or s["text_vi"])
            story_title = s["title_vi"] if vi_first else s["title_en"]
            extra = ""
            if lang == "both" and s["text_en"]:
                gist = ' <span class="gist">(English gist)</span>' if s["translation"] == "gist" else ""
                extra = f'<p class="tr" lang="en"><em>{_E(s["title_en"] or "")}</em> · {_E(s["text_en"])}{gist}</p>'
            elif lang == "en" and s["translation"] == "gist":
                extra = f'<p class="tr" lang="vi">{_E(s["text_vi"])}</p>'
            told = (f"Kể ngày {_fmt_date(s['date'])}" if vi_first else f"Told on {_fmt_date(s['date'], 'en')}") \
                if s["date"] else ""
            ppl = (f'<p class="people">{"Người trong chuyện" if vi_first else "People"}: {_E(people)}</p>'
                   if people else "")
            body.append(f'<article class="story"><h3>{_E(story_title or "")}</h3>'
                        f'<p class="meta">{_E(meta)}</p><p class="text" lang="{"vi" if vi_first else "en"}">'
                        f'<span class="q">“</span>{_E(primary)}<span class="q">”</span></p>{extra}{ppl}'
                        f'<p class="told">{_E(told)}</p></article>')
        chapters.append(f'<section class="chapter"><p class="num">{"Chương" if vi_first else "Chapter"} {n}</p>'
                        f'<h2>{_E(tvi if vi_first else ten)}</h2>{"".join(body)}</section>')
    if not chapters:
        chapters.append(f'<section class="chapter empty"><p>{"Chưa có câu chuyện nào được chia sẻ." if vi_first else "No shared stories yet."}</p></section>')
    sim_vi, sim_en = "Dữ liệu mô phỏng", "Simulated data"
    note_vi = ("Sổ này chỉ có những chuyện người kể đã đồng ý chia sẻ; những chuyện giữ riêng không có ở đây. "
               "Chỉ lưu chữ, không lưu giọng nói.")
    note_en = ("This book holds only the stories the teller agreed to share; private stories are not included. "
               "Text only; no voice is stored.")
    return f"""<!doctype html>
<html lang="{'vi' if vi_first else 'en'}"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_E(title)}</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Noto+Serif:ital,wght@0,400;0,600;1,400&family=Be+Vietnam+Pro:wght@500;600&display=swap" rel="stylesheet">
<style>
:root {{ --ink:#2b2420; --ink2:#5b4f47; --line:#d9cfc2; --paper:#fbf7f0; --accent:#7a3b2e; }}
* {{ box-sizing:border-box; }}
html {{ background:#efe8dc; }}
body {{ margin:0 auto; max-width:46rem; padding:2.5rem 1.25rem 4rem; background:var(--paper); color:var(--ink);
  font-family:"Noto Serif", Georgia, "Times New Roman", serif; font-size:1.125rem; line-height:1.7; }}
.cover {{ min-height:80vh; display:flex; flex-direction:column; justify-content:center; text-align:center;
  border-bottom:1px solid var(--line); margin-bottom:3rem; padding:2rem 0; }}
.cover .orn {{ color:var(--accent); letter-spacing:.6em; font-size:.9rem; }}
.cover h1 {{ font-size:clamp(2rem, 7vw, 3.1rem); line-height:1.15; margin:1.2rem 0 .8rem; font-weight:600; }}
.cover p {{ color:var(--ink2); margin:.3rem auto; max-width:32rem; font-style:italic; }}
.cover .small {{ font-family:"Be Vietnam Pro", system-ui, sans-serif; font-style:normal; font-size:.85rem; margin-top:2rem; }}
.badge {{ display:inline-block; border:1px solid var(--ink2); border-radius:99px; padding:.1rem .7rem; font-size:.8rem;
  font-family:"Be Vietnam Pro", system-ui, sans-serif; color:var(--ink2); }}
.chapter {{ margin:0 0 3rem; }}
.chapter .num {{ font-family:"Be Vietnam Pro", system-ui, sans-serif; text-transform:uppercase; letter-spacing:.18em;
  font-size:.75rem; color:var(--accent); margin:0; }}
.chapter h2 {{ font-size:1.9rem; font-weight:600; margin:.2rem 0 1.5rem; border-bottom:1px solid var(--line); padding-bottom:.6rem; }}
.story {{ margin:0 0 2.2rem; break-inside:avoid; }}
.story h3 {{ font-size:1.3rem; margin:0; font-weight:600; }}
.meta {{ font-family:"Be Vietnam Pro", system-ui, sans-serif; color:var(--ink2); font-size:.85rem; margin:.15rem 0 .6rem; }}
.text {{ margin:0; text-indent:0; }}
.text .q {{ color:var(--accent); }}
.tr {{ color:var(--ink2); font-size:1rem; margin:.5rem 0 0; }}
.gist {{ font-size:.8rem; }}
.people, .told {{ font-family:"Be Vietnam Pro", system-ui, sans-serif; font-size:.8rem; color:var(--ink2); margin:.4rem 0 0; }}
footer {{ border-top:1px solid var(--line); padding-top:1rem; font-size:.85rem; color:var(--ink2); }}
.print {{ position:fixed; right:1rem; bottom:1rem; font:600 .95rem "Be Vietnam Pro", system-ui, sans-serif; color:#fff;
  background:var(--accent); border:0; border-radius:99px; padding:.7rem 1.2rem; cursor:pointer; }}
@media print {{ html, body {{ background:#fff; }} body {{ max-width:none; padding:0; }} .print {{ display:none; }}
  .cover {{ min-height:auto; height:90vh; page-break-after:always; border:0; }} .chapter {{ page-break-before:always; }}
  @page {{ margin:2cm 2.2cm; }} }}
</style></head>
<body>
<header class="cover">
  <div class="orn">❦ ❦ ❦</div>
  <h1>{_E(title)}</h1>
  <p>{_E(subtitle_vi if vi_first else subtitle_en)}</p>
  {f'<p lang="en">{_E(subtitle_en)}</p>' if lang == "both" else ""}
  <p class="small">{_E(span)} · {len(stories)} {"câu chuyện" if vi_first else "stories"}</p>
  {f'<p class="small"><span class="badge">{sim_vi} / {sim_en}</span></p>' if simulated else ""}
</header>
{"".join(chapters)}
<footer><p>{_E(note_vi if vi_first else note_en)}</p>{f'<p lang="en">{_E(note_en)}</p>' if lang == "both" else ""}
<p>Chào Bà · Út Thương{f" · {sim_vi} / {sim_en}" if simulated else ""}</p></footer>
<button class="print" onclick="window.print()">{"In sổ" if vi_first else "Print"}</button>
</body></html>"""


def _fmt_date(iso: str | None, lang: str = "vi") -> str:
    if not iso:
        return ""
    d = Date.fromisoformat(iso[:10])
    return f"{d.day:02d}/{d.month:02d}/{d.year}" if lang == "vi" else d.strftime("%-d %b %Y")


# ---------------------------------------------------------------------------------------------- activities summary
def _rate(xs: list[str]) -> float | None:
    xs = [x for x in xs if x in ("success", "partial", "miss")]
    if not xs:
        return None
    return round((sum(1 for x in xs if x == "success") + 0.5 * sum(1 for x in xs if x == "partial")) / len(xs), 3)


def _mean(xs: list[float]) -> float | None:
    return round(sum(xs) / len(xs), 2) if xs else None


def activities_summary(svc, elder_id: str, role: str = "primary") -> dict:
    store = svc.store
    sim = svc.is_simulated(elder_id)
    if svc.sharing_paused(elder_id) and not _is_elder(role):
        return {"sharing_paused": True, "simulated": sim}
    recs = {r["day"]: r for r in store.records(elder_id) if not (r.get("simulated") and r.get("channel") == "web")}
    games = activity_rows(store, elder_id, "game")
    nudges = activity_rows(store, elder_id, "nudge")
    questions = activity_rows(store, elder_id, "life_question")
    plans = activity_rows(store, elder_id, "care_plan")
    last_day = max([r["day"] for r in games + nudges] + list(recs) or [0])

    # weekly trend of the games (success rate counts a partial answer as half)
    trend = []
    if games:
        first = min(g["day"] for g in games)
        w = 0
        while first + 7 * w <= last_day:
            a, b = first + 7 * w, first + 7 * w + 6
            gs = [g for g in games if a <= g["day"] <= b]
            if gs:
                trend.append({"week": w + 1, "day_from": a, "day_to": b, "played": len(gs),
                              "success_rate": _rate([g["outcome"] for g in gs]),
                              "mean_level": _mean([g["level"] for g in gs if g["level"]])})
            w += 1
    by_cat: dict[str, dict] = {}
    for g in games:
        c = by_cat.setdefault(g["category"], {"category": g["category"], "played": 0, "outcomes": []})
        c["played"] += 1
        c["outcomes"].append(g["outcome"])
    game_cats = [{"category": k, "label_vi": act.GAME_LABEL.get(k, (k, k))[0], "label_en": act.GAME_LABEL.get(k, (k, k))[1],
                  "played": v["played"], "success_rate": _rate(v["outcomes"])} for k, v in by_cat.items()]
    early = [g["outcome"] for g in games if g["day"] <= (games[0]["day"] + 27 if games else 0)]
    recent = [g["outcome"] for g in games if g["day"] > last_day - 28]
    nud_cats: dict[str, int] = {}
    for n in nudges:
        nud_cats[n["category"]] = nud_cats.get(n["category"], 0) + 1

    # Association (NOT causation): next-day mood / poor-sleep mention after days with vs without an activity.
    def outcome_next(days: set[int]):
        mood, poor = [], []
        for d in days:
            r = recs.get(d + 1)
            if r and r.get("answered") and r.get("mood") is not None:
                mood.append(float(r["mood"]))
                poor.append(1.0 if (r.get("symptoms") or {}).get("insomnia") else 0.0)
        return mood, poor
    answered = {d for d, r in recs.items() if r.get("answered")}
    assoc = []
    groups = [(f"nudge:{c}", {n["day"] for n in nudges if n["category"] == c}, act.NUDGES[c][1], act.NUDGES[c][2])
              for c in act.NUDGES if any(n["category"] == c for n in nudges)]
    groups.append(("game_day", {g["day"] for g in games}, "Ngày có chơi trò nhớ", "Days with a memory game"))
    for key, with_days, lvi, len_ in groups:
        with_days &= answered
        without = answered - with_days
        mw, pw = outcome_next(with_days)
        mo, po = outcome_next(without)
        if len(mw) < 5 or len(mo) < 5:
            continue
        assoc.append({"activity": key, "label_vi": lvi, "label_en": len_, "days_with": len(mw), "days_without": len(mo),
                      "next_day_mood_with": _mean(mw), "next_day_mood_without": _mean(mo),
                      "mood_diff": round((_mean(mw) or 0) - (_mean(mo) or 0), 2),
                      "next_day_poor_sleep_with": _mean(pw), "next_day_poor_sleep_without": _mean(po)})
    assoc.sort(key=lambda a: -a["mood_diff"])

    improve = None
    if plans:
        p = plans[-1]
        d0 = p["day"]
        pre = [recs[d] for d in range(d0 - 14, d0) if d in recs and recs[d].get("answered")]
        post = [recs[d] for d in range(d0 + 1, last_day + 1) if d in recs and recs[d].get("answered")]
        plan_nudges = [n for n in nudges if n["day"] >= d0 and n["detail"].get("care_plan")]
        improve = {"day": d0, "date": p["date"], "focus": p["detail"].get("focus") or [],
                   "focus_labels": [{"category": c, "label_vi": act.NUDGES[c][1], "label_en": act.NUDGES[c][2]}
                                    for c in p["detail"].get("focus") or [] if c in act.NUDGES],
                   "label_vi": p["detail"].get("label_vi"), "label_en": p["detail"].get("label_en"),
                   "plan_nudges_delivered": len(plan_nudges),
                   "mood_before": _mean([float(r["mood"]) for r in pre if r.get("mood") is not None]),
                   "mood_after": _mean([float(r["mood"]) for r in post if r.get("mood") is not None]),
                   "poor_sleep_before": _mean([1.0 if (r.get("symptoms") or {}).get("insomnia") else 0.0 for r in pre]),
                   "poor_sleep_after": _mean([1.0 if (r.get("symptoms") or {}).get("insomnia") else 0.0 for r in post])}

    # Games the elder played by tapping on the standing screen (stored by elder_ui.py; read, not duplicated).
    screen_games = None
    try:
        from . import elder_ui
        elder_ui.ensure_tables(store)
        plays = [elder_ui._play(r) for r in elder_ui._rows(store, "elder_game_play", elder_id, "0001-01-01")]
        by_game: dict[str, list[bool]] = {}
        for pl in plays:
            by_game.setdefault(pl["game"], []).append(pl["correct"])
        recent_plays = [pl for pl in plays if pl["day"] is not None and pl["day"] > last_day - 14]
        screen_games = {
            "played": len(plays),
            "correct_rate": round(sum(pl["correct"] for pl in plays) / len(plays), 3) if plays else None,
            "played_last_14_days": len(recent_plays),
            "by_game": [{"game": g, "played": len(v), "correct_rate": round(sum(v) / len(v), 3)}
                        for g, v in by_game.items()],
            "source_vi": "Trò chơi bấm trên màn hình đứng (người cao tuổi tự chơi)",
            "source_en": "Tap games on the standing screen (played by the elder)"}
    except Exception as e:  # pragma: no cover - the screen module is optional
        log.warning("screen game plays unavailable: %s", e)

    stories = all_stories(store, elder_id)
    half = len(stories) // 2
    narrative = None
    if len(stories) >= 4:
        e_w = _mean([float(s["word_count"] or 0) for s in stories[:half]])
        r_w = _mean([float(s["word_count"] or 0) for s in stories[half:]])
        narrative = {"stories": len(stories), "words_early": e_w, "words_recent": r_w,
                     "change_pct": round(100 * (r_w - e_w) / e_w, 1) if e_w else None,
                     "note_vi": "Độ dài trung bình các câu chuyện (gồm cả chuyện giữ riêng, chỉ đếm số chữ). Chỉ để "
                                "tham khảo, không dùng cho đèn hằng ngày.",
                     "note_en": "Average story length (including private stories, word counts only). Exploratory; "
                                "not used by the daily light."}
    return {
        "games": {"played": len(games), "success_rate": _rate([g["outcome"] for g in games]),
                  "success_rate_first_4_weeks": _rate(early), "success_rate_last_4_weeks": _rate(recent),
                  "current_level": act.next_level([g["outcome"] for g in games]), "by_category": game_cats,
                  "trend": trend},
        "nudges": {"delivered": len(nudges), "by_category": [
            {"category": c, "label_vi": act.NUDGES[c][1], "label_en": act.NUDGES[c][2], "count": nud_cats.get(c, 0)}
            for c in act.NUDGES if nud_cats.get(c)]},
        "screen_games": screen_games,
        "life_questions": {"asked": len(questions), "stories": len(stories)},
        "associations": assoc,
        "association_note_vi": "Chỉ là liên quan, không phải nhân quả: ngày hôm sau có thể khác vì nhiều lý do khác "
                               "(thời tiết, thuốc, con cháu ghé thăm). Mẫu nhỏ.",
        "association_note_en": "Association, not causation: the next day can differ for many other reasons (weather, "
                               "medication, visits). Small samples.",
        "improve": improve,
        "narrative": narrative,
        "difficulty_rule_vi": "Trò chơi tự dễ hơn sau một lần chưa nhớ ra, khó hơn sau hai lần nhớ đúng liền (mức 1–3).",
        "difficulty_rule_en": "Games get easier after a miss and harder after two successes in a row (levels 1–3).",
        "simulated": sim or any(g["simulated"] for g in games),
    }


# ============================================================================================ routes
class ShareIn(BaseModel):
    confirmed_by_elder_or_proxy: bool = False
    requested_by: str | None = None


def register(app) -> None:
    def ident(request: Request) -> tuple[str, str]:
        return (unquote(request.headers.get("x-actor", "family:primary"))[:80],
                unquote(request.headers.get("x-role", "primary"))[:40])

    def guard(request: Request, elder_id: str, action: str):
        s = request.app.state.svc
        if not s.elder_or_none(elder_id):
            raise HTTPException(404, f"unknown elder {elder_id}")
        a, r = ident(request)
        s.store.log_access(elder_id, a, r, action, str(request.url.path))
        return s, a, r

    @app.get("/api/elders/{elder_id}/memories")
    def memories(request: Request, elder_id: str):
        s, _, r = guard(request, elder_id, "read_memories")
        return memories_view(s, elder_id, r)

    @app.get("/api/elders/{elder_id}/memories/export", response_class=HTMLResponse)
    def memories_export(request: Request, elder_id: str, lang: str = "vi"):
        s, _, _ = guard(request, elder_id, "read_memories_export")
        return HTMLResponse(export_html(s, elder_id, lang))

    def change(request: Request, elder_id: str, mid: int, shared: bool, body: ShareIn | None):
        body = body or ShareIn()
        a, r = ident(request)
        if not _is_elder(r) and not body.confirmed_by_elder_or_proxy:
            raise HTTPException(400, {
                "error": "confirmation_required", "field": "confirmed_by_elder_or_proxy",
                "message_en": ("Whether a story is shared is the elder's decision. A family member can change it only "
                               "after the elder (or their legal proxy) has confirmed. Send "
                               "{\"confirmed_by_elder_or_proxy\": true}."),
                "message_vi": ("Chia sẻ câu chuyện hay không là quyền của người cao tuổi. Người nhà chỉ đổi được sau khi "
                               "chính người cao tuổi (hoặc người đại diện hợp pháp) đã xác nhận.")})
        s, _, _ = guard(request, elder_id, "share_memory" if shared else "unshare_memory")
        out = set_shared(s, elder_id, mid, shared, a, r, body.confirmed_by_elder_or_proxy, body.requested_by)
        if out is None:
            raise HTTPException(404, "story not found")
        return out

    @app.post("/api/elders/{elder_id}/memories/{mid}/share")
    def share(request: Request, elder_id: str, mid: int, body: ShareIn | None = None):
        return change(request, elder_id, mid, True, body)

    @app.post("/api/elders/{elder_id}/memories/{mid}/unshare")
    def unshare(request: Request, elder_id: str, mid: int, body: ShareIn | None = None):
        return change(request, elder_id, mid, False, body)

    @app.get("/api/elders/{elder_id}/activities")
    def activities_ep(request: Request, elder_id: str):
        s, _, r = guard(request, elder_id, "read_activities")
        return activities_summary(s, elder_id, r)
