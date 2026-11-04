"""Family connection as a measured wellbeing series ("Kết nối gia đình").

Social isolation and loneliness are health risks in their own right (TECHNICAL_DOCUMENTATION §8.4), so Chào Bà
counts the family's contact with the elder week by week and shows it next to the health signals:

* ``calls_visits``: family calls and visits (``family_contact``), the measure the DMAIC care plan already uses;
* ``micro``: love cards and photos (``kudos``, ``family_photo``), counted apart because a ten-second card is not a
  call;
* ``members``: how many different people in the care circle were in touch that week;
* ``days_in_touch``: on how many of the 7 days at least one person was in touch;
* ``elder_replies``: the elder's own replies and hearts on cards and photos (engagement, never scored).

The series **never feeds the daily light**: it describes the family, not the elder's health, and a quiet week must
not turn a parent's light yellow. Weeks are 7-day bins ending on the latest call day (or a later family touch). Everything follows the
elder's ``family_sharing`` pause like the other health views.

  GET /api/elders/{id}/connection?weeks=12
"""
from __future__ import annotations

from datetime import date as Date, timedelta
from urllib.parse import unquote

from fastapi import FastAPI, HTTPException, Request

WEEKS = 12
NOTE_VI = ("Số lần cả nhà liên lạc mỗi tuần. Không tính vào đèn sức khỏe: con số này nói về cả nhà, không nói về "
           "sức khỏe của người thân.")
NOTE_EN = ("How often the family was in touch each week. Not part of the health light: it describes the family, "
           "not your parent's health.")


def _who(name: str | None, member_id: str | None) -> str:
    return (member_id or (name or "").strip().lower()) or "?"


def connection(svc, elder_id: str, weeks: int = WEEKS) -> dict:
    st = svc.store
    simulated = svc.is_simulated(elder_id)
    if svc.sharing_paused(elder_id):
        return {"weeks": [], "summary": None, "sharing_paused": True, "simulated": simulated}
    recs = st.records(elder_id)
    if not recs:
        return {"weeks": [], "summary": None, "sharing_paused": False, "simulated": simulated}
    weeks = max(1, min(int(weeks), 26))

    # (date, who, kind) for every touch in the window; kind: contact | micro | reply
    touches: list[tuple[Date, str, str]] = []
    for c in st.contacts(elder_id):
        touches.append((Date.fromisoformat(c["date"]), _who(c["member_name"], c["member_id"]), "contact"))
    for r in st.q("SELECT date, sender_id, sender_name, replied_at, heart FROM kudos WHERE elder_id=?", (elder_id,)):
        d = Date.fromisoformat(r["date"])
        touches.append((d, _who(r["sender_name"], r["sender_id"]), "micro"))
        if r["replied_at"] or r["heart"]:
            touches.append((d, "elder", "reply"))
    for r in st.q("SELECT date, sender_id, sender_name, heart_at FROM family_photo WHERE elder_id=?", (elder_id,)):
        d = Date.fromisoformat(r["date"])
        touches.append((d, _who(r["sender_name"], r["sender_id"]), "micro"))
        if r["heart_at"]:
            touches.append((d, "elder", "reply"))

    # weeks end on the latest call day, or later if the family was in touch since (a card sent this morning)
    end = max([Date.fromisoformat(recs[-1]["date"])] + [x[0] for x in touches])
    start = end - timedelta(days=7 * weeks - 1)
    out = []
    for w in range(weeks):
        w0 = start + timedelta(days=7 * w)
        w1 = w0 + timedelta(days=6)
        t = [x for x in touches if w0 <= x[0] <= w1]
        family = [x for x in t if x[2] != "reply"]
        out.append({"from": w0.isoformat(), "to": w1.isoformat(),
                    "calls_visits": sum(1 for x in t if x[2] == "contact"),
                    "micro": sum(1 for x in t if x[2] == "micro"),
                    "members": len({x[1] for x in family}),
                    "days_in_touch": len({x[0] for x in family}),
                    "elder_replies": sum(1 for x in t if x[2] == "reply")})

    def two_weeks(ws: list[dict]) -> dict:
        return {k: sum(w[k] for w in ws) for k in ("calls_visits", "micro", "days_in_touch", "elder_replies")}
    summary = {"last_14_days": two_weeks(out[-2:]), "previous_14_days": two_weeks(out[-4:-2]) if weeks >= 4 else None,
               "circle_size": len(_circle(st, elder_id))}
    return {"weeks": out, "summary": summary, "in_light": False, "note_vi": NOTE_VI, "note_en": NOTE_EN,
            "sharing_paused": False, "simulated": simulated}


def _circle(store, elder_id: str) -> list[dict]:
    from .family import circle
    return [m for m in circle(store, elder_id) if m.get("role") != "elder_self"]


def register(app: FastAPI) -> None:
    @app.get("/api/elders/{elder_id}/connection")
    def get_connection(request: Request, elder_id: str, weeks: int = WEEKS):
        s = request.app.state.svc
        if not s.elder_or_none(elder_id):
            raise HTTPException(404, f"unknown elder {elder_id}")
        s.store.log_access(elder_id, unquote(request.headers.get("x-actor", "family:primary"))[:80],
                           unquote(request.headers.get("x-role", "primary"))[:40], "read_connection",
                           str(request.url.path))
        return connection(s, elder_id, weeks)
