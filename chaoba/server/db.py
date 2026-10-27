"""SQLite store for the prototype (data/runtime/chaoba.db, created on startup).

Mirrors the production Postgres/Supabase schema in schema.sql (same table names). Structured blobs are stored as
JSON text. There is no audio column anywhere: the browser only sends text + VAD timings, and transcripts carry
an expiry (7 days) and are purged on startup and after every call.
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB = ROOT / "data" / "runtime" / "chaoba.db"
TRANSCRIPT_DAYS = 7

DDL = """
CREATE TABLE IF NOT EXISTS elder (
  id TEXT PRIMARY KEY, profile_json TEXT NOT NULL, simulated INTEGER NOT NULL DEFAULT 1,
  opted_out INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS family_member (
  elder_id TEXT NOT NULL, id TEXT NOT NULL, name TEXT, relation TEXT, role TEXT,
  PRIMARY KEY (elder_id, id));
CREATE TABLE IF NOT EXISTS consent (
  id INTEGER PRIMARY KEY AUTOINCREMENT, elder_id TEXT NOT NULL, kind TEXT NOT NULL, granted INTEGER NOT NULL,
  granted_by TEXT, note TEXT, detail_json TEXT, ts TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS call_session (
  id TEXT PRIMARY KEY, elder_id TEXT NOT NULL, channel TEXT NOT NULL, day INTEGER, started_at TEXT NOT NULL,
  ended_at TEXT, status TEXT NOT NULL, end_reason TEXT, emergency INTEGER NOT NULL DEFAULT 0,
  prompt_version TEXT, engine TEXT, transcript_json TEXT, transcript_expires_at TEXT,
  simulated INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS call_analysis (
  call_id TEXT PRIMARY KEY, elder_id TEXT NOT NULL, day INTEGER, analysis_json TEXT NOT NULL,
  metrics_json TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS memory_fact (
  id INTEGER PRIMARY KEY AUTOINCREMENT, elder_id TEXT NOT NULL, day INTEGER, fact_vi TEXT NOT NULL,
  question_vi TEXT, cue_vi TEXT, keywords_json TEXT, source TEXT, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS metric_daily (
  elder_id TEXT NOT NULL, day INTEGER NOT NULL, date TEXT NOT NULL, record_json TEXT NOT NULL,
  simulated INTEGER NOT NULL DEFAULT 1, PRIMARY KEY (elder_id, day));
CREATE TABLE IF NOT EXISTS baseline (
  elder_id TEXT NOT NULL, metric TEXT NOT NULL, center REAL, scale REAL, updated_at TEXT,
  PRIMARY KEY (elder_id, metric));
CREATE TABLE IF NOT EXISTS daily_light (
  elder_id TEXT NOT NULL, day INTEGER NOT NULL, date TEXT NOT NULL, light TEXT NOT NULL, light_json TEXT NOT NULL,
  PRIMARY KEY (elder_id, day));
CREATE TABLE IF NOT EXISTS alert (
  id INTEGER PRIMARY KEY AUTOINCREMENT, elder_id TEXT NOT NULL, day INTEGER, date TEXT, type TEXT NOT NULL,
  severity TEXT NOT NULL, explanation_vi TEXT, explanation_en TEXT, acknowledged INTEGER NOT NULL DEFAULT 0,
  acknowledged_by TEXT, call_id TEXT, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS dmaic_cycle (
  elder_id TEXT PRIMARY KEY, define_json TEXT, intervention_day INTEGER, rebaseline_days_json TEXT,
  seed_json TEXT, updated_at TEXT);
CREATE TABLE IF NOT EXISTS family_note (
  id INTEGER PRIMARY KEY AUTOINCREMENT, elder_id TEXT NOT NULL, day INTEGER, author TEXT NOT NULL,
  text TEXT NOT NULL, to_elder INTEGER NOT NULL DEFAULT 0, simulated INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS access_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT, elder_id TEXT, actor TEXT NOT NULL, role TEXT, action TEXT NOT NULL,
  resource TEXT, ts TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS care_event (
  id INTEGER PRIMARY KEY AUTOINCREMENT, elder_id TEXT NOT NULL, day INTEGER NOT NULL, type TEXT NOT NULL,
  label_vi TEXT, label_en TEXT);
CREATE INDEX IF NOT EXISTS ix_alert_elder ON alert(elder_id, day);
CREATE INDEX IF NOT EXISTS ix_access_elder ON access_log(elder_id, ts);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Store:
    def __init__(self, path: str | os.PathLike | None = None):
        self.path = Path(path or os.environ.get("CHAOBA_DB") or DEFAULT_DB)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        with self.lock:
            self.conn.executescript(DDL)
            self.conn.commit()

    # ---------------------------------------------------------------- low level
    def q(self, sql: str, args: tuple = ()) -> list[sqlite3.Row]:
        with self.lock:
            return list(self.conn.execute(sql, args).fetchall())

    def one(self, sql: str, args: tuple = ()) -> sqlite3.Row | None:
        rows = self.q(sql, args)
        return rows[0] if rows else None

    def x(self, sql: str, args: tuple = ()) -> int:
        with self.lock:
            cur = self.conn.execute(sql, args)
            self.conn.commit()
            return cur.lastrowid

    def xmany(self, sql: str, rows: list[tuple]) -> None:
        with self.lock:
            self.conn.executemany(sql, rows)
            self.conn.commit()

    def close(self) -> None:
        with self.lock:
            self.conn.close()

    # ---------------------------------------------------------------- elders
    def elder_ids(self) -> list[str]:
        return [r["id"] for r in self.q("SELECT id FROM elder ORDER BY created_at, id")]

    def elder(self, elder_id: str) -> dict | None:
        r = self.one("SELECT * FROM elder WHERE id=?", (elder_id,))
        if not r:
            return None
        p = json.loads(r["profile_json"])
        p["opted_out"] = bool(r["opted_out"])
        p["simulated"] = bool(r["simulated"])
        return p

    def set_opt_out(self, elder_id: str, opted_out: bool, by: str = "elder") -> None:
        self.x("UPDATE elder SET opted_out=? WHERE id=?", (1 if opted_out else 0, elder_id))
        self.add_consent(elder_id, "daily_call", not opted_out, by,
                         "opt-out during call; scheduling stopped" if opted_out else "daily calls resumed")

    # ---------------------------------------------------------------- records / lights
    def records(self, elder_id: str) -> list[dict]:
        return [json.loads(r["record_json"]) for r in
                self.q("SELECT record_json FROM metric_daily WHERE elder_id=? ORDER BY day", (elder_id,))]

    def upsert_record(self, rec: dict) -> None:
        self.x("INSERT OR REPLACE INTO metric_daily(elder_id, day, date, record_json, simulated) VALUES (?,?,?,?,?)",
               (rec["elder_id"], rec["day"], rec["date"], json.dumps(rec, ensure_ascii=False),
                1 if rec.get("simulated", True) else 0))

    def lights(self, elder_id: str) -> list[dict]:
        return [json.loads(r["light_json"]) for r in
                self.q("SELECT light_json FROM daily_light WHERE elder_id=? ORDER BY day", (elder_id,))]

    def replace_lights(self, elder_id: str, lights: list[dict]) -> None:
        with self.lock:
            self.conn.execute("DELETE FROM daily_light WHERE elder_id=?", (elder_id,))
            self.conn.executemany(
                "INSERT INTO daily_light(elder_id, day, date, light, light_json) VALUES (?,?,?,?,?)",
                [(elder_id, l["day"], l["date"], l["light"], json.dumps(l, ensure_ascii=False)) for l in lights])
            self.conn.commit()

    def set_baseline(self, elder_id: str, base: dict) -> None:
        with self.lock:
            self.conn.execute("DELETE FROM baseline WHERE elder_id=?", (elder_id,))
            self.conn.executemany(
                "INSERT INTO baseline(elder_id, metric, center, scale, updated_at) VALUES (?,?,?,?,?)",
                [(elder_id, m, v.get("center"), v.get("scale"), now_iso()) for m, v in base.items()])
            self.conn.commit()

    def baseline(self, elder_id: str) -> dict:
        return {r["metric"]: {"center": r["center"], "scale": r["scale"]}
                for r in self.q("SELECT * FROM baseline WHERE elder_id=?", (elder_id,))}

    # ---------------------------------------------------------------- alerts
    def add_alert(self, elder_id: str, day: int, date: str, type_: str, severity: str, vi: str, en: str,
                  call_id: str | None = None) -> int:
        return self.x("INSERT INTO alert(elder_id, day, date, type, severity, explanation_vi, explanation_en, "
                      "acknowledged, call_id, created_at) VALUES (?,?,?,?,?,?,?,0,?,?)",
                      (elder_id, day, date, type_, severity, vi, en, call_id, now_iso()))

    def alerts(self, elder_id: str) -> list[dict]:
        return [{"id": r["id"], "day": r["day"], "date": r["date"], "type": r["type"], "severity": r["severity"],
                 "explanation_vi": r["explanation_vi"], "explanation_en": r["explanation_en"],
                 "acknowledged": bool(r["acknowledged"])}
                for r in self.q("SELECT * FROM alert WHERE elder_id=? ORDER BY day DESC, id DESC", (elder_id,))]

    def ack_alert(self, elder_id: str, alert_id: int, by: str) -> bool:
        r = self.one("SELECT id FROM alert WHERE elder_id=? AND id=?", (elder_id, alert_id))
        if not r:
            return False
        self.x("UPDATE alert SET acknowledged=1, acknowledged_by=? WHERE id=?", (by, alert_id))
        return True

    # ---------------------------------------------------------------- notes / log / events
    def notes(self, elder_id: str) -> list[dict]:
        return [{"id": r["id"], "day": r["day"], "author": r["author"], "text": r["text"],
                 "to_elder": bool(r["to_elder"]), "simulated": bool(r["simulated"]), "created_at": r["created_at"]}
                for r in self.q("SELECT * FROM family_note WHERE elder_id=? ORDER BY id DESC", (elder_id,))]

    def add_note(self, elder_id: str, author: str, text: str, day: int | None, to_elder: bool = False,
                 simulated: bool = False) -> int:
        return self.x("INSERT INTO family_note(elder_id, day, author, text, to_elder, simulated, created_at) "
                      "VALUES (?,?,?,?,?,?,?)", (elder_id, day, author, text, 1 if to_elder else 0,
                                                1 if simulated else 0, now_iso()))

    def log_access(self, elder_id: str | None, actor: str, role: str, action: str, resource: str) -> None:
        self.x("INSERT INTO access_log(elder_id, actor, role, action, resource, ts) VALUES (?,?,?,?,?,?)",
               (elder_id, actor, role, action, resource, now_iso()))

    def access_log(self, elder_id: str, limit: int = 50) -> list[dict]:
        return [dict(r) for r in self.q("SELECT actor, role, action, resource, ts FROM access_log WHERE elder_id=? "
                                         "ORDER BY id DESC LIMIT ?", (elder_id, limit))]

    def add_consent(self, elder_id: str, kind: str, granted: bool, by: str | None, note: str | None = None,
                    detail: dict | None = None, ts: str | None = None) -> None:
        self.x("INSERT INTO consent(elder_id, kind, granted, granted_by, note, detail_json, ts) VALUES (?,?,?,?,?,?,?)",
               (elder_id, kind, 1 if granted else 0, by, note, json.dumps(detail or {}, ensure_ascii=False),
                ts or now_iso()))

    def consents(self, elder_id: str) -> list[dict]:
        out = []
        for r in self.q("SELECT * FROM consent WHERE elder_id=? ORDER BY id", (elder_id,)):
            d = json.loads(r["detail_json"] or "{}")
            d.update({"kind": r["kind"], "type": r["kind"], "granted": bool(r["granted"]), "granted_by": r["granted_by"],
                      "note": r["note"], "ts": r["ts"]})
            out.append(d)
        return out

    def events(self, elder_id: str) -> list[dict]:
        return [{"day": r["day"], "type": r["type"], "label_vi": r["label_vi"], "label_en": r["label_en"]}
                for r in self.q("SELECT * FROM care_event WHERE elder_id=? ORDER BY day, id", (elder_id,))]

    def add_event(self, elder_id: str, day: int, type_: str, vi: str, en: str) -> None:
        self.x("INSERT INTO care_event(elder_id, day, type, label_vi, label_en) VALUES (?,?,?,?,?)",
               (elder_id, day, type_, vi, en))

    # ---------------------------------------------------------------- memory facts / calls
    def add_memory_fact(self, elder_id: str, day: int | None, fact_vi: str, source: str,
                        question_vi: str | None = None, cue_vi: str | None = None,
                        keywords: list[str] | None = None) -> None:
        self.x("INSERT INTO memory_fact(elder_id, day, fact_vi, question_vi, cue_vi, keywords_json, source, created_at)"
               " VALUES (?,?,?,?,?,?,?,?)", (elder_id, day, fact_vi, question_vi, cue_vi,
                                            json.dumps(keywords or [], ensure_ascii=False), source, now_iso()))

    def memory_facts(self, elder_id: str) -> list[dict]:
        out = []
        for r in self.q("SELECT * FROM memory_fact WHERE elder_id=? ORDER BY id", (elder_id,)):
            d = dict(r)
            d["keywords"] = json.loads(d.pop("keywords_json") or "[]")
            out.append(d)
        return out

    def save_call(self, call_id: str, elder_id: str, channel: str, started_at: str, prompt_version: str,
                  engine: str) -> None:
        self.x("INSERT INTO call_session(id, elder_id, channel, started_at, status, prompt_version, engine, simulated)"
               " VALUES (?,?,?,?,?,?,?,0)", (call_id, elder_id, channel, started_at, "active", prompt_version, engine))

    def finish_call(self, call_id: str, day: int | None, status: str, end_reason: str | None, emergency: bool,
                    transcript: list[dict], engine: str) -> None:
        exp = (datetime.now(timezone.utc) + timedelta(days=TRANSCRIPT_DAYS)).isoformat(timespec="seconds")
        self.x("UPDATE call_session SET day=?, ended_at=?, status=?, end_reason=?, emergency=?, transcript_json=?, "
               "transcript_expires_at=?, engine=? WHERE id=?",
               (day, now_iso(), status, end_reason, 1 if emergency else 0, json.dumps(transcript, ensure_ascii=False),
                exp, engine, call_id))

    def save_analysis(self, call_id: str, elder_id: str, day: int | None, analysis: dict, metrics: dict) -> None:
        self.x("INSERT OR REPLACE INTO call_analysis(call_id, elder_id, day, analysis_json, metrics_json, created_at)"
               " VALUES (?,?,?,?,?,?)", (call_id, elder_id, day, json.dumps(analysis, ensure_ascii=False),
                                         json.dumps(metrics), now_iso()))

    def last_analyses(self, elder_id: str, n: int = 3) -> list[dict]:
        return [json.loads(r["analysis_json"]) for r in
                self.q("SELECT analysis_json FROM call_analysis WHERE elder_id=? ORDER BY created_at DESC LIMIT ?",
                       (elder_id, n))]

    def purge_transcripts(self) -> int:
        with self.lock:
            cur = self.conn.execute("UPDATE call_session SET transcript_json=NULL WHERE transcript_expires_at IS NOT "
                                    "NULL AND transcript_expires_at < ? AND transcript_json IS NOT NULL", (now_iso(),))
            self.conn.commit()
            return cur.rowcount
