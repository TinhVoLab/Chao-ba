"""Elder standing-screen API (the 9:16 home display at /screen in the web app).

Small, additive endpoints the elder's own screen writes to. Every row is a *self-report* by the elder (a tap on the
screen); nothing here is scored, diagnostic, or fed into the control chart.

  GET  /api/elders/{id}/screen          ambient bundle: today's medication reminders with today's status, recent
                                        family messages (notes with to_elder), today's mood check-in, game plays today
  POST /api/elders/{id}/medication_log  {status: "taken"|"not_yet", medication?, time?}
  GET  /api/elders/{id}/medication_log?days=14
  POST /api/elders/{id}/mood_checkin    {mood: "happy"|"neutral"|"sad"}
  GET  /api/elders/{id}/mood_checkin?days=14
  POST /api/elders/{id}/game_plays      {game: "ca_dao"|"family_names", item_id, correct, choice?}
  GET  /api/elders/{id}/game_plays?days=14
  POST /api/elders/{id}/help            {pressed_at?}  the "Cần giúp / Help" button: a red alert for the family

The Help button is the one exception to "nothing here is scored": it raises a red ``help_button`` alert (needs a
human review like every red alert, care_review.py). The screen asks for confirmation with a 10-second countdown that
sends unless the elder taps "bấm nhầm", so a person who cannot tap again is still heard. Presses within
``HELP_DEDUP_MIN`` minutes of an open help alert return that alert instead of raising another.

The tables live in this module (created on first use, same SQLite file) so the shared schema in db.py is untouched.
POST /api/demo/reset also clears them (a middleware below), so a demo reset leaves no screen rows behind.
Register with ``register(app)`` from app.py.
"""
from __future__ import annotations

from typing import Literal
from urllib.parse import unquote

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

from .db import Store, now_iso

DDL = """
CREATE TABLE IF NOT EXISTS elder_med_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT, elder_id TEXT NOT NULL, day INTEGER, date TEXT NOT NULL,
  medication TEXT, sched_time TEXT, status TEXT NOT NULL, source TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS ix_med_log_elder ON elder_med_log(elder_id, date);
CREATE TABLE IF NOT EXISTS elder_mood_checkin (
  id INTEGER PRIMARY KEY AUTOINCREMENT, elder_id TEXT NOT NULL, day INTEGER, date TEXT NOT NULL,
  mood TEXT NOT NULL, source TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS ix_mood_checkin_elder ON elder_mood_checkin(elder_id, date);
CREATE TABLE IF NOT EXISTS elder_game_play (
  id INTEGER PRIMARY KEY AUTOINCREMENT, elder_id TEXT NOT NULL, day INTEGER, date TEXT NOT NULL,
  game TEXT NOT NULL, item_id TEXT, correct INTEGER NOT NULL, choice TEXT, created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS ix_game_play_elder ON elder_game_play(elder_id, date);
"""
TABLES = ("elder_med_log", "elder_mood_checkin", "elder_game_play")
MOOD_VI = {"happy": "vui", "neutral": "bình thường", "sad": "buồn"}
MOOD_EN = {"happy": "happy", "neutral": "okay", "sad": "sad"}
MESSAGE_DAYS = 7


class MedLogIn(BaseModel):
    status: Literal["taken", "not_yet"]
    medication: str | None = Field(default=None, max_length=120)
    time: str | None = Field(default=None, max_length=20)   # the scheduled time from the profile, e.g. "07:00"


HELP_DEDUP_MIN = 10


class HelpIn(BaseModel):
    pressed_at: str | None = Field(default=None, max_length=40)   # client time (an offline press is sent later)


class MoodIn(BaseModel):
    mood: Literal["happy", "neutral", "sad"]


class GamePlayIn(BaseModel):
    game: Literal["ca_dao", "family_names"]
    item_id: str = Field(max_length=60)
    correct: bool
    choice: str | None = Field(default=None, max_length=120)


def ensure_tables(store: Store) -> None:
    if getattr(store, "_elder_ui_ready", False):
        return
    with store.lock:
        store.conn.executescript(DDL)
        store.conn.commit()
    store._elder_ui_ready = True


def clear(store: Store, elder_id: str | None = None) -> None:
    ensure_tables(store)
    with store.lock:
        for t in TABLES:
            if elder_id is None:
                store.conn.execute(f"DELETE FROM {t}")
            else:
                store.conn.execute(f"DELETE FROM {t} WHERE elder_id=?", (elder_id,))
        store.conn.commit()


def _since(date_iso: str, days: int) -> str:
    from datetime import date as Date, timedelta
    return (Date.fromisoformat(date_iso) - timedelta(days=max(1, min(int(days), 365)) - 1)).isoformat()


def _rows(store: Store, table: str, elder_id: str, since: str) -> list[dict]:
    return [dict(r) for r in store.q(f"SELECT * FROM {table} WHERE elder_id=? AND date>=? ORDER BY id", (elder_id, since))]


def _med(r: dict) -> dict:
    return {"id": r["id"], "day": r["day"], "date": r["date"], "medication": r["medication"], "time": r["sched_time"],
            "status": r["status"], "source": r["source"], "created_at": r["created_at"]}


def _mood(r: dict) -> dict:
    return {"id": r["id"], "day": r["day"], "date": r["date"], "mood": r["mood"], "label_vi": MOOD_VI[r["mood"]],
            "label_en": MOOD_EN[r["mood"]], "source": r["source"], "self_report": True, "created_at": r["created_at"]}


def _play(r: dict) -> dict:
    return {"id": r["id"], "day": r["day"], "date": r["date"], "game": r["game"], "item_id": r["item_id"],
            "correct": bool(r["correct"]), "choice": r["choice"], "created_at": r["created_at"]}


def _timed(time: str | None) -> bool:
    t = (time or "").strip()
    return len(t) in (4, 5) and ":" in t and t.replace(":", "").isdigit()


def medication_today(store: Store, elder_id: str, profile: dict, date: str) -> list[dict]:
    """Profile medications with today's latest status from the screen (None = not answered yet)."""
    logs = _rows(store, "elder_med_log", elder_id, date)
    out = []
    for m in profile.get("medications") or []:
        name, time = m.get("name"), m.get("time")
        mine = [r for r in logs if r["date"] == date and (r["medication"] in (None, name))]
        last = mine[-1] if mine else None
        out.append({"name": name, "time": time, "timed": _timed(time), "status": last["status"] if last else None,
                    "answered_at": last["created_at"] if last else None})
    return out


def register(app: FastAPI) -> None:
    def svc(request: Request):
        return request.app.state.svc

    def guard(request: Request, elder_id: str, action: str):
        s = svc(request)
        if not s.elder_or_none(elder_id):
            raise HTTPException(404, f"unknown elder {elder_id}")
        ensure_tables(s.store)
        s.store.log_access(elder_id, unquote(request.headers.get("x-actor", f"elder:{elder_id}"))[:80],
                           unquote(request.headers.get("x-role", "elder_self"))[:40], action, str(request.url.path))
        return s

    def source(request: Request) -> str:
        return "elder_screen" if unquote(request.headers.get("x-role", "elder_self")) in ("elder_self", "elder") \
            else "family_app"

    @app.middleware("http")
    async def _clear_on_demo_reset(request: Request, call_next):
        response = await call_next(request)
        if request.method == "POST" and request.url.path == "/api/demo/reset" and response.status_code == 200:
            clear(request.app.state.svc.store, request.query_params.get("elder") or None)
        return response

    @app.get("/api/elders/{elder_id}/screen")
    def screen(request: Request, elder_id: str):
        s = guard(request, elder_id, "read_screen")
        prof = s.elder_or_none(elder_id)
        day, date = s.current_day(elder_id)
        since = _since(date, MESSAGE_DAYS)
        msgs = [n for n in s.store.notes(elder_id) if n.get("to_elder") and (n.get("date") or date) >= since]
        moods = _rows(s.store, "elder_mood_checkin", elder_id, date)
        plays = _rows(s.store, "elder_game_play", elder_id, date)
        return {"elder_id": elder_id, "day": day, "date": date,
                "medications": medication_today(s.store, elder_id, prof, date),
                "messages": sorted(msgs, key=lambda n: (n.get("day") or 0, n.get("id") or 0), reverse=True)[:3],
                "mood_today": _mood(moods[-1]) if moods else None,
                "game_plays_today": len(plays),
                "opted_out": bool(prof.get("opted_out")),
                "simulated": s.is_simulated(elder_id)}

    @app.post("/api/elders/{elder_id}/medication_log")
    def add_med(request: Request, elder_id: str, body: MedLogIn):
        s = guard(request, elder_id, "log_medication")
        prof = s.elder_or_none(elder_id)
        meds = prof.get("medications") or []
        name = body.medication or (meds[0].get("name") if meds else None)
        time = body.time or next((m.get("time") for m in meds if m.get("name") == name), None)
        day, date = s.current_day(elder_id)
        rid = s.store.x("INSERT INTO elder_med_log(elder_id, day, date, medication, sched_time, status, source, "
                        "created_at) VALUES (?,?,?,?,?,?,?,?)",
                        (elder_id, day, date, name, time, body.status, source(request), now_iso()))
        row = dict(s.store.one("SELECT * FROM elder_med_log WHERE id=?", (rid,)))
        return {"ok": True, **_med(row), "today": medication_today(s.store, elder_id, prof, date)}

    @app.get("/api/elders/{elder_id}/medication_log")
    def get_med(request: Request, elder_id: str, days: int = 14):
        s = guard(request, elder_id, "read_medication")
        prof = s.elder_or_none(elder_id)
        _, date = s.current_day(elder_id)
        return {"entries": [_med(r) for r in _rows(s.store, "elder_med_log", elder_id, _since(date, days))],
                "today": medication_today(s.store, elder_id, prof, date), "date": date,
                "simulated": s.is_simulated(elder_id)}

    @app.post("/api/elders/{elder_id}/mood_checkin")
    def add_mood(request: Request, elder_id: str, body: MoodIn):
        s = guard(request, elder_id, "mood_checkin")
        day, date = s.current_day(elder_id)
        rid = s.store.x("INSERT INTO elder_mood_checkin(elder_id, day, date, mood, source, created_at) "
                        "VALUES (?,?,?,?,?,?)", (elder_id, day, date, body.mood, source(request), now_iso()))
        return {"ok": True, **_mood(dict(s.store.one("SELECT * FROM elder_mood_checkin WHERE id=?", (rid,))))}

    @app.get("/api/elders/{elder_id}/mood_checkin")
    def get_mood(request: Request, elder_id: str, days: int = 14):
        s = guard(request, elder_id, "read_mood_checkin")
        _, date = s.current_day(elder_id)
        rows = [_mood(r) for r in _rows(s.store, "elder_mood_checkin", elder_id, _since(date, days))]
        today = [r for r in rows if r["date"] == date]
        return {"entries": rows, "today": today[-1] if today else None, "date": date,
                "note_en": "Self-report from the elder's screen; not a clinical measure.",
                "note_vi": "Người cao tuổi tự chọn trên màn hình; không phải đánh giá y khoa.",
                "simulated": s.is_simulated(elder_id)}

    @app.post("/api/elders/{elder_id}/help")
    def press_help(request: Request, elder_id: str, body: HelpIn | None = None):
        from datetime import datetime, timedelta, timezone
        s = guard(request, elder_id, "help_button")
        prof = s.elder_or_none(elder_id)
        day, date = s.current_day(elder_id)
        now = datetime.now(timezone.utc)
        try:
            pressed = datetime.fromisoformat((body.pressed_at if body else None) or "")
            pressed = pressed if pressed.tzinfo and pressed <= now + timedelta(minutes=1) else now
        except ValueError:
            pressed = now
        since = (now - timedelta(minutes=HELP_DEDUP_MIN)).isoformat(timespec="seconds")
        dup = s.store.one("SELECT id FROM alert WHERE elder_id=? AND type='help_button' AND created_at>=? "
                          "AND acknowledged=0 ORDER BY id DESC LIMIT 1", (elder_id, since))
        if dup:
            return {"ok": True, "alert_id": dup["id"], "duplicate": True}
        hm = pressed.astimezone().strftime("%H:%M")
        name = prof.get("display_name", "")
        h = prof.get("honorific", "bà")
        vi = (f"{name[:1].upper() + name[1:]} bấm nút “Cần giúp” trên màn hình lúc {hm}. Xin gia đình gọi cho {h} "
              f"ngay. Nếu không ai liên lạc được, nhờ hàng xóm hoặc gọi 115.")
        en = (f"{prof.get('name_en', name)} pressed the Help button on the screen at {hm}. Please call now. If nobody "
              f"can reach them, ask a neighbour or call 115.")
        aid = s.store.add_alert(elder_id, day, date, "help_button", "red", vi, en)
        return {"ok": True, "alert_id": aid, "duplicate": False}

    @app.post("/api/elders/{elder_id}/game_plays")
    def add_play(request: Request, elder_id: str, body: GamePlayIn):
        s = guard(request, elder_id, "game_play")
        day, date = s.current_day(elder_id)
        rid = s.store.x("INSERT INTO elder_game_play(elder_id, day, date, game, item_id, correct, choice, created_at) "
                        "VALUES (?,?,?,?,?,?,?,?)", (elder_id, day, date, body.game, body.item_id,
                                                     1 if body.correct else 0, body.choice, now_iso()))
        return {"ok": True, **_play(dict(s.store.one("SELECT * FROM elder_game_play WHERE id=?", (rid,))))}

    @app.get("/api/elders/{elder_id}/game_plays")
    def get_plays(request: Request, elder_id: str, days: int = 14):
        s = guard(request, elder_id, "read_game_plays")
        _, date = s.current_day(elder_id)
        rows = [_play(r) for r in _rows(s.store, "elder_game_play", elder_id, _since(date, days))]
        return {"plays": rows, "today": sum(1 for r in rows if r["date"] == date),
                "days_played": len({r["date"] for r in rows}), "date": date, "simulated": s.is_simulated(elder_id)}
