"""FastAPI app: `uvicorn chaoba.server.app:app --port 8000`.

Implements the REST API in CONTRACT.md plus the static elder web-call page at /call?elder=hanh.
Family reads are written to access_log (actor from the `X-Actor` header, role from `X-Role`; defaults
"family:primary"/"primary" because the prototype has no auth - production uses Supabase Auth + RLS, see schema.sql).
"""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .db import Store
from .service import Service, llm_enabled

log = logging.getLogger("chaoba.server")
STATIC = Path(__file__).parent / "static"


class CallStart(BaseModel):
    elder_id: str
    channel: str = "web"
    simulated: bool = False  # true when the elder side is scripted (demo sim mode)


class TurnIn(BaseModel):
    text: str = ""
    start: float | None = None
    end: float | None = None
    pauses: list[float] = Field(default_factory=list)


class NoteIn(BaseModel):
    author: str
    text: str
    to_elder: bool = False   # extension: message to be read to the elder at the end of the next call


def create_app(db_path: str | None = None, seed: bool = True) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        store = Store(db_path)
        svc = Service(store)
        if seed:
            svc.seed()
        app.state.svc = svc
        yield
        store.close()

    app = FastAPI(title="Chào Bà API", version="0.1.0", lifespan=lifespan)
    app.add_middleware(CORSMiddleware,
                       allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
                       allow_methods=["*"], allow_headers=["*"])
    app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")

    def svc(request: Request) -> Service:
        return request.app.state.svc

    def elder_guard(request: Request, elder_id: str, action: str) -> Service:
        s = svc(request)
        if not s.elder_or_none(elder_id):
            raise HTTPException(404, f"unknown elder {elder_id}")
        s.store.log_access(elder_id, request.headers.get("x-actor", "family:primary"),
                           request.headers.get("x-role", "primary"), action, str(request.url.path))
        return s

    @app.get("/")
    def root():
        return RedirectResponse("/call?elder=hanh")

    @app.get("/api/health")
    def health():
        return {"ok": True, "llm": "claude" if llm_enabled() else "fallback"}

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
        return elder_guard(request, elder_id, "read_alerts").store.alerts(elder_id)

    @app.post("/api/elders/{elder_id}/alerts/{alert_id}/ack")
    def ack(request: Request, elder_id: str, alert_id: int):
        s = elder_guard(request, elder_id, "ack_alert")
        if not s.store.ack_alert(elder_id, alert_id, request.headers.get("x-actor", "family:primary")):
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
        recs = s.store.records(elder_id)
        nid = s.store.add_note(elder_id, note.author, note.text.strip(), recs[-1]["day"] if recs else None,
                               to_elder=note.to_elder)
        return {"id": nid, "ok": True}

    @app.get("/api/elders/{elder_id}/privacy")
    def privacy(request: Request, elder_id: str):
        return elder_guard(request, elder_id, "read_privacy").privacy(elder_id)

    @app.post("/api/elders/{elder_id}/resume")
    def resume(request: Request, elder_id: str):
        """Extension: re-enable daily calls after an opt-out (recorded as a new consent row)."""
        s = elder_guard(request, elder_id, "resume_calls")
        s.store.set_opt_out(elder_id, False, by=request.headers.get("x-actor", "family:primary"))
        return {"ok": True, "scheduling_active": True}

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
        return s.start_call(body.elder_id, body.channel, body.simulated)

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

    return app


app = create_app(os.environ.get("CHAOBA_DB"))
