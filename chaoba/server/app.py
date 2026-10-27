"""FastAPI app: `uvicorn chaoba.server.app:app --port 8000`.

Implements the REST API in CONTRACT.md plus the static elder web-call page at /call?elder=hanh.
Family reads are written to access_log (actor from the `X-Actor` header, role from `X-Role`; defaults
"family:primary"/"primary" because the prototype has no auth - production uses Supabase Auth + RLS, see schema.sql).
Reads are de-duplicated to one row per actor / action / resource / day (with a counter); writes always get a row.

Environment:
  CHAOBA_DB            SQLite path (default data/runtime/chaoba.db)
  CHAOBA_END_DATE      pin the seeded calendar (day 90 = this date; default yesterday)
  CHAOBA_CORS_ORIGINS  comma-separated allowed origins (e.g. "https://app.chaoba.vn"). Unset: any http(s) origin on
                       localhost / 127.0.0.1 / [::1], any port (development).
  CHAOBA_DEMO          "1" (default) enables demo-only endpoints (POST /api/demo/reset); set "0" in production.
  CHAOBA_VOICE_ENGINE  "browser" (default) | "gemini": default voice engine of web calls (Gemini Live only when
                       credentials exist: GEMINI_API_KEY, or GOOGLE_GENAI_USE_VERTEXAI=true + GOOGLE_CLOUD_PROJECT);
                       see chaoba/agent/gemini_live.py for CHAOBA_GEMINI_* settings.
"""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import unquote

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .db import Store
from .family import register as register_family, seed_all as seed_family
from .community import register as register_community
from .service import Service, llm_enabled, demo_enabled
from . import memories as memory_book   # Sổ ký ức + prevention activities (memories.py)
from . import kudos                     # "Gửi yêu thương": family micro-interactions (kudos.py)
from chaoba.agent import gemini_live
from . import voice as voice_mod        # optional Gemini Live voice engine: /ws/voice/{call_id} (voice.py)

LOCALHOST_ORIGIN_RE = r"^https?://(localhost|127\.0\.0\.1|\[::1\])(:\d+)?$"


def cors_settings() -> dict:
    """CORSMiddleware kwargs from CHAOBA_CORS_ORIGINS (comma list); default = localhost on any port (dev)."""
    env = os.environ.get("CHAOBA_CORS_ORIGINS", "").strip()
    if env:
        return {"allow_origins": [o.strip().rstrip("/") for o in env.split(",") if o.strip()]}
    return {"allow_origins": [], "allow_origin_regex": LOCALHOST_ORIGIN_RE}

log = logging.getLogger("chaoba.server")
STATIC = Path(__file__).parent / "static"


class CallStart(BaseModel):
    elder_id: str
    channel: str = "web"
    simulated: bool = False  # true when the elder side is scripted (demo sim mode)
    engine: str | None = None  # voice engine: "gemini" | "browser" (default: CHAOBA_VOICE_ENGINE, else "browser")


class TurnIn(BaseModel):
    text: str = ""
    start: float | None = None
    end: float | None = None
    pauses: list[float] = Field(default_factory=list)


class ContactIn(BaseModel):
    kind: str = "call"                 # call | visit | message
    member_id: str | None = None       # family member id from the profile (e.g. "lan")
    member_name: str | None = None
    duration_min: int | None = None


class ConsentChangeIn(BaseModel):
    # The consent belongs to the elder. A family member asking to withdraw it must state that the elder (or their
    # legal proxy) confirmed the request; `requested_by` defaults to the X-Actor header.
    confirmed_by_elder_or_proxy: bool = False
    requested_by: str | None = None
    reason: str | None = None


class NoteIn(BaseModel):
    author: str
    text: str
    to_elder: bool = False   # extension: message to be read to the elder at the end of the next call


def create_app(db_path: str | None = None, seed: bool = True) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        store = Store(db_path)
        svc = Service(store)
        memory_book.install(svc)   # life-story question / game / nudge in calls; story + activity log at call end
        kudos.install(svc)         # relay family cards in calls; micro-contact counts (never counted as calls)
        if seed:
            svc.seed()
            seed_family(svc)   # simulated care circles, rota, tasks (family.py)
            memory_book.seed_all(svc)   # simulated stories + activity log
            kudos.seed_all(svc)         # simulated family cards + replies (one advice answer saved as "Lời má dạy")
        app.state.svc = svc
        yield
        store.close()

    app = FastAPI(title="Chào Bà API", version="0.1.0", lifespan=lifespan)
    app.add_middleware(CORSMiddleware, allow_methods=["*"], allow_headers=["*"], **cors_settings())
    app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")

    def svc(request: Request) -> Service:
        return request.app.state.svc

    def actor(request: Request) -> str:
        # HTTP headers are ASCII: the app percent-encodes Vietnamese names ("Th%E1%BA%A3o" -> "Thảo").
        return unquote(request.headers.get("x-actor", "family:primary"))[:80]

    def role(request: Request) -> str:
        return unquote(request.headers.get("x-role", "primary"))[:40]

    def elder_guard(request: Request, elder_id: str, action: str) -> Service:
        s = svc(request)
        if not s.elder_or_none(elder_id):
            raise HTTPException(404, f"unknown elder {elder_id}")
        s.store.log_access(elder_id, actor(request), unquote(request.headers.get("x-role", "primary"))[:40], action,
                           str(request.url.path))
        return s

    @app.get("/")
    def root():
        return RedirectResponse("/call?elder=hanh")

    @app.get("/api/health")
    def health():
        return {"ok": True, "llm": "claude" if llm_enabled() else "fallback",
                "voice": gemini_live.public_voice_config()["default_engine"]}

    @app.get("/api/elders")
    def elders(request: Request):
        return svc(request).list_elders()

    @app.get("/api/elders/{elder_id}")
    def elder(request: Request, elder_id: str):
        s = elder_guard(request, elder_id, "read_profile")
        p = s.elder_or_none(elder_id)
        return p | {"simulated": s.is_simulated(elder_id)}

    @app.get("/api/elders/{elder_id}/today")
    def today(request: Request, elder_id: str):
        return elder_guard(request, elder_id, "read_today").today(elder_id)

    @app.get("/api/elders/{elder_id}/timeline")
    def timeline(request: Request, elder_id: str, days: int = 90):
        return elder_guard(request, elder_id, "read_timeline").timeline(elder_id, days)

    @app.get("/api/elders/{elder_id}/alerts")
    def alerts(request: Request, elder_id: str):
        s = elder_guard(request, elder_id, "read_alerts")
        return [] if s.sharing_paused(elder_id) else s.store.alerts(elder_id)

    @app.post("/api/elders/{elder_id}/alerts/{alert_id}/ack")
    def ack(request: Request, elder_id: str, alert_id: int):
        s = elder_guard(request, elder_id, "ack_alert")
        if not s.store.ack_alert(elder_id, alert_id, actor(request)):
            raise HTTPException(404, "alert not found")
        return {"ok": True, "id": alert_id, "acknowledged": True}

    @app.get("/api/elders/{elder_id}/dmaic")
    def dmaic(request: Request, elder_id: str):
        return elder_guard(request, elder_id, "read_dmaic").dmaic(elder_id)

    @app.get("/api/elders/{elder_id}/notes")
    def notes(request: Request, elder_id: str):
        return elder_guard(request, elder_id, "read_notes").store.notes(elder_id)

    @app.post("/api/elders/{elder_id}/notes")
    def add_note(request: Request, elder_id: str, note: NoteIn):
        s = elder_guard(request, elder_id, "write_note")
        if not note.text.strip():
            raise HTTPException(422, "empty note")
        day, date = s.current_day(elder_id)
        nid = s.store.add_note(elder_id, note.author, note.text.strip(), day, to_elder=note.to_elder)
        return {"id": nid, "ok": True, "day": day, "date": date, "author": note.author, "text": note.text.strip(),
                "to_elder": note.to_elder}

    @app.get("/api/elders/{elder_id}/contacts")
    def contacts(request: Request, elder_id: str, days: int = 90):
        return elder_guard(request, elder_id, "read_contacts").contacts(elder_id, days)

    @app.post("/api/elders/{elder_id}/contacts")
    def add_contact(request: Request, elder_id: str, body: ContactIn):
        """Family logs a call/visit (the app's "Gọi má" button posts kind=call)."""
        from .service import CONTACT_KINDS
        s = elder_guard(request, elder_id, "log_contact")
        if body.kind not in CONTACT_KINDS:
            raise HTTPException(422, f"kind must be one of {CONTACT_KINDS}")
        return s.log_contact(elder_id, body.member_id, body.member_name, body.kind, body.duration_min)

    @app.post("/api/elders/{elder_id}/consents/{kind}/withdraw")
    def withdraw_consent(request: Request, elder_id: str, kind: str, body: ConsentChangeIn | None = None):
        """Withdraw one consent purpose; processing for it stops (daily_call also pauses scheduling, like opt-out).

        The consent is the elder's: unless the caller is the elder (X-Role: elder_self), the body must carry
        `confirmed_by_elder_or_proxy: true` (else 400). `requested_by` (default: X-Actor) is recorded."""
        from .service import CONSENT_KINDS
        if kind not in CONSENT_KINDS:
            raise HTTPException(404, f"unknown consent type {kind}")
        body = body or ConsentChangeIn()
        r = role(request)
        if r not in ("elder_self", "elder") and not body.confirmed_by_elder_or_proxy:
            raise HTTPException(400, {
                "error": "confirmation_required",
                "field": "confirmed_by_elder_or_proxy",
                "message_en": ("This consent belongs to the elder. A family member can withdraw it only after the elder "
                               "(or their legal proxy) has confirmed. Send {\"confirmed_by_elder_or_proxy\": true}."),
                "message_vi": ("Đây là sự đồng ý của người cao tuổi. Người nhà chỉ rút được sau khi chính người cao tuổi "
                               "(hoặc người đại diện hợp pháp) đã xác nhận."),
            })
        s = elder_guard(request, elder_id, "withdraw_consent")
        return s.set_consent(elder_id, kind, False, actor(request), requested_by=body.requested_by or actor(request),
                             confirmed_by_elder_or_proxy=bool(body.confirmed_by_elder_or_proxy) or r in ("elder_self", "elder"),
                             role=r, reason=body.reason)

    @app.post("/api/elders/{elder_id}/consents/{kind}/grant")
    def grant_consent(request: Request, elder_id: str, kind: str):
        """Re-grant a withdrawn purpose (for daily_call this is the same as POST /resume)."""
        from .service import CONSENT_KINDS
        if kind not in CONSENT_KINDS:
            raise HTTPException(404, f"unknown consent type {kind}")
        s = elder_guard(request, elder_id, "grant_consent")
        return s.set_consent(elder_id, kind, True, actor(request), requested_by=actor(request), role=role(request))

    @app.get("/api/elders/{elder_id}/privacy")
    def privacy(request: Request, elder_id: str):
        return elder_guard(request, elder_id, "read_privacy").privacy(elder_id)

    @app.post("/api/elders/{elder_id}/resume")
    def resume(request: Request, elder_id: str):
        """Extension: re-enable daily calls after an opt-out (recorded as a new consent row)."""
        s = elder_guard(request, elder_id, "resume_calls")
        s.store.set_opt_out(elder_id, False, by=actor(request))
        return {"ok": True, "scheduling_active": True}

    @app.post("/api/demo/reset")
    def demo_reset(request: Request, elder: str | None = None):
        """Demo only (CHAOBA_DEMO=1, the default): delete live calls, notes, alerts and contacts and re-seed the
        simulated personas (all, or one with ?elder=hanh). 403 when CHAOBA_DEMO=0."""
        if not demo_enabled():
            raise HTTPException(403, "demo endpoints are disabled (CHAOBA_DEMO=0)")
        s = svc(request)
        if elder and elder not in ("hanh", "tu", "control") and not s.elder_or_none(elder):
            raise HTTPException(404, f"unknown elder {elder}")
        out = s.reset(elder)
        seed_family(s)
        memory_book.seed_all(s)
        kudos.seed_all(s)
        return out

    @app.get("/api/evaluation")
    def evaluation(request: Request):
        return svc(request).evaluation()

    @app.post("/api/calls")
    def start_call(request: Request, body: CallStart):
        s = svc(request)
        p = s.elder_or_none(body.elder_id)
        if not p:
            raise HTTPException(404, f"unknown elder {body.elder_id}")
        if p.get("opted_out"):
            raise HTTPException(409, "elder opted out of daily calls (POST /api/elders/{id}/resume to re-enable)")
        return s.start_call(body.elder_id, body.channel, body.simulated, body.engine)

    @app.post("/api/calls/{call_id}/turns")
    def turn(request: Request, call_id: str, body: TurnIn):
        try:
            return svc(request).turn(call_id, body.text, body.start, body.end, body.pauses)
        except KeyError:
            raise HTTPException(404, "unknown or finished call")

    @app.get("/api/calls/{call_id}/simulate")
    def simulate(request: Request, call_id: str):
        """Extension (demo only): next scripted elder line, so the web call can run hands-free."""
        try:
            return svc(request).simulate_elder(call_id)
        except KeyError:
            raise HTTPException(404, "unknown or finished call")

    @app.post("/api/calls/{call_id}/end")
    def end(request: Request, call_id: str):
        try:
            return svc(request).end_call(call_id)
        except KeyError:
            raise HTTPException(404, "unknown call")

    @app.get("/call")
    def call_page():
        return FileResponse(STATIC / "call.html", media_type="text/html")

    from .elder_ui import register as register_elder_ui   # elder standing-screen endpoints (/screen in the web app)
    register_elder_ui(app)
    register_family(app)      # /api/elders/{id}/family/* (family.py)
    register_community(app)   # /api/community/* (community.py)
    memory_book.register(app)   # /api/elders/{id}/memories*, /activities (memories.py)
    kudos.register(app)         # /api/elders/{id}/kudos* (kudos.py)
    voice_mod.register(app)     # /api/voice/config, WebSocket /ws/voice/{call_id} (voice.py, gemini_live.py)
    return app


app = create_app(os.environ.get("CHAOBA_DB"))
