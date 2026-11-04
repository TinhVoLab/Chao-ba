"""Family together on the big screen ("Cả nhà ghé thăm"): the adult children, each far away, drop by the elder's
standing screen in ten seconds a day, and the elder sees the whole family at a glance without doing anything.

* **Photo wall** (``family_photo``): each child sends a photo of their day (lunch, a grandchild's school drawing, the
  street where they work) with a short caption. The screen shows the last week's photos as a large slow slideshow; the
  elder may tap a heart, and the sender sees it.
* **Who dropped by today** (``presence``): every member of the care circle with whether they have been in touch today
  (a love card, a photo, a call or a visit). The screen shows the faces as a strip; the family app shows the same strip
  and gently tells a member who has not dropped by yet.
* **Family moment** (``family_moment``): when every child has dropped by on the same day, the screen shows
  "Cả nhà nhớ {má}" and the elder can send one heart back to everyone with a single tap.

The elder never has to type, scroll or learn anything: looking is enough, one tap at most. A photo is a micro-contact
like a kudos card: it never counts as a call or visit (the "nobody called" nudge ignores it). Captions pass the same
free-text checks as the cards (no diagnoses, no medication advice). Images are small data URLs (JPEG / PNG / WebP,
resized in the browser); SVG uploads are refused. Seeded photos are simulated drawings, not photos of real people.

  GET  /api/elders/{id}/together                     presence today, photos (7 days), moment
  POST /api/elders/{id}/photos                       {image, caption?}         family members
  POST /api/elders/{id}/photos/{pid}/heart                                     the elder
  POST /api/elders/{id}/together/heart                                         the elder (moment heart back)
"""
from __future__ import annotations

import re
from datetime import date as Date, datetime, timedelta, timezone
from urllib.parse import quote, unquote

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

from chaoba.agent.textnorm import normalize

from .db import Store, now_iso
from .kudos import ELDER_ROLES, check_free_text, kin_word, vn_time

PHOTO_DAILY_LIMIT = 3
PHOTO_DAYS = 7
MAX_PHOTOS = 12
MAX_CAPTION = 80
MAX_IMAGE_CHARS = 450_000          # ~330 KB of JPEG once base64-encoded; the app resizes to 900 px first
_IMAGE_RE = re.compile(r"^data:image/(jpeg|png|webp);base64,[A-Za-z0-9+/]+=*$")


# ================================================================================================ simulated drawings
def _svg(body: str, sky: str, ground: str) -> str:
    svg = (f"<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 400 300'>"
           f"<rect width='400' height='300' fill='{sky}'/><rect y='210' width='400' height='90' fill='{ground}'/>"
           f"{body}</svg>")
    return "data:image/svg+xml;utf8," + quote(svg)


DRAWINGS = {
    # a family lunch: a pot of canh chua and three bowls on a wooden table
    "lunch": _svg("<rect x='40' y='170' width='320' height='18' rx='6' fill='#8a5a3b'/>"
                  "<ellipse cx='200' cy='150' rx='62' ry='22' fill='#e9a23b'/><rect x='138' y='118' width='124' height='34' "
                  "rx='10' fill='#c8553d'/><circle cx='180' cy='112' r='7' fill='#3f8f4f'/><circle cx='214' cy='108' r='6' "
                  "fill='#f2c14e'/><path d='M80 160h50l-8 14h-34z' fill='#fff'/><path d='M270 160h50l-8 14h-34z' fill='#fff'/>"
                  "<path d='M180 196h40l-6 10h-28z' fill='#fff'/>", "#fde8c8", "#f4d3a4"),
    # a grandchild's school drawing with "10" in red pen
    "drawing": _svg("<rect x='90' y='40' width='220' height='200' rx='8' fill='#fff' stroke='#c9c2b4' stroke-width='3'/>"
                    "<circle cx='150' cy='100' r='26' fill='#f2c14e'/><path d='M120 200l40-60 30 40 25-30 45 50z' "
                    "fill='#5a9e6f'/><text x='250' y='95' font-family='sans-serif' font-size='44' font-weight='700' "
                    "fill='#d7263d'>10</text><path d='M240 104q20 12 48 0' stroke='#d7263d' stroke-width='4' fill='none'/>",
                    "#dcecf7", "#b9d6ea"),
    # an autumn street in Hà Nội: a lamp post and yellow leaves
    "street": _svg("<rect x='60' y='90' width='90' height='120' fill='#c9b79c'/><rect x='170' y='60' width='110' height='150' "
                   "fill='#e2cfa9'/><rect x='300' y='110' width='70' height='100' fill='#b9a284'/><rect x='240' y='120' "
                   "width='5' height='90' fill='#4a4a4a'/><circle cx='242' cy='116' r='9' fill='#f7d774'/>"
                   "<circle cx='90' cy='240' r='6' fill='#e3a72f'/><circle cx='150' cy='255' r='5' fill='#e3a72f'/>"
                   "<circle cx='320' cy='250' r='6' fill='#d98c1f'/>", "#f6e3b4", "#9c8f7a"),
    # the mai tree blossoming in a pot
    "flowers": _svg("<rect x='170' y='190' width='60' height='40' rx='6' fill='#a0522d'/><path d='M200 190V110M200 140l-40-30"
                    "M200 125l38-28' stroke='#6b4226' stroke-width='6' fill='none'/>"
                    "<g fill='#f7c948'><circle cx='160' cy='108' r='12'/><circle cx='238' cy='96' r='12'/>"
                    "<circle cx='200' cy='104' r='12'/><circle cx='182' cy='84' r='9'/><circle cx='222' cy='120' r='9'/></g>",
                    "#fff4dc", "#e7d6b5"),
    # the morning sea at Vũng Tàu
    "sea": _svg("<circle cx='300' cy='90' r='34' fill='#ffd36e'/><rect y='150' width='400' height='60' fill='#5aa9d6'/>"
                "<path d='M0 170q25-10 50 0t50 0 50 0 50 0 50 0 50 0 50 0 50 0' stroke='#fff' stroke-width='3' fill='none'/>",
                "#ffe5c4", "#f1d7a6"),
}

# Seeded photos (simulated): (day offset from today, member, drawing, hh:mm, caption vi, caption en, hearted)
SEED: dict[str, list[tuple]] = {
    "hanh": [
        (-5, "minh", "street", "17:40", "Hà Nội vào thu rồi má", "Autumn has come to Hà Nội, Mom", True),
        (-3, "lan", "flowers", "08:15", "Chậu mai má cho con nở rồi nè", "The mai you gave me is blooming", True),
        (-1, "vy", "sea", "06:30", "Sáng nay cháu ra biển, nhớ bà", "Morning at the sea, missing you Grandma", True),
        (0, "lan", "lunch", "06:20", "Con nấu canh chua theo cách má chỉ", "I made canh chua your way", False),
        (0, "vy", "drawing", "06:45", "Bé Na vẽ tặng bà, được 10 điểm", "Na drew this for you and got a 10", False),
    ],
    "tu": [
        (-2, "ngan", "sea", "07:10", "Ba ơi, biển sáng nay đẹp lắm", "Dad, the sea was lovely this morning", True),
        (0, "khoa", "lunch", "06:30", "Bữa sáng của con nè ba", "My breakfast, Dad", False),
    ],
}


# ================================================================================================ store helpers
def _row(r) -> dict:
    return {"id": r["id"], "day": r["day"], "date": r["date"], "sender_id": r["sender_id"],
            "sender_name": r["sender_name"], "caption": r["caption"] or "", "image": r["image"],
            "hearted": bool(r["heart_at"]), "heart_at": r["heart_at"], "simulated": bool(r["simulated"]),
            "created_at": r["created_at"]}


def photos(store: Store, elder_id: str, since: str) -> list[dict]:
    return [_row(r) for r in store.q("SELECT * FROM family_photo WHERE elder_id=? AND date>=? ORDER BY created_at DESC, "
                                     "id DESC LIMIT ?", (elder_id, since, MAX_PHOTOS))]


def insert_photo(store: Store, elder_id: str, day: int | None, date: str, sender_id: str | None, sender_name: str,
                 image: str, caption: str, simulated: bool = False, created_at: str | None = None,
                 heart_at: str | None = None) -> int:
    # seeded photos count as already mentioned in a call, so the scripted demo call is unchanged
    return store.x("INSERT INTO family_photo(elder_id, day, date, sender_id, sender_name, caption, image, heart_at, "
                   "relayed_at, simulated, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                   (elder_id, day, date, sender_id, sender_name, caption, image, heart_at,
                    created_at if simulated else None, int(simulated), created_at or now_iso()))


def _ts_at(date_iso: str, hhmm: str) -> str:
    """A seeded timestamp; never in the future (a seeded 'this morning' photo is moved to just before now)."""
    h, m = map(int, hhmm.split(":"))
    ts = datetime.fromisoformat(date_iso).replace(hour=h, minute=m).astimezone()
    now = datetime.now().astimezone()
    # UTC like now_iso(), so created_at strings sort in time order
    return min(ts, now - timedelta(minutes=5)).astimezone(timezone.utc).isoformat(timespec="seconds")


def presence(svc, elder_id: str, date: str) -> list[dict]:
    """Every care-circle member and whether (and how) they were in touch on ``date``."""
    from .family import circle
    st = svc.store
    out = []
    for m in circle(st, elder_id):
        key = normalize(m["name"] or "")

        def mine(r) -> bool:
            return (m["id"] and r["sender_id"] == m["id"]) or normalize(r["sender_name"] or "") == key

        via: dict[str, str] = {}
        for r in st.q("SELECT sender_id, sender_name, created_at FROM kudos WHERE elder_id=? AND date=?", (elder_id, date)):
            if mine(r):
                via.setdefault("love", r["created_at"])
        for r in st.q("SELECT sender_id, sender_name, created_at FROM family_photo WHERE elder_id=? AND date=?",
                      (elder_id, date)):
            if mine(r):
                via.setdefault("photo", r["created_at"])
        for r in st.q("SELECT member_id, member_name, kind, created_at FROM family_contact WHERE elder_id=? AND date=?",
                      (elder_id, date)):
            if (m["id"] and r["member_id"] == m["id"]) or normalize(r["member_name"] or "") == key:
                via.setdefault(r["kind"] if r["kind"] in ("call", "visit") else "call", r["created_at"])
        first = min(via.values()) if via else None
        out.append({"member_id": m["id"], "name": m["name"], "relation": m["relation"], "relation_vi": m["relation_vi"],
                    "city": m.get("city"), "visited": bool(via), "via": sorted(via, key=lambda k: via[k]),
                    "first_at": first, "first_time": vn_time(first) if first else None})
    return out


def moment(store: Store, elder_id: str, date: str) -> dict:
    r = store.one("SELECT heart_at FROM family_moment WHERE elder_id=? AND date=?", (elder_id, date))
    return {"heart_at": r["heart_at"] if r else None, "hearted": bool(r and r["heart_at"])}


def summary(svc, elder_id: str, viewer=None) -> dict:
    """The screen's and the family app's shared view of today."""
    _, today = svc.current_day(elder_id)
    prof = svc.store.elder(elder_id) or {}
    kw = kin_word(prof)
    members = presence(svc, elder_id, today)
    here = [m for m in members if m["visited"]]
    all_here = bool(members) and len(here) == len(members)
    since = (Date.fromisoformat(today) - timedelta(days=PHOTO_DAYS - 1)).isoformat()
    me = next((m for m in members if viewer is not None and m["member_id"] == viewer.member_id), None)
    k, K = kw["k"], kw["k"][:1].upper() + kw["k"][1:]
    names = [m["name"] for m in here]
    if not here:
        line_vi, line_en = f"Hôm nay chưa ai ghé thăm {k}.", f"Nobody has dropped by {kw['en']} yet today."
    elif all_here:
        line_vi, line_en = f"Cả nhà đã ghé thăm {k} hôm nay.", f"The whole family dropped by {kw['en']} today."
    else:
        line_vi = f"{', '.join(names)} đã ghé thăm {k} hôm nay."
        line_en = f"{', '.join(names)} dropped by {kw['en']} today."
    # the same line as the elder reads it on their own screen (no "má" talking about themself)
    if not here:
        screen_vi, screen_en = "Hôm nay các con chưa ghé.", "No one has dropped by yet today."
    elif all_here:
        screen_vi, screen_en = "Hôm nay cả nhà đều đã ghé thăm.", "The whole family dropped by today."
    else:
        screen_vi, screen_en = f"Hôm nay {', '.join(names)} đã ghé thăm.", f"{', '.join(names)} dropped by today."
    return {"date": today, "members": members, "screen_vi": screen_vi, "screen_en": screen_en, "visited_count": len(here), "total": len(members),
            "all_here": all_here, "line_vi": line_vi, "line_en": line_en,
            "moment": {**moment(svc.store, elder_id, today), "title_vi": f"Cả nhà nhớ {k}",
                       "title_en": f"The whole family is thinking of {kw['en']}",
                       "body_vi": f"Hôm nay con cháu ai cũng ghé thăm {k}. {K} chạm trái tim để gửi thương lại cả nhà nha.",
                       "body_en": f"Everyone dropped by today. Tap the heart to send love back to the whole family."},
            "companion": companion(members, all_here, kw),
            "me": ({"visited": me["visited"], "via": me["via"]} if me else None),
            "photos": photos(svc.store, elder_id, since), "photo_limit_per_day": PHOTO_DAILY_LIMIT,
            "address_vi": k, "address_en": kw["en"], "simulated": svc.is_simulated(elder_id)}


# ================================================================================================ Út Thương
# When the children are busy, Út Thương keeps the elder company: the screen invites a chat on a day nobody has dropped
# by yet, and the morning call mentions today's photos ("Chị Lan gửi hình lên màn hình cho bà nè: ...").
def relay_photos(svc, elder_id: str, limit: int = 2) -> list:
    """Today's photos not hearted nor mentioned in a call yet, as one-way relay lines (marked at call end). Negative ids keep them apart from kudos
    card ids (kudos.on_call_end looks cards up by id and skips unknown ones)."""
    from chaoba.agent.relay import RelayItem
    from .family import circle
    from .kudos import sender_ref
    _, today = svc.current_day(elder_id)
    members = {m["id"]: m for m in circle(svc.store, elder_id)}
    out = []
    for r in svc.store.q("SELECT * FROM family_photo WHERE elder_id=? AND date=? AND heart_at IS NULL AND relayed_at IS NULL ORDER BY id",
                         (elder_id, today))[:limit]:
        cap = (r["caption"] or "").strip().replace("{", "(").replace("}", ")")
        spoken = "{s} gửi hình lên màn hình cho {h} nè" + (f": {cap}" + ("" if cap[-1:] in ".?!" else ".") if cap else ".")
        out.append(RelayItem(id=-r["id"], kind="message", template_id=None, sender=r["sender_name"],
                             sender_ref=sender_ref(members.get(r["sender_id"] or ""), r["sender_name"]),
                             spoken_vi=spoken))
    return out


def install(svc) -> None:
    """Append today's photos to the cards relayed in the call and mark the announced ones at call end (after
    kudos.install, idempotent)."""
    if getattr(svc, "_together_installed", False):
        return
    orig_ctx, orig_end = svc.build_context, svc.end_call

    def build_context(elder_id: str):
        ctx = orig_ctx(elder_id)
        try:
            ctx.relay = list(getattr(ctx, "relay", None) or []) + relay_photos(svc, elder_id)
        except Exception:  # never block a call on the photos
            pass
        return ctx

    def end_call(call_id: str):
        state = svc.active.get(call_id) if call_id not in svc.results else None
        result = orig_end(call_id)
        if state is not None and not (state.emergency or state.declined):
            ids = [-i for a in state.relay_answers for i in (a.get("announced") or []) if isinstance(i, int) and i < 0]
            for pid in ids:
                svc.store.x("UPDATE family_photo SET relayed_at=COALESCE(relayed_at, ?) WHERE elder_id=? AND id=?",
                            (now_iso(), state.ctx.elder.id, pid))
        return result

    svc.build_context, svc.end_call = build_context, end_call
    svc._together_installed = True


def companion(members: list[dict], all_here: bool, kw: dict) -> dict | None:
    """The screen's invitation from Út Thương on a day the children are busy (nobody has dropped by yet)."""
    if any(m["visited"] for m in members) or all_here:
        return None
    k = kw["k"]
    return {"line_vi": f"Các con bận chút xíu, lát ghé thăm {k}. Giờ {k} nói chuyện với Út Thương cho vui nha?",
            "line_en": f"The children are busy for now and will drop by later. Shall we have a chat meanwhile?"}


# ================================================================================================ seed
def seed_all(svc) -> None:
    from .family import CIRCLES
    st = svc.store
    for eid, plan in SEED.items():
        if not st.elder(eid) or st.one("SELECT 1 FROM family_photo WHERE elder_id=? LIMIT 1", (eid,)):
            continue
        day0, today = svc.current_day(eid)
        members = {m["member_id"]: m for m in CIRCLES.get(eid, [])}
        for off, mid, drawing, hhmm, cap_vi, _cap_en, hearted in plan:
            if mid not in members:
                continue
            date = (Date.fromisoformat(today) + timedelta(days=off)).isoformat()
            ts = _ts_at(date, hhmm)
            heart = (datetime.fromisoformat(ts) + timedelta(minutes=40)).isoformat(timespec="seconds") if hearted else None
            insert_photo(st, eid, None if day0 is None else day0 + off, date, mid, members[mid]["name"],
                         DRAWINGS[drawing], cap_vi, simulated=True, created_at=ts, heart_at=heart)


def timeline_items(svc, elder_id: str, viewer, lo: int, hi: int) -> list[dict]:
    """Family timeline rows: one per photo, with the elder's heart."""
    kw = kin_word(svc.store.elder(elder_id) or {})
    items = []
    for r in svc.store.q("SELECT * FROM family_photo WHERE elder_id=? AND day BETWEEN ? AND ?", (elder_id, lo, hi)):
        p = _row(r)
        cap = f": “{p['caption']}”" if p["caption"] else ""
        items.append({"kind": "photo", "uid": f"photo-{p['id']}", "day": p["day"], "actor": p["sender_name"],
                      "title_vi": f"{p['sender_name']} gửi {kw['k']} một tấm ảnh{cap}",
                      "title_en": f"{p['sender_name']} sent {kw['en']} a photo{cap}",
                      "text_vi": f"{kw['k'].capitalize()} đã thả tim." if p["hearted"] else "Đang hiện trên màn hình.",
                      "text_en": f"{kw['en'].capitalize()} sent a heart." if p["hearted"] else "Showing on the screen.",
                      "extra": {"photo_id": p["id"], "heart": p["hearted"], "simulated": p["simulated"]}})
    return items


# ================================================================================================ routes
class PhotoIn(BaseModel):
    image: str = Field(max_length=MAX_IMAGE_CHARS + 100)
    caption: str | None = Field(default=None, max_length=400)


def register(app: FastAPI) -> None:
    from .family import NON_FAMILY_ROLES, TIMELINE_PROVIDERS, resolve_viewer, seed_elder
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
                                      "message_vi": "Phần này chỉ dành cho người nhà và chính người cao tuổi.",
                                      "message_en": "This is for family members and the elder only."})
        seed_elder(s, elder_id)
        s.store.log_access(elder_id, v.name, v.role, action, str(request.url.path))
        return s, v

    def elder_only(v):
        if v.role not in ELDER_ROLES:
            raise HTTPException(403, {"error": "elder_only", "message_vi": "Chỉ người cao tuổi mới thả tim được.",
                                      "message_en": "Only the elder can send this heart."})

    @app.get("/api/elders/{elder_id}/together")
    def together(request: Request, elder_id: str):
        s, v = ctx(request, elder_id, "read_together")
        return {**summary(s, elder_id, None if v.role in ELDER_ROLES else v), "viewer": v.as_dict()}

    @app.post("/api/elders/{elder_id}/photos")
    def send_photo(request: Request, elder_id: str, body: PhotoIn):
        s, v = ctx(request, elder_id, "send_photo")
        if v.role in ELDER_ROLES:
            raise HTTPException(403, {"error": "family_sender_only",
                                      "message_vi": "Người nhà gửi ảnh; người cao tuổi xem trên màn hình.",
                                      "message_en": "Family members send photos; the elder sees them on the screen."})
        if len(body.image) > MAX_IMAGE_CHARS or not _IMAGE_RE.match(body.image):
            raise HTTPException(422, {"error": "bad_image", "field": "image",
                                      "message_vi": "Ảnh cần là JPEG, PNG hoặc WebP và nhỏ hơn khoảng 300 KB.",
                                      "message_en": "The photo must be JPEG, PNG or WebP and under about 300 KB."})
        caption = (body.caption or "").strip()
        if len(caption) > MAX_CAPTION:
            raise HTTPException(422, {"error": "text_length", "field": "caption", "max": MAX_CAPTION,
                                      "message_vi": f"Lời kèm ảnh tối đa {MAX_CAPTION} ký tự.",
                                      "message_en": f"Captions are at most {MAX_CAPTION} characters."})
        if caption and (bad := check_free_text(caption)):
            raise HTTPException(422, bad)
        day, today = s.current_day(elder_id)
        n = len([r for r in s.store.q("SELECT sender_id, sender_name FROM family_photo WHERE elder_id=? AND date=?",
                                      (elder_id, today))
                 if r["sender_id"] == v.member_id or normalize(r["sender_name"]) == normalize(v.name)])
        if n >= PHOTO_DAILY_LIMIT:
            raise HTTPException(429, {"error": "daily_limit", "limit": PHOTO_DAILY_LIMIT,
                                      "message_vi": f"Hôm nay bạn đã gửi {PHOTO_DAILY_LIMIT} ảnh rồi. Mai gửi tiếp nha!",
                                      "message_en": f"You've sent {PHOTO_DAILY_LIMIT} photos today. Send more tomorrow!"})
        pid = insert_photo(s.store, elder_id, day, today, v.member_id, v.name, body.image, caption)
        p = _row(s.store.one("SELECT * FROM family_photo WHERE id=?", (pid,)))
        return {"ok": True, "photo": p, "remaining_today": PHOTO_DAILY_LIMIT - n - 1}

    @app.post("/api/elders/{elder_id}/photos/{pid}/heart")
    def heart_photo(request: Request, elder_id: str, pid: int):
        s, v = ctx(request, elder_id, "photo_heart")
        elder_only(v)
        if not s.store.one("SELECT 1 FROM family_photo WHERE elder_id=? AND id=?", (elder_id, pid)):
            raise HTTPException(404, "photo not found")
        s.store.x("UPDATE family_photo SET heart_at=COALESCE(heart_at, ?) WHERE elder_id=? AND id=?",
                  (now_iso(), elder_id, pid))
        return {"ok": True, "photo": _row(s.store.one("SELECT * FROM family_photo WHERE id=?", (pid,)))}

    @app.post("/api/elders/{elder_id}/together/heart")
    def heart_family(request: Request, elder_id: str):
        s, v = ctx(request, elder_id, "family_heart")
        elder_only(v)
        _, today = s.current_day(elder_id)
        if not summary(s, elder_id)["all_here"]:
            raise HTTPException(409, {"error": "not_everyone_yet",
                                      "message_vi": "Khi cả nhà đều ghé thăm trong ngày, trái tim mới hiện ra.",
                                      "message_en": "The heart appears once the whole family has dropped by today."})
        s.store.x("INSERT INTO family_moment(elder_id, date, heart_at) VALUES (?,?,?) ON CONFLICT(elder_id, date) "
                  "DO UPDATE SET heart_at=COALESCE(heart_at, excluded.heart_at)", (elder_id, today, now_iso()))
        return {"ok": True, "moment": moment(s.store, elder_id, today)}
