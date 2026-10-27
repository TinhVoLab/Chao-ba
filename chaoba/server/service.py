"""Business logic behind the REST API: seeding, daily context, call lifecycle, light/alert updates."""
from __future__ import annotations

import json
import logging
import os
import threading
import uuid
from dataclasses import asdict
from datetime import date as Date, timedelta
from pathlib import Path

from chaoba.core.models import DailyLight, DailyRecord, to_dict
from chaoba.core import control_chart, explain as explain_mod, metrics as metrics_mod

from chaoba.agent.analysis import analyze_call
from chaoba.agent.orchestrator import Orchestrator, CallState, default_engine
from chaoba.agent.persona import ElderView
from chaoba.agent.prompts import (DailyContext, PROMPT_VERSION, recall_from_fact, default_family_greeting,
                                  content_keywords)

from .db import Store, now_iso, ROOT

log = logging.getLogger("chaoba.server")

SEED_PERSONAS = ("hanh", "tu", "control")
SEED_DAYS = 90
CONSENT_KINDS = ("daily_call", "voice_metrics", "family_sharing", "clinician_sharing", "research_use")
CONTACT_KINDS = ("call", "visit", "message")
CONTACT_NUDGE_DAYS = 3  # the family app nudges when nobody has called or visited for this many days


def seed_end_date() -> Date:
    """Calendar date of the last seeded day (day 90): CHAOBA_END_DATE (ISO) if set, else yesterday (server local date).

    Day 90 is the most recent *completed* morning call, so a live call made today becomes day 91 dated today, and
    no seeded date ever lies in the future. Day indices and values do not depend on the anchor."""
    env = os.environ.get("CHAOBA_END_DATE")
    if env:
        return Date.fromisoformat(env)
    return Date.today() - timedelta(days=1)
LEVEL = {"gray": -1, "green": 0, "yellow": 1, "red": 2}
DEMO_FAMILY_MESSAGES = {  # simulated messages the family "left" for the elder, played at the end of the call
    "hanh": ("Lan", "Lan nhắn: chủ nhật này con về thăm má, má đừng nấu nhiều nha."),
    "tu": ("Khoa", "Khoa nhắn: cuối tuần con chở ba đi uống cà phê với mấy bạn cờ."),
    "control": ("Thảo", "Thảo nhắn: chiều nay con ghé ăn cơm với ba."),
}


def _mid(name: str) -> str:
    """'Ông Bảy' -> 'ông Bảy' when used mid-sentence."""
    return name[:1].lower() + name[1:] if name else name


def llm_enabled() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def _light_obj(d: dict) -> DailyLight:
    return DailyLight(**{k: d.get(k) for k in DailyLight.__dataclass_fields__ if k in d})


class Service:
    def __init__(self, store: Store, orchestrator: Orchestrator | None = None):
        self.store = store
        self.orch = orchestrator or Orchestrator(default_engine())
        self.active: dict[str, CallState] = {}
        self.results: dict[str, dict] = {}
        self.alerted_calls: set[str] = set()
        # Calls whose elder side was scripted (demo sim mode); their days are stored simulated=True.
        self.sim_calls: set[str] = set()
        self._eval_cache: dict | None = None
        self._lock = threading.RLock()

    # ================================================================== seed
    def seed(self) -> None:
        from chaoba.core import synth
        end = seed_end_date()
        for key in SEED_PERSONAS:
            if self.store.one("SELECT id FROM elder WHERE id=?", (key,)):
                continue
            p = synth.generate_persona(key, days=SEED_DAYS, end_date=end)
            self._seed_persona(key, p)
        self.store.purge_transcripts()

    def _seed_persona(self, key: str, p: dict) -> None:
        st = self.store
        prof = p["elder"]
        st.x("INSERT INTO elder(id, profile_json, simulated, opted_out, created_at) VALUES (?,?,?,0,?)",
             (prof["id"], json.dumps(prof, ensure_ascii=False), 1 if p.get("simulated", True) else 0, now_iso()))
        st.xmany("INSERT OR REPLACE INTO family_member(elder_id, id, name, relation, role) VALUES (?,?,?,?,?)",
                 [(prof["id"], f.get("id"), f.get("name"), f.get("relation"), f.get("role"))
                  for f in prof.get("family") or []])
        for c in p.get("consents") or []:
            st.add_consent(prof["id"], c.get("type", "daily_call"), bool(c.get("granted", True)), c.get("by"),
                           c.get("scope_en"), detail=c, ts=c.get("date"))
        for r in p["records"]:
            st.upsert_record(r)
        lights = p.get("lights")
        rebase = p.get("rebaseline_days") or []
        if not lights:
            lights = self._evaluate(prof, p["records"], rebase)
        st.replace_lights(prof["id"], lights)
        st.set_baseline(prof["id"], p.get("baseline") or control_chart.current_baseline(p["records"], None, rebase))
        for e in p.get("events") or []:
            st.add_event(prof["id"], e["day"], e["type"], e.get("label_vi", ""), e.get("label_en", ""))
        for n in p.get("notes") or []:
            st.add_note(prof["id"], n.get("author", "?"), n["text"], n.get("day"), simulated=True)
        for c in p.get("contacts") or []:
            st.add_contact(prof["id"], c["day"], c["date"], c.get("member_id"), c.get("member_name"), c["kind"],
                           c.get("duration_min"), source="simulated", simulated=True)
        if key in DEMO_FAMILY_MESSAGES:
            author, msg = DEMO_FAMILY_MESSAGES[key]
            st.add_note(prof["id"], author, msg, p["records"][-1]["day"], to_elder=True, simulated=True)
        for f in prof.get("memory_facts") or []:
            r = recall_from_fact(f, prof.get("honorific", "bà"))
            st.add_memory_fact(prof["id"], None, f, "profile", r.question_vi, r.cue_vi, r.keywords)
        dm = p.get("dmaic") or {}
        define = p.get("define") or {"goals": prof.get("goals") or []}
        if dm.get("new_baseline_day"):
            define.setdefault("new_baseline_day", dm["new_baseline_day"])
        st.x("INSERT OR REPLACE INTO dmaic_cycle(elder_id, define_json, intervention_day, rebaseline_days_json, "
             "seed_json, updated_at) VALUES (?,?,?,?,?,?)",
             (prof["id"], json.dumps(define, ensure_ascii=False), dm.get("intervention_day"), json.dumps(rebase),
              json.dumps(dm, ensure_ascii=False), now_iso()))
        # Historical alerts from light rises (older ones pre-acknowledged so the demo inbox is realistic).
        last_day = p["records"][-1]["day"]
        prev = "green"
        for l in lights:
            if l["light"] == "gray":
                continue
            if LEVEL[l["light"]] > LEVEL[prev] and l["light"] in ("yellow", "red"):
                aid = st.add_alert(prof["id"], l["day"], l["date"], self._alert_type(l), l["light"],
                                   l.get("explanation_vi", ""), l.get("explanation_en", ""))
                if l["day"] < last_day - 7:
                    st.x("UPDATE alert SET acknowledged=1, acknowledged_by=? WHERE id=?",
                         (f"{(prof.get('family') or [{}])[0].get('name', 'family')} (simulated)", aid))
            prev = l["light"]

    @staticmethod
    def _alert_type(light: dict) -> str:
        reasons = [r for r in light.get("reasons") or [] if r.get("code") not in ("recovering",)]
        return reasons[0]["code"] if reasons else f"light_{light['light']}"

    # ================================================================== helpers
    @staticmethod
    def _eval_records(records: list[dict]) -> list[DailyRecord]:
        recs = [DailyRecord(**{k: r.get(k) for k in DailyRecord.__dataclass_fields__ if k in r}) for r in records]
        for rr, r in zip(recs, records):
            rr.symptoms = dict(r.get("symptoms") or {})
            # Baselines are not split by channel in the prototype. Web calls are evaluated as "sim" so day 91
            # is scored against the existing (simulated) baseline rather than a fresh one that is still building.
            # The stored record keeps channel "web"; only the evaluation view is mapped.
            if rr.channel == "web":
                rr.channel = "sim"
        return recs

    def _evaluate(self, prof: dict, records: list[dict], rebase: list[int], llm_last: bool = False) -> list[dict]:
        recs = self._eval_records(records)
        lights = control_chart.evaluate_series(recs, control_chart.ControlConfig(), rebaseline_days=rebase or None)
        out = []
        for i, l in enumerate(lights):
            use_llm = llm_last and i == len(lights) - 1 and llm_enabled()
            l.explanation_vi, l.explanation_en = explain_mod.explain(l, prof.get("display_name", ""),
                                                                     prof.get("name_en", ""), use_llm=use_llm)
            out.append(to_dict(l))
        return out

    def elder_or_none(self, elder_id: str) -> dict | None:
        return self.store.elder(elder_id)

    def is_simulated(self, elder_id: str) -> bool:
        return bool(self.store.one("SELECT 1 FROM metric_daily WHERE elder_id=? AND simulated=1 LIMIT 1", (elder_id,)))

    def current_day(self, elder_id: str) -> tuple[int | None, str]:
        """(day index, ISO date) of *now* on this elder's calendar: today's date, or the last record's day if that is
        later (e.g. after a live call). Used to date family notes and contacts."""
        recs = self.store.records(elder_id)
        today = Date.today()
        if not recs:
            return None, today.isoformat()
        last_day, last_date = recs[-1]["day"], Date.fromisoformat(recs[-1]["date"])
        if today > last_date:
            return last_day + (today - last_date).days, today.isoformat()
        return last_day, last_date.isoformat()

    def sharing_paused(self, elder_id: str) -> bool:
        return not self.store.consent_granted(elder_id, "family_sharing")

    def contact_status(self, elder_id: str) -> dict:
        """Family contact summary relative to the latest call day: last contact and days since."""
        recs = self.store.records(elder_id)
        ref = recs[-1]["day"] if recs else 0
        cs = self.store.contacts(elder_id)
        last = cs[-1] if cs else None
        since = max(0, ref - last["day"]) if last else None
        return {"last": last, "days_since": since, "nudge": since is not None and since >= CONTACT_NUDGE_DAYS,
                "nudge_after_days": CONTACT_NUDGE_DAYS}

    def _rebase(self, elder_id: str) -> list[int]:
        r = self.store.one("SELECT rebaseline_days_json FROM dmaic_cycle WHERE elder_id=?", (elder_id,))
        return json.loads(r["rebaseline_days_json"] or "[]") if r else []

    # ================================================================== read endpoints
    def list_elders(self) -> list[dict]:
        out = []
        for eid in self.store.elder_ids():
            p = self.store.elder(eid)
            lights = self.store.lights(eid)
            out.append({"id": eid, "display_name": p.get("display_name"), "name_en": p.get("name_en"),
                        "age": p.get("age"), "province": p.get("province"),
                        "light": "gray" if (not lights or self.sharing_paused(eid)) else lights[-1]["light"],
                        "sharing_paused": self.sharing_paused(eid),
                        "opted_out": p.get("opted_out", False), "simulated": self.is_simulated(eid)})
        return out

    def today(self, elder_id: str) -> dict:
        recs = self.store.records(elder_id)
        lights = self.store.lights(elder_id)
        if not recs:
            return {"date": None, "day": None, "light": "gray", "reasons": [], "explanation_vi": "", "explanation_en": "",
                    "summary_vi": "", "summary_en": "", "answered": False, "mood": None, "simulated": False}
        r = recs[-1]
        contact = self.contact_status(elder_id)
        if self.sharing_paused(elder_id):
            return {"date": r["date"], "day": r["day"], "light": "gray", "reasons": [{"code": "sharing_paused"}],
                    "explanation_vi": "Chia sẻ với gia đình đang tạm dừng (đã rút đồng ý). Bật lại trong mục Quyền riêng tư.",
                    "explanation_en": "Sharing with the family is paused (consent withdrawn). Turn it back on in Privacy.",
                    "summary_vi": "", "summary_en": "", "answered": False, "mood": None, "channel": r.get("channel"),
                    "sharing_paused": True, "contact": contact, "simulated": bool(r.get("simulated", True))}
        l = next((x for x in reversed(lights) if x["day"] == r["day"]), lights[-1] if lights else {})
        return {"date": r["date"], "day": r["day"], "light": l.get("light", "gray"), "reasons": l.get("reasons", []),
                "explanation_vi": l.get("explanation_vi", ""), "explanation_en": l.get("explanation_en", ""),
                "summary_vi": r.get("summary_vi", ""), "summary_en": r.get("summary_en", ""),
                "answered": bool(r.get("answered")), "mood": r.get("mood"), "channel": r.get("channel"),
                "sharing_paused": False, "contact": contact, "simulated": bool(r.get("simulated", True))}

    def timeline(self, elder_id: str, days: int = 90) -> dict:
        recs = self.store.records(elder_id)
        lights = self.store.lights(elder_id)
        days = max(1, int(days))
        if self.sharing_paused(elder_id):
            return {"records": [], "lights": [], "baseline": {}, "baselines": [], "events": [],
                    "sharing_paused": True, "simulated": self.is_simulated(elder_id)}
        recs_w = recs[-days:]
        first = recs_w[0]["day"] if recs_w else 0
        return {"records": recs_w, "lights": [l for l in lights if l["day"] >= first],
                "baseline": self.store.baseline(elder_id),
                "baselines": [b for b in self.baselines(elder_id, recs) if b["to_day"] >= first],
                "events": [e for e in self.store.events(elder_id) if e["day"] >= first],
                "sharing_paused": False, "simulated": self.is_simulated(elder_id)}

    def baselines(self, elder_id: str, recs: list[dict] | None = None) -> list[dict]:
        """Baseline history as used by the control chart: [{from_day, to_day, window, metrics:{m:{center,scale}}}].

        ``from_day`` is the first day judged against this baseline; ``window`` the days it was estimated from (the
        first 21 days for the initial baseline, the trailing 21 days before a re-baseline)."""
        recs = recs if recs is not None else self.store.records(elder_id)
        if not recs:
            return []
        rebase = self._rebase(elder_id)
        cfg = control_chart.ControlConfig()
        segs = control_chart.baseline_segments(self._eval_records(recs), cfg, rebase or None)
        last = recs[-1]["day"]
        out = []
        for i, sg in enumerate(segs):
            to_day = (segs[i + 1]["from_day"] - 1) if i + 1 < len(segs) else last
            if i == 0:
                window = [recs[0]["day"], sg["from_day"] - 1]
            else:
                window = [max(recs[0]["day"], sg["from_day"] - cfg.baseline_days), sg["from_day"] - 1]
            out.append({"from_day": sg["from_day"], "to_day": to_day, "window": window,
                        "metrics": {m: {"center": round(v["center"], 4), "scale": round(v["scale"], 4)}
                                    for m, v in sg["baseline"].items()}})
        return out

    def dmaic(self, elder_id: str) -> dict:
        row = self.store.one("SELECT * FROM dmaic_cycle WHERE elder_id=?", (elder_id,))
        seed = json.loads(row["seed_json"] or "{}") if row else {}
        define = json.loads(row["define_json"] or "{}") if row else {}
        iv = row["intervention_day"] if row else None
        recs = self.store.records(elder_id)
        lights = self.store.lights(elder_id)
        from chaoba.core.dmaic import compute_cycle
        if self.sharing_paused(elder_id):
            return {"phases": [], "effect": {}, "new_baseline_day": None, "contact": None, "sharing_paused": True,
                    "simulated": self.is_simulated(elder_id)}
        try:
            cyc = compute_cycle(recs, lights, define, iv, contacts=self.store.contacts(elder_id))
        except Exception as e:  # pragma: no cover - fall back to the seeded cycle
            log.warning("compute_cycle failed: %s", e)
            cyc = dict(seed)
        # Keep the richer seeded Define text (concern/context) if our reconstructed `define` lacks it.
        seed_def = next((ph for ph in seed.get("phases", []) if ph.get("phase") == "define"), None)
        if seed_def and "concern_vi" not in define:
            cyc["phases"] = [seed_def if ph.get("phase") == "define" else ph for ph in cyc.get("phases", [])]
        cyc["sharing_paused"] = False
        cyc["simulated"] = self.is_simulated(elder_id)
        return cyc

    def privacy(self, elder_id: str) -> dict:
        p = self.store.elder(elder_id) or {}
        return {"consents": self.store.current_consents(elder_id), "consent_history": self.store.consents(elder_id),
                "access_log": self.store.access_log(elder_id),
                "data_retention": {"audio": "not stored", "transcript_days": 7,
                                   "metrics": "derived numbers kept while enrolled",
                                   "llm_processing": "claude" if llm_enabled() else "server-side rules (no LLM)"},
                "scheduling_active": not p.get("opted_out", False),
                "simulated": self.is_simulated(elder_id)}

    # ================================================================== consent / contact writes
    def set_consent(self, elder_id: str, kind: str, granted: bool, by: str) -> dict:
        """Withdraw (granted=False) or re-grant a consent purpose. Processing for that purpose stops/starts at once:
        daily_call pauses/resumes scheduling (same as an in-call opt-out), voice_metrics stops storing speech
        metrics, family_sharing hides the light, trends, alerts and care cycle from the family app."""
        if kind == "daily_call":
            self.store.x("UPDATE elder SET opted_out=? WHERE id=?", (0 if granted else 1, elder_id))
        self.store.add_consent(elder_id, kind, granted, by,
                               ("re-granted from the family app" if granted else "withdrawn from the family app"))
        return {"ok": True, "kind": kind, "granted": granted,
                "status": "active" if granted else "withdrawn",
                "scheduling_active": not (self.store.elder(elder_id) or {}).get("opted_out", False)}

    def log_contact(self, elder_id: str, member_id: str | None, member_name: str | None, kind: str,
                    duration_min: int | None = None) -> dict:
        day, date = self.current_day(elder_id)
        prof = self.store.elder(elder_id) or {}
        fam = {f.get("id"): f.get("name") for f in prof.get("family") or []}
        name = member_name or fam.get(member_id or "") or member_id or "family"
        cid = self.store.add_contact(elder_id, day or 0, date, member_id, name, kind, duration_min, source="app")
        return {"id": cid, "ok": True, "day": day, "date": date, "kind": kind, "member_name": name,
                "status": self.contact_status(elder_id)}

    def contacts(self, elder_id: str, days: int = 90) -> dict:
        recs = self.store.records(elder_id)
        last = recs[-1]["day"] if recs else 0
        cs = [c for c in self.store.contacts(elder_id) if c["day"] > last - max(1, int(days))]
        from chaoba.core.dmaic import contact_rate
        return {"contacts": cs, **self.contact_status(elder_id),
                "per_week_last_14_days": contact_rate(cs, max(1, last - 13), last) if recs else None,
                "simulated": self.is_simulated(elder_id)}

    def evaluation(self) -> dict:
        if self._eval_cache is not None:
            return self._eval_cache
        path = ROOT / "data" / "eval" / "report.json"
        if path.exists():
            try:
                self._eval_cache = json.loads(path.read_text()) | {"source": str(path.relative_to(ROOT))}
                return self._eval_cache
            except Exception:
                pass
        try:
            from chaoba.core import synth, evaluation
            cohort = synth.generate_cohort(n=60, days=120)
            rep = evaluation.run_evaluation(cohort)
            self._eval_cache = rep | {"source": "computed on startup (n=60, run scripts/run_eval.py for full report)",
                                      "simulated": True}
        except Exception as e:
            return {"available": False, "reason": f"evaluation not available yet: {e}", "simulated": True}
        return self._eval_cache

    # ================================================================== calls
    def build_context(self, elder_id: str) -> DailyContext:
        prof = self.store.elder(elder_id)
        ev = ElderView.from_profile(prof)
        recs = self.store.records(elder_id)
        last_day = recs[-1]["day"] if recs else 0
        summaries = [r["summary_vi"] for r in recs if r.get("summary_vi")][-3:]
        hooks: list[str] = []
        for a in self.store.last_analyses(elder_id, 2):
            hooks += a.get("followup_hooks") or []
        facts = self.store.memory_facts(elder_id)
        recent = [f for f in facts if f["day"] is not None and last_day - 2 <= f["day"] <= last_day]
        if recent:
            f = recent[-1]
        else:
            from chaoba.agent.prompts import CURATED_RECALL
            from chaoba.agent.textnorm import normalize
            prof_facts = ([f for f in facts if f["source"] == "profile" and normalize(f["fact_vi"]) in CURATED_RECALL]
                          or [f for f in facts if f["source"] == "profile"] or facts)
            f = prof_facts[(last_day + 1) % len(prof_facts)] if prof_facts else None
        recall = None
        if f:
            recall = recall_from_fact(f["fact_vi"], ev.honorific, f["day"], f.get("question_vi"), f.get("cue_vi"),
                                      f.get("keywords") or None)
        to_elder = [n for n in self.store.notes(elder_id) if n["to_elder"]]
        msg = to_elder[0]["text"] if to_elder else None
        return DailyContext(elder=ev, profile=prof, last_summaries=summaries, followup_hooks=hooks[:3], recall=recall,
                            family_message=msg, family_greeting=default_family_greeting(ev), day=last_day + 1)

    def start_call(self, elder_id: str, channel: str = "web", simulated: bool = False) -> dict:
        ctx = self.build_context(elder_id)
        call_id = uuid.uuid4().hex[:12]
        if simulated:
            self.sim_calls.add(call_id)
        state, greeting = self.orch.start(ctx, call_id, channel)
        with self._lock:
            self.active[call_id] = state
        self.store.save_call(call_id, elder_id, channel, now_iso(), PROMPT_VERSION, self.orch.engine.name)
        return {"call_id": call_id, "greeting_text": greeting, "phase": state.phase, "engine": self.orch.engine.name,
                "prompt_version": PROMPT_VERSION, "notice_vi": "Không lưu ghi âm", "notice_en": "No audio is recorded"}

    def turn(self, call_id: str, text: str, start: float | None, end: float | None, pauses: list[float]) -> dict:
        state = self.active.get(call_id)
        if state is None:
            raise KeyError(call_id)
        res = self.orch.handle_turn(state, text, start, end, pauses)
        eid = state.ctx.elder.id
        if res.emergency and call_id not in self.alerted_calls:
            self.alerted_calls.add(call_id)
            self._emergency_alert(state)
        if res.event == "opt_out":
            self.store.set_opt_out(eid, True, by="elder (in call)")
        return {"reply_text": res.reply_text, "phase": res.phase, "emergency": res.emergency,
                "end_call": res.end_call, "event": res.event}

    def simulate_elder(self, call_id: str) -> dict:
        """Demo helper: the next scripted elder utterance for this call (flagged simulated)."""
        from chaoba.agent.simulator import next_elder_line
        state = self.active.get(call_id)
        if state is None:
            raise KeyError(call_id)
        self.sim_calls.add(call_id)  # any scripted elder line makes the whole call simulated
        return next_elder_line(state)

    def _emergency_alert(self, state: CallState) -> None:
        eid = state.ctx.elder.id
        prof = state.ctx.profile
        hit = state.emergency_hits[-1] if state.emergency_hits else {}
        recs = self.store.records(eid)
        day = (recs[-1]["day"] + 1) if recs else 1
        date = self._next_date(recs)
        quote = hit.get("quote", "")
        vi = (f"Trong cuộc gọi, {_mid(prof.get('display_name', ''))} nói: “{quote}”. Út Thương đã hướng dẫn gọi 115. "
              f"Xin gia đình gọi cho {prof.get('honorific', 'bà')} ngay.")
        en = (f"During the call {prof.get('name_en')} said: “{quote}”. The assistant advised calling 115. "
              f"Please call now.")
        self.store.add_alert(eid, day, date, "emergency", "red", vi, en, state.call_id)

    @staticmethod
    def _next_date(recs: list[dict]) -> str:
        if not recs:
            return Date.today().isoformat()
        return (Date.fromisoformat(recs[-1]["date"]) + timedelta(days=1)).isoformat()

    def end_call(self, call_id: str) -> dict:
        if call_id in self.results:
            return self.results[call_id]
        state = self.active.get(call_id)
        if state is None:
            raise KeyError(call_id)
        eid = state.ctx.elder.id
        prof = state.ctx.profile
        state.ended = True
        sim = call_id in self.sim_calls
        m = metrics_mod.compute_call_metrics(state.turns)
        analysis = analyze_call(state.turns, prof, state.ctx.recall, state.recall_free_text, state.recall_cued_text,
                                emergency=state.emergency, opted_out=state.opted_out)
        recs = self.store.records(eid)
        elder_turns = state.elder_turns()
        spoke = any(t.text.strip() for t in elder_turns)
        day = None
        if state.opted_out and not state.emergency:
            # Opt-out: no daily record at all (the elder withdrew); the family is told via an alert.
            nday = (recs[-1]["day"] + 1) if recs else 1
            self._opt_out_alert(eid, prof, nday, self._next_date(recs), call_id)
        elif elder_turns and (state.declined or not spoke) and not state.emergency:
            # Declined consent today, or only silence: an unanswered day (no metrics, no mood).
            day = (recs[-1]["day"] + 1) if recs else 1
            date = self._next_date(recs)
            name_vi, name_en = prof.get("display_name", ""), prof.get("name_en", "")
            if state.declined:
                s_vi = f"{name_vi} bận, chưa muốn trò chuyện hôm nay. Út Thương sẽ gọi lại ngày mai."
                s_en = f"{name_en} was busy and preferred not to talk today. The assistant will call again tomorrow."
            else:
                s_vi = f"{name_vi} không trả lời trong cuộc gọi hôm nay."
                s_en = f"{name_en} did not respond during today's call."
            analysis.summary_vi, analysis.summary_en = s_vi, s_en
            analysis.mood, analysis.symptoms, analysis.recall_score, analysis.recall_cue_level = 3, {}, None, None
            rec = DailyRecord(elder_id=eid, day=day, date=date, channel="web", answered=False, valid=False,
                              summary_vi=s_vi, summary_en=s_en, simulated=sim)
            self.store.upsert_record(to_dict(rec))
            self._refresh_lights(eid, prof, state, day, date)
            self.store.add_event(eid, day, "web_call_unanswered",
                                 "Cuộc gọi web: từ chối hôm nay" if state.declined else "Cuộc gọi web: không trả lời",
                                 "Web call: declined today" if state.declined else "Web call: no response")
        elif elder_turns:
            day = (recs[-1]["day"] + 1) if recs else 1
            date = self._next_date(recs)
            # voice_metrics consent withdrawn -> no speech metrics are kept for this call (answered, not scored)
            keep = bool(m.valid) and self.store.consent_granted(eid, "voice_metrics")
            rec = DailyRecord(
                elder_id=eid, day=day, date=date, channel="web", answered=True, valid=keep,
                speech_rate_sps=m.speech_rate_sps if keep else None,
                pause_ratio=m.pause_ratio if keep else None,
                filled_pause_rate=m.filled_pause_rate if keep else None,
                mattr=m.mattr if keep else None,
                recall_score=float(analysis.recall_score) if analysis.recall_score is not None else None,
                mood=analysis.mood, symptoms={k: len(v) for k, v in analysis.symptoms.items() if v},
                summary_vi=analysis.summary_vi, summary_en=analysis.summary_en, simulated=sim)
            self.store.upsert_record(to_dict(rec))
            self._refresh_lights(eid, prof, state, day, date)
            for f in analysis.memory_facts_new:
                self.store.add_memory_fact(eid, day, f, "call", keywords=content_keywords(f))
            if sim:
                self.store.add_event(eid, day, "web_call", "Cuộc gọi web (người nói giả lập)",
                                     "Web call (simulated elder)")
            else:
                self.store.add_event(eid, day, "web_call", "Cuộc gọi web (thật, không phải mô phỏng)",
                                     "Live web call (not simulated)")
        self.store.save_analysis(call_id, eid, day, asdict(analysis), asdict(m))
        self.store.finish_call(call_id, day, "completed", state.end_reason or "completed", state.emergency,
                               state.transcript(), state.engine_used)
        self.store.purge_transcripts()
        result = {"metrics": asdict(m), "analysis": asdict(analysis), "today": self.today(eid),
                  "day": day, "simulated": sim}
        with self._lock:
            self.results[call_id] = result
            self.active.pop(call_id, None)
        return result

    def _opt_out_alert(self, eid: str, prof: dict, day: int, date: str, call_id: str) -> None:
        self.store.add_alert(eid, day, date, "opt_out", "yellow",
                             f"{prof.get('display_name')} đã yêu cầu ngưng cuộc gọi buổi sáng. Gia đình nên hỏi thăm lý do.",
                             f"{prof.get('name_en')} asked to stop the morning calls. Please check in about why.",
                             call_id)

    def _refresh_lights(self, eid: str, prof: dict, state: CallState, day: int, date: str) -> None:
        old = self.store.lights(eid)
        prev_light = next((l["light"] for l in reversed(old) if l["light"] != "gray"), "green")
        rebase = self._rebase(eid)
        lights = self._evaluate(prof, self.store.records(eid), rebase, llm_last=True)
        new = lights[-1]
        if state.emergency:
            hit = state.emergency_hits[-1] if state.emergency_hits else {}
            new["light"] = "red"
            new["reasons"] = [{"code": "emergency", "category": hit.get("category"), "quote": hit.get("quote")}] + \
                new.get("reasons", [])
            new["explanation_vi"] = (f"Sáng nay {_mid(prof.get('display_name', ''))} nói điều cần chú ý ngay. Út Thương đã "
                                     f"hướng dẫn gọi 115. Xin gia đình gọi cho {prof.get('honorific', 'bà')} liền.")
            new["explanation_en"] = (f"This morning {prof.get('name_en')} said something that needs attention now. "
                                     f"The assistant advised calling 115. Please call right away.")
        self.store.replace_lights(eid, lights)
        try:
            self.store.set_baseline(eid, control_chart.current_baseline(self.store.records(eid), None, rebase or None))
        except Exception as e:  # pragma: no cover
            log.warning("baseline refresh failed: %s", e)
        if not state.emergency and new["light"] in ("yellow", "red") and LEVEL[new["light"]] > LEVEL[prev_light]:
            self.store.add_alert(eid, day, date, self._alert_type(new), new["light"], new.get("explanation_vi", ""),
                                 new.get("explanation_en", ""), state.call_id)
        if state.opted_out:
            self._opt_out_alert(eid, prof, day, date, state.call_id)
        scams = [f for f in state.flags if f["type"] == "scam"]
        if scams:
            self.store.add_alert(eid, day, date, "scam_topic", "yellow",
                                 f"{prof.get('display_name')} có nhắc chuyện tiền/ngân hàng/mã OTP: “{scams[0]['quote']}”. "
                                 "Út Thương đã nhắc không đưa mã số qua điện thoại. Gia đình nên hỏi thăm.",
                                 f"{prof.get('name_en')} mentioned money/bank/OTP: “{scams[0]['quote']}”. The assistant "
                                 "warned not to share codes by phone. Please check in.", state.call_id)
