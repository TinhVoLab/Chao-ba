"""Family coordination: one shared picture of how the elder is doing, assembled from fragments.

Each adult child usually hears a different fragment (mom tells one about back pain, another about poor sleep) and nobody
puts them together. This module adds, on top of the existing notes / contacts / call records:

* **Shared timeline** (``timeline``): call summaries, family notes, contacts, alerts, care events, task changes and the
  rota in one feed, filtered by the viewer's role.
* **Weekly synthesis** (``synthesis``): rule-based "pieces put together" across sources ("this week Mom mentioned back
  pain 3 times: to Lan, to Minh and to Út Thương"). With ``ANTHROPIC_API_KEY`` the text is reworded by Claude Haiku
  through ``chaoba.core.explain`` and accepted only if it passes the same post-check (no new numbers, no diagnostic
  words); otherwise the rule text is shown.
* **Call rota** (``rota``): weekday -> family member; "your turn today" for the viewer and a nudge when nobody has called
  or visited for ``CONTACT_NUDGE_DAYS`` days.
* **Before-you-call suggestions** (``suggestions``): topics from yesterday's call, memory facts, call follow-up hooks
  and the synthesis, minus what another family member already asked this week.
* **Care tasks** (``care_task``): take Mom to the clinic, buy medicine, visit; assignee, due date, done.
* **Roles** (``Viewer``): ``primary`` sees everything; ``viewer`` sees summaries (other people's notes and verbatim
  quotes are hidden); ``elder_self`` sees everything about themself plus who has been looking (``access``).
  ``clinician`` / ``health_station`` are not family roles (403 here; see community.py).

Everything seeded here is simulated (``simulated: true``). The prototype has no login: identity comes from the
``X-Actor`` / ``X-Role`` headers; a header can never raise a member above the role stored in their care circle.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date as Date, timedelta
from urllib.parse import unquote

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel

from chaoba.agent.analysis import extract_symptoms
from chaoba.agent.prompts import content_keywords
from chaoba.agent.textnorm import normalize
from chaoba.core import explain as explain_mod
from chaoba.core.synth import ACTS

from .db import QUOTE_RE, PURGED_VI, Store, now_iso
from .service import CONTACT_NUDGE_DAYS, Service, llm_enabled

FAMILY_ROLES = ("primary", "viewer", "elder_self")
NON_FAMILY_ROLES = ("clinician", "health_station")
TASK_KINDS = ("appointment", "medicine", "visit", "other")
WEEKDAYS_VI = ("Thứ Hai", "Thứ Ba", "Thứ Tư", "Thứ Năm", "Thứ Sáu", "Thứ Bảy", "Chủ nhật")
WEEKDAYS_EN = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
MON_EN = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
AI_NAME = "Út Thương"

# Care circles of the seeded personas (simulated). `role`: primary = full view, viewer = summaries only.
CIRCLES: dict[str, list[dict]] = {
    "hanh": [
        {"member_id": "lan", "name": "Lan", "relation": "daughter", "role": "primary", "city": "TP.HCM"},
        {"member_id": "minh", "name": "Minh", "relation": "son", "role": "viewer", "city": "Hà Nội"},
        {"member_id": "vy", "name": "Vy", "relation": "granddaughter", "role": "viewer", "city": "Bến Tre"},
    ],
    "tu": [
        {"member_id": "ba_tu", "name": "Bà Tư", "relation": "wife", "role": "primary", "city": "TP.HCM"},
        {"member_id": "khoa", "name": "Khoa", "relation": "son", "role": "viewer", "city": "TP.HCM"},
        {"member_id": "ngan", "name": "Ngân", "relation": "daughter", "role": "viewer", "city": "Đà Nẵng"},
    ],
    "control": [
        {"member_id": "thao", "name": "Thảo", "relation": "daughter", "role": "primary", "city": "Cần Thơ"},
        {"member_id": "tam", "name": "Tâm", "relation": "son", "role": "viewer", "city": "TP.HCM"},
    ],
}
RELATION_VI = {"daughter": "con gái", "son": "con trai", "granddaughter": "cháu gái", "grandson": "cháu trai",
               "wife": "vợ", "husband": "chồng", "niece": "cháu", "nephew": "cháu"}
# Rota seeds: weekday (Mon=0) -> member id.
ROTAS = {
    "hanh": {0: "lan", 1: "minh", 2: "lan", 3: "vy", 4: "lan", 5: "minh", 6: "vy"},
    "tu": {0: "khoa", 1: "ngan", 2: "khoa", 3: "ngan", 4: "khoa", 5: "ngan", 6: "khoa"},
    "control": {0: "thao", 1: "tam", 2: "thao", 3: "tam", 4: "thao", 5: "thao", 6: "tam"},
}

# Curated before-you-call topics for the seeded memory facts (profile facts carry no English).
FACT_TOPICS = {
    "cây mai trước nhà sắp ra nụ": ("Cây mai trước nhà sắp ra nụ. Hỏi {k} mai ra nụ chưa nhé.",
                                    "The apricot-blossom tree out front is about to bud. Ask {K} if it has.",
                                    ["mai", "nụ"]),
    "thích nghe cải lương": ("{K} thích nghe cải lương. Hỏi {k} dạo này nghe tuồng nào hay.",
                             "{K} loves cải lương opera. Ask which piece {he} has been enjoying.", ["cải", "lương"]),
    "từng dạy văn ở trường lê quý đôn 30 năm": ("{K} dạy Văn 30 năm. Hỏi {k} kể chuyện một người học trò cũ.",
                                                "{K} taught literature for 30 years. Ask about a former student.",
                                                ["học", "trò"]),
    "thích chơi cờ tướng": ("{K} mê cờ tướng. Hỏi {k} ván cờ gần nhất thắng hay thua.",
                            "{K} loves Chinese chess. Ask how the last game went.", ["cờ"]),
    "có 2 chậu lan quý": ("Hỏi {k} hai chậu lan quý có ra bông chưa.", "Ask whether {his} two orchids are flowering.",
                          ["lan"]),
    "nuôi cá trong ao sau nhà": ("Hỏi {k} đàn cá trong ao sau nhà lớn chưa.", "Ask how the fish in the pond are doing.",
                                 ["cá", "ao"]),
    "hay đi chợ nổi cái răng": ("Hỏi {k} dạo này có ra chợ nổi Cái Răng không.",
                                "Ask whether {he} has been to Cái Răng floating market lately.", ["chợ", "nổi"]),
}
TOPIC_VI = {"pain": "đau nhức", "insomnia": "khó ngủ", "dizziness": "chóng mặt", "skipped_meal": "bỏ bữa",
            "fall": "té ngã", "sadness": "buồn trong người", "missed_medication": "quên uống thuốc"}
TOPIC_EN = {"pain": "pain", "insomnia": "poor sleep", "dizziness": "dizziness", "skipped_meal": "skipped meals",
            "fall": "a fall", "sadness": "feeling low", "missed_medication": "missed medication"}
PAIN_PART = (("lưng", "đau lưng", "back pain"), ("gối", "đau gối", "knee pain"), ("đầu", "nhức đầu", "headache"),
             ("chân", "đau chân", "leg pain"), ("khớp", "đau khớp", "joint pain"), ("vai", "đau vai", "shoulder pain"))
FOLLOW_UP = {
    "pain": ("hỏi {k} chỗ đau đỡ chưa; nếu đau kéo dài, nên đưa {k} đi khám",
             "ask whether it feels better; if the pain lasts, consider a check-up"),
    "insomnia": ("hỏi {k} tối qua ngủ được không", "ask how {he} slept last night"),
    "dizziness": ("hỏi {k} còn chóng mặt không; nếu còn, nên đưa {k} đi khám",
                  "ask whether the dizziness is still there; if so, consider a check-up"),
    "skipped_meal": ("hỏi {k} dạo này ăn uống ra sao", "ask how {he} is eating"),
    "fall": ("hỏi {k} đi đứng có vững không, và xem lại chỗ dễ trượt trong nhà",
             "ask whether {he} feels steady, and check the house for slippery spots"),
    "sadness": ("dành thêm chút thời gian trò chuyện với {k}", "spend a little more time talking with {him}"),
    "missed_medication": ("nhắc {k} uống thuốc đúng giờ", "remind {him} about the medication times"),
}
# Simulated fragments for the demo week (day offsets from the last seeded day). Bà Hạnh's back pain reaches three
# different ears: Lan on the phone, Út Thương in a morning call, Minh by Zalo message.
SEED_NOTES = {
    "hanh": [(-5, "Lan", "Má kêu đau lưng mấy bữa nay, nói tại bưng chậu mai ra sân."),
             (-3, "Minh", "Nhắn Zalo hỏi thăm, má nói lưng còn nhức, tối ngủ không ngon."),
             (-1, "Vy", "Bà Năm hàng xóm nhắn con: bà vẫn tưới cây mai mỗi sáng, ăn cơm được.")],
    "tu": [(-4, "Ngân", "Gọi ba, ba kể chuyện học trò cũ tới thăm, vui lắm.")],
    "control": [(-2, "Tâm", "Ba nói chân hơi mỏi khi đi chợ về, chắc tại đi bộ nhiều.")],
}
SEED_AI_SYMPTOM = {"hanh": (-2, "pain", " Bà than đau lưng.", " She complained of back pain.")}
SEED_ASKED = {"hanh": [(-5, "lan", "fact:cây mai trước nhà sắp ra nụ")]}


def _ddmm(iso: str | None) -> str:
    return f"{iso[8:10]}/{iso[5:7]}" if iso and len(iso) >= 10 else ""


def _en_date(iso: str | None) -> str:
    if not iso or len(iso) < 10:
        return ""
    return f"{int(iso[8:10])} {MON_EN[int(iso[5:7]) - 1]}"


def kin(prof: dict) -> dict:
    """How the adult children address and refer to the elder (má / ba)."""
    female = (prof.get("honorific") or "bà") in ("bà", "cô", "dì", "mợ")
    return ({"k": "má", "K": "Má", "ken": "Mom", "he": "she", "him": "her", "his": "her"} if female else
            {"k": "ba", "K": "Ba", "ken": "Dad", "he": "he", "him": "him", "his": "his"})


def _fill_vi(s: str, kk: dict) -> str:
    return s.replace("{k}", kk["k"]).replace("{K}", kk["K"])


def _fill_en(s: str, kk: dict) -> str:
    return (s.replace("{K}", kk["ken"]).replace("{k}", kk["ken"]).replace("{he}", kk["he"])
            .replace("{him}", kk["him"]).replace("{his}", kk["his"]))


# ====================================================================== circle / identity
def circle(store: Store, elder_id: str) -> list[dict]:
    rows = store.q("SELECT * FROM care_circle WHERE elder_id=? ORDER BY sort, member_id", (elder_id,))
    if rows:
        return [{"id": r["member_id"], "name": r["name"], "relation": r["relation"],
                 "relation_vi": RELATION_VI.get(r["relation"] or "", r["relation"] or ""), "role": r["role"],
                 "city": r["city"]} for r in rows]
    prof = store.elder(elder_id) or {}   # elders without a seeded circle: derive one from the profile
    return [{"id": f.get("id"), "name": f.get("name"), "relation": f.get("relation"),
             "relation_vi": RELATION_VI.get(f.get("relation") or "", f.get("relation") or ""),
             "role": "primary" if f.get("role") == "primary" else "viewer", "city": None}
            for f in prof.get("family") or []]


def _norm_name(s: str) -> str:
    return normalize(s or "")


@dataclass
class Viewer:
    name: str
    role: str
    member_id: str | None

    @property
    def full(self) -> bool:
        return self.role in ("primary", "elder_self")

    def as_dict(self) -> dict:
        return {"member_id": self.member_id, "name": self.name, "role": self.role,
                "permissions": {"full_view": self.full, "edit_rota": self.role == "primary",
                                "manage_tasks": self.role in ("primary", "viewer"),
                                "see_access_log": True}}


def resolve_viewer(store: Store, elder_id: str, actor: str, role: str) -> Viewer:
    """Who is asking. A header can lower but never raise the role stored in the care circle."""
    role = role if role in FAMILY_ROLES + NON_FAMILY_ROLES else "viewer"
    if role == "elder_self":
        return Viewer(actor, "elder_self", None)
    key = _norm_name(actor)
    m = next((x for x in circle(store, elder_id) if _norm_name(x["name"]) == key or (x["id"] or "") == actor), None)
    if m:
        eff = "viewer" if "viewer" in (role, m["role"]) else m["role"]
        if role in NON_FAMILY_ROLES:
            eff = role
        return Viewer(m["name"], eff, m["id"])
    return Viewer(actor, role, None)


# ====================================================================== seed
def seed_all(svc: Service) -> None:
    for eid in svc.store.elder_ids():
        seed_elder(svc, eid)


def seed_elder(svc: Service, elder_id: str) -> None:
    """Simulated family-coordination data for a seeded persona (idempotent; re-run after a demo reset)."""
    st = svc.store
    if st.one("SELECT 1 FROM family_seed WHERE elder_id=?", (elder_id,)) or elder_id not in CIRCLES:
        return
    recs = st.records(elder_id)
    if not recs:
        return
    last = max(r["day"] for r in recs)
    seeded_last = max((r["day"] for r in recs if r.get("simulated", True)), default=last)
    today = Date.fromisoformat(svc.current_day(elder_id)[1])
    st.xmany("INSERT OR REPLACE INTO care_circle(elder_id, member_id, name, relation, role, city, sort) "
             "VALUES (?,?,?,?,?,?,?)",
             [(elder_id, m["member_id"], m["name"], m["relation"], m["role"], m["city"], i)
              for i, m in enumerate(CIRCLES[elder_id])])
    primary = CIRCLES[elder_id][0]
    st.xmany("INSERT OR REPLACE INTO care_rota(elder_id, weekday, member_id, updated_by, updated_day, updated_at) "
             "VALUES (?,?,?,?,?,?)", [(elder_id, wd, mid, primary["name"], seeded_last - 6, now_iso())
                                      for wd, mid in ROTAS[elder_id].items()])
    for off, author, text in SEED_NOTES.get(elder_id, []):
        st.add_note(elder_id, author, text, seeded_last + off, simulated=True)
    if elder_id in SEED_AI_SYMPTOM:
        off, sym, add_vi, add_en = SEED_AI_SYMPTOM[elder_id]
        r = st.record(elder_id, seeded_last + off)
        if r and r.get("answered") and not (r.get("symptoms") or {}).get(sym):
            r["symptoms"] = {**(r.get("symptoms") or {}), sym: 1}
            r["summary_vi"] = (r.get("summary_vi") or "") + add_vi
            r["summary_en"] = (r.get("summary_en") or "") + add_en
            st.upsert_record(r)
    for off, mid, key in SEED_ASKED.get(elder_id, []):
        d = seeded_last + off
        name = next((m["name"] for m in CIRCLES[elder_id] if m["member_id"] == mid), mid)
        st.x("INSERT INTO topic_asked(elder_id, topic_key, member_id, member_name, day, date, simulated, created_at) "
             "VALUES (?,?,?,?,?,?,1,?)", (elder_id, key, mid, name, d, st.date_of_day(elder_id, d), now_iso()))
    for t in _seed_tasks(elder_id, today, seeded_last):
        st.x("INSERT INTO care_task(elder_id, kind, title_vi, title_en, assignee_id, due_date, done, done_by, done_day, "
             "created_by, created_day, simulated, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,1,?)",
             (elder_id, t["kind"], t["vi"], t["en"], t["to"], t["due"], 1 if t.get("done") else 0, t.get("done_by"),
              t.get("done_day"), t["by"], t["day"], now_iso()))
    st.x("INSERT OR REPLACE INTO family_seed(elder_id, seeded_at) VALUES (?,?)", (elder_id, now_iso()))


def _seed_tasks(elder_id: str, today: Date, last: int) -> list[dict]:
    def plus(n: int) -> str:
        return (today + timedelta(days=n)).isoformat()
    sat = (5 - today.weekday()) % 7 or 7
    if elder_id == "hanh":
        return [
            {"kind": "appointment", "vi": "Đưa má đi tái khám huyết áp ở trạm y tế",
             "en": "Take Mom to her blood-pressure check-up at the health station", "to": "lan", "due": plus(7),
             "by": "Lan", "day": last - 5},
            {"kind": "medicine", "vi": "Mua thuốc huyết áp cho má (còn khoảng 5 ngày thuốc)",
             "en": "Buy Mom's blood-pressure medicine (about 5 days left)", "to": "vy", "due": plus(2),
             "by": "Lan", "day": last - 4},
            {"kind": "visit", "vi": "Về thăm má cuối tuần", "en": "Visit Mom at the weekend", "to": "minh",
             "due": plus(sat), "by": "Minh", "day": last - 3},
            {"kind": "other", "vi": "Gửi máy đo huyết áp mới về cho má", "en": "Send Mom a new blood-pressure monitor",
             "to": "minh", "due": plus(-3), "by": "Lan", "day": last - 8, "done": True, "done_by": "Minh",
             "done_day": last - 2},
        ]
    if elder_id == "tu":
        return [
            {"kind": "appointment", "vi": "Đưa ba đi khám định kỳ, mang theo báo cáo xu hướng",
             "en": "Take Dad to his routine check-up and bring the trend report", "to": "khoa", "due": plus(10),
             "by": "Bà Tư", "day": last - 6},
            {"kind": "visit", "vi": "Chở ba đi uống cà phê với bạn cờ", "en": "Drive Dad to coffee with his chess friends",
             "to": "khoa", "due": plus(sat), "by": "Khoa", "day": last - 2},
        ]
    return [{"kind": "medicine", "vi": "Mua thêm thuốc giảm đau khớp theo toa", "en": "Refill the prescribed joint-pain tablets",
             "to": "thao", "due": plus(4), "by": "Thảo", "day": last - 3}]


# ====================================================================== rota
def rota(svc: Service, elder_id: str, viewer: Viewer | None = None, history_days: int = 7) -> dict:
    st = svc.store
    members = {m["id"]: m for m in circle(st, elder_id)}
    rows = {r["weekday"]: r for r in st.q("SELECT * FROM care_rota WHERE elder_id=?", (elder_id,))}
    today_day, today_date = svc.current_day(elder_id)
    today = Date.fromisoformat(today_date)
    contacts = st.contacts(elder_id)
    by_date: dict[str, list[dict]] = {}
    for c in contacts:
        by_date.setdefault(c["date"], []).append(c)

    def slot(wd: int) -> dict:
        r = rows.get(wd)
        mid = r["member_id"] if r else None
        return {"weekday": wd, "weekday_vi": WEEKDAYS_VI[wd], "weekday_en": WEEKDAYS_EN[wd], "member_id": mid,
                "member_name": members.get(mid, {}).get("name") if mid else None}

    week = [slot(wd) for wd in range(7)]
    created = min((r["updated_day"] for r in rows.values() if r["updated_day"] is not None), default=None)
    history = []
    for i in range(history_days - 1, -1, -1):
        d = today - timedelta(days=i)
        day_idx = (today_day - i) if today_day is not None else None
        s = slot(d.weekday())
        cs = by_date.get(d.isoformat(), [])
        history.append({"date": d.isoformat(), "day": day_idx, **s,
                        "contacted": bool(cs), "by_assignee": any(c["member_id"] == s["member_id"] for c in cs),
                        "contacts": [{"member_name": c["member_name"], "kind": c["kind"]} for c in cs],
                        "before_rota": created is not None and day_idx is not None and day_idx < created})
    cur = slot(today.weekday())
    done_today = any(c["member_id"] == cur["member_id"] for c in by_date.get(today_date, [])) if cur["member_id"] else False
    anyone_today = bool(by_date.get(today_date))
    cs = svc.contact_status(elder_id)
    gap = {"days_since": cs["days_since"], "nudge": cs["nudge"], "threshold": CONTACT_NUDGE_DAYS,
           "last": cs["last"]}
    if anyone_today:
        gap = {**gap, "days_since": 0, "nudge": False}
    out = {"week": week, "today": {**cur, "date": today_date, "done": done_today, "anyone_called": anyone_today},
           "history": history, "gap": gap, "created_day": created}
    if viewer and viewer.member_id:
        mine = [s for s in week if s["member_id"] == viewer.member_id]
        nxt = None
        for i in range(0, 8):
            d = today + timedelta(days=i)
            if rows.get(d.weekday()) and rows[d.weekday()]["member_id"] == viewer.member_id:
                if i == 0 and done_today:
                    continue
                nxt = {"date": d.isoformat(), "weekday": d.weekday(), "in_days": i}
                break
        out["mine"] = {"weekdays": [s["weekday"] for s in mine], "your_turn": cur["member_id"] == viewer.member_id
                       and not done_today, "next": nxt}
    kk = kin(st.elder(elder_id) or {})
    msg_vi = msg_en = None
    if gap["nudge"] and gap["days_since"] is not None:
        who = cur["member_name"]
        msg_vi = f"Đã {gap['days_since']} ngày chưa ai gọi {kk['k']}." + (f" Hôm nay tới lượt {who}." if who else "")
        msg_en = f"No one has called {kk['ken']} for {gap['days_since']} days." + (f" Today is {who}'s turn." if who else "")
    out["nudge_vi"], out["nudge_en"] = msg_vi, msg_en
    return out


def set_rota(svc: Service, elder_id: str, assignments: dict, viewer: Viewer) -> dict:
    if viewer.role != "primary":
        raise HTTPException(403, {"error": "primary_only", "message_vi": "Chỉ người chăm sóc chính được sửa lịch gọi.",
                                  "message_en": "Only the primary carer can change the rota."})
    ids = {m["id"] for m in circle(svc.store, elder_id)}
    rows = []
    for k, mid in (assignments or {}).items():
        try:
            wd = int(k)
        except (TypeError, ValueError):
            raise HTTPException(422, f"weekday must be 0-6 (Mon=0), got {k!r}")
        if not 0 <= wd <= 6:
            raise HTTPException(422, f"weekday must be 0-6 (Mon=0), got {wd}")
        if mid is not None and mid not in ids:
            raise HTTPException(422, f"unknown family member {mid!r}")
        rows.append((wd, mid))
    day, _ = svc.current_day(elder_id)
    for wd, mid in rows:
        if mid is None:
            svc.store.x("DELETE FROM care_rota WHERE elder_id=? AND weekday=?", (elder_id, wd))
        else:
            svc.store.x("INSERT OR REPLACE INTO care_rota(elder_id, weekday, member_id, updated_by, updated_day, "
                        "updated_at) VALUES (?,?,?,?,?,?)", (elder_id, wd, mid, viewer.name, day, now_iso()))
    return {"ok": True, **rota(svc, elder_id, viewer)}


# ====================================================================== tasks
def _task_row(r, members: dict, today: str) -> dict:
    return {"id": r["id"], "kind": r["kind"], "title_vi": r["title_vi"], "title_en": r["title_en"] or r["title_vi"],
            "assignee_id": r["assignee_id"], "assignee_name": members.get(r["assignee_id"], {}).get("name"),
            "due_date": r["due_date"], "overdue": bool(r["due_date"] and not r["done"] and r["due_date"] < today),
            "done": bool(r["done"]), "done_by": r["done_by"], "done_day": r["done_day"], "created_by": r["created_by"],
            "created_day": r["created_day"], "simulated": bool(r["simulated"])}


def tasks(svc: Service, elder_id: str, include_done: bool = True) -> list[dict]:
    members = {m["id"]: m for m in circle(svc.store, elder_id)}
    _, today = svc.current_day(elder_id)
    rows = svc.store.q("SELECT * FROM care_task WHERE elder_id=? ORDER BY done, COALESCE(due_date, '9999'), id",
                       (elder_id,))
    return [_task_row(r, members, today) for r in rows if include_done or not r["done"]]


def _get_task(svc: Service, elder_id: str, tid: int):
    r = svc.store.one("SELECT * FROM care_task WHERE elder_id=? AND id=?", (elder_id, tid))
    if not r:
        raise HTTPException(404, "task not found")
    return r


def _check_due(due: str | None) -> str | None:
    if due in (None, ""):
        return None
    try:
        return Date.fromisoformat(due).isoformat()
    except ValueError:
        raise HTTPException(422, "due_date must be YYYY-MM-DD")


def add_task(svc: Service, elder_id: str, viewer: Viewer, kind: str, title: str, assignee_id: str | None,
             due_date: str | None) -> dict:
    if viewer.role not in ("primary", "viewer"):
        raise HTTPException(403, "only family members can add care tasks")
    if kind not in TASK_KINDS:
        raise HTTPException(422, f"kind must be one of {TASK_KINDS}")
    title = (title or "").strip()
    if not title or len(title) > 160:
        raise HTTPException(422, "title must be 1-160 characters")
    members = {m["id"]: m for m in circle(svc.store, elder_id)}
    if assignee_id and assignee_id not in members:
        raise HTTPException(422, f"unknown family member {assignee_id!r}")
    day, today = svc.current_day(elder_id)
    tid = svc.store.x("INSERT INTO care_task(elder_id, kind, title_vi, title_en, assignee_id, due_date, done, created_by,"
                      " created_day, simulated, created_at) VALUES (?,?,?,?,?,?,0,?,?,0,?)",
                      (elder_id, kind, title, None, assignee_id, _check_due(due_date), viewer.name, day, now_iso()))
    return {"ok": True, **_task_row(_get_task(svc, elder_id, tid), members, today)}


def update_task(svc: Service, elder_id: str, tid: int, viewer: Viewer, body: dict) -> dict:
    r = _get_task(svc, elder_id, tid)
    own = viewer.member_id is not None and viewer.member_id == r["assignee_id"]
    mine = _norm_name(viewer.name) == _norm_name(r["created_by"] or "")
    if not (viewer.role == "primary" or (viewer.role == "viewer" and (own or mine))):
        raise HTTPException(403, {"error": "not_allowed", "message_vi": "Bạn chỉ sửa được việc giao cho mình hoặc do mình tạo.",
                                  "message_en": "You can only change tasks assigned to you or created by you."})
    members = {m["id"]: m for m in circle(svc.store, elder_id)}
    day, today = svc.current_day(elder_id)
    sets, args = [], []
    if body.get("done") is not None:
        done = bool(body["done"])
        sets += ["done=?", "done_by=?", "done_day=?"]
        args += [1 if done else 0, viewer.name if done else None, day if done else None]
    if "assignee_id" in body and body["assignee_id"] is not None:
        if body["assignee_id"] not in members:
            raise HTTPException(422, f"unknown family member {body['assignee_id']!r}")
        sets.append("assignee_id=?")
        args.append(body["assignee_id"])
    if "due_date" in body and body["due_date"] is not None:
        sets.append("due_date=?")
        args.append(_check_due(body["due_date"]))
    if body.get("title"):
        t = str(body["title"]).strip()[:160]
        sets += ["title_vi=?", "title_en=?"]
        args += [t, None]
    if sets:
        svc.store.x(f"UPDATE care_task SET {', '.join(sets)} WHERE id=?", (*args, tid))
    return {"ok": True, **_task_row(_get_task(svc, elder_id, tid), members, today)}


def delete_task(svc: Service, elder_id: str, tid: int, viewer: Viewer) -> dict:
    r = _get_task(svc, elder_id, tid)
    if not (viewer.role == "primary" or _norm_name(viewer.name) == _norm_name(r["created_by"] or "")):
        raise HTTPException(403, "only the primary carer or the task's creator can delete it")
    svc.store.x("DELETE FROM care_task WHERE id=?", (tid,))
    return {"ok": True, "id": tid, "deleted": True}


# ====================================================================== synthesis
def _window(svc: Service, elder_id: str, days: int) -> tuple[int, int, str]:
    ref_day, ref_date = svc.current_day(elder_id)
    ref_day = ref_day if ref_day is not None else 0
    return ref_day - max(1, int(days)) + 1, ref_day, ref_date


def _part_label(topic: str, phrases: list[str]) -> tuple[str, str]:
    if topic == "pain":
        text = normalize(" ".join(phrases))
        for key, vi, en in PAIN_PART:
            if re.search(rf"\b{key}\b", text):
                return vi, en
    return TOPIC_VI.get(topic, topic), TOPIC_EN.get(topic, topic)


def synthesis(svc: Service, elder_id: str, days: int = 7, use_llm: bool | None = None) -> dict:
    """Weekly "pieces put together": the same complaint heard by several people (family notes + the AI's calls).

    Rule-based and deterministic. Optional Claude Haiku rewording (with a key) must pass explain.postcheck."""
    st = svc.store
    prof = st.elder(elder_id) or {}
    kk = kin(prof)
    lo, hi, ref_date = _window(svc, elder_id, days)
    paused = svc.sharing_paused(elder_id)
    mentions: list[dict] = []
    if not paused:   # call-derived data is withheld from the family while sharing is withdrawn
        for r in st.records(elder_id):
            if not (lo <= r["day"] <= hi) or not r.get("answered"):
                continue
            for k, v in (r.get("symptoms") or {}).items():
                if v and not k.startswith("concern:") and k in TOPIC_VI:
                    mentions.append({"topic": k, "source": "ai", "who": AI_NAME, "day": r["day"], "date": r["date"],
                                     "phrase": r.get("summary_vi") or ""})
    for n in st.notes(elder_id):
        if n["day"] is None or not (lo <= n["day"] <= hi) or n["to_elder"]:
            continue
        for k, quotes in extract_symptoms([n["text"]], prof.get("honorific")).items():
            if k in TOPIC_VI:
                mentions.append({"topic": k, "source": "note", "who": n["author"], "day": n["day"], "date": n["date"],
                                 "phrase": n["text"]})
    topics: dict[str, list[dict]] = {}
    for m in sorted(mentions, key=lambda x: (x["day"], x["source"])):
        topics.setdefault(m["topic"], []).append(m)
    items = []
    for k, ms in topics.items():
        label_vi, label_en = _part_label(k, [m["phrase"] for m in ms])
        people = sorted({m["who"] for m in ms if m["source"] == "note"})
        ai = sum(1 for m in ms if m["source"] == "ai")
        heard_vi = [f"với Út Thương trong cuộc gọi sáng ({_ddmm(m['date'])})" if m["source"] == "ai" else
                    f"với {m['who']} ({_ddmm(m['date'])})" for m in ms]
        heard_en = [f"to Út Thương in the morning call ({_en_date(m['date'])})" if m["source"] == "ai" else
                    f"to {m['who']} ({_en_date(m['date'])})" for m in ms]
        n = len(ms)
        times_vi = f"{n} lần" if n > 1 else "1 lần"
        times_en = f"{n} times" if n > 1 else "once"
        text_vi = f"{kk['K']} nhắc {label_vi} {times_vi}: " + _join_vi(heard_vi) + "."
        text_en = f"{kk['ken']} mentioned {label_en} {times_en}: " + _join_en(heard_en) + "."
        items.append({"topic": k, "label_vi": label_vi, "label_en": label_en, "count": n, "ai": ai,
                      "people": people, "sources": len(people) + (1 if ai else 0),
                      "first_day": ms[0]["day"], "last_day": ms[-1]["day"],
                      "mentions": [{"source": m["source"], "who": m["who"], "date": m["date"], "day": m["day"]}
                                   for m in ms],
                      "text_vi": text_vi, "text_en": text_en})
    items.sort(key=lambda x: (-x["sources"], -x["count"], x["topic"]))
    top = items[0] if items else None
    if top and top["sources"] >= 2:
        fu_vi, fu_en = FOLLOW_UP.get(top["topic"], ("hỏi thăm {k} chuyện này", "ask {him} about it"))
        who_vi, who_en = _who(top, kk)
        summary_vi = (f"Tuần này {kk['k']} nhắc {top['label_vi']} {top['count']} lần, {who_vi}. Mỗi người chỉ nghe một "
                      f"mảnh; ghép lại thì thấy chuyện này lặp lại. Có thể {_fill_vi(fu_vi, kk)}.")
        summary_en = (f"This week {kk['ken']} mentioned {top['label_en']} {top['count']} times, {who_en}. Each person "
                      f"heard one piece; put together, it keeps coming up. You could {_fill_en(fu_en, kk)}.")
    elif items:
        summary_vi = "Tuần này: " + " ".join(i["text_vi"] for i in items[:2])
        summary_en = "This week: " + " ".join(i["text_en"] for i in items[:2])
    else:
        summary_vi = f"Tuần này không ai trong nhà ghi nhận {kk['k']} than phiền điều gì lặp lại."
        summary_en = f"This week nobody in the family recorded {kk['ken']} repeating a complaint."
    contacts = [c for c in st.contacts(elder_id) if lo <= c["day"] <= hi]
    calls = [c for c in contacts if c["kind"] == "call"]
    visits = [c for c in contacts if c["kind"] == "visit"]
    contact_vi = (f"Gia đình gọi {len(calls)} lần, về thăm {len(visits)} lần"
                  + (f" ({', '.join(sorted({c['member_name'] for c in contacts}))})." if contacts else "."))
    contact_en = (f"Family calls: {len(calls)}, visits: {len(visits)}"
                  + (f" ({', '.join(sorted({c['member_name'] for c in contacts}))})." if contacts else "."))
    engine = "rules"
    use_llm = llm_enabled() if use_llm is None else use_llm
    if use_llm and items:
        res = explain_mod._llm_reword(summary_vi, summary_en)   # same post-check as the daily explanation
        if res:
            summary_vi, summary_en = res
            engine = "claude"
    if explain_mod.contains_blocked(summary_vi) or explain_mod.contains_blocked(summary_en):  # never expected
        summary_vi, summary_en = "Xem từng mục bên dưới.", "See the items below."
    return {"from_day": lo, "to_day": hi, "from_date": st.date_of_day(elder_id, lo) or ref_date, "to_date": ref_date,
            "days": hi - lo + 1, "items": items, "summary_vi": summary_vi, "summary_en": summary_en,
            "contact_vi": contact_vi, "contact_en": contact_en, "engine": engine, "sharing_paused": paused,
            "simulated": svc.is_simulated(elder_id)}


def _who(item: dict, kk: dict) -> tuple[str, str]:
    p = len(item["people"])
    parts_vi, parts_en = [], []
    if p:
        parts_vi.append(f"với {p} người trong nhà ({', '.join(item['people'])})")
        parts_en.append(f"to {p} family member{'s' if p > 1 else ''} ({', '.join(item['people'])})")
    if item["ai"]:
        parts_vi.append("với Út Thương")
        parts_en.append("to Út Thương")
    return " và ".join(parts_vi), " and ".join(parts_en)


def _cap(s: str) -> str:
    return s[:1].upper() + s[1:]


def _join_vi(xs: list[str]) -> str:
    return xs[0] if len(xs) == 1 else ", ".join(xs[:-1]) + " và " + xs[-1]


def _join_en(xs: list[str]) -> str:
    return xs[0] if len(xs) == 1 else ", ".join(xs[:-1]) + " and " + xs[-1]


# ====================================================================== suggestions
def _act_lookup(elder_id: str, summary_vi: str) -> list[tuple[str, str]]:
    acts = ACTS.get(elder_id) or [a for v in ACTS.values() for a in v]
    s = summary_vi or ""
    return [(vi, en) for vi, en in acts if vi in s]


GENERIC = {"kể", "chuyện", "nói", "ngồi", "làm", "đi", "xem", "với", "trên", "buổi", "sáng", "ra", "cho", "bà", "ông",
           "má", "ba", "con", "một", "giấc", "hôm", "qua", "nay"}


def _keywords(text: str) -> list[str]:
    return [k for k in content_keywords(text, limit=8) if k not in GENERIC][:4]


def _tokens(text: str) -> set[str]:
    return set(normalize(text).split())


def _covered(keywords: list[str], text: str) -> bool:
    toks = _tokens(text)
    hits = [k for k in keywords if k in toks]
    return len(hits) >= min(2, len(keywords)) if keywords else False


def suggestions(svc: Service, elder_id: str, viewer: Viewer | None = None, days: int = 7, limit: int = 4) -> dict:
    """Topics to bring up in your next call, freshest first; topics a sibling already asked this week are moved to
    ``already_asked`` (with who and when) so the elder is not asked the same thing three times."""
    st = svc.store
    prof = st.elder(elder_id) or {}
    kk = kin(prof)
    lo, hi, _ = _window(svc, elder_id, days)
    paused = svc.sharing_paused(elder_id)
    cands: list[dict] = []
    recs = [r for r in st.records(elder_id) if r.get("answered") and r["day"] < hi + 1]
    if not paused:
        # 1. follow-up hooks and new facts from recent live calls (Vietnamese only)
        for a in st.last_analyses(elder_id, 2):
            for h in (a.get("followup_hooks") or [])[:2]:
                if PURGED_VI not in h:
                    cands.append({"key": f"hook:{normalize(h)[:60]}", "source": "call",
                                  "text_vi": f"Út Thương ghi lại: “{h}”. Hỏi {kk['k']} thêm nhé.",
                                  "text_en": f"From the morning call (in Vietnamese): “{h}”. Ask {kk['him']} more.",
                                  "keywords": _keywords(h), "day": None})
        # 2. what the elder talked about in the latest call (activities in the call summary)
        for r in reversed(recs[-2:]):
            for vi, en in _act_lookup(elder_id, r.get("summary_vi", ""))[:2]:
                when_vi = ("Sáng nay" if r["day"] == hi else "Hôm qua" if r["day"] == hi - 1
                           else f"Ngày {_ddmm(r['date'])}")
                when_en = ("This morning" if r["day"] == hi else "Yesterday" if r["day"] == hi - 1
                           else f"On {_en_date(r['date'])}")
                cands.append({"key": f"act:{vi}", "source": "call", "day": r["day"],
                              "text_vi": f"{when_vi} {kk['k']} {vi}. Hỏi {kk['k']} thêm chuyện này nhé.",
                              "text_en": f"{when_en} {kk['ken']} {en}. Ask {kk['him']} about it.",
                              "keywords": _keywords(vi)})
    # 3. what the family pieced together this week (a care topic; listed first)
    syn = synthesis(svc, elder_id, days, use_llm=False)
    for it in syn["items"][:1]:
        if it["count"] >= 2:
            fu_vi, fu_en = FOLLOW_UP.get(it["topic"], ("hỏi thăm {k} chuyện này", "ask {him} about it"))
            cands.insert(0, {"key": f"care:{it['topic']}", "source": "synthesis", "day": it["last_day"],
                             "text_vi": f"Tuần này {kk['k']} nhắc {it['label_vi']} {it['count']} lần. "
                                        f"{_cap(_fill_vi(fu_vi, kk))}.",
                             "text_en": f"{kk['ken']} mentioned {it['label_en']} {it['count']} times this week. "
                                        f"{_cap(_fill_en(fu_en, kk))}.",
                             "keywords": []})
    # 4. memory facts: recent call facts, then curated profile facts
    for f in reversed(st.memory_facts(elder_id)):
        if PURGED_VI in f["fact_vi"]:
            continue
        nf = normalize(f["fact_vi"])
        if f["source"] == "call" and f["day"] is not None and f["day"] >= lo:
            cands.append({"key": f"fact:{nf}", "source": "memory", "day": f["day"],
                          "text_vi": f"{kk['K']} có kể: “{f['fact_vi']}”. Hỏi thêm {kk['k']} nhé.",
                          "text_en": f"{kk['ken']} mentioned (in Vietnamese): “{f['fact_vi']}”. Ask more.",
                          "keywords": f.get("keywords") or _keywords(f["fact_vi"])})
        elif f["source"] == "profile" and nf in FACT_TOPICS:
            vi, en, kw = FACT_TOPICS[nf]
            cands.append({"key": f"fact:{nf}", "source": "memory", "day": None, "text_vi": _fill_vi(vi, kk),
                          "text_en": _fill_en(en, kk), "keywords": kw})
    # who already asked / talked about it this week
    asked = st.q("SELECT * FROM topic_asked WHERE elder_id=? AND day>=? ORDER BY day DESC, id DESC", (elder_id, lo))
    notes = [n for n in st.notes(elder_id) if n["day"] is not None and n["day"] >= lo and not n["to_elder"]]
    seen, fresh, done = set(), [], []
    for c in cands:
        if c["key"] in seen:
            continue
        seen.add(c["key"])
        by = [{"name": a["member_name"], "date": a["date"], "member_id": a["member_id"], "how": "asked"}
              for a in asked if a["topic_key"] == c["key"]]
        if c["keywords"]:
            by += [{"name": n["author"], "date": n["date"], "member_id": None, "how": "note"} for n in notes
                   if _covered(c["keywords"], n["text"]) and all(b["name"] != n["author"] for b in by)]
        if viewer:   # your own asks still count; you just see them as yours
            for b in by:
                b["you"] = _norm_name(b["name"]) == _norm_name(viewer.name)
        out = {k: v for k, v in c.items() if k != "keywords"} | {"asked_by": by}
        (done if by else fresh).append(out)
    return {"suggestions": fresh[:limit], "already_asked": done[:limit], "window_from_day": lo,
            "sharing_paused": paused, "simulated": svc.is_simulated(elder_id)}


def mark_asked(svc: Service, elder_id: str, viewer: Viewer, topic_key: str) -> dict:
    topic_key = (topic_key or "").strip()[:200]
    if not topic_key:
        raise HTTPException(422, "topic_key required")
    day, date = svc.current_day(elder_id)
    svc.store.x("INSERT INTO topic_asked(elder_id, topic_key, member_id, member_name, day, date, simulated, created_at) "
                "VALUES (?,?,?,?,?,?,0,?)", (elder_id, topic_key, viewer.member_id, viewer.name, day, date, now_iso()))
    return {"ok": True, "topic_key": topic_key, "member_name": viewer.name, "day": day, "date": date}


# ====================================================================== timeline
EVENT_SKIP = ("web_call", "web_call_unanswered", "enrolment")


def timeline(svc: Service, elder_id: str, viewer: Viewer, days: int = 14) -> dict:
    """One feed for the whole family, newest first. Viewers see summaries: other people's notes are hidden and
    verbatim quotes are removed from alerts."""
    st = svc.store
    prof = st.elder(elder_id) or {}
    kk = kin(prof)
    lo, hi, _ = _window(svc, elder_id, days)
    paused = svc.sharing_paused(elder_id)
    members = {m["id"]: m for m in circle(st, elder_id)}
    items: list[dict] = []

    def add(kind: str, uid: str, day: int | None, actor: str | None, title_vi: str, title_en: str,
            text_vi: str = "", text_en: str = "", **extra):
        items.append({"id": f"{kind}:{uid}", "kind": kind, "day": day, "date": st.date_of_day(elder_id, day),
                      "actor": actor, "title_vi": title_vi, "title_en": title_en, "text_vi": text_vi,
                      "text_en": text_en, "redacted": False, **extra})

    if not paused:
        lights = {l["day"]: l["light"] for l in st.lights(elder_id)}
        for r in st.records(elder_id):
            if lo <= r["day"] <= hi:
                rehearsal = bool(r.get("simulated")) and r.get("channel") == "web"
                if r.get("answered"):
                    tv, te = "Cuộc gọi sáng với Út Thương", "Morning call with Út Thương"
                else:
                    tv, te = f"{kk['K']} không bắt máy", f"{kk['ken']} did not pick up"
                add("call", str(r["day"]), r["day"], AI_NAME, tv, te, r.get("summary_vi") or "",
                    r.get("summary_en") or "", light=lights.get(r["day"]), rehearsal=rehearsal,
                    simulated=bool(r.get("simulated", True)))
        for a in st.alerts(elder_id):
            if a["day"] is not None and lo <= a["day"] <= hi:
                vi, en = a["explanation_vi"] or "", a["explanation_en"] or ""
                red = not viewer.full and (QUOTE_RE.search(vi) or QUOTE_RE.search(en))
                if not viewer.full:
                    vi, en = QUOTE_RE.sub("“…”", vi), QUOTE_RE.sub("“…”", en)
                add("alert", str(a["id"]), a["day"], AI_NAME,
                    "Cảnh báo đỏ" if a["severity"] == "red" else "Cảnh báo vàng",
                    "Red alert" if a["severity"] == "red" else "Yellow alert", vi, en, severity=a["severity"],
                    alert_type=a["type"], acknowledged=a["acknowledged"])
                items[-1]["redacted"] = bool(red)
        for r in _self_reports(st, elder_id, st.date_of_day(elder_id, lo) or ""):
            add("self_report", r["uid"], r["day"], prof.get("display_name"), r["vi"], r["en"],
                "Tự bấm trên màn hình ở nhà; không tính điểm.", "Tapped on the home screen; not scored.",
                report_kind=r["kind"])
        for i, e in enumerate(st.events(elder_id)):
            if lo <= e["day"] <= hi and e["type"] not in EVENT_SKIP:
                add("event", f"{e['day']}-{i}", e["day"], None, e["label_vi"] or e["type"], e["label_en"] or e["type"],
                    event_type=e["type"])
    for n in st.notes(elder_id):
        if n["day"] is None or not (lo <= n["day"] <= hi):
            continue
        own = _norm_name(n["author"]) == _norm_name(viewer.name)
        if viewer.full or own:
            add("note", str(n["id"]), n["day"], n["author"],
                f"Ghi chú của {n['author']}" + (f" (nhắn cho {kk['k']})" if n["to_elder"] else ""),
                f"Note from {n['author']}" + (f" (message to {kk['ken']})" if n["to_elder"] else ""),
                n["text"], n["text"], to_elder=n["to_elder"], simulated=n["simulated"], text_lang="vi")
        else:
            add("note", str(n["id"]), n["day"], n["author"], f"Ghi chú của {n['author']}", f"Note from {n['author']}",
                "Chỉ người chăm sóc chính xem được nội dung; phần tóm tắt tuần đã gộp ghi chú này.",
                "Only the primary carer sees the text; the weekly summary already includes it.",
                to_elder=n["to_elder"], simulated=n["simulated"])
            items[-1]["redacted"] = True
    for c in st.contacts(elder_id):
        if lo <= c["day"] <= hi:
            mins = f" ({c['duration_min']} phút)" if c.get("duration_min") else ""
            mins_en = f" ({c['duration_min']} min)" if c.get("duration_min") else ""
            verb_vi = {"call": f"gọi cho {kk['k']}", "visit": f"về thăm {kk['k']}", "message": f"nhắn tin cho {kk['k']}"}
            verb_en = {"call": f"called {kk['ken']}", "visit": f"visited {kk['ken']}", "message": f"messaged {kk['ken']}"}
            add("contact", str(c["id"]), c["day"], c["member_name"],
                f"{c['member_name']} {verb_vi.get(c['kind'], c['kind'])}{mins}",
                f"{c['member_name']} {verb_en.get(c['kind'], c['kind'])}{mins_en}", contact_kind=c["kind"],
                simulated=c["simulated"])
    for t in tasks(svc, elder_id):
        who = t["assignee_name"] or "?"
        if t["created_day"] is not None and lo <= t["created_day"] <= hi:
            due_vi = f", hạn {_ddmm(t['due_date'])}" if t["due_date"] else ""
            due_en = f", due {_en_date(t['due_date'])}" if t["due_date"] else ""
            add("task", f"{t['id']}-new", t["created_day"], t["created_by"], f"Việc mới: {t['title_vi']}",
                f"New task: {t['title_en']}", f"Giao cho {who}{due_vi}.", f"Assigned to {who}{due_en}.",
                task_id=t["id"], task_kind=t["kind"], simulated=t["simulated"])
        if t["done"] and t["done_day"] is not None and lo <= t["done_day"] <= hi:
            add("task", f"{t['id']}-done", t["done_day"], t["done_by"], f"Đã xong: {t['title_vi']}",
                f"Done: {t['title_en']}", "", "", task_id=t["id"], task_kind=t["kind"], simulated=t["simulated"])
    rr = st.one("SELECT updated_by, updated_day FROM care_rota WHERE elder_id=? ORDER BY updated_day DESC LIMIT 1",
                (elder_id,))
    if rr and rr["updated_day"] is not None and lo <= rr["updated_day"] <= hi:
        add("rota", str(rr["updated_day"]), rr["updated_day"], rr["updated_by"], "Cập nhật lịch gọi luân phiên",
            "Call rota updated", "Mỗi ngày một người gọi hỏi thăm.", "One person calls each day.")
    ro = rota(svc, elder_id, viewer)
    if ro["gap"]["nudge"]:
        add("gap", str(hi), hi, None, ro["nudge_vi"] or "", ro["nudge_en"] or "", severity="yellow")
    order = {"gap": 0, "alert": 1, "call": 2, "self_report": 3, "note": 3, "contact": 4, "task": 5, "event": 6, "rota": 7}
    items.sort(key=lambda x: (-(x["day"] or 0), order.get(x["kind"], 9), x["id"]))
    upcoming = [t for t in tasks(svc, elder_id, include_done=False) if t["kind"] == "appointment"]
    return {"items": items, "upcoming": upcoming, "from_day": lo, "to_day": hi, "viewer": viewer.as_dict(),
            "members": list(members.values()), "sharing_paused": paused, "simulated": svc.is_simulated(elder_id)}


def _self_reports(st: Store, elder_id: str, since: str) -> list[dict]:
    """The elder's own taps on the standing screen (elder_ui.py): medication taken / not yet, mood check-in.
    Read-only here, never scored. Empty if that module's tables do not exist."""
    try:
        from . import elder_ui
        elder_ui.ensure_tables(st)
        meds = elder_ui._rows(st, "elder_med_log", elder_id, since)
        moods = elder_ui._rows(st, "elder_mood_checkin", elder_id, since)
    except Exception:   # pragma: no cover - module absent or schema changed
        return []
    kk = kin(st.elder(elder_id) or {})
    out = []
    for r in meds:
        t = _vn_time(r["created_at"])
        med = f" ({r['medication']})" if r.get("medication") else ""
        if r["status"] == "taken":
            vi, en = f"{kk['K']} bấm “Đã uống thuốc”{med} lúc {t}", f"{kk['ken']} tapped “Took my medicine”{med} at {t}"
        else:
            vi, en = f"{kk['K']} bấm “Chưa uống”{med} lúc {t}", f"{kk['ken']} tapped “Not yet”{med} at {t}"
        out.append({"uid": f"med{r['id']}", "day": r["day"], "kind": "medication", "vi": vi, "en": en})
    for r in moods:
        mv = {"happy": "vui", "neutral": "bình thường", "sad": "buồn"}.get(r["mood"], r["mood"])
        me = {"happy": "happy", "neutral": "okay", "sad": "sad"}.get(r["mood"], r["mood"])
        t = _vn_time(r["created_at"])
        out.append({"uid": f"mood{r['id']}", "day": r["day"], "kind": "mood",
                    "vi": f"{kk['K']} tự chọn tâm trạng: {mv} (lúc {t})", "en": f"{kk['ken']} chose mood: {me} (at {t})"})
    return out


def _vn_time(iso: str | None) -> str:
    try:
        from datetime import datetime
        d = datetime.fromisoformat(iso) + timedelta(hours=7)
        return d.strftime("%H:%M")
    except Exception:
        return ""


# ====================================================================== access ("who is looking")
def access(svc: Service, elder_id: str, days: int = 7) -> dict:
    """Per-person summary of the access log: who looked at the elder's information and when (elder-facing)."""
    rows = svc.store.q("SELECT actor, role, action, ts, n, last_ts FROM access_log WHERE elder_id=? ORDER BY id DESC "
                       "LIMIT 2000", (elder_id,))
    _, today = svc.current_day(elder_id)
    since = (Date.fromisoformat(today) - timedelta(days=max(1, days) - 1)).isoformat()
    people: dict[str, dict] = {}
    for r in rows:
        if (r["ts"] or "")[:10] < since and (r["last_ts"] or "")[:10] < since:
            continue
        p = people.setdefault(r["actor"], {"actor": r["actor"], "role": r["role"], "views": 0, "writes": 0,
                                           "last_ts": r["last_ts"] or r["ts"]})
        if r["action"].startswith("read_"):
            p["views"] += int(r["n"] or 1)
        else:
            p["writes"] += 1
        p["last_ts"] = max(p["last_ts"] or "", r["last_ts"] or r["ts"] or "")
    return {"days": days, "people": sorted(people.values(), key=lambda p: p["last_ts"] or "", reverse=True),
            "simulated": svc.is_simulated(elder_id)}


# ====================================================================== routes
class TaskIn(BaseModel):
    kind: str = "other"
    title: str
    assignee_id: str | None = None
    due_date: str | None = None


class TaskPatch(BaseModel):
    done: bool | None = None
    assignee_id: str | None = None
    due_date: str | None = None
    title: str | None = None


class RotaIn(BaseModel):
    assignments: dict[str, str | None]


class AskedIn(BaseModel):
    topic_key: str


def register(app: FastAPI) -> None:
    """Family-coordination routes under /api/elders/{id}/family (see CONTRACT.md)."""

    def ctx(request: Request, elder_id: str, action: str) -> tuple[Service, Viewer]:
        s: Service = request.app.state.svc
        if not s.elder_or_none(elder_id):
            raise HTTPException(404, f"unknown elder {elder_id}")
        actor = unquote(request.headers.get("x-actor", "family:primary"))[:80]
        role = unquote(request.headers.get("x-role", "primary"))[:40]
        v = resolve_viewer(s.store, elder_id, actor, role)
        if v.role in NON_FAMILY_ROLES:
            raise HTTPException(403, {"error": "family_only",
                                      "message_vi": "Trang gia đình chỉ dành cho người nhà và chính người cao tuổi.",
                                      "message_en": "The family space is for family members and the elder only."})
        seed_elder(s, elder_id)   # no-op once seeded; covers elders added after startup
        s.store.log_access(elder_id, v.name, v.role, action, str(request.url.path))
        return s, v

    base = "/api/elders/{elder_id}/family"

    @app.get(base)
    def family_overview(request: Request, elder_id: str):
        s, v = ctx(request, elder_id, "read_family")
        return {"viewer": v.as_dict(), "members": circle(s.store, elder_id), "rota": rota(s, elder_id, v),
                "tasks": tasks(s, elder_id), "suggestions": suggestions(s, elder_id, v),
                "synthesis": synthesis(s, elder_id), "access": access(s, elder_id),
                "sharing_paused": s.sharing_paused(elder_id), "simulated": s.is_simulated(elder_id)}

    @app.get(base + "/timeline")
    def family_timeline(request: Request, elder_id: str, days: int = 14):
        s, v = ctx(request, elder_id, "read_family_timeline")
        return timeline(s, elder_id, v, max(1, min(int(days), 120)))

    @app.get(base + "/synthesis")
    def family_synthesis(request: Request, elder_id: str, days: int = 7):
        s, _ = ctx(request, elder_id, "read_family_synthesis")
        return synthesis(s, elder_id, max(1, min(int(days), 60)))

    @app.get(base + "/rota")
    def family_rota(request: Request, elder_id: str):
        s, v = ctx(request, elder_id, "read_rota")
        return rota(s, elder_id, v)

    @app.post(base + "/rota")
    def family_set_rota(request: Request, elder_id: str, body: RotaIn):
        s, v = ctx(request, elder_id, "write_rota")
        return set_rota(s, elder_id, body.assignments, v)

    @app.get(base + "/tasks")
    def family_tasks(request: Request, elder_id: str, include_done: bool = True):
        s, _ = ctx(request, elder_id, "read_tasks")
        return {"tasks": tasks(s, elder_id, include_done), "kinds": list(TASK_KINDS),
                "simulated": s.is_simulated(elder_id)}

    @app.post(base + "/tasks")
    def family_add_task(request: Request, elder_id: str, body: TaskIn):
        s, v = ctx(request, elder_id, "write_task")
        return add_task(s, elder_id, v, body.kind, body.title, body.assignee_id, body.due_date)

    @app.post(base + "/tasks/{task_id}")
    def family_update_task(request: Request, elder_id: str, task_id: int, body: TaskPatch):
        s, v = ctx(request, elder_id, "update_task")
        return update_task(s, elder_id, task_id, v, body.model_dump(exclude_unset=True))

    @app.delete(base + "/tasks/{task_id}")
    def family_delete_task(request: Request, elder_id: str, task_id: int):
        s, v = ctx(request, elder_id, "delete_task")
        return delete_task(s, elder_id, task_id, v)

    @app.get(base + "/suggestions")
    def family_suggestions(request: Request, elder_id: str):
        s, v = ctx(request, elder_id, "read_suggestions")
        return suggestions(s, elder_id, v)

    @app.post(base + "/suggestions/asked")
    def family_mark_asked(request: Request, elder_id: str, body: AskedIn):
        s, v = ctx(request, elder_id, "mark_topic_asked")
        return mark_asked(s, elder_id, v, body.topic_key)

    @app.get(base + "/access")
    def family_access(request: Request, elder_id: str, days: int = 7):
        s, _ = ctx(request, elder_id, "read_access_summary")
        return access(s, elder_id, max(1, min(int(days), 90)))

