"""Brain-health context for the family Trends page ("Bối cảnh sức khỏe não bộ").

The daily light (control_chart.py) is about *change in cognitive and functional signals against the person's own
baseline*. This endpoint puts the other signals Chào Bà already records next to it, for the last 14 or 28 days, so a
family (and a reviewer) can see the light in context: story recall, speech rate, poor-sleep mentions, mood, medication
taps, family connection, symptoms mentioned and memory-game plays. It is a summary of existing data, not a score:

* nothing here is new input to the light, and nothing is combined into a risk number;
* "vs her usual" is given only where a personal baseline exists (speech rate, recall: the baseline segment in force,
  service.baselines); other items are compared with the previous period of the same length;
* a chart signal is called "outside her usual range" only when the light itself flagged it in the window (a
  ``metric_trend`` / ``metric_shift`` / ``multi_metric`` reason for that metric); no new threshold is introduced;
* recall is stated as counts ("full recall 9 of 12 calls, usually about 11"), never as a percentage (explain.py);
* the elder's ``family_sharing`` pause hides everything (like timeline / connection); with ``voice_metrics``
  withdrawn there are no new speech values and the item says so;
* metabolic, genomic and wearable data are not part of this prototype: future consented connectors only.

  GET /api/elders/{id}/brain_context?days=14|28
"""
from __future__ import annotations

from datetime import date as Date, timedelta
from urllib.parse import unquote

import numpy as np
from fastapi import FastAPI, HTTPException, Request

from chaoba.core.control_chart import CONCERN_PREFIX
from chaoba.core.explain import _pct

WINDOWS = (14, 28)
CHART_CODES = ("metric_trend", "metric_shift", "multi_metric")
SYM_VI = {"pain": "đau nhức", "insomnia": "ngủ không ngon", "skipped_meal": "ăn ít / bỏ bữa", "dizziness": "chóng mặt",
          "fall": "té ngã", "sadness": "thấy buồn", "missed_medication": "quên uống thuốc"}
SYM_EN = {"pain": "aches or pain", "insomnia": "poor sleep", "skipped_meal": "eating little / skipped meals",
          "dizziness": "dizziness", "fall": "a fall", "sadness": "feeling down", "missed_medication": "missed medication"}
FUTURE_VI = "Dữ liệu chuyển hóa, gen và thiết bị đeo: kết nối trong tương lai, chỉ khi có đồng ý (chưa có trong bản thử này)."
FUTURE_EN = "Metabolic, genomic and wearable data: future consented connectors (not in this prototype)."
NOTE_VI = ("Đặt cạnh đèn tín hiệu để dễ hiểu bối cảnh. Đây không phải kết luận bệnh và không gộp thành điểm số; đèn "
           "chỉ báo thay đổi so với mức thường ngày của chính người thân.")
NOTE_EN = ("Shown beside the light for context. Not a medical finding and not combined into a score; the light only "
           "flags change against your parent's own usual.")


def _d(iso: str) -> Date:
    return Date.fromisoformat(iso[:10])


def _flagged_days(lights: list[dict], metric: str) -> int:
    n = 0
    for l in lights:
        if l.get("light") not in ("yellow", "red"):
            continue
        for r in l.get("reasons") or []:
            if r.get("code") in CHART_CODES and (r.get("metric") == metric or metric in (r.get("metrics") or [])):
                n += 1
                break
    return n


def _vals(recs, key):
    return [float(r[key]) for r in recs if r.get("answered") and r.get("valid") and r.get(key) is not None]


def _item(key, in_light, available=True, **kw):
    return {"key": key, "in_light": in_light, "available": available, **kw}


def brain_context(svc, elder_id: str, days: int = 14) -> dict:
    days = days if days in WINDOWS else WINDOWS[0]
    simulated = svc.is_simulated(elder_id)
    base = {"days": days, "simulated": simulated, "future_vi": FUTURE_VI, "future_en": FUTURE_EN,
            "note_vi": NOTE_VI, "note_en": NOTE_EN}
    if svc.sharing_paused(elder_id):
        return {**base, "sharing_paused": True, "light": None, "items": []}
    st = svc.store
    recs = st.records(elder_id)
    if not recs:
        return {**base, "sharing_paused": False, "light": None, "items": []}
    _, today = svc.current_day(elder_id)
    end = max(_d(today), _d(recs[-1]["date"]))
    start = end - timedelta(days=days - 1)
    p_start = start - timedelta(days=days)

    def win(rows, lo, hi):
        return [r for r in rows if lo <= _d(r["date"]) <= hi]
    now, prev = win(recs, start, end), win(recs, p_start, start - timedelta(days=1))
    lights = win(st.lights(elder_id), start, end)
    counts = {c: sum(1 for l in lights if l["light"] == c) for c in ("green", "yellow", "red", "gray")}
    light = {"counts": counts, "latest": lights[-1]["light"] if lights else None}

    segs = svc.baselines(elder_id, recs)
    seg = segs[-1] if segs else None
    items = []

    # ---- story recall (chart metric; counts, never a %) ----------------------------------------
    asked = [r for r in now if r.get("valid") and r.get("recall_score") is not None]
    if seg and asked:
        w0, w1 = seg["window"]
        b = [r for r in recs if w0 <= r["day"] <= w1 and r.get("valid") and r.get("recall_score") is not None]
        usual = round(sum(1 for r in b if r["recall_score"] >= 3) / len(b) * len(asked)) if b else None
        items.append(_item("recall", True, free=sum(1 for r in asked if r["recall_score"] >= 3), asked=len(asked),
                           usual=usual, flagged_days=_flagged_days(lights, "recall_score"), compare="baseline"))
    else:
        items.append(_item("recall", True, False, reason="no_baseline" if asked else "no_calls"))

    # ---- speech rate (chart metric) -----------------------------------------------------------
    sr = _vals(now, "speech_rate_sps")
    c = ((seg or {}).get("metrics") or {}).get("speech_rate_sps", {}).get("center")
    if sr and c:
        ch = (float(np.mean(sr)) - c) / c * 100.0
        items.append(_item("speech_rate", True, mean=round(float(np.mean(sr)), 2), usual=round(c, 2),
                           change_pct=_pct(ch), direction="slower" if ch < 0 else "faster", calls=len(sr),
                           flagged_days=_flagged_days(lights, "speech_rate_sps"), compare="baseline"))
    else:
        off = not st.consent_granted(elder_id, "voice_metrics")
        items.append(_item("speech_rate", True, False,
                           reason="voice_metrics_off" if off else ("no_baseline" if sr else "no_calls")))

    # ---- poor-sleep mentions, low mood, symptoms (event rules of the light) ---------------------
    def sym_days(rows, s):
        return sum(1 for r in rows if (r.get("symptoms") or {}).get(s))
    answered = [r for r in now if r.get("answered")]
    items.append(_item("sleep", True, bool(answered), days=sym_days(now, "insomnia"),
                       prev=sym_days(prev, "insomnia") if prev else None, calls=len(answered), compare="previous"))
    moods = [r["mood"] for r in now if r.get("mood") is not None]
    pmoods = [r["mood"] for r in prev if r.get("mood") is not None]
    checkins = _checkins(st, elder_id, start, end)
    items.append(_item("mood", True, bool(moods or checkins), low_days=sum(1 for m in moods if m <= 2),
                       prev=sum(1 for m in pmoods if m <= 2) if pmoods else None, calls=len(moods),
                       checkins=checkins, compare="previous"))
    mentions: dict[str, int] = {}
    for r in now:
        for k, v in (r.get("symptoms") or {}).items():
            if v and not k.startswith(CONCERN_PREFIX) and k != "insomnia":
                mentions[k] = mentions.get(k, 0) + 1
    concerns = sum(1 for r in now for k, v in (r.get("symptoms") or {}).items() if v and k.startswith(CONCERN_PREFIX))
    top = sorted(mentions.items(), key=lambda kv: (-kv[1], kv[0]))[:3]
    items.append(_item("symptoms", True, bool(answered), days=sum(1 for r in now if any(
        v and k != "insomnia" for k, v in (r.get("symptoms") or {}).items())),
        prev=sum(1 for r in prev if any(v and k != "insomnia" for k, v in (r.get("symptoms") or {}).items()))
        if prev else None,
        top=[{"symptom": k, "days": n, "label_vi": SYM_VI.get(k, k), "label_en": SYM_EN.get(k, k)} for k, n in top],
        concerns=concerns, compare="previous"))

    # ---- medication taps on the elder's screen (not in the light) ----------------------------
    items.append(_medication(svc, elder_id, start, end, p_start))

    # ---- family connection (connection.py; never in the light) -------------------------------
    from .connection import connection
    cn = connection(svc, elder_id, weeks=2 * (days // 7))
    wk = cn.get("weeks") or []
    k = days // 7
    if wk:
        items.append(_item("connection", False, days_in_touch=sum(w["days_in_touch"] for w in wk[-k:]),
                           prev=sum(w["days_in_touch"] for w in wk[:-k]) if len(wk) >= 2 * k else None,
                           calls_visits=sum(w["calls_visits"] for w in wk[-k:]), compare="previous"))
    else:
        items.append(_item("connection", False, False, reason="no_data"))

    # ---- memory-game plays on the screen (engagement only, never scored) ---------------------
    plays = _screen_rows(st, elder_id, "elder_game_play", start, end)
    pplays = _screen_rows(st, elder_id, "elder_game_play", p_start, start - timedelta(days=1))
    items.append(_item("games", False, plays=len(plays), days_played=len({r["date"] for r in plays}),
                       prev=len(pplays), compare="previous"))

    return {**base, "sharing_paused": False, "from": start.isoformat(), "to": end.isoformat(), "light": light,
            "baseline_from_day": seg["from_day"] if seg else None, "items": items}


def _screen_rows(store, elder_id, table, lo: Date, hi: Date) -> list[dict]:
    from .elder_ui import ensure_tables
    ensure_tables(store)
    return [dict(r) for r in store.q(f"SELECT * FROM {table} WHERE elder_id=? AND date>=? AND date<=? ORDER BY id",
                                     (elder_id, lo.isoformat(), hi.isoformat()))]


def _checkins(store, elder_id, lo, hi) -> dict | None:
    rows = _screen_rows(store, elder_id, "elder_mood_checkin", lo, hi)
    if not rows:
        return None
    return {m: sum(1 for r in rows if r["mood"] == m) for m in ("happy", "neutral", "sad")}


def _medication(svc, elder_id, start, end, p_start) -> dict:
    prof = svc.elder_or_none(elder_id) or {}
    if not prof.get("medications"):
        return _item("medication", False, False, reason="no_medications")

    def taken(rows):
        last: dict[str, str] = {}
        for r in rows:  # latest tap of each day wins
            last[r["date"]] = r["status"]
        return sum(1 for s in last.values() if s == "taken"), len(last)
    now = _screen_rows(svc.store, elder_id, "elder_med_log", start, end)
    if not now:
        return _item("medication", False, False, reason="not_logged")
    t, n = taken(now)
    pt, pn = taken(_screen_rows(svc.store, elder_id, "elder_med_log", p_start, start - timedelta(days=1)))
    return _item("medication", False, taken_days=t, answered_days=n, prev_taken_days=pt if pn else None,
                 compare="previous")


def register(app: FastAPI) -> None:
    @app.get("/api/elders/{elder_id}/brain_context")
    def get_brain_context(request: Request, elder_id: str, days: int = 14):
        s = request.app.state.svc
        if not s.elder_or_none(elder_id):
            raise HTTPException(404, f"unknown elder {elder_id}")
        if days not in WINDOWS:
            raise HTTPException(422, {"error": "bad_window", "allowed": list(WINDOWS)})
        s.store.log_access(elder_id, unquote(request.headers.get("x-actor", "family:primary"))[:80],
                           unquote(request.headers.get("x-role", "primary"))[:40], "read_brain_context",
                           str(request.url.path))
        return brain_context(s, elder_id, days)
