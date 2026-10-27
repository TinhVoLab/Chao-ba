"""Gemini Live voice engine (optional): proxy bridge + WebSocket, all against the offline fake session (no keys,
no network, no sound). See chaoba/agent/gemini_live.py and chaoba/agent/gemini_fake.py."""
import asyncio
import json
import sqlite3

import pytest
from fastapi.testclient import TestClient

from chaoba.agent import gemini_live as gl
from chaoba.agent.gemini_fake import fake_connector, FRAME_BYTES
from chaoba.server.app import create_app
from chaoba.server import voice as voice_mod

GEMINI_ENV = ("GEMINI_API_KEY", "GOOGLE_API_KEY", "GOOGLE_GENAI_USE_VERTEXAI", "GOOGLE_CLOUD_PROJECT",
              "GOOGLE_CLOUD_LOCATION", "CHAOBA_VOICE_ENGINE", "CHAOBA_GEMINI_FAKE", "CHAOBA_GEMINI_MODEL",
              "CHAOBA_GEMINI_VOICE", "CHAOBA_GEMINI_LANGUAGE_CODE", "ANTHROPIC_API_KEY")


@pytest.fixture()
def client(tmp_path, monkeypatch):
    for k in GEMINI_ENV:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("CHAOBA_GEMINI_FAKE", "1")
    monkeypatch.setenv("CHAOBA_GEMINI_FAKE_DELAY", "0")
    with TestClient(create_app(str(tmp_path / "v.db"))) as c:
        c.db_path = str(tmp_path / "v.db")
        yield c


def start_live(c, elder="hanh", sim=True):
    r = c.post("/api/calls", json={"elder_id": elder, "channel": "web", "simulated": sim, "engine": "gemini"}).json()
    assert r["voice"]["engine"] == "gemini-live" and r["engine"] == "gemini-live"
    return r


class Harness:
    """Runs one LiveBridge in-process: a browser inbox, the messages the browser received, the fake session."""

    def __init__(self, svc, call_id, connector=None, **opts):
        self.svc, self.call_id = svc, call_id
        self.out: list[dict] = []
        self.audio_frames = 0
        self.inbox: asyncio.Queue = asyncio.Queue()
        opts.setdefault("tick", 0.02)
        self.bridge = gl.LiveBridge(svc, call_id, self._sj, self._sb, connector or fake_connector(), **opts)
        self.task: asyncio.Task | None = None

    async def _sj(self, d):
        self.out.append(d)

    async def _sb(self, b):
        self.audio_frames += 1

    def start(self):
        self.task = asyncio.create_task(self.bridge.run(self.inbox.get))

    @property
    def fake(self):
        return self.bridge.session

    def count(self, kind):
        return sum(1 for x in self.out if x["type"] == kind)

    def of(self, kind):
        return [x for x in self.out if x["type"] == kind]

    async def until(self, pred, timeout=5.0):
        for _ in range(int(timeout / 0.01)):
            if pred():
                return True
            await asyncio.sleep(0.01)
        raise AssertionError(f"timeout; got {[x['type'] for x in self.out][-12:]}")

    async def ended(self):
        await self.until(lambda: self.count("ended") or (self.task and self.task.done()))

    async def finish(self):
        await self.inbox.put(None)
        await asyncio.wait_for(self.task, 5)


async def simulated_call(h: Harness, max_turns=40):
    """Drive a whole call with the simulator's elder lines sent as text (sim mode in the browser)."""
    h.start()
    done = 0
    for i in range(max_turns):
        await h.until(lambda: h.count("agent_done") > done or h.count("ended"))
        if h.count("ended"):
            break
        done = h.count("agent_done")
        line = h.svc.simulate_elder(h.call_id)
        await h.inbox.put({"type": "text", "text": line["text"], "start": 10.0 * i + 1,
                           "end": 10.0 * i + 1 + line.get("duration_sec", 5), "pauses": line.get("pauses", [])})
    await h.ended()
    await h.finish()


# ------------------------------------------------------------------------------------------- credentials / config
def test_credentials_detection_both_modes():
    assert gl.gemini_credentials({})["available"] is False
    dev = gl.gemini_credentials({"GEMINI_API_KEY": "secret-key-123"})
    assert dev == {"available": True, "mode": "developer", "reason": "Gemini Developer API key"}
    assert "secret-key-123" not in json.dumps(dev)
    v = gl.gemini_credentials({"GOOGLE_GENAI_USE_VERTEXAI": "true", "GOOGLE_CLOUD_PROJECT": "chaoba-demo",
                               "GOOGLE_CLOUD_LOCATION": "us-central1"})
    assert v["available"] and v["mode"] == "vertex" and v["project"] == "chaoba-demo" and v["location"] == "us-central1"
    assert gl.gemini_credentials({"GOOGLE_GENAI_USE_VERTEXAI": "true"})["available"] is False   # project missing
    # Vertex wins when switched on, even if a developer key is also present
    assert gl.gemini_credentials({"GOOGLE_GENAI_USE_VERTEXAI": "1", "GOOGLE_CLOUD_PROJECT": "p",
                                  "GEMINI_API_KEY": "k"})["mode"] == "vertex"
    assert gl.gemini_credentials({"CHAOBA_GEMINI_FAKE": "1"})["mode"] == "fake"


def test_engine_choice_and_config_never_expose_key():
    env = {"GEMINI_API_KEY": "AIza-very-secret"}
    assert gl.choose_engine(None, "web", env)["engine"] == "browser"           # default stays the browser pipeline
    assert gl.choose_engine("gemini", "web", env)["engine"] == "gemini-live"
    assert gl.choose_engine(None, "web", env | {"CHAOBA_VOICE_ENGINE": "gemini"})["engine"] == "gemini-live"
    assert gl.choose_engine("browser", "web", env | {"CHAOBA_VOICE_ENGINE": "gemini"})["engine"] == "browser"
    no = gl.choose_engine("gemini", "web", {})
    assert no["engine"] == "browser" and "note_vi" in no
    pub = gl.public_voice_config(env | {"CHAOBA_VOICE_ENGINE": "gemini"})
    assert pub["default_engine"] == "gemini" and pub["gemini"]["model"] == gl.DEFAULT_MODEL
    assert "AIza-very-secret" not in json.dumps(pub) + json.dumps(gl.choose_engine("gemini", "web", env))


def test_live_config_is_valid_and_hides_recall_answer(client):
    from google.genai import types
    svc = client.app.state.svc
    ctx = svc.build_context("hanh")
    assert ctx.recall is not None
    cfg = gl.build_live_config(ctx, gl.LiveSettings())
    parsed = types.LiveConnectConfig.model_validate(cfg)        # the SDK accepts it as is
    assert parsed.response_modalities == [types.Modality.AUDIO]
    assert parsed.speech_config.voice_config.prebuilt_voice_config.voice_name == gl.DEFAULT_VOICE
    assert parsed.input_audio_transcription is not None and parsed.output_audio_transcription is not None
    names = [f.name for f in parsed.tools[0].function_declarations]
    assert names == ["next_step", "report_answer", "flag_emergency", "end_call"]
    assert ctx.recall.question_vi in cfg["system_instruction"]
    assert ctx.recall.fact_vi not in cfg["system_instruction"]
    assert "HIDDEN recall answer" not in cfg["system_instruction"]


# ------------------------------------------------------------------------------------------- full call via tools
def test_tool_calls_drive_the_whole_call_and_end_path_updates_day(client):
    svc = client.app.state.svc
    r = start_live(client)
    cid = r["call_id"]
    recall_fact = svc.active[cid].ctx.recall.fact_vi
    h = Harness(svc, cid)
    asyncio.run(simulated_call(h))
    assert h.of("ended")[0]["reason"] == "completed"
    fake = h.fake
    # tools drove the phases: one next_step per elder line, the end_call after the goodbye
    responses = [v for k, v in fake.sent if k == "tool_response"]
    steps = [v["response"] for v in responses if v["name"] == "next_step"]
    assert len(steps) >= 8 and h.bridge.meta["tool_calls"]["next_step"] == len(steps)
    modes = {s["mode"] for s in steps}
    assert {"exact", "adapt"} <= modes
    assert steps[-1]["end_call_after"] is True and steps[-1]["mode"] == "exact"
    phases = [s["phase"] for s in steps]
    for p in ("wellbeing", "recall", "story", "closing"):
        assert p in phases
    # the recall question goes out word for word; the hidden answer never reaches the model
    q = svc.active[cid].ctx.recall.question_vi
    assert any(s["mode"] == "exact" and q in s["line"] for s in steps)
    assert recall_fact not in fake.all_text_sent()
    # every agent caption came from the output transcription; the elder turns are in the server state
    assert h.audio_frames > 0
    st = svc.active[cid]
    assert st.engine_used == "gemini-live" and len(st.elder_turns()) == len(steps)
    end = client.post(f"/api/calls/{cid}/end").json()
    assert end["day"] is not None and end["today"]["calls"] >= 1
    assert end["voice"]["engine"] == "gemini-live" and end["voice"]["model"] == gl.DEFAULT_MODEL
    assert end["voice"]["latency_p50_ms"] is not None and end["voice"]["usage"]["total_tokens"] > 0
    row = sqlite3.connect(client.db_path).execute("SELECT engine, voice_json FROM call_session WHERE id=?",
                                                  (cid,)).fetchone()
    assert row[0] == "gemini-live" and json.loads(row[1])["engine"] == "gemini-live"


# ------------------------------------------------------------------------------------------- safety interception
def test_emergency_in_input_transcription_interrupts_and_raises_red_alert(client):
    svc = client.app.state.svc
    cid = start_live(client, sim=False)["call_id"]

    async def go():
        h = Harness(svc, cid)
        h.start()
        await h.until(lambda: h.count("agent_done") >= 1)
        await h.fake.elder_speaks("Dạ được con. Mà sáng nay tui bị tức ngực quá trời", chunks=4, respond=False)
        await h.ended()
        await h.finish()
        return h

    h = asyncio.run(go())
    kinds = [x["type"] for x in h.out]
    assert "interrupt" in kinds and kinds.index("interrupt") < kinds.index("ended")
    turn = h.of("turn")[-1]
    assert turn["emergency"] is True and turn["tier"] == "acute" and turn["end_call"] is True
    assert h.of("ended")[0]["reason"] == "emergency"
    # the model was told to say our fixed message, and the mic stream to Gemini was closed
    said = [v for k, v in h.fake.sent if k == "client_content"]
    assert "115" in said[-1] and said[-1].startswith("[HỆ THỐNG – KHẨN]")
    assert ("audio_stream_end", True) in h.fake.sent
    assert "115" in [x for x in h.of("transcript") if x["who"] == "agent" and x["final"]][-1]["text"]
    # no next_step was needed: the server caught it from the streaming transcription
    assert h.bridge.meta["tool_calls"].get("next_step", 0) == 0
    alerts = client.get("/api/elders/hanh/alerts").json()
    assert any(a["type"] == "emergency" and a["severity"] == "red" for a in alerts)
    end = client.post(f"/api/calls/{cid}/end").json()
    assert end["today"]["emergency"] is True


def test_emergency_while_model_speaks_drops_its_audio(client):
    svc = client.app.state.svc
    cid = start_live(client, sim=False)["call_id"]

    async def go():
        h = Harness(svc, cid, connector=fake_connector(chunk_delay=0.05))
        h.start()
        await h.until(lambda: h.audio_frames > 0)            # greeting still streaming
        await h.fake.elder_speaks("Tui té trong nhà tắm hổng đứng dậy được", respond=False)
        await h.ended()
        await h.finish()
        return h

    h = asyncio.run(go())
    assert h.of("turn")[-1]["tier"] == "acute"
    assert any(x["type"] == "interrupt" and x["reason"] == "safety" for x in h.out)
    finals = [x["text"] for x in h.of("transcript") if x["who"] == "agent" and x["final"]]
    assert finals and "115" in finals[-1]


def test_typed_emergency_and_safety_tts_fallback(client):
    """If Gemini never starts the safety message, the browser is told to say it itself."""
    svc = client.app.state.svc
    cid = start_live(client, sim=False)["call_id"]

    async def go():
        h = Harness(svc, cid, safety_tts_timeout=0.2)
        h.start()
        await h.until(lambda: h.count("agent_done") >= 1)
        h.fake.send_client_content = _mute_client_content    # model goes silent
        await h.inbox.put({"type": "text", "text": "Tui hổng muốn sống nữa con ơi"})
        await h.ended()
        await h.finish()
        return h

    async def _mute_client_content(**kw):
        return None

    h = asyncio.run(go())
    say = h.of("say")
    assert say and "115" in say[0]["text"] and h.bridge.meta["safety_tts_fallback"] is True
    assert h.of("turn")[-1]["emergency"] is True


def test_layer2_flag_emergency_tool(client):
    svc = client.app.state.svc
    cid = start_live(client, sim=False)["call_id"]

    async def go():
        h = Harness(svc, cid)
        h.start()
        await h.until(lambda: h.count("agent_done") >= 1)
        await h.fake.elder_speaks("Trong lồng ngực tui nó bóp nghẹt lại con ơi", respond=False)
        h.fake.model_calls("flag_emergency", {"category": "chest_pain", "quote": "bóp nghẹt", "acute": True})
        await h.ended()
        await h.finish()
        return h

    h = asyncio.run(go())
    assert h.of("turn")[-1]["emergency"] is True
    st = svc.active[cid]
    assert st.emergency_hits[-1]["layer"] == 2
    assert any(a["type"] == "emergency" for a in client.get("/api/elders/hanh/alerts").json())


def test_scam_and_diagnosis_guardrails_are_said_exactly(client):
    svc = client.app.state.svc
    cid = start_live(client, sim=False)["call_id"]

    async def go():
        h = Harness(svc, cid)
        h.start()
        await h.until(lambda: h.count("agent_done") >= 1)
        await h.inbox.put({"type": "text", "text": "Dạ được con."})
        await h.until(lambda: h.count("agent_done") >= 2)
        await h.inbox.put({"type": "text", "text": "Có người gọi xin mã OTP của tui đó con"})
        await h.until(lambda: h.count("agent_done") >= 3)
        await h.inbox.put({"type": "text", "text": "Tui bị bệnh tiểu đường hả con?"})
        await h.until(lambda: h.count("agent_done") >= 4)
        await h.finish()
        return h

    h = asyncio.run(go())
    steps = [v["response"] for k, v in h.fake.sent if k == "tool_response" and v["name"] == "next_step"]
    assert [s["mode"] for s in steps[-2:]] == ["exact", "exact"]
    events = [t["event"] for t in h.of("turn")]
    assert events[-2:] == ["scam", "diagnosis"]
    assert not h.bridge.meta["violations"]


def test_forbidden_output_phrase_is_interrupted_and_corrected(client):
    svc = client.app.state.svc
    cid = start_live(client, sim=False)["call_id"]

    async def go():
        h = Harness(svc, cid, connector=fake_connector(misbehave="chắc bà bị tiểu đường rồi"))
        h.start()
        await h.until(lambda: h.bridge.meta["violations"])
        await h.until(lambda: h.count("agent_done") >= 1)
        await h.finish()
        return h

    h = asyncio.run(go())
    v = h.bridge.meta["violations"][0]
    assert v["match"] == "tiểu đường"
    assert any(x["type"] == "interrupt" and x["reason"] == "correction" for x in h.out)
    said = [v for k, v in h.fake.sent if k == "client_content"]
    assert "kể thêm cho con nghe" in said[-1]                     # the neutral fallback sentence
    finals = [x["text"] for x in h.of("transcript") if x["who"] == "agent" and x["final"]]
    assert finals and "tiểu đường" not in finals[-1]
    assert "tiểu đường" not in svc.active[cid].turns[0].text      # the transcript keeps the correction


def test_barge_in_forwards_interrupt(client):
    svc = client.app.state.svc
    cid = start_live(client, sim=False)["call_id"]

    async def go():
        h = Harness(svc, cid, connector=fake_connector(chunk_delay=0.05))
        h.start()
        await h.until(lambda: h.audio_frames > 0)
        await h.fake.elder_speaks("Dạ được con", respond=True)
        await h.until(lambda: h.count("turn") >= 1)
        await h.finish()
        return h

    h = asyncio.run(go())
    assert any(x["type"] == "interrupt" and x["reason"] == "barge_in" for x in h.out)
    assert h.bridge.meta["interruptions"] >= 1


def test_vad_events_give_turn_timings_and_latency(client):
    svc = client.app.state.svc
    cid = start_live(client, sim=False)["call_id"]

    async def go():
        h = Harness(svc, cid)
        h.start()
        await h.until(lambda: h.count("agent_done") >= 1)
        for kind, t in (("speech", 12.0), ("silence", 13.1), ("speech", 13.9), ("silence", 15.5)):
            await h.inbox.put({"type": "vad", "state": kind, "t": t})
        await h.inbox.put(b"\x00\x01" * 800)                  # one 50 ms mic frame (counted, never kept)
        await asyncio.sleep(0.05)
        await h.fake.elder_speaks("Dạ được con, rảnh mà", respond=True)
        await h.until(lambda: h.count("agent_done") >= 2)
        await h.finish()
        return h

    h = asyncio.run(go())
    t = svc.active[cid].elder_turns()[0]
    assert (t.start, t.end, t.pauses) == (12.0, 15.5, [0.8])
    assert h.bridge.meta["latency_ms"] and h.bridge.meta["audio_in_bytes"] == 1600


def test_fallback_when_connect_fails(client):
    svc = client.app.state.svc
    cid = start_live(client, sim=False)["call_id"]

    async def go():
        h = Harness(svc, cid, connector=gl.failing_connector())
        h.start()
        await asyncio.wait_for(h.task, 5)
        return h

    h = asyncio.run(go())
    assert h.out[0]["type"] == "fallback" and h.out[0]["reason"].startswith("connect_failed")
    st = svc.active[cid]
    assert st.engine_used == "gemini-live>browser"
    # the same call carries on with the browser pipeline (POST /turns) and ends normally
    r = client.post(f"/api/calls/{cid}/turns", json={"text": "Dạ được con", "start": 5, "end": 7}).json()
    assert r["reply_text"] and not r["end_call"]
    end = client.post(f"/api/calls/{cid}/end").json()
    assert end["voice"]["fallback"].startswith("connect_failed")


def test_no_audio_is_persisted(client):
    svc = client.app.state.svc
    cid = start_live(client, sim=False)["call_id"]

    async def go():
        h = Harness(svc, cid)
        h.start()
        await h.until(lambda: h.count("agent_done") >= 1)
        for _ in range(20):
            await h.inbox.put(bytes(range(256)) * 12)            # mic frames
        await h.fake.elder_speaks("Dạ rảnh con", respond=True)
        await h.until(lambda: h.count("agent_done") >= 2)
        await h.finish()
        return h

    h = asyncio.run(go())
    client.post(f"/api/calls/{cid}/end")
    assert h.bridge.meta["audio_in_bytes"] == 20 * 3072 and h.bridge.meta["audio_out_bytes"] > 0
    assert all(isinstance(v, int) for k, v in h.fake.sent if k == "audio")      # lengths only
    con = sqlite3.connect(client.db_path)
    for (table,) in con.execute("SELECT name FROM sqlite_master WHERE type='table'"):
        cols = [r[1] for r in con.execute(f"PRAGMA table_info({table})")]
        for col in cols:
            n = con.execute(f"SELECT COUNT(*) FROM {table} WHERE typeof({col})='blob'").fetchone()[0]
            assert n == 0, f"binary data in {table}.{col}"
        assert not any("audio" in c and c != "audio" for c in cols if c not in ("voice_json",))
    voice = json.loads(con.execute("SELECT voice_json FROM call_session WHERE id=?", (cid,)).fetchone()[0])
    assert voice["audio_stored"] is False and len(json.dumps(voice)) < 20000


# ------------------------------------------------------------------------------------------- HTTP + WebSocket
def test_websocket_end_to_end_with_fake(client):
    cid = start_live(client)["call_id"]
    svc = client.app.state.svc
    got: list[dict] = []
    audio = 0
    with client.websocket_connect(f"/ws/voice/{cid}") as ws:
        def pump_until(pred, limit=4000):
            nonlocal audio
            for _ in range(limit):
                m = ws.receive()
                if m.get("bytes") is not None:
                    audio += 1
                    continue
                d = json.loads(m["text"])
                got.append(d)
                if pred(d):
                    return d
            raise AssertionError("no message")

        ready = pump_until(lambda d: d["type"] == "ready")
        assert ready["model"] == gl.DEFAULT_MODEL and ready["output_rate"] == 24000
        for i in range(30):
            d = pump_until(lambda d: d["type"] in ("agent_done", "ended"))
            if d["type"] == "ended":
                break
            line = svc.simulate_elder(cid)
            ws.send_text(json.dumps({"type": "text", "text": line["text"], "start": 10 * i + 1,
                                     "end": 10 * i + 1 + line.get("duration_sec", 5), "pauses": line["pauses"]}))
        assert d["type"] == "ended" and d["reason"] == "completed"
    assert audio > 0 and FRAME_BYTES == 4800
    end = client.post(f"/api/calls/{cid}/end").json()
    assert end["voice"]["engine"] == "gemini-live" and end["today"]["calls"] >= 1


def test_websocket_rejects_browser_calls_and_reports_missing_credentials(client, monkeypatch):
    cid = client.post("/api/calls", json={"elder_id": "hanh", "engine": "browser"}).json()["call_id"]
    with client.websocket_connect(f"/ws/voice/{cid}") as ws:
        assert json.loads(ws.receive_text())["error"] == "unknown_call"
    monkeypatch.delenv("CHAOBA_GEMINI_FAKE")
    r = client.post("/api/calls", json={"elder_id": "hanh", "engine": "gemini"}).json()
    assert r["voice"]["engine"] == "browser" and "note_vi" in r["voice"] and r["engine"] == "scripted"
    cfg = client.get("/api/voice/config").json()
    assert cfg["default_engine"] == "browser" and cfg["gemini"]["available"] is False
    assert "voice_engine" in client.get("/api/elders/hanh/privacy").json()["data_retention"]


def test_fake_fail_mode_falls_back_over_websocket(client, monkeypatch):
    monkeypatch.setenv("CHAOBA_GEMINI_FAKE", "fail")
    cid = start_live(client, sim=False)["call_id"]
    with client.websocket_connect(f"/ws/voice/{cid}") as ws:
        d = json.loads(ws.receive_text())
    assert d["type"] == "fallback" and d["note_vi"]
    assert voice_mod.CONNECTOR_FACTORY is None


# ------------------------------------------------------------------------------------------- benchmark harness
def test_voice_bench_without_credentials_exits_cleanly(tmp_path):
    import os
    import subprocess
    import sys
    from pathlib import Path
    root = Path(__file__).resolve().parents[2]
    env = {k: v for k, v in os.environ.items() if k not in GEMINI_ENV}
    p = subprocess.run([sys.executable, str(root / "scripts" / "voice_bench.py"), "--out", str(tmp_path / "b.json")],
                       env=env, capture_output=True, text=True, timeout=60)
    assert p.returncode == 2 and "no Gemini credentials" in p.stderr
    p = subprocess.run([sys.executable, str(root / "scripts" / "voice_bench.py"), "--fake", "--calls", "1",
                        "--out", str(tmp_path / "b.json")], env=env, capture_output=True, text=True, timeout=120)
    assert p.returncode == 0, p.stderr
    rep = json.loads((tmp_path / "b.json").read_text())
    assert rep["summary"]["calls_completed"] == 1 and rep["summary"]["safety_server_ok"] == "9/9"
    assert rep["summary"]["emergency_said_115"] == "3/3"
    assert rep["cost"]["pricing"]["status"] == "to verify"


def test_layer2_non_acute_flag_asks_one_confirming_question(client):
    svc = client.app.state.svc
    cid = start_live(client, sim=False)["call_id"]

    async def go():
        h = Harness(svc, cid)
        h.start()
        await h.until(lambda: h.count("agent_done") >= 1)
        await h.fake.elder_speaks("Tuần rồi tui thấy lồng ngực hơi bóp lại một chút", respond=False)
        h.fake.model_calls("flag_emergency", {"category": "chest_pain", "quote": "lồng ngực hơi bóp", "acute": False})
        await h.until(lambda: h.count("agent_done") >= 2)
        await h.finish()
        return h

    h = asyncio.run(go())
    turn = h.of("turn")[-1]
    assert turn["event"] == "health_concern" and turn["tier"] == "non_acute" and not turn["end_call"]
    resp = [v["response"] for k, v in h.fake.sent if k == "tool_response" and v["name"] == "flag_emergency"][-1]
    assert resp["mode"] == "exact" and "đang đau" in resp["line"]
    assert any(a["type"] == "health_concern" for a in client.get("/api/elders/hanh/alerts").json())
