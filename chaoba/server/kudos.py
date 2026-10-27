"""Family micro-interactions ("Gửi yêu thương / Send some love"): small cards from the adult children to the elder.

An adult child taps one card in the family app; the elder answers with one tap on the standing screen, or by voice
when the morning call relays it (phone-only package). Card kinds:

* ``checkin``  structured question, big answer buttons: "Má ăn cơm chưa?" (Ăn rồi / Chưa ăn), sleep, feeling, medicine.
               The answers are the elder's **self-reports**: shown to the family, never scored into the light.
* ``love``     one-way affection ("Thương má", "Con nhớ má", "Chúc má ngủ ngon", "Cảm ơn má"); the elder can send a
               heart back.
* ``advice``   "Hỏi ý má": the child asks for the elder's know-how (canh chua, a child's cough, mai blossoms, or free
               text). The elder answers by voice / typing or "Để má gọi lại nói"; with the elder's consent the answer is
               saved to the Sổ ký ức (memory book, memories.py) as a "Lời má dạy" story.
* ``care_tip`` gentle caring advice ("Trời nóng, má nhớ uống nước nha"); presets or free text, never medical advice.
* ``message``  a short free-text line (voice notes are a future feature).

Rules
- Free text (custom advice question, care tip, message) passes the same no-diagnosis blocklist as the explanations
  (``chaoba.core.explain.contains_blocked``) plus the call guardrails; anything about medication changes or doses is
  refused with a friendly message (422 ``medical_advice``).
- At most ``DAILY_LIMIT`` cards per sender per day (429 ``daily_limit``): small taps must never replace a call.
- Micro-contacts are counted separately from calls / visits: the "N days since anyone called" nudge ignores them, and
  the DMAIC contact metric gets a separate ``micro_*`` series.
- Roles (care circle, family.py): the elder (``X-Role: elder_self``) reads the inbox and replies; family members send
  and read what they sent (``box=sent``) or the family's cards (``box=family``: a viewer sees other people's free
  text redacted). ``clinician`` / ``health_station``: 403.
- Consent: while ``family_sharing`` is withdrawn, family roles get no check-in answers (``reply_hidden: true``).

Wiring (kept out of service.py, like memories.py): ``install(svc)`` wraps ``build_context`` (relay pending cards in the
call), ``end_call`` (store the relayed answers), ``contact_status`` (adds ``micro_7d``) and ``dmaic`` (micro series).
``seed_all(svc)`` adds simulated history; ``register(app)`` adds the routes below. Table ``kudos`` (db.py).

  GET  /api/elders/{id}/kudos/catalog
  POST /api/elders/{id}/kudos                     {kind, template_id? | text?, from?}
  GET  /api/elders/{id}/kudos?box=inbox|sent|family&days=28&pending=0|1
  POST /api/elders/{id}/kudos/{kid}/seen          {via?: screen|call, snooze_minutes?}
  POST /api/elders/{id}/kudos/{kid}/reply         {choice? | text? | heart?, via: screen|call}
  POST /api/elders/{id}/kudos/{kid}/save          {confirmed_by_elder_or_proxy?, decline?}
"""
from __future__ import annotations

import functools
import json
import logging
import re
from datetime import date as Date, datetime, timedelta, timezone
from urllib.parse import unquote

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

from chaoba.agent import guardrails as g
from chaoba.agent.persona import RELATION_HONORIFIC
from chaoba.agent.relay import RelayItem
from chaoba.agent.textnorm import normalize
from chaoba.core import explain as explain_mod

from .db import Store, now_iso

log = logging.getLogger("chaoba.kudos")

KINDS = ("checkin", "love", "advice", "care_tip", "message")
DAILY_LIMIT = 6
RELAY_DAYS = 3            # cards older than this are not relayed in the call any more
MAX_TEXT = 160
ELDER_ROLES = ("elder_self", "elder")


# ================================================================================================ catalog
def _c(cid: str, vi: str, en: str) -> dict:
    return {"id": cid, "vi": vi, "en": en}


# {k}/{K}: how the sender addresses the elder (má / ba / bà / ông), {me}/{Me}: the sender's self-reference (con / cháu /
# tui). English: {K} = Mom / Dad / Grandma / Grandpa / dear. ``relay`` is what Út Thương says in the call ({s} = sender
# as Út Thương names them, {h} = the elder's honorific). ``icon`` is a lucide icon name the app maps to an illustration.
TEMPLATES: list[dict] = [
    {"id": "ate", "kind": "checkin", "icon": "soup", "topic": "food", "health": True,
     "label_vi": "{K} ăn cơm chưa?", "label_en": "Have you eaten?",
     "vi": "{K} ăn cơm chưa?", "en": "Have you eaten, {K}?",
     "relay": "{s} hỏi {h} ăn cơm chưa {h}?",
     "choices": [_c("ate", "Ăn rồi", "I've eaten"), _c("not_yet", "Chưa ăn", "Not yet")]},
    {"id": "slept", "kind": "checkin", "icon": "moon", "topic": "sleep", "health": True,
     "label_vi": "Tối qua {k} ngủ ngon không?", "label_en": "Did you sleep well?",
     "vi": "Tối qua {k} ngủ ngon không?", "en": "Did you sleep well last night, {K}?",
     "relay": "{s} hỏi tối qua {h} ngủ ngon hông {h}?",
     "choices": [_c("good", "Ngon", "Well"), _c("meh", "Hơi khó ngủ", "A bit restless"),
                 _c("awake", "Thức nhiều", "Awake a lot")]},
    {"id": "feeling", "kind": "checkin", "icon": "sun", "topic": "feel", "health": True,
     "label_vi": "Hôm nay {k} thấy trong người sao?", "label_en": "How do you feel today?",
     "vi": "Hôm nay {k} thấy trong người sao?", "en": "How are you feeling today, {K}?",
     "relay": "{s} hỏi hôm nay {h} thấy trong người sao {h}?",
     "choices": [_c("well", "Khỏe", "Well"), _c("ok", "Bình thường", "Okay"), _c("tired", "Hơi mệt", "A bit tired")]},
    {"id": "meds", "kind": "checkin", "icon": "pill", "topic": None, "health": True,
     "label_vi": "{K} uống thuốc chưa?", "label_en": "Taken your medicine?",
     "vi": "{K} uống thuốc chưa?", "en": "Have you taken your medicine, {K}?",
     "relay": "{s} hỏi {h} uống thuốc chưa {h}?",
     "choices": [_c("yes", "Rồi", "Yes"), _c("no", "Chưa", "Not yet")]},
    {"id": "love", "kind": "love", "icon": "heart",
     "label_vi": "Thương {k}", "label_en": "Love you",
     "vi": "{Me} thương {k} nhiều lắm", "en": "Love you lots, {K}"},
    {"id": "miss", "kind": "love", "icon": "heart-handshake",
     "label_vi": "{Me} nhớ {k}", "label_en": "Miss you",
     "vi": "{Me} nhớ {k} quá", "en": "I miss you, {K}"},
    {"id": "goodnight", "kind": "love", "icon": "moon-star",
     "label_vi": "Chúc {k} ngủ ngon", "label_en": "Good night",
     "vi": "Chúc {k} ngủ ngon nha", "en": "Good night, {K}"},
    {"id": "thanks", "kind": "love", "icon": "flower",
     "label_vi": "Cảm ơn {k}", "label_en": "Thank you",
     "vi": "{Me} cảm ơn {k} nhiều lắm", "en": "Thank you so much, {K}"},
    {"id": "canh_chua", "kind": "advice", "icon": "chef-hat",
     "label_vi": "Nấu canh chua sao cho ngon?", "label_en": "How to cook canh chua?",
     "vi": "Nấu canh chua sao cho ngon hả {k}?", "en": "How do you make a good canh chua (sour soup), {K}?",
     "relay": "{s} hỏi {h} nấu canh chua sao cho ngon, {h} chỉ giùm với?",
     "story_vi": "nấu canh chua", "story_en": "making canh chua"},
    {"id": "cough", "kind": "advice", "icon": "baby",
     "label_vi": "Bé Na ho, {k} có mẹo gì không?", "label_en": "Little Na has a cough: any tips?",
     "vi": "Bé Na ho, {k} có mẹo gì không?", "en": "Little Na has a cough. Any tips, {K}?",
     "relay": "{s} hỏi bé Na bị ho, {h} có mẹo gì hông?",
     "story_vi": "mẹo khi cháu ho", "story_en": "when a grandchild has a cough", "folk_note": True},
    {"id": "mai", "kind": "advice", "icon": "flower-2",
     "label_vi": "Trồng mai sao cho ra nụ đúng Tết?", "label_en": "Mai blossoms right on Tết?",
     "vi": "Trồng mai sao cho ra nụ đúng Tết hả {k}?", "en": "How do you get the mai tree to bloom right on Tết, {K}?",
     "relay": "{s} hỏi {h} trồng mai sao cho ra nụ đúng Tết, {h} chỉ giùm với?",
     "story_vi": "chăm mai ra nụ đúng Tết", "story_en": "getting the mai to bloom on Tết"},
    {"id": "water", "kind": "care_tip", "icon": "droplets",
     "label_vi": "Trời nóng, nhớ uống nước", "label_en": "Hot day: drink water",
     "vi": "Trời nóng, {k} nhớ uống nước nha", "en": "It's hot, {K}: remember to drink water",
     "relay": "{s} dặn trời nóng {h} nhớ uống nước nha."},
    {"id": "sun", "kind": "care_tip", "icon": "sunrise",
     "label_vi": "Ra nắng sáng 15 phút", "label_en": "15 minutes of morning sun",
     "vi": "Ra nắng sáng 15 phút cho khỏe xương nha {k}", "en": "15 minutes of morning sun is good for your bones, {K}",
     "relay": "{s} dặn {h} ra nắng sáng chừng mười lăm phút cho khỏe xương nha."},
    {"id": "walk", "kind": "care_tip", "icon": "footprints",
     "label_vi": "Chiều mát đi bộ chút", "label_en": "A short walk when it's cool",
     "vi": "Chiều mát {k} đi bộ quanh nhà chút nha", "en": "Take a little walk around the house when it's cool, {K}",
     "relay": "{s} dặn chiều mát {h} đi bộ quanh nhà chút nha."},
    {"id": "rest", "kind": "care_tip", "icon": "armchair",
     "label_vi": "Trưa nhớ nghỉ ngơi", "label_en": "Rest at midday",
     "vi": "Trưa {k} nhớ nghỉ ngơi chút cho khỏe nha", "en": "Remember to rest a little at midday, {K}",
     "relay": "{s} dặn trưa {h} nhớ nghỉ ngơi chút nha."},
]
BY_ID = {t["id"]: t for t in TEMPLATES}
CARE_TIP_CHOICES = [_c("ok", "Nhớ rồi", "Got it")]
GROUPS = [
    {"kind": "checkin", "label_vi": "Hỏi thăm", "label_en": "Check in"},
    {"kind": "love", "label_vi": "Gửi thương", "label_en": "Love"},
    {"kind": "advice", "label_vi": "Hỏi ý {k}", "label_en": "Ask {K}'s advice"},
    {"kind": "care_tip", "label_vi": "Lời dặn", "label_en": "Caring tip"},
    {"kind": "message", "label_vi": "Tự viết", "label_en": "Write your own"},
]
FREE_RELAY = {"advice": "{s} muốn hỏi ý {h} nè: {t} {H} chỉ giùm với?",
              "care_tip": "{s} dặn {h}: {t}",
              "message": "{s} nhắn {h}: {t}"}
VOICE_NOTE = {"available": False,
              "note_vi": "Gửi lời nhắn bằng giọng nói là tính năng tương lai; bản thử chỉ gửi chữ.",
              "note_en": "Voice notes are a future feature; the prototype sends text only."}
SELF_REPORT_NOTE = {"note_vi": "Câu trả lời là người cao tuổi tự chọn: chỉ để gia đình biết, không tính vào đèn.",
                    "note_en": "Answers are the elder's own self-report: for the family to know, never scored into "
                               "the light."}


def address(prof: dict, relation: str | None) -> dict:
    """How a family member of this relation addresses the elder and themself."""
    female = (prof.get("honorific") or "bà").lower() in ("bà", "cô", "dì", "mợ")
    rel = (relation or "").lower()
    if rel in ("granddaughter", "grandson", "grandchild"):
        return {"k": "bà" if female else "ông", "me": "cháu", "K_en": "Grandma" if female else "Grandpa",
                "callee": "con"}
    if rel in ("wife", "husband"):
        return {"k": "bà" if female else "ông", "me": "tui", "K_en": "dear", "callee": ""}
    if rel in ("daughter", "son", "child", "daughter_in_law", "son_in_law"):
        return {"k": "má" if female else "ba", "me": "con", "K_en": "Mom" if female else "Dad", "callee": "con"}
    return {"k": (prof.get("honorific") or "bà").lower(), "me": "con", "K_en": "Mom" if female else "Dad",
            "callee": "con"}


def kin_word(prof: dict) -> dict:
    female = (prof.get("honorific") or "bà").lower() in ("bà", "cô", "dì", "mợ")
    return {"k": "má" if female else "ba", "K": "Má" if female else "Ba", "en": "Mom" if female else "Dad"}


def _fill(s: str, a: dict) -> str:
    me = a["me"]
    return (s.replace("{K}", a["k"].capitalize()).replace("{k}", a["k"]).replace("{Me}", me.capitalize())
            .replace("{me}", me))


def _fill_en(s: str, a: dict) -> str:
    return s.replace("{K}", a["K_en"]).replace("{k}", a["K_en"])


def render_template(t: dict, a: dict) -> dict:
    choices = t.get("choices") or (CARE_TIP_CHOICES if t["kind"] == "care_tip" else [])
    return {"id": t["id"], "kind": t["kind"], "icon": t.get("icon"), "health": bool(t.get("health")),
            "label_vi": _fill(t["label_vi"], a), "label_en": _fill_en(t["label_en"], a),
            "text_vi": _fill(t["vi"], a), "text_en": _fill_en(t["en"], a), "choices": choices,
            "folk_note": bool(t.get("folk_note"))}


def sender_ref(member: dict | None, name: str) -> str:
    """How Út Thương names the sender in the call: "chị Lan", "anh Minh", "cháu Vy", "bà Tư"."""
    parts = (name or "").split()
    if len(parts) > 1 and parts[0].lower() in ("bà", "ông", "cô", "chú", "anh", "chị", "dì", "cậu"):
        return parts[0].lower() + " " + " ".join(parts[1:])
    rel = ((member or {}).get("relation") or "").lower()
    if rel in ("granddaughter", "grandson", "grandchild"):
        return f"cháu {name}"
    h = RELATION_HONORIFIC.get(rel, "")
    return f"{h} {name}".strip()


# ================================================================================================ free-text check
_DOSE_RE = re.compile(r"\d+([.,]\d+)?\s*(mg|mcg|µg|ml|viên|v\b|giọt|ống|gói|cữ|lần\s*(/|một|mỗi)\s*ngày|cc\b)")
_DOSE_WORDS = ["liều", "tăng thuốc", "giảm thuốc", "uống thêm", "đổi thuốc", "bỏ thuốc", "ngưng thuốc", "ngừng thuốc",
               "thôi uống", "uống gấp", "nửa viên", "hai viên", "ba viên", "thêm viên", "thuốc ngủ", "kháng sinh",
               "dose", "double the", "stop taking", "mg "]


def check_free_text(text: str) -> dict | None:
    """None if the free text may be sent; else the refusal detail (friendly, bilingual)."""
    t = (text or "").strip()
    n = normalize(t)
    if explain_mod.contains_blocked(t) or g.detect_diagnosis_request(t):
        return {"error": "diagnosis_words", "field": "text",
                "message_vi": "Chào Bà không chuyển lời nhắn có chẩn đoán hay tên bệnh. Bạn viết lại bằng lời hỏi thăm "
                              "nhẹ nhàng nha; chuyện sức khỏe xin hỏi bác sĩ.",
                "message_en": "Chào Bà does not pass on messages with diagnoses or disease labels. Please rephrase as a "
                              "gentle check-in; health questions belong with the doctor."}
    if (g.detect_medication_change(t) or _DOSE_RE.search(n) or any(w in n for w in _DOSE_WORDS)):
        return {"error": "medical_advice", "field": "text",
                "message_vi": "Lời nhắn này có nhắc tới thuốc hay liều thuốc. Để an toàn, Chào Bà không chuyển lời khuyên "
                              "về thuốc; việc đổi thuốc xin để bác sĩ dặn trực tiếp. Bạn gửi lời thương hay hỏi thăm nha.",
                "message_en": "This message mentions medicine or a dose. To keep things safe, Chào Bà does not pass on "
                              "medication advice; changes should come from the doctor. Send love or a check-in instead."}
    if g.detect_scam(t):
        return {"error": "money_topic", "field": "text",
                "message_vi": "Chào Bà không chuyển lời nhắn về tiền, tài khoản hay mã OTP, để người cao tuổi quen là "
                              "không ai hỏi những chuyện đó qua đây.",
                "message_en": "Chào Bà does not pass on messages about money, accounts or OTP codes, so the elder learns "
                              "that nobody asks for those here."}
    return None


# ================================================================================================ storage helpers
def _ts_at(date_iso: str, hhmm: str) -> str:
    """ISO UTC timestamp for a Vietnam local time (UTC+7) on a date."""
    h, m = (int(x) for x in hhmm.split(":"))
    d = datetime.fromisoformat(date_iso).replace(hour=h, minute=m, tzinfo=timezone(timedelta(hours=7)))
    return d.astimezone(timezone.utc).isoformat(timespec="seconds")


def vn_time(iso: str | None) -> str:
    try:
        return (datetime.fromisoformat(iso) + timedelta(hours=7)).strftime("%H:%M") if iso else ""
    except Exception:
        return ""


def _row(r) -> dict:
    d = dict(r)
    d["choices"] = json.loads(d.pop("choices_json") or "[]")
    d["reply"] = json.loads(d.pop("reply_json") or "null")
    d["save"] = json.loads(d.pop("save_json") or "null")
    return d


def rows(store: Store, elder_id: str, since: str | None = None) -> list[dict]:
    sql = "SELECT * FROM kudos WHERE elder_id=?" + (" AND date>=?" if since else "") + " ORDER BY created_at, id"
    return [_row(r) for r in store.q(sql, (elder_id, since) if since else (elder_id,))]


def get(store: Store, elder_id: str, kid: int) -> dict | None:
    r = store.one("SELECT * FROM kudos WHERE elder_id=? AND id=?", (elder_id, kid))
    return _row(r) if r else None


def _since(date_iso: str, days: int) -> str:
    return (Date.fromisoformat(date_iso) - timedelta(days=max(1, int(days)) - 1)).isoformat()


def sent_today(store: Store, elder_id: str, sender_id: str | None, sender_name: str, date: str) -> int:
    r = store.one("SELECT COUNT(*) AS n FROM kudos WHERE elder_id=? AND date=? AND (sender_id=? OR sender_name=?)",
                  (elder_id, date, sender_id or "", sender_name))
    return int(r["n"]) if r else 0


def insert(store: Store, elder_id: str, day: int | None, date: str, sender_id: str | None, sender_name: str,
           card: dict, *, custom: bool, simulated: bool = False, created_at: str | None = None) -> int:
    return store.x(
        "INSERT INTO kudos(elder_id, day, date, sender_id, sender_name, kind, template_id, text_vi, text_en, custom, "
        "health, choices_json, status, simulated, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,'sent',?,?)",
        (elder_id, day, date, sender_id, sender_name, card["kind"], card.get("template_id"), card["text_vi"],
         card.get("text_en"), 1 if custom else 0, 1 if card.get("health") else 0,
         json.dumps(card.get("choices") or [], ensure_ascii=False), 1 if simulated else 0, created_at or now_iso()))


def mark_seen(store: Store, elder_id: str, kid: int, via: str, at: str | None = None,
              snooze_minutes: int | None = None) -> None:
    at = at or now_iso()
    store.x("UPDATE kudos SET seen_at=COALESCE(seen_at, ?), seen_via=COALESCE(seen_via, ?), "
            "status=CASE WHEN status='sent' THEN 'seen' ELSE status END WHERE elder_id=? AND id=?",
            (at, via, elder_id, kid))
    if snooze_minutes:
        until = (datetime.fromisoformat(at) + timedelta(minutes=int(snooze_minutes))).isoformat(timespec="seconds")
        store.x("UPDATE kudos SET snooze_until=? WHERE elder_id=? AND id=?", (until, elder_id, kid))


def set_reply(store: Store, elder_id: str, k: dict, *, choice: str | None = None, text: str | None = None,
              heart: bool = False, via: str = "screen", at: str | None = None, simulated: bool = False,
              call_id: str | None = None) -> dict:
    at = at or now_iso()
    old = k.get("reply") or {}
    reply = dict(old)
    if choice:
        c = next((x for x in k["choices"] if x["id"] == choice), None)
        reply.update(choice=choice, choice_vi=c["vi"] if c else ("Để má gọi lại nói" if choice == "call_back" else choice),
                     choice_en=c["en"] if c else ("Will call back to tell you" if choice == "call_back" else choice))
    if text:
        reply["text"] = text.strip()[:600]
    if heart:
        reply["heart"] = True
    reply.update(via=via, at=at, simulated=bool(simulated or old.get("simulated")))
    mark_seen(store, elder_id, k["id"], via, at)
    store.x("UPDATE kudos SET reply_json=?, replied_at=COALESCE(replied_at, ?), status='replied', "
            "heart=MAX(heart, ?), call_id=COALESCE(call_id, ?), snooze_until=NULL WHERE elder_id=? AND id=?",
            (json.dumps(reply, ensure_ascii=False), at, 1 if heart else 0, call_id, elder_id, k["id"]))
    return get(store, elder_id, k["id"])


# ================================================================================================ views
def view(svc, elder_id: str, k: dict, viewer=None, prof: dict | None = None) -> dict:
    """API shape of one card. ``viewer`` None = the elder (everything)."""
    prof = prof or svc.store.elder(elder_id) or {}
    kw = kin_word(prof)
    elder_view = viewer is None or viewer.role in ELDER_ROLES
    own = viewer is not None and (viewer.member_id == k["sender_id"] or normalize(viewer.name) == normalize(k["sender_name"]))
    redacted = not elder_view and not own and viewer.role != "primary" and bool(k["custom"])
    reply = dict(k["reply"]) if k["reply"] else None
    reply_hidden = False
    if reply and not elder_view and k["health"] and svc.sharing_paused(elder_id):
        reply, reply_hidden = None, True
    if reply and redacted:
        reply.pop("text", None)
    t = BY_ID.get(k["template_id"] or "")
    status = k["status"]
    out = {"id": k["id"], "day": k["day"], "date": k["date"], "kind": k["kind"], "template_id": k["template_id"],
           "icon": (t or {}).get("icon") or {"advice": "lightbulb", "care_tip": "sprout", "message": "message-circle"}
           .get(k["kind"], "heart"),
           "sender_id": k["sender_id"], "sender_name": k["sender_name"],
           "text_vi": "Lời nhắn riêng" if redacted else k["text_vi"],
           "text_en": "A private message" if redacted else (k["text_en"] or k["text_vi"]),
           "text_lang": "vi" if k["custom"] and not redacted else None,
           "custom": bool(k["custom"]), "health": bool(k["health"]), "choices": k["choices"],
           "status": status, "sent_at": k["created_at"], "sent_time": vn_time(k["created_at"]),
           "seen_at": k["seen_at"], "seen_via": k["seen_via"], "replied_at": k["replied_at"],
           "reply_time": vn_time(k["replied_at"]), "reply": reply, "reply_hidden": reply_hidden,
           "heart": bool(k["heart"]), "redacted": redacted, "folk_note": bool((t or {}).get("folk_note")),
           "story": ({"id": k["story_id"], "saved": True} if k["story_id"] else
                     {"id": None, "saved": False, "declined": True} if (k["save"] or {}).get("declined") else None),
           "simulated": bool(k["simulated"])}
    rel = _relation(svc, elder_id, k["sender_id"])
    a = address(prof, rel)
    out["sender_relation"] = rel
    out["elder_self_vi"] = a["k"]          # how the elder names herself to this sender: "má", "bà", "ông"
    out["status_vi"], out["status_en"] = status_words(out, kw)
    out["reply_vi"], out["reply_en"] = reply_words(out, kw, a)
    return out


def _relation(svc, elder_id: str, member_id: str | None) -> str | None:
    from .family import circle
    return next((m["relation"] for m in circle(svc.store, elder_id) if m["id"] == member_id), None)


def status_words(k: dict, kw: dict) -> tuple[str, str]:
    if k["status"] == "replied":
        return f"{kw['K']} đã trả lời", f"{kw['en']} replied"
    if k["status"] == "seen":
        via = " (qua cuộc gọi)" if k["seen_via"] == "call" else ""
        return f"{kw['K']} đã xem{via}", f"{kw['en']} has seen it" + (" (in the call)" if k["seen_via"] == "call" else "")
    return "Đã gửi", "Sent"


def reply_words(k: dict, kw: dict, a: dict) -> tuple[str, str]:
    """ "Má trả lời: Ăn rồi con · 07:42", "❤ Má gửi thương lại", "Má nói: …" """
    if k["reply_hidden"]:
        return (f"{kw['K']} đã trả lời (ẩn vì chia sẻ sức khỏe đang tạm dừng)",
                f"{kw['en']} replied (hidden while health sharing is paused)")
    r = k["reply"]
    if not r:
        return "", ""
    t = f" · {k['reply_time']}" if k["reply_time"] else ""
    callee = f" {a['callee']}" if a.get("callee") else ""
    vi, en = [], []
    if r.get("choice") == "call_back":
        vi.append(f"{kw['K']} muốn gọi lại nói trực tiếp")
        en.append(f"{kw['en']} wants to call back and tell you")
    elif r.get("choice"):
        vi.append(f"{kw['K']} trả lời: {r['choice_vi']}{callee}")
        en.append(f"{kw['en']} replied: {r['choice_en']}")
    if r.get("text") and r.get("choice") not in (None, "call_back"):
        vi[-1] += f" (“{r['text']}”)"
        en[-1] += f" (in Vietnamese: “{r['text']}”)"
    elif r.get("text") and not r.get("choice"):
        vi.append(f"{kw['K']} nói: “{r['text']}”")
        en.append(f"{kw['en']} said (in Vietnamese): “{r['text']}”")
    if r.get("heart"):
        vi.append(f"❤ {kw['K']} gửi thương lại")
        en.append(f"❤ {kw['en']} sent love back")
    via_vi = " (qua cuộc gọi sáng)" if r.get("via") == "call" else ""
    via_en = " (in the morning call)" if r.get("via") == "call" else ""
    sim_vi = " · diễn tập mô phỏng" if r.get("simulated") and r.get("via") == "call" else ""
    sim_en = " · simulated rehearsal" if r.get("simulated") and r.get("via") == "call" else ""
    return ". ".join(vi) + via_vi + t + sim_vi, ". ".join(en) + via_en + t + sim_en


def micro_count(store: Store, elder_id: str, date_from: str, date_to: str) -> int:
    r = store.one("SELECT COUNT(*) AS n FROM kudos WHERE elder_id=? AND date>=? AND date<=?",
                  (elder_id, date_from, date_to))
    return int(r["n"]) if r else 0


# ================================================================================================ call relay
def relay_items(svc, elder_id: str) -> list[RelayItem]:
    """Cards the elder has not seen yet (sent in the last RELAY_DAYS days), as RelayItems for the call."""
    from .family import circle
    _, today = svc.current_day(elder_id)
    since = _since(today, RELAY_DAYS)
    members = {m["id"]: m for m in circle(svc.store, elder_id)}
    prof = svc.store.elder(elder_id) or {}
    out = []
    for k in rows(svc.store, elder_id, since):
        if k["status"] != "sent":
            continue
        m = members.get(k["sender_id"] or "")
        ref = sender_ref(m, k["sender_name"])
        t = BY_ID.get(k["template_id"] or "")
        if t and t.get("relay"):
            spoken = t["relay"]
        elif k["kind"] in FREE_RELAY:
            body = k["text_vi"].strip().replace("{", "(").replace("}", ")")
            spoken = FREE_RELAY[k["kind"]].replace("{t}", body if body[-1:] in ".?!" else body + ".")
        else:
            spoken = ""
        h = (prof.get("honorific") or "bà").lower()
        spoken = spoken.replace("{H}", h.capitalize())
        out.append(RelayItem(id=k["id"], kind=k["kind"], template_id=k["template_id"], sender=k["sender_name"],
                             sender_ref=ref, spoken_vi=spoken, choices=k["choices"],
                             topic=(t or {}).get("topic")))
    return out


def on_call_end(svc, state, result: dict) -> list[dict]:
    """Store the answers the elder gave to relayed cards (via "call"); announced cards are marked seen."""
    store = svc.store
    eid = state.ctx.elder.id
    out: list[dict] = []
    if state.emergency or state.declined or not state.ctx.relay:
        return out
    sim = bool(result.get("simulated"))
    for a in state.relay_answers:
        for aid in a.get("announced") or []:
            k = get(store, eid, aid)
            if not k:
                continue
            if a.get("item_id") is None and not a.get("declined") and a.get("text"):
                set_reply(store, eid, k, text=a["text"], heart=True, via="call", simulated=sim, call_id=state.call_id)
                out.append({"id": aid, "reply": "heart"})
            else:
                mark_seen(store, eid, aid, "call")
                out.append({"id": aid, "seen": True})
        if a.get("item_id") is not None:
            k = get(store, eid, a["item_id"])
            if not k:
                continue
            if a.get("declined"):
                mark_seen(store, eid, k["id"], "call")
                out.append({"id": k["id"], "seen": True})
                continue
            text = None if a.get("choice") and k["kind"] == "checkin" and len(a.get("text", "").split()) <= 3 \
                else a.get("text")
            if a.get("choice") == "call_back":
                text = None
            set_reply(store, eid, k, choice=a.get("choice"), text=text, via="call", simulated=sim,
                      call_id=state.call_id)
            out.append({"id": k["id"], "choice": a.get("choice"), "text": bool(text)})
    return out


# ================================================================================================ install
def install(svc) -> None:
    """Wrap the service: relay pending cards in calls, store relayed answers, micro-contact counts (idempotent)."""
    if getattr(svc, "_kudos_installed", False):
        return
    orig_ctx, orig_end, orig_contact, orig_dmaic = svc.build_context, svc.end_call, svc.contact_status, svc.dmaic

    @functools.wraps(orig_ctx)
    def build_context(elder_id: str):
        ctx = orig_ctx(elder_id)
        try:
            ctx.relay = relay_items(svc, elder_id)
        except Exception as e:  # never block a call on the cards
            log.warning("kudos relay context failed: %s", e)
        return ctx

    @functools.wraps(orig_end)
    def end_call(call_id: str):
        fresh = call_id not in svc.results
        state = svc.active.get(call_id)
        result = orig_end(call_id)
        if fresh and state is not None:
            try:
                result["kudos_relay"] = on_call_end(svc, state, result)
            except Exception as e:  # pragma: no cover - never fail the call end
                log.warning("kudos end-of-call failed: %s", e)
        return result

    @functools.wraps(orig_contact)
    def contact_status(elder_id: str) -> dict:
        out = orig_contact(elder_id)
        try:
            _, today = svc.current_day(elder_id)
            out["micro_7d"] = micro_count(svc.store, elder_id, _since(today, 7), today)
        except Exception as e:  # pragma: no cover
            log.warning("kudos micro count failed: %s", e)
        return out

    @functools.wraps(orig_dmaic)
    def dmaic(elder_id: str) -> dict:
        cyc = orig_dmaic(elder_id)
        if cyc.get("sharing_paused") or not cyc.get("contact"):
            return cyc
        try:
            add_micro_series(svc, elder_id, cyc)
        except Exception as e:  # pragma: no cover
            log.warning("kudos dmaic series failed: %s", e)
        return cyc

    svc.build_context, svc.end_call, svc.contact_status, svc.dmaic = build_context, end_call, contact_status, dmaic
    svc._kudos_installed = True


def add_micro_series(svc, elder_id: str, cyc: dict, weeks: int = 6) -> None:
    """DMAIC Improve: micro-contacts per week as a separate series next to calls / visits."""
    from chaoba.core.dmaic import contact_rate
    ks = [{"day": k["day"]} for k in rows(svc.store, elder_id) if k["day"] is not None]
    c = cyc["contact"]
    for key in ("pre", "post", "recent"):
        w = c.get(f"{key}_window")
        if w:
            c[f"micro_{key}_per_week"] = contact_rate(ks, *w) if ks else 0.0
    recs = svc.store.records(elder_id)
    last = recs[-1]["day"] if recs else 0
    calls = svc.store.contacts(elder_id)
    weekly = []
    for i in range(weeks - 1, -1, -1):
        d1 = last - 7 * i
        d0 = d1 - 6
        weekly.append({"day_from": d0, "day_to": d1, "date_from": svc.store.date_of_day(elder_id, d0),
                       "date_to": svc.store.date_of_day(elder_id, d1),
                       "calls_visits": sum(1 for x in calls if d0 <= x["day"] <= d1 and x["kind"] in ("call", "visit")),
                       "micro": sum(1 for x in ks if d0 <= x["day"] <= d1)})
    c["weekly"] = weekly
    c["micro_note_vi"] = ("Liên lạc nhỏ (lời thương, câu hỏi thăm) được đếm riêng; chúng không thay cho cuộc gọi hay "
                          "lần ghé thăm.")
    c["micro_note_en"] = "Micro-contacts (love taps, check-in questions) are counted separately; they never replace a call or visit."


# ================================================================================================ timeline provider
def timeline_items(svc, elder_id: str, viewer, lo: int, hi: int) -> list[dict]:
    """Family timeline rows (family.py calls registered providers): one per card, with the reply inline."""
    prof = svc.store.elder(elder_id) or {}
    kw = kin_word(prof)
    items = []
    for k in rows(svc.store, elder_id):
        if k["day"] is None or not (lo <= k["day"] <= hi):
            continue
        v = view(svc, elder_id, k, viewer, prof)
        q = v["text_vi"] if v["redacted"] else f"“{v['text_vi']}”"
        qe = v["text_en"] if v["redacted"] else f"“{v['text_en']}”"
        text_vi = v["reply_vi"] or (v["status_vi"] + ".")
        text_en = v["reply_en"] or (v["status_en"] + ".")
        items.append({"kind": "kudos", "uid": str(k["id"]), "day": k["day"], "actor": k["sender_name"],
                      "title_vi": f"{k['sender_name']} gửi {kw['k']}: {q}", "title_en": f"{k['sender_name']} to {kw['en']}: {qe}",
                      "text_vi": text_vi, "text_en": text_en,
                      "extra": {"kudos_id": k["id"], "kudos_kind": k["kind"], "status": v["status"],
                                "heart": v["heart"], "redacted": v["redacted"], "simulated": v["simulated"],
                                "icon": v["icon"]}})
    return items


# ================================================================================================ memory book
def save_to_memory(svc, elder_id: str, k: dict, by: str, role: str, confirmed: bool) -> dict:
    from . import memories
    if k.get("story_id"):
        return {"ok": True, "id": k["id"], "story_id": k["story_id"], "already": True}
    text = ((k.get("reply") or {}).get("text") or "").strip()
    prof = svc.store.elder(elder_id) or {}
    kw = kin_word(prof)
    t = BY_ID.get(k["template_id"] or "") or {}
    topic_vi = t.get("story_vi") or k["text_vi"].rstrip("?").strip()[:60]
    topic_en = t.get("story_en") or (k["text_en"] or "").rstrip("?").strip()[:60] or "a question from the family"
    story = {"question_id": None, "theme": "advice",
             "title_vi": f"Lời {kw['k']} dạy: {topic_vi}", "title_en": f"{kw['en']}'s advice: {topic_en}",
             "text_vi": text,
             "text_en": k.get("_text_en") or f"(In Vietnamese.) Answer to {k['sender_name']}'s question: "
                                             f"“{k['text_en'] or k['text_vi']}”",
             "people": [{"vi": k["sender_name"], "en": k["sender_name"]}], "places": [],
             "era": {"label_vi": "Lời dặn bây giờ", "label_en": "Advice for today", "decade": None},
             "word_count": len(text.split()), "translation": "human" if k.get("_text_en") else "gist"}
    ts = k.get("_ts") or now_iso()
    who = "elder (on the screen)" if role in ELDER_ROLES else by
    consent = {"answer": "yes", "asked_in_call": False, "by": who, "ts": ts, "source": "kudos",
               "history": [{"shared": True, "by": who, "role": role, "confirmed_by_elder_or_proxy": confirmed,
                            "ts": ts}]}
    sid = memories.add_story(svc.store, elder_id, story, k["day"], k["date"], shared=True, consent=consent,
                             source="kudos", simulated=bool(k["simulated"]))
    svc.store.x("UPDATE kudos SET story_id=?, save_json=? WHERE elder_id=? AND id=?",
                (sid, json.dumps({"saved": True, "by": who, "ts": ts}, ensure_ascii=False), elder_id, k["id"]))
    return {"ok": True, "id": k["id"], "story_id": sid, "title_vi": story["title_vi"], "title_en": story["title_en"]}


# ================================================================================================ seed
# (offset from the last seeded day, sender id, template id, sent HH:MM, reply {choice|text|heart}, minutes to reply,
#  via). Every seeded card is answered or seen, so no seeded card is relayed in a call.
SEED: dict[str, list[tuple]] = {
    "hanh": [
        (-27, "lan", "love", "19:10", {"heart": True}, 25, "screen"),
        (-25, "minh", "ate", "11:50", {"choice": "ate"}, 15, "screen"),
        (-23, "vy", "water", "09:00", {"choice": "ok", "heart": True}, 40, "screen"),
        (-21, "lan", "slept", "07:00", {"choice": "good"}, 20, "screen"),
        (-19, "minh", "miss", "20:00", {"heart": True}, 10, "screen"),
        (-17, "vy", "feeling", "08:00", {"choice": "well"}, 30, "screen"),
        (-13, "minh", "meds", "07:30", {"choice": "yes"}, 12, "screen"),
        (-12, "vy", "goodnight", "21:00", {"heart": True}, 5, "screen"),
        (-10, "lan", "canh_chua", "10:00", {"text": "canh_chua"}, 380, "screen"),
        (-8, "lan", "feeling", "08:10", {"choice": "tired"}, 30, "screen"),
        (-6, "minh", "thanks", "18:00", {"heart": True}, 45, "screen"),
        (-5, "vy", "ate", "11:30", {"choice": "ate"}, 20, "screen"),
        (-3, "minh", "slept", "07:00", {"choice": "meh"}, 35, "screen"),
        (-2, "lan", "love", "19:00", {"heart": True}, 15, "screen"),
        (-1, "vy", "sun", "06:40", {"choice": "ok"}, 50, "screen"),
        (0, "minh", "ate", "07:20", {"choice": "ate"}, 22, "screen"),
    ],
    "tu": [
        (-18, "khoa", "ate", "11:40", {"choice": "ate"}, 25, "call"),
        (-12, "ngan", "miss", "20:30", {"heart": True}, 720, "call"),
        (-8, "ba_tu", "walk", "15:00", {"choice": "ok"}, 60, "screen"),
        (-4, "khoa", "slept", "07:10", {"choice": "meh"}, 40, "call"),
        (-1, "ngan", "love", "19:30", {"heart": True}, 30, "screen"),
    ],
    "control": [
        (-14, "thao", "feeling", "08:00", {"choice": "well"}, 20, "screen"),
        (-6, "tam", "thanks", "19:00", {"heart": True}, 30, "screen"),
        (-2, "thao", "water", "12:00", {"choice": "ok"}, 45, "screen"),
    ],
}
SEED_CANH_CHUA = {
    "vi": "Nấu canh chua phải có me chín nghen con. Dầm me với nước ấm lấy nước cho chua thanh, đừng chua gắt. Cá lóc "
          "rửa với muối cho hết nhớt, chiên sơ cho chắc thịt. Nước sôi mới bỏ thơm với cà chua, nêm chút đường, chút "
          "nước mắm cho dịu. Bạc hà, đậu bắp, giá bỏ vô sau cùng, sôi lại là tắt bếp liền cho rau còn giòn. Rắc ngò om "
          "với ngò gai, phi chút tỏi vàng thả vô là thơm cả nhà. Má nấu vậy hoài, tụi bây hồi nhỏ ăn hết nồi.",
    "en": "Canh chua needs ripe tamarind, child. Mash it in warm water for a clean sourness, not a sharp one. Rub the "
          "snakehead fish with salt to clean it and fry it lightly so the flesh stays firm. When the water boils, add "
          "pineapple and tomato, a little sugar and fish sauce to soften it. Taro stem, okra and bean sprouts go in last; "
          "once it boils again, turn off the heat so the vegetables stay crisp. Sprinkle rice-paddy herb and sawtooth "
          "coriander, add a little golden fried garlic and the whole house smells good. I always cooked it that way; "
          "you children used to finish the whole pot.",
}


def seed_all(svc) -> None:
    from .family import CIRCLES
    store = svc.store
    for eid, plan in SEED.items():
        if not store.elder(eid) or store.one("SELECT 1 FROM kudos WHERE elder_id=? LIMIT 1", (eid,)):
            continue
        recs = store.records(eid)
        if not recs:
            continue
        last = max((r["day"] for r in recs if r.get("simulated", True)), default=recs[-1]["day"])
        prof = store.elder(eid) or {}
        members = {m["member_id"]: m for m in CIRCLES.get(eid, [])}
        for off, sid, tid, hhmm, reply, mins, via in plan:
            day = last + off
            date = store.date_of_day(eid, day)
            if not date or sid not in members:
                continue
            m = members[sid]
            card = render_template(BY_ID[tid], address(prof, m["relation"]))
            card["template_id"] = tid
            sent = _ts_at(date, hhmm)
            kid = insert(store, eid, day, date, sid, m["name"], card, custom=False, simulated=True, created_at=sent)
            at = (datetime.fromisoformat(sent) + timedelta(minutes=mins)).isoformat(timespec="seconds")
            k = get(store, eid, kid)
            text = SEED_CANH_CHUA["vi"] if reply.get("text") == "canh_chua" else None
            k = set_reply(store, eid, k, choice=reply.get("choice"), text=text, heart=bool(reply.get("heart")),
                          via=via, at=at, simulated=True)
            if text:
                k["_text_en"], k["_ts"] = SEED_CANH_CHUA["en"], at
                save_to_memory(svc, eid, k, "Bà Hạnh (on the screen, simulated)", "elder_self", True)


# ================================================================================================ routes
class KudosIn(BaseModel):
    kind: str
    template_id: str | None = Field(default=None, max_length=40)
    text: str | None = Field(default=None, max_length=400)
    from_: str | None = Field(default=None, alias="from", max_length=80)

    model_config = {"populate_by_name": True}


class SeenIn(BaseModel):
    via: str = "screen"
    snooze_minutes: int | None = Field(default=None, ge=1, le=24 * 60)


class ReplyIn(BaseModel):
    choice: str | None = Field(default=None, max_length=40)
    text: str | None = Field(default=None, max_length=1200)
    heart: bool = False
    via: str = "screen"


class SaveIn(BaseModel):
    confirmed_by_elder_or_proxy: bool = False
    decline: bool = False


def register(app: FastAPI) -> None:
    from .family import NON_FAMILY_ROLES, TIMELINE_PROVIDERS, circle, resolve_viewer, seed_elder
    if timeline_items not in TIMELINE_PROVIDERS:
        TIMELINE_PROVIDERS.append(timeline_items)

    def ctx(request: Request, elder_id: str, action: str):
        s = request.app.state.svc
        if not s.elder_or_none(elder_id):
            raise HTTPException(404, f"unknown elder {elder_id}")
        actor = unquote(request.headers.get("x-actor", "family:primary"))[:80]
        role = unquote(request.headers.get("x-role", "primary"))[:40]
        v = resolve_viewer(s.store, elder_id, actor, "elder_self" if role in ELDER_ROLES else role)
        if v.role in NON_FAMILY_ROLES:
            raise HTTPException(403, {"error": "family_only",
                                      "message_vi": "Lời thương chỉ dành cho người nhà và chính người cao tuổi.",
                                      "message_en": "Love notes are for family members and the elder only."})
        seed_elder(s, elder_id)
        s.store.log_access(elder_id, v.name, v.role, action, str(request.url.path))
        return s, v

    def family_only(v):
        if v.role in ELDER_ROLES:
            raise HTTPException(403, {"error": "family_sender_only",
                                      "message_vi": "Người nhà gửi lời thương; người cao tuổi trả lời trên màn hình.",
                                      "message_en": "Family members send cards; the elder replies on the screen."})

    def elder_only(v):
        if v.role not in ELDER_ROLES:
            raise HTTPException(403, {"error": "elder_only",
                                      "message_vi": "Chỉ người cao tuổi mới mở và trả lời lời nhắn của mình.",
                                      "message_en": "Only the elder opens and answers their own cards."})

    def card_or_404(s, elder_id: str, kid: int) -> dict:
        k = get(s.store, elder_id, kid)
        if not k:
            raise HTTPException(404, "card not found")
        return k

    base = "/api/elders/{elder_id}/kudos"

    @app.get(base + "/catalog")
    def catalog(request: Request, elder_id: str):
        s, v = ctx(request, elder_id, "read_kudos_catalog")
        prof = s.store.elder(elder_id) or {}
        rel = next((m["relation"] for m in circle(s.store, elder_id) if m["id"] == v.member_id), None)
        a = address(prof, rel)
        _, today = s.current_day(elder_id)
        n = sent_today(s.store, elder_id, v.member_id, v.name, today) if v.role not in ELDER_ROLES else 0
        groups = [{**gr, "label_vi": _fill(gr["label_vi"], a), "label_en": _fill_en(gr["label_en"], a)} for gr in GROUPS]
        return {"viewer": v.as_dict(), "address_vi": a["k"], "address_en": a["K_en"],
                "templates": [render_template(t, a) for t in TEMPLATES], "groups": groups,
                "limit_per_day": DAILY_LIMIT, "sent_today": n, "remaining_today": max(0, DAILY_LIMIT - n),
                "max_text": MAX_TEXT, "voice_note": VOICE_NOTE, "self_report": SELF_REPORT_NOTE,
                "can_send": v.role not in ELDER_ROLES, "simulated": s.is_simulated(elder_id)}

    @app.post(base)
    def send(request: Request, elder_id: str, body: KudosIn):
        s, v = ctx(request, elder_id, "send_kudos")
        family_only(v)
        if body.from_ and body.from_ not in (v.member_id, v.name):
            raise HTTPException(403, {"error": "not_allowed", "message_vi": "Chỉ gửi được với tên của chính bạn.",
                                      "message_en": "You can only send as yourself."})
        if body.kind not in KINDS:
            raise HTTPException(422, f"kind must be one of {KINDS}")
        day, today = s.current_day(elder_id)
        n = sent_today(s.store, elder_id, v.member_id, v.name, today)
        if n >= DAILY_LIMIT:
            kw = kin_word(s.store.elder(elder_id) or {})
            raise HTTPException(429, {"error": "daily_limit", "limit": DAILY_LIMIT,
                                      "message_vi": f"Hôm nay bạn đã gửi {DAILY_LIMIT} lời thương rồi, {kw['k']} đọc từ "
                                                    f"từ nha. Mai gửi tiếp, hoặc gọi {kw['k']} một cuộc!",
                                      "message_en": f"You've sent {DAILY_LIMIT} cards today; let {kw['en']} enjoy them. "
                                                    f"Send more tomorrow, or give {kw['en']} a call!"})
        prof = s.store.elder(elder_id) or {}
        rel = next((m["relation"] for m in circle(s.store, elder_id) if m["id"] == v.member_id), None)
        a = address(prof, rel)
        text = (body.text or "").strip()
        if body.template_id:
            t = BY_ID.get(body.template_id)
            if not t or t["kind"] != body.kind:
                raise HTTPException(422, {"error": "unknown_template", "field": "template_id"})
            card = render_template(t, a)
            card["template_id"] = t["id"]
            custom = False
        else:
            if body.kind in ("checkin", "love"):
                raise HTTPException(422, {"error": "template_required", "field": "template_id"})
            if not text or len(text) > MAX_TEXT:
                raise HTTPException(422, {"error": "text_length", "field": "text", "max": MAX_TEXT,
                                          "message_vi": f"Lời nhắn cần từ 1 tới {MAX_TEXT} ký tự.",
                                          "message_en": f"Messages need 1 to {MAX_TEXT} characters."})
            bad = check_free_text(text)
            if bad:
                raise HTTPException(422, bad)
            card = {"kind": body.kind, "template_id": None, "text_vi": text, "text_en": text, "health": False,
                    "choices": CARE_TIP_CHOICES if body.kind == "care_tip" else []}
            custom = True
        kid = insert(s.store, elder_id, day, today, v.member_id, v.name, card, custom=custom)
        k = get(s.store, elder_id, kid)
        return {"ok": True, "kudos": view(s, elder_id, k, v, prof), "sent_today": n + 1,
                "remaining_today": max(0, DAILY_LIMIT - n - 1)}

    @app.get(base)
    def listing(request: Request, elder_id: str, box: str = "sent", days: int = 28, pending: bool = False):
        s, v = ctx(request, elder_id, f"read_kudos_{box}"[:40])
        if box not in ("inbox", "sent", "family"):
            raise HTTPException(422, "box must be inbox, sent or family")
        if box == "inbox":
            elder_only(v)
        else:
            family_only(v)
        _, today = s.current_day(elder_id)
        prof = s.store.elder(elder_id) or {}
        ks = rows(s.store, elder_id, _since(today, max(1, min(int(days), 120))))
        now = now_iso()
        if box == "sent":
            ks = [k for k in ks if k["sender_id"] == v.member_id or normalize(k["sender_name"]) == normalize(v.name)]
        if box == "inbox" and pending:
            ks = [k for k in ks if k["status"] != "replied" and not (k["snooze_until"] and k["snooze_until"] > now)
                  and not (k["status"] == "seen" and k["kind"] in ("love", "care_tip", "message"))]
        items = [view(s, elder_id, k, None if box == "inbox" else v, prof) for k in ks]
        items = items if (box == "inbox" and pending) else list(reversed(items))   # queue oldest first, lists newest
        n = sent_today(s.store, elder_id, v.member_id, v.name, today) if box != "inbox" else 0
        return {"box": box, "items": items, "viewer": v.as_dict(), "date": today,
                "micro_7d": micro_count(s.store, elder_id, _since(today, 7), today),
                "sent_today": n, "remaining_today": max(0, DAILY_LIMIT - n), "limit_per_day": DAILY_LIMIT,
                "sharing_paused": s.sharing_paused(elder_id), "self_report": SELF_REPORT_NOTE,
                "simulated": s.is_simulated(elder_id)}

    @app.post(base + "/{kid}/seen")
    def seen(request: Request, elder_id: str, kid: int, body: SeenIn | None = None):
        s, v = ctx(request, elder_id, "kudos_seen")
        elder_only(v)
        body = body or SeenIn()
        card_or_404(s, elder_id, kid)
        mark_seen(s.store, elder_id, kid, body.via if body.via in ("screen", "call") else "screen",
                  snooze_minutes=body.snooze_minutes)
        return {"ok": True, "kudos": view(s, elder_id, get(s.store, elder_id, kid))}

    @app.post(base + "/{kid}/reply")
    def reply(request: Request, elder_id: str, kid: int, body: ReplyIn):
        s, v = ctx(request, elder_id, "kudos_reply")
        elder_only(v)
        k = card_or_404(s, elder_id, kid)
        choice = (body.choice or "").strip() or None
        text = (body.text or "").strip() or None
        if not (choice or text or body.heart):
            raise HTTPException(422, {"error": "empty_reply", "message_vi": "Chọn một câu trả lời hoặc gửi thương lại.",
                                      "message_en": "Pick an answer or send love back."})
        valid = {c["id"] for c in k["choices"]} | ({"call_back"} if k["kind"] == "advice" else set())
        if choice and choice not in valid:
            raise HTTPException(422, {"error": "unknown_choice", "field": "choice", "choices": sorted(valid)})
        out = set_reply(s.store, elder_id, k, choice=choice, text=text, heart=body.heart,
                        via=body.via if body.via in ("screen", "call") else "screen")
        return {"ok": True, "kudos": view(s, elder_id, out),
                "can_save": out["kind"] == "advice" and bool((out["reply"] or {}).get("text")) and not out["story_id"]}

    @app.post(base + "/{kid}/save")
    def save(request: Request, elder_id: str, kid: int, body: SaveIn | None = None):
        body = body or SaveIn()
        s, v = ctx(request, elder_id, "kudos_save_memory")
        k = card_or_404(s, elder_id, kid)
        if k["kind"] != "advice" or not (k["reply"] or {}).get("text"):
            raise HTTPException(409, {"error": "nothing_to_save",
                                      "message_vi": "Chỉ lưu được câu trả lời cho lời hỏi ý.",
                                      "message_en": "Only an answer to an advice question can be saved."})
        if body.decline:
            elder_only(v)
            s.store.x("UPDATE kudos SET save_json=? WHERE elder_id=? AND id=?",
                      (json.dumps({"declined": True, "ts": now_iso()}), elder_id, kid))
            return {"ok": True, "id": kid, "story_id": None, "declined": True}
        if v.role not in ELDER_ROLES and not body.confirmed_by_elder_or_proxy:
            raise HTTPException(400, {
                "error": "confirmation_required", "field": "confirmed_by_elder_or_proxy",
                "message_en": "Saving the answer to the memory book is the elder's decision. A family member can do it "
                              "only after the elder (or their legal proxy) has agreed. Send "
                              "{\"confirmed_by_elder_or_proxy\": true}.",
                "message_vi": "Lưu lời dạy vào Sổ ký ức là quyền của người cao tuổi. Người nhà chỉ lưu được sau khi chính "
                              "người cao tuổi (hoặc người đại diện hợp pháp) đã đồng ý."})
        return save_to_memory(s, elder_id, k, v.name, v.role, bool(body.confirmed_by_elder_or_proxy)
                              or v.role in ELDER_ROLES)
