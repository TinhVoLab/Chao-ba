"""Community dashboard for a commune/ward health station (B2G): a simulated ward of older adults on daily calls.

``GET /api/community/overview`` (``X-Role: clinician`` or ``health_station``; anything else -> 403) returns, for the
simulated "Phường X, TP.HCM" (~60 elders from ``chaoba.core.synth.generate_cohort`` plus the 3 demo personas):

* counts by light today, and the ward's daily light counts over the last 30 days;
* a **prioritised visit list**: red first, then yellow (each by days in that state, then missed family contact, then
  living alone), then a "check-in" group of green elders who live alone and have had no family contact for
  ``CHECKIN_NO_CONTACT_DAYS``. Rows are **pseudonymised** (initials + age + area); no names, no addresses, no map;
* an anonymised aggregate: which recorded interventions **coincided** with a return to green within
  ``RECOVERY_DAYS``. Association only: in this simulation interventions are assigned at random, so differences are
  noise by construction; episodes whose outcome window is not over yet are reported as open, not as failures.

Only elders whose ``clinician_sharing`` consent is active appear (the demo personas use their stored consent; ~5 % of
the simulated cohort is simulated as not sharing and only counted). Each read is written to the access log of every
persona shown, so the elder's privacy page lists the health station. Everything here is ``simulated: true``.
Wording follows the rest of Chào Bà: change relative to the person's own baseline, never a diagnosis.
"""
from __future__ import annotations

import threading
from datetime import date as Date, timedelta
from urllib.parse import unquote

import numpy as np
from fastapi import FastAPI, HTTPException, Request

from chaoba.core import control_chart, synth
from chaoba.core.explain import METRIC_EN, METRIC_VI, SYMPTOM_EN, SYMPTOM_VI
from chaoba.core.models import DailyRecord

from .service import Service, seed_end_date

ALLOWED_ROLES = ("clinician", "health_station")
COHORT_N, COHORT_DAYS, COHORT_SEED = 60, 120, 2026
TREND_DAYS = 30
RECOVERY_DAYS = 21
MISSED_CONTACT_DAYS = 7
CHECKIN_NO_CONTACT_DAYS = 10
WARD = {"name_vi": "Phường X, TP.HCM (mô phỏng)", "name_en": "Ward X, Ho Chi Minh City (simulated)"}
AREAS = [f"Khu phố {i}" for i in range(1, 7)]
INTERVENTIONS = {
    "family_calls": ("Gia đình gọi thường hơn", "Family called more often"),
    "station_visit": ("Trạm y tế đến thăm tại nhà", "Health-station home visit"),
    "clinic_visit": ("Đi khám bác sĩ", "Doctor visit"),
    "none": ("Chưa ghi nhận can thiệp", "No intervention recorded"),
}
INTERVENTION_P = {"family_calls": 0.35, "station_visit": 0.25, "clinic_visit": 0.2, "none": 0.2}
PERSONA_META = {  # where the demo personas sit in the simulated ward (pseudonymised like everyone else)
    "hanh": {"full": "Nguyễn Thị Hạnh", "area": "Khu phố 3"},
    "tu": {"full": "Trần Văn Tư", "area": "Khu phố 1"},
    "control": {"full": "Lê Văn Bảy", "area": "Khu phố 5"},
}
EVENT_INTERVENTION = {"doctor_visit": "clinic_visit", "care_plan": "family_calls"}
LEVEL = {"gray": -1, "green": 0, "yellow": 1, "red": 2}
DISCLAIMER_VI = ("Dữ liệu mô phỏng. Danh sách giúp sắp xếp thứ tự thăm hỏi, không phải chẩn đoán: đèn chỉ cho biết "
                 "thay đổi so với mức thường ngày của chính người đó.")
DISCLAIMER_EN = ("Simulated data. The list helps order home visits; it is not a diagnosis: a light only shows change "
                 "relative to the person's own usual pattern.")
ASSOC_NOTE_VI = ("Chỉ là trùng thời điểm, không chứng minh nguyên nhân. Trong mô phỏng này can thiệp được gán ngẫu "
                 "nhiên, nên khác biệt giữa các nhóm là do ngẫu nhiên. Nhóm dưới 5 đợt: chưa đủ để so sánh.")
ASSOC_NOTE_EN = ("Coincidence in time only, not cause. In this simulation interventions are assigned at random, so "
                 "differences between groups are chance. Groups under 5 episodes: too few to compare.")

_cache: dict[str, list[dict]] = {}
_lock = threading.Lock()


def _initials(full: str) -> str:
    return ".".join(w[0].upper() for w in full.split() if w) + "."


def reason_label(r: dict) -> tuple[str, str] | None:
    """Short, non-diagnostic VI/EN label for one control-chart reason (None for info-only codes)."""
    c = r.get("code")
    if c in ("metric_trend", "metric_shift") and r.get("metric"):
        m = r["metric"]
        vi, en = METRIC_VI.get(m, m), METRIC_EN.get(m, m)
        return f"{vi[:1].upper()}{vi[1:]} thường ngày", f"{en[:1].upper()}{en[1:]} than usual"
    if c == "multi_metric":
        return "Nhiều chỉ số lệch khỏi mức riêng", "Several signals off own baseline"
    if c == "symptom_repeat":
        s = r.get("symptom", "")
        return f"Nhắc {SYMPTOM_VI.get(s, s)} nhiều lần", f"Mentioned {SYMPTOM_EN.get(s, s)} repeatedly"
    if c == "multi_symptom":
        return "Kể nhiều điều khó chịu khác nhau", "Mentioned several different complaints"
    if c == "unanswered":
        return f"Không bắt máy {r.get('days', '')} ngày", f"No answer for {r.get('days', '')} days"
    if c == "low_mood":
        return "Tâm trạng thấp nhiều ngày", "Low mood on several days"
    if c == "fall":
        return "Có kể bị té ngã", "Mentioned a fall"
    if c == "emergency":
        return "Có cuộc gọi khẩn cấp", "Emergency during a call"
    if c == "health_concern":
        return "Kể một chuyện sức khỏe cần hỏi thăm", "Mentioned a health concern to follow up"
    return None


def _days_in_state(series: list[tuple[str, str]]) -> int:
    if not series:
        return 0
    cur, n = series[-1][1], 0
    for _, l in reversed(series):
        if l != cur:
            break
        n += 1
    return n


def episodes(series: list[tuple[str, str]], end: Date, assign) -> list[dict]:
    """Yellow/red episodes in a (date, light) series: start = first non-green day after green; end = next green day.
    ``assign(start_date)`` returns the intervention key recorded for that episode."""
    out, cur, prev = [], None, "green"
    for d, l in series:
        if l == "gray":
            continue
        if cur is None and LEVEL[l] >= 1 and prev == "green":
            cur = {"start": d, "peak": l}
        elif cur is not None:
            if LEVEL[l] > LEVEL[cur["peak"]]:
                cur["peak"] = l
            if l == "green":
                cur["end"] = d
                out.append(cur)
                cur = None
        prev = l
    if cur is not None:
        out.append(cur)
    for e in out:
        start = Date.fromisoformat(e["start"])
        e["intervention"] = assign(e["start"])
        e["days_to_green"] = (Date.fromisoformat(e["end"]) - start).days if e.get("end") else None
        observable = (end - start).days >= RECOVERY_DAYS
        e["recovered"] = e["days_to_green"] is not None and e["days_to_green"] <= RECOVERY_DAYS
        e["open"] = not observable and not e["recovered"]
    return out


def _cohort(end: Date) -> list[dict]:
    """The simulated ward (cached per calendar anchor): records -> lights through the same control chart."""
    key = end.isoformat()
    with _lock:
        if key in _cache:
            return _cache[key]
        rows = []
        for i, e in enumerate(synth.generate_cohort(n=COHORT_N, days=COHORT_DAYS, seed=COHORT_SEED)):
            rng = np.random.default_rng([COHORT_SEED, 77, i])
            recs = [DailyRecord(**{k: r.get(k) for k in DailyRecord.__dataclass_fields__ if k in r})
                    for r in e["records"]]
            for rr, r in zip(recs, e["records"]):
                rr.symptoms = dict(r.get("symptoms") or {})
            lights = control_chart.evaluate_series(recs)
            last = lights[-1].day
            series = [((end - timedelta(days=last - l.day)).isoformat(), l.light) for l in lights]
            p = e["elder"]
            female = p.get("honorific") == "bà"
            given = p["display_name"].split(" ", 1)[1]
            full = f"{rng.choice(synth.FAMILY)} {'Thị' if female else 'Văn'} {given}"
            alone = bool(p.get("lives_alone"))
            gap = int(rng.integers(0, 4)) if rng.random() < 0.75 else int(rng.integers(5, 21) + (4 if alone else 0))
            kinds = list(INTERVENTION_P)
            probs = np.array(list(INTERVENTION_P.values()))

            def assign(_start, _rng=rng, _k=kinds, _p=probs):
                return str(_rng.choice(_k, p=_p / _p.sum()))
            rows.append({"pid": f"w{i + 1:03d}", "initials": _initials(full), "age": int(p["age"]),
                         "area": AREAS[int(rng.integers(0, len(AREAS)))], "lives_alone": alone,
                         "series": series, "reasons": lights[-1].reasons, "days_since_contact": gap,
                         "sharing": bool(rng.random() >= 0.05), "persona": False,
                         "episodes": episodes(series, end, assign)})
        _cache.clear()
        _cache[key] = rows
        return rows


def _personas(svc: Service, end: Date) -> list[dict]:
    out = []
    for n, eid in enumerate(svc.store.elder_ids()):
        p = svc.store.elder(eid) or {}
        lights = svc.store.lights(eid)
        if not lights:
            continue
        meta = PERSONA_META.get(eid, {"full": p.get("display_name", eid), "area": AREAS[0]})
        series = [(l["date"], l["light"]) for l in lights]
        cs = svc.contact_status(eid)
        events = svc.store.events(eid)
        dates = {r["day"]: r["date"] for r in svc.store.records(eid)}

        def assign(start, _ev=events, _dates=dates):
            s = Date.fromisoformat(start)
            for e in _ev:
                d = _dates.get(e["day"])
                if d and 0 <= (Date.fromisoformat(d) - s).days <= 14 and e["type"] in EVENT_INTERVENTION:
                    return EVENT_INTERVENTION[e["type"]]
            return "none"
        out.append({"pid": f"d{n + 1:02d}", "initials": _initials(meta["full"]), "age": int(p.get("age") or 0),
                    "area": meta["area"], "lives_alone": bool(p.get("lives_alone")), "series": series,
                    "reasons": lights[-1].get("reasons") or [], "days_since_contact": cs["days_since"],
                    "sharing": svc.store.consent_granted(eid, "clinician_sharing"), "persona": True,
                    "episodes": episodes(series, Date.fromisoformat(series[-1][0]), assign)})
    return out


def _row(e: dict) -> dict:
    light = e["series"][-1][1] if e["series"] else "gray"
    labels = [x for x in (reason_label(r) for r in e["reasons"]) if x]
    dsc = e["days_since_contact"]
    n = _days_in_state(e["series"])
    return {"pid": e["pid"], "label": f"{e['initials']} · {e['age']} · {e['area']}", "initials": e["initials"],
            "age": e["age"], "area": e["area"], "light": light, "days_in_state": n,
            "since_date": e["series"][-n][0] if n else None, "reasons_vi": [x[0] for x in labels][:3],
            "reasons_en": [x[1] for x in labels][:3], "days_since_contact": dsc,
            "missed_contact": dsc is not None and dsc >= MISSED_CONTACT_DAYS, "lives_alone": e["lives_alone"],
            "demo_persona": e["persona"]}


def priority_key(row: dict) -> tuple:
    """Within a group: longer in this state first, then missed family contact, then living alone."""
    return (-row["days_in_state"], not row["missed_contact"], not row["lives_alone"], row["pid"])


def visit_list(rows: list[dict]) -> list[dict]:
    red = sorted([r for r in rows if r["light"] == "red"], key=priority_key)
    yellow = sorted([r for r in rows if r["light"] == "yellow"], key=priority_key)
    check = sorted([r for r in rows if r["light"] in ("green", "gray") and r["lives_alone"]
                    and (r["days_since_contact"] or 0) >= CHECKIN_NO_CONTACT_DAYS],
                   key=lambda r: (-(r["days_since_contact"] or 0), r["pid"]))
    out = []
    for group, rs in (("red", red), ("yellow", yellow), ("check_in", check)):
        for r in rs:
            out.append({**r, "group": group, "rank": len(out) + 1})
    return out


def associations(elders: list[dict]) -> list[dict]:
    out = []
    for k, (vi, en) in INTERVENTIONS.items():
        eps = [ep for e in elders for ep in e["episodes"] if ep["intervention"] == k]
        closed = [ep for ep in eps if not ep["open"]]
        rec = [ep for ep in closed if ep["recovered"]]
        days = sorted(ep["days_to_green"] for ep in rec)
        out.append({"intervention": k, "label_vi": vi, "label_en": en, "episodes": len(closed),
                    "open": len(eps) - len(closed), "recovered": len(rec),
                    "rate": round(len(rec) / len(closed), 3) if closed else None,
                    "median_days_to_green": days[len(days) // 2] if days else None,
                    "enough": len(closed) >= 5})
    return out


def overview(svc: Service) -> dict:
    end = seed_end_date()
    elders = _personas(svc, end) + _cohort(end)
    shared = [e for e in elders if e["sharing"]]
    rows = [_row(e) for e in shared]
    counts = {k: sum(1 for r in rows if r["light"] == k) for k in ("red", "yellow", "green", "gray")}
    last = end   # the cohort's calendar anchor (a live call today is not in the trend yet)
    trend = []
    for i in range(TREND_DAYS - 1, -1, -1):
        d = (last - timedelta(days=i)).isoformat()
        c = {"date": d, "red": 0, "yellow": 0, "green": 0, "gray": 0}
        for e in shared:
            lmap = e.setdefault("_map", dict(e["series"]))
            c[lmap.get(d, "gray")] += 1
        trend.append(c)
    return {"ward": {**WARD, "elders": len(elders), "sharing": len(shared), "not_sharing": len(elders) - len(shared),
                     "demo_personas": sum(1 for e in shared if e["persona"])},
            "as_of": last.isoformat(), "counts": counts,
            "lives_alone": sum(1 for r in rows if r["lives_alone"]),
            "missed_contact": sum(1 for r in rows if r["missed_contact"]),
            "visit_list": visit_list(rows), "trend": trend, "interventions": associations(shared),
            "method": {"recovery_days": RECOVERY_DAYS, "missed_contact_days": MISSED_CONTACT_DAYS,
                       "checkin_no_contact_days": CHECKIN_NO_CONTACT_DAYS, "trend_days": TREND_DAYS,
                       "cohort": {"n": COHORT_N, "days": COHORT_DAYS, "seed": COHORT_SEED}},
            "association_note_vi": ASSOC_NOTE_VI, "association_note_en": ASSOC_NOTE_EN,
            "disclaimer_vi": DISCLAIMER_VI, "disclaimer_en": DISCLAIMER_EN, "simulated": True}


def register(app: FastAPI) -> None:
    @app.get("/api/community/overview")
    def community_overview(request: Request):
        actor = unquote(request.headers.get("x-actor", "family:primary"))[:80]
        role = unquote(request.headers.get("x-role", "primary"))[:40]
        if role not in ALLOWED_ROLES:
            raise HTTPException(403, {"error": "clinician_only",
                                      "message_vi": "Bảng cộng đồng chỉ dành cho trạm y tế / nhân viên y tế.",
                                      "message_en": "The community dashboard is for health-station / clinical staff."})
        s: Service = request.app.state.svc
        out = overview(s)
        for eid in s.store.elder_ids():   # each sharing persona's privacy page shows the health station's read
            if s.store.consent_granted(eid, "clinician_sharing"):
                s.store.log_access(eid, actor, role, "read_community", str(request.url.path))
        s.store.log_access(None, actor, role, "read_community", str(request.url.path))
        return out
