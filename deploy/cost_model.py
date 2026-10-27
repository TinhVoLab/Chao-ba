"""Per-call cost model for Chào Bà, built from a measured scripted call.

    .venv/bin/python deploy/cost_model.py                 # estimate tokens from text size (no key needed)
    ANTHROPIC_API_KEY=... .venv/bin/python deploy/cost_model.py --count-tokens   # exact counts via count_tokens

What is MEASURED: one complete hands-free call for Bà Hạnh (scripted elder lines from chaoba.agent.simulator) is run
through the real API in-process twice: (1) with the scripted engine, to get the call transcript, turn count, phase of
every turn and spoken length; (2) with ClaudeEngine and the Claude post-call analyser wired to a *recording fake
client*, to capture the exact request payloads (system prompt, per-call context, tool, history, directive) that would
be sent per turn. No request leaves the machine unless --count-tokens is given.

What is ASSUMED (edit the constants below; every one must be verified before quoting a price):
token-per-byte ratio, model list prices, STT / TTS / telephony per-minute or per-character prices, hosting, FX rate.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# ------------------------------------------------------------------------------------------- assumptions
VND_PER_USD = 26_000            # assumption (planning rate)
CALLS_PER_MONTH = 30            # one call every day (the 5-calls-a-week option = 21.5/month is shown too)
BILLED_MINUTES = 4.5            # design target: closing starts at 4:30 (orchestrator). The simulated call below is
                                # shorter (TTS-timed scripted lines), so per-minute items use this design length.
TARGET_VND = 100_000            # B2C price-point target per person-month
BYTES_PER_TOKEN = 3.0           # assumption: UTF-8 bytes / 3. Conservative for English (~4 chars/token);
                                # Vietnamese diacritics are 2-3 bytes each, so ~2 tokens per syllable. Verify with
                                # --count-tokens (Claude's tokenizer) before quoting.
# Claude list prices, US$ per 1M tokens (Anthropic first-party API, cached 2026-10; verify on the pricing page).
PRICES = {
    "claude-opus-5-5":   {"in": 4.00, "out": 20.00, "cache_read": 0.20, "cache_write": 5.00},
    "claude-sonnet-5-5": {"in": 2.00, "out": 10.00, "cache_read": 0.20, "cache_write": 2.50},
    "claude-haiku-5-5":  {"in": 0.10, "out": 0.50,  "cache_read": 0.01, "cache_write": 0.125},
}
# cache_write = 1.25 x input (5-minute TTL); Haiku cache_read assumed 0.1 x input. Output tokens per conversation
# turn include no thinking (conversation runs with thinking off / low effort); analysis output assumed 700 tokens
# (JSON summary, symptoms, recall, facts, hooks) plus 1,500 thinking tokens at effort "medium" (assumption).
ANALYSIS_OUT_TOKENS = 700 + 1_500
REWORD_CALLS_PER_CALL = 1       # Haiku rewording of the newest family explanation (explain.py)
# Voice and telephony: PLANNING ASSUMPTIONS ONLY, not quotes. Replace with written quotes from >= 2 providers each.
VOICE = {
    "web":          {"label": "browser Web Speech API (as built)", "stt_per_min": 0.0, "tts_per_mchar": 0.0, "tel_per_min": 0.0},
    "intl_sip":     {"label": "international cloud STT/TTS + domestic SIP", "stt_per_min": 0.016, "tts_per_mchar": 16.0, "tel_per_min": 0.030},
    "domestic_sip": {"label": "domestic vi-VN STT/TTS + domestic SIP", "stt_per_min": 0.006, "tts_per_mchar": 4.0, "tel_per_min": 0.030},
}
HOSTING_USD_PER_PERSON_MONTH = 0.20   # assumption: API + Postgres + workers + monitoring at >= 1,000 enrolled elders


@dataclass
class Scenario:
    key: str
    label: str
    voice: str
    conversation: str | None   # None = scripted engine (no LLM in the call)
    analysis: str | None       # None = rule-based analyser


SCENARIOS = [
    Scenario("A", "Web call + Haiku 5.5 conversation + Opus 5.5 analysis", "web", "claude-haiku-5-5", "claude-opus-5-5"),
    Scenario("B", "Domestic SIP + Sonnet 5.5 conversation + Opus 5.5 analysis + international STT/TTS",
             "intl_sip", "claude-sonnet-5-5", "claude-opus-5-5"),
    Scenario("C", "Domestic SIP + Haiku 5.5 conversation + Haiku 5.5 analysis + domestic STT/TTS",
             "domestic_sip", "claude-haiku-5-5", "claude-haiku-5-5"),
    Scenario("D", "Domestic SIP + scripted conversation + rule-based analysis + domestic STT/TTS (no LLM)",
             "domestic_sip", None, None),
]


# ------------------------------------------------------------------------------------------- measurement
class _Block:
    def __init__(self, text):
        self.type, self.text = "text", text


class _Resp:
    stop_reason = "end_turn"

    def __init__(self, text):
        self.content = [_Block(text)]


class RecordingClient:
    """Stands in for anthropic.Anthropic(): records every request, answers with a typical short reply."""
    log: list[dict] = []

    def __init__(self, *a, **k):
        self.messages = self
        self.beta = type("B", (), {"messages": self})()

    def create(self, **kw):
        RecordingClient.log.append(kw)
        if "output_config" in kw and "format" in (kw.get("output_config") or {}):
            return _Resp("{}")  # analysis: invalid on purpose -> rule-based result; we only need the request size
        if kw.get("tools"):
            return _Resp("Dạ, nghe vậy con mừng lắm. Sáng nay bà ăn sáng món gì vậy bà?")
        return _Resp("VI: x\nEN: y")


def _run_call(engine: str) -> dict:
    """Run one simulated call for 'hanh' through the API in-process. Returns transcript and recorded requests."""
    from fastapi.testclient import TestClient
    import anthropic

    db = Path(tempfile.mkdtemp()) / "cost.db"
    if engine == "claude":
        os.environ["ANTHROPIC_API_KEY"] = "fake-key-for-measurement"
        anthropic.Anthropic = RecordingClient  # type: ignore[misc]
    else:
        os.environ.pop("ANTHROPIC_API_KEY", None)
    RecordingClient.log = []
    from chaoba.server.app import create_app
    with TestClient(create_app(str(db))) as c:
        start = c.post("/api/calls", json={"elder_id": "hanh", "channel": "web", "simulated": True}).json()
        turns = [{"speaker": "agent", "text": start["greeting_text"], "phase": "greeting"}]
        t = 0.0
        for _ in range(40):
            line = c.get(f"/api/calls/{start['call_id']}/simulate").json()
            dur = max(1.5, len(line["text"].split()) / 3.8) + sum(line.get("pauses", []))
            r = c.post(f"/api/calls/{start['call_id']}/turns",
                       json={"text": line["text"], "start": t, "end": t + dur, "pauses": line.get("pauses", [])}).json()
            t += dur + max(1.0, len(r["reply_text"].split()) / 3.0)
            turns.append({"speaker": "elder", "text": line["text"], "phase": r["phase"]})
            turns.append({"speaker": "agent", "text": r["reply_text"], "phase": r["phase"]})
            if r.get("end_call"):
                break
        c.post(f"/api/calls/{start['call_id']}/end")
    os.environ.pop("ANTHROPIC_API_KEY", None)
    return {"turns": turns, "seconds": t, "requests": list(RecordingClient.log)}


def _tok(obj) -> float:
    s = obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False)
    return len(s.encode("utf-8")) / BYTES_PER_TOKEN


def _exact(model: str, req: dict) -> int:
    import anthropic
    client = anthropic.Anthropic()
    msgs = [m for m in req["messages"] if m["role"] != "system"]
    return client.messages.count_tokens(model=model, system=req.get("system"), tools=req.get("tools", []),
                                         messages=msgs).input_tokens


def measure(count_tokens: bool) -> dict:
    scripted = _run_call("scripted")
    claude = _run_call("claude")
    conv = [r for r in claude["requests"] if r.get("tools")]
    analysis = [r for r in claude["requests"] if "format" in (r.get("output_config") or {})]
    agent_turns = [t for t in scripted["turns"] if t["speaker"] == "agent"]
    by_phase: dict[str, dict] = {}
    for t in scripted["turns"]:
        p = by_phase.setdefault(t["phase"], {"elder_turns": 0, "agent_turns": 0, "elder_tok": 0.0, "agent_tok": 0.0})
        p[f"{t['speaker']}_turns"] += 1
        p[f"{t['speaker']}_tok"] += _tok(t["text"])
    # Per conversation request: cached prefix = static persona prompt + tool; the rest is uncached.
    per_req = []
    for r in conv:
        prefix = _tok(r["system"][0]["text"]) + _tok(r["tools"])
        rest = _tok(r["system"][1]["text"]) + _tok(r["messages"])
        if count_tokens:
            total = _exact("claude-haiku-5-5", r)
            share = prefix / (prefix + rest)
            prefix, rest = total * share, total * (1 - share)
        per_req.append({"prefix": prefix, "rest": rest})
    out_per_turn = sum(_tok(t["text"]) for t in agent_turns[1:]) / max(1, len(agent_turns) - 1)
    analysis_in = (_exact("claude-opus-5-5", analysis[0]) if count_tokens and analysis
                   else sum(_tok(a["system"]) + _tok(a["messages"]) for a in analysis[:1]))
    tts_chars = sum(len(t["text"]) for t in agent_turns)
    return {
        "minutes": scripted["seconds"] / 60, "turns": len(scripted["turns"]), "conv_requests": len(per_req),
        "by_phase": by_phase, "per_req": per_req, "out_per_turn": out_per_turn,
        "analysis_in": analysis_in, "tts_chars": tts_chars, "exact": count_tokens,
    }


def cost(m: dict, s: Scenario, calls: float = CALLS_PER_MONTH) -> dict:
    llm = 0.0
    if s.conversation:
        p = PRICES[s.conversation]
        for i, r in enumerate(m["per_req"]):
            prefix_rate = p["cache_write"] if i == 0 else p["cache_read"]
            llm += (r["prefix"] * prefix_rate + r["rest"] * p["in"] + m["out_per_turn"] * p["out"]) / 1e6
    if s.analysis:
        p = PRICES[s.analysis]
        llm += (m["analysis_in"] * p["in"] + ANALYSIS_OUT_TOKENS * p["out"]) / 1e6
    if s.conversation or s.analysis:  # rewording only exists when an LLM is configured
        p = PRICES["claude-haiku-5-5"]
        llm += REWORD_CALLS_PER_CALL * (250 * p["in"] + 120 * p["out"]) / 1e6
    v = VOICE[s.voice]
    stt = BILLED_MINUTES * v["stt_per_min"]
    tts = m["tts_chars"] / 1e6 * v["tts_per_mchar"]
    tel = BILLED_MINUTES * v["tel_per_min"]
    per_call = llm + stt + tts + tel
    month = per_call * calls + HOSTING_USD_PER_PERSON_MONTH
    # Highest telephony price per minute that still meets the target at this call frequency.
    budget = TARGET_VND / VND_PER_USD - HOSTING_USD_PER_PERSON_MONTH
    tel_max = (budget / calls - (llm + stt + tts)) / BILLED_MINUTES
    return {"llm": llm, "stt": stt, "tts": tts, "tel": tel, "per_call": per_call, "month_usd": month,
            "month_vnd": month * VND_PER_USD, "tel_max_vnd": tel_max * VND_PER_USD}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--count-tokens", action="store_true", help="exact input tokens via the API (needs a key)")
    a = ap.parse_args()
    m = measure(a.count_tokens)
    src = "count_tokens" if m["exact"] else f"estimated (UTF-8 bytes / {BYTES_PER_TOKEN:g})"
    print(f"Measured call: {m['minutes']:.1f} min, {m['turns']} turns, {m['conv_requests']} conversation requests; "
          f"input tokens {src}\n")
    print("| Phase | Elder turns | Agent turns | Elder tokens | Agent tokens |\n|---|---:|---:|---:|---:|")
    for ph, p in m["by_phase"].items():
        print(f"| {ph} | {p['elder_turns']} | {p['agent_turns']} | {p['elder_tok']:.0f} | {p['agent_tok']:.0f} |")
    pr = m["per_req"]
    print(f"\nConversation request: cached prefix ≈ {pr[0]['prefix']:.0f} tok; uncached part grows "
          f"{pr[0]['rest']:.0f} → {pr[-1]['rest']:.0f} tok; output ≈ {m['out_per_turn']:.0f} tok/turn; "
          f"analysis input ≈ {m['analysis_in']:.0f} tok; TTS {m['tts_chars']} characters/call\n")
    print(f"Per-minute items billed at {BILLED_MINUTES} min/call; {VND_PER_USD:,} VND/USD; hosting "
          f"${HOSTING_USD_PER_PERSON_MONTH}/person-month.\n")
    print("| Scenario | LLM | STT | TTS | Telephony | Per call | Person-month, 30 calls | Person-month, 5 calls/week "
          "| Max telephony for < 100k VND at 30 calls |")
    print("|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    for s in SCENARIOS:
        c = cost(m, s)
        w = cost(m, s, 21.5)
        mark = lambda x: "**yes**" if x < TARGET_VND else "no"
        tel = "n/a (no telephony)" if VOICE[s.voice]["tel_per_min"] == 0 else (
            "not reachable" if c["tel_max_vnd"] <= 0 else f"{c['tel_max_vnd']:,.0f} VND/min")
        print(f"| {s.key}. {s.label} | ${c['llm']:.4f} | ${c['stt']:.4f} | ${c['tts']:.4f} | ${c['tel']:.4f} | "
              f"${c['per_call']:.3f} | {c['month_vnd']:,.0f} VND ({mark(c['month_vnd'])}) | "
              f"{w['month_vnd']:,.0f} VND ({mark(w['month_vnd'])}) | {tel} |")


if __name__ == "__main__":
    main()
