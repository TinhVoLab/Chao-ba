"""Human review of red alerts by a clinician or the commune health station ("Trạm y tế xem xét").

Every red alert (a red light, a reported emergency or a health concern from a call) is marked ``needs_review`` until a
person with a clinical role has looked at it and recorded what was done. Chào Bà never decides on care by itself: the
light only says that something changed against the person's own usual; the review records the human decision.

* Only ``X-Role: clinician`` or ``health_station`` may review (anything else -> 403), and only while the elder's
  ``clinician_sharing`` consent is active (else 403). Each review is written to the access log, so the elder's
  privacy page shows who reviewed.
* ``outcome`` is one of ``OUTCOMES`` (no further action, family keeps watching, station phoned, home visit, repeat
  check in 2 weeks, referred to a doctor / geriatrics / neurology / mental-health services, sent to emergency care)
  plus an optional short note (<= 280 characters). The specialty referrals are the reviewer's own decision; Chào Bà
  never suggests one (the light does not know why a signal changed). The 2-week repeat interval is a placeholder to
  be set with clinical partners. A review can be corrected by
  reviewing again; the latest one is kept.
* The family sees the review on the alert ("Trạm y tế đã xem: hẹn khám bác sĩ"); the health-station board lists red
  alerts still waiting for review (pseudonymised, sharing elders only).

  POST /api/elders/{id}/alerts/{aid}/review     {outcome, note?}          clinician / health_station

Seeded review (simulated): Bà Hạnh's red alert on day 43 was reviewed on day 44 by the station and referred to a
doctor, matching the doctor visit in her DMAIC story.
"""
from __future__ import annotations

from urllib.parse import unquote

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

from .db import Store, now_iso

REVIEW_ROLES = ("clinician", "health_station")
MAX_NOTE = 280
OUTCOMES = {
    "no_action": ("Không cần can thiệp thêm", "No further action needed"),
    "family_follow_up": ("Gia đình tiếp tục theo dõi", "Family keeps watching"),
    "phone_check": ("Trạm đã gọi hỏi thăm", "Station phoned to check in"),
    "home_visit": ("Đến nhà thăm", "Home visit"),
    "repeat_assessment": ("Kiểm tra lại sau 2 tuần", "Repeat check in 2 weeks"),   # interval: set with clinical partners
    "gp_referral": ("Hẹn khám bác sĩ", "Referred to a doctor"),
    "geriatrics": ("Chuyển khám lão khoa", "Referred to geriatrics"),
    "neurology": ("Chuyển khám thần kinh", "Referred to neurology"),
    "mental_health": ("Chuyển dịch vụ sức khỏe tâm thần", "Referred to mental-health services"),
    "emergency": ("Đã chuyển cấp cứu", "Sent to emergency care"),
}
COLUMNS = (("review_outcome", "TEXT"), ("review_note", "TEXT"), ("reviewed_by", "TEXT"), ("reviewed_role", "TEXT"),
           ("reviewed_at", "TEXT"), ("reviewed_day", "INTEGER"))
SEED = {"hanh": {"alert_day": 43, "review_day": 44, "outcome": "gp_referral", "by": "Y sĩ Trạm y tế phường (mô phỏng)",
                 "note": "Đã gọi cho chị Lan, hẹn khám huyết áp sáng mai."}}


def migrate(conn) -> None:
    cols = {r[1] for r in conn.execute("PRAGMA table_info(alert)")}
    for col, ddl in COLUMNS:
        if col not in cols:
            conn.execute(f"ALTER TABLE alert ADD COLUMN {col} {ddl}")


def review_of(r) -> dict | None:
    """The review fields of an alert row, or None if not reviewed."""
    keys = r.keys()
    if "review_outcome" not in keys or not r["review_outcome"]:
        return None
    vi, en = OUTCOMES.get(r["review_outcome"], (r["review_outcome"], r["review_outcome"]))
    return {"outcome": r["review_outcome"], "outcome_vi": vi, "outcome_en": en, "note": r["review_note"] or "",
            "by": r["reviewed_by"], "role": r["reviewed_role"], "at": r["reviewed_at"], "day": r["reviewed_day"]}


def set_review(store: Store, alert_id: int, outcome: str, note: str, by: str, role: str, day: int | None,
               at: str | None = None) -> None:
    store.x("UPDATE alert SET review_outcome=?, review_note=?, reviewed_by=?, reviewed_role=?, reviewed_at=?, "
            "reviewed_day=? WHERE id=?", (outcome, note, by, role, at or now_iso(), day, alert_id))


def pending(store: Store, elder_id: str) -> list[dict]:
    return [a for a in store.alerts(elder_id) if a["needs_review"]]


def seed_all(svc) -> None:
    st = svc.store
    for eid, s in SEED.items():
        r = st.one("SELECT id FROM alert WHERE elder_id=? AND day=? AND severity='red' ORDER BY id LIMIT 1",
                   (eid, s["alert_day"]))
        date = st.date_of_day(eid, s["review_day"])
        if r and date:
            set_review(st, r["id"], s["outcome"], s["note"], s["by"], "health_station", s["review_day"],
                       at=f"{date}T09:30:00+07:00")


class ReviewIn(BaseModel):
    outcome: str
    note: str | None = Field(default=None, max_length=MAX_NOTE * 2)


def register(app: FastAPI) -> None:
    @app.post("/api/elders/{elder_id}/alerts/{alert_id}/review")
    def review(request: Request, elder_id: str, alert_id: int, body: ReviewIn):
        s = request.app.state.svc
        actor = unquote(request.headers.get("x-actor", "family:primary"))[:80]
        role = unquote(request.headers.get("x-role", "primary"))[:40]
        if not s.elder_or_none(elder_id):
            raise HTTPException(404, f"unknown elder {elder_id}")
        if role not in REVIEW_ROLES:
            raise HTTPException(403, {"error": "clinician_only",
                                      "message_vi": "Chỉ nhân viên y tế / trạm y tế được xem xét cảnh báo.",
                                      "message_en": "Only clinical / health-station staff can review alerts."})
        if not s.store.consent_granted(elder_id, "clinician_sharing"):
            raise HTTPException(403, {"error": "not_shared",
                                      "message_vi": "Người cao tuổi chưa đồng ý chia sẻ với nhân viên y tế.",
                                      "message_en": "The older adult has not agreed to share with clinical staff."})
        if body.outcome not in OUTCOMES:
            raise HTTPException(422, {"error": "bad_outcome", "allowed": list(OUTCOMES)})
        note = (body.note or "").strip()
        if len(note) > MAX_NOTE:
            raise HTTPException(422, {"error": "note_too_long", "max": MAX_NOTE})
        a = s.store.one("SELECT id, severity FROM alert WHERE elder_id=? AND id=?", (elder_id, alert_id))
        if not a:
            raise HTTPException(404, "alert not found")
        if a["severity"] != "red":
            raise HTTPException(409, {"error": "not_red", "message_en": "Only red alerts need a clinical review."})
        recs = s.store.records(elder_id)
        set_review(s.store, alert_id, body.outcome, note, actor, role, recs[-1]["day"] if recs else None)
        s.store.log_access(elder_id, actor, role, "review_alert", str(request.url.path))
        return next(x for x in s.store.alerts(elder_id) if x["id"] == alert_id)
