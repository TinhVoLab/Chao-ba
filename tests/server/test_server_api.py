import pytest
from fastapi.testclient import TestClient

from chaoba.server.app import create_app
from chaoba.agent.textnorm import word_count


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    app = create_app(str(tmp_path / "t.db"))
    with TestClient(app) as c:
        yield c


def run_simulated_call(c, elder="hanh"):
    r = c.post("/api/calls", json={"elder_id": elder, "channel": "web"})
    assert r.status_code == 200
    call = r.json()
    assert call["greeting_text"] and call["phase"] == "greeting"
    cid, t = call["call_id"], 12.0
    replies = []
    for _ in range(25):
        line = c.get(f"/api/calls/{cid}/simulate").json()
        dur = line.get("duration_sec") or word_count(line["text"]) / 3.8 + sum(line["pauses"])
        out = c.post(f"/api/calls/{cid}/turns", json={"text": line["text"], "start": t, "end": t + dur,
                                                      "pauses": line["pauses"]}).json()
        replies.append(out)
        t += dur + 6
        if out["end_call"]:
            break
    return cid, replies


def test_health_and_seed(client):
    assert client.get("/api/health").json() == {"ok": True, "llm": "fallback"}
    elders = client.get("/api/elders").json()
    assert {e["id"] for e in elders} == {"hanh", "tu", "control"}
    assert all(e["simulated"] and e["light"] in ("green", "yellow", "red", "gray") for e in elders)


def test_seed_is_idempotent(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    path = str(tmp_path / "x.db")
    for _ in range(2):
        with TestClient(create_app(path)) as c:
            n = len(c.get("/api/elders/hanh/timeline?days=365").json()["records"])
            alerts = len(c.get("/api/elders/hanh/alerts").json())
    assert n == 90 and alerts > 0


def test_family_read_endpoints(client):
    p = client.get("/api/elders/hanh").json()
    assert p["display_name"] == "Bà Hạnh" and p["simulated"] is True
    t = client.get("/api/elders/hanh/today").json()
    for k in ("date", "day", "light", "reasons", "explanation_vi", "explanation_en", "summary_vi", "summary_en",
              "answered", "mood", "simulated"):
        assert k in t
    assert t["day"] == 90 and t["simulated"] is True
    tl = client.get("/api/elders/hanh/timeline?days=30").json()
    assert len(tl["records"]) == 30 and tl["lights"] and tl["baseline"] and "events" in tl
    assert set(tl["baseline"]["speech_rate_sps"]) >= {"center", "scale"}
    alerts = client.get("/api/elders/hanh/alerts").json()
    a = alerts[0]
    assert {"id", "day", "date", "type", "severity", "explanation_vi", "explanation_en", "acknowledged"} <= set(a)
    unacked = [x for x in alerts if not x["acknowledged"]] or alerts
    r = client.post(f"/api/elders/hanh/alerts/{unacked[0]['id']}/ack")
    assert r.status_code == 200
    assert next(x for x in client.get("/api/elders/hanh/alerts").json() if x["id"] == unacked[0]["id"])["acknowledged"]
    d = client.get("/api/elders/hanh/dmaic").json()
    assert [ph["phase"] for ph in d["phases"]][:2] == ["define", "measure"] and "effect" in d
    assert d["intervention_day"] == 44
    n = client.post("/api/elders/hanh/notes", json={"author": "Lan", "text": "Con gọi má rồi."})
    assert n.status_code == 200
    assert client.get("/api/elders/hanh/notes").json()[0]["text"] == "Con gọi má rồi."
    pr = client.get("/api/elders/hanh/privacy", headers={"X-Actor": "Lan", "X-Role": "primary"}).json()
    assert pr["data_retention"] == pr["data_retention"] | {"audio": "not stored", "transcript_days": 7}
    assert pr["consents"] and pr["access_log"]
    assert any(x["action"] == "read_today" for x in pr["access_log"])
    assert pr["access_log"][0]["actor"] == "Lan"
    assert client.get("/api/elders/nobody/today").status_code == 404


def test_cors_for_family_app(client):
    r = client.get("/api/elders", headers={"Origin": "http://localhost:3000"})
    assert r.headers.get("access-control-allow-origin") == "http://localhost:3000"


def test_call_page_served(client):
    r = client.get("/call?elder=hanh")
    assert r.status_code == 200 and "SpeechRecognition" in r.text and "Không lưu ghi âm" in r.text


def test_full_web_call_appends_day_91(client):
    cid, replies = run_simulated_call(client)
    assert replies[-1]["end_call"] and not any(r["emergency"] for r in replies)
    phases = [r["phase"] for r in replies]
    for ph in ("wellbeing", "recall", "story", "closing"):
        assert ph in phases
    out = client.post(f"/api/calls/{cid}/end").json()
    m, a, today = out["metrics"], out["analysis"], out["today"]
    assert m["valid"] and m["speech_rate_sps"] > 0 and m["word_count"] > 60
    assert a["recall_score"] == 1 and a["recall_cue_level"] == "cued"
    assert today["day"] == 91 and today["simulated"] is True and today["light"] != "gray"
    tl = client.get("/api/elders/hanh/timeline?days=90").json()
    last = tl["records"][-1]
    assert last["day"] == 91 and last["channel"] == "web" and last["simulated"] is True  # scripted elder → stored as simulated
    assert tl["lights"][-1]["day"] == 91
    # idempotent end, finished call rejects turns
    assert client.post(f"/api/calls/{cid}/end").json()["today"]["day"] == 91
    assert client.post(f"/api/calls/{cid}/turns", json={"text": "alo"}).status_code == 404
    # a second call on the same date is a sub-call of day 91 (never a future-dated day 92)
    cid2, _ = run_simulated_call(client)
    t2 = client.post(f"/api/calls/{cid2}/end").json()["today"]
    assert t2["day"] == 91 and t2["calls"] == 2 and t2["is_today"] is True


def test_emergency_call_creates_red_alert(client):
    cid = client.post("/api/calls", json={"elder_id": "tu", "channel": "web"}).json()["call_id"]
    client.post(f"/api/calls/{cid}/turns", json={"text": "Dạ được con.", "start": 5, "end": 7})
    r = client.post(f"/api/calls/{cid}/turns", json={"text": "Hồi sáng tui bị té ngoài sân, đau quá.",
                                                    "start": 12, "end": 16, "pauses": []}).json()
    assert r["emergency"] and r["end_call"] and "115" in r["reply_text"]
    alerts = client.get("/api/elders/tu/alerts").json()
    assert alerts[0]["type"] == "emergency" and alerts[0]["severity"] == "red" and not alerts[0]["acknowledged"]
    out = client.post(f"/api/calls/{cid}/end").json()
    assert out["analysis"]["emergency"] and out["today"]["light"] == "red"
    assert out["today"]["reasons"][0]["code"] == "emergency"
    assert len([a for a in client.get("/api/elders/tu/alerts").json() if a["type"] == "emergency"]) == 1


def test_opt_out_stops_scheduling(client):
    cid = client.post("/api/calls", json={"elder_id": "control"}).json()["call_id"]
    client.post(f"/api/calls/{cid}/turns", json={"text": "Dạ được."})
    client.post(f"/api/calls/{cid}/turns", json={"text": "Thôi đừng gọi nữa con."})
    r = client.post(f"/api/calls/{cid}/turns", json={"text": "Ừ đúng rồi."}).json()
    assert r["end_call"] and r["event"] == "opt_out"
    client.post(f"/api/calls/{cid}/end")
    pr = client.get("/api/elders/control/privacy").json()
    assert pr["scheduling_active"] is False
    assert any(c["kind"] == "daily_call" and not c["granted"] for c in pr["consents"])
    assert client.post("/api/calls", json={"elder_id": "control"}).status_code == 409
    assert any(a["type"] == "opt_out" for a in client.get("/api/elders/control/alerts").json())
    client.post("/api/elders/control/resume")
    assert client.post("/api/calls", json={"elder_id": "control"}).status_code == 200


def test_scam_topic_alerts_family(client):
    cid = client.post("/api/calls", json={"elder_id": "hanh"}).json()["call_id"]
    client.post(f"/api/calls/{cid}/turns", json={"text": "Dạ được."})
    r = client.post(f"/api/calls/{cid}/turns", json={"text": "Có ai gọi kêu tui đọc mã OTP để nhận quà."}).json()
    assert r["event"] == "scam"
    client.post(f"/api/calls/{cid}/end")
    assert any(a["type"] == "scam_topic" for a in client.get("/api/elders/hanh/alerts").json())


def test_no_audio_anywhere(client):
    svc = client.app.state.svc
    cols = [r["name"] for t in ("call_session", "call_analysis", "metric_daily")
            for r in svc.store.q(f"PRAGMA table_info({t})")]
    assert not any("audio" in c or "recording" in c for c in cols)
    sql = open("chaoba/server/schema.sql").read().lower()
    assert "audio " not in sql.replace("no audio", "").replace("deliberately no audio", "")


def test_evaluation_endpoint(client):
    r = client.get("/api/evaluation")
    assert r.status_code == 200 and isinstance(r.json(), dict)


def test_opt_out_appends_no_day(client):
    cid = client.post("/api/calls", json={"elder_id": "hanh"}).json()["call_id"]
    client.post(f"/api/calls/{cid}/turns", json={"text": "Dạ được."})
    client.post(f"/api/calls/{cid}/turns", json={"text": "Đừng gọi nữa con."})
    client.post(f"/api/calls/{cid}/turns", json={"text": "Ừ, đúng rồi."})
    out = client.post(f"/api/calls/{cid}/end").json()
    assert out["day"] is None and out["today"]["day"] == 90
    assert client.get("/api/elders/hanh/timeline?days=5").json()["records"][-1]["day"] == 90


def test_declined_consent_appends_unanswered_day(client):
    cid = client.post("/api/calls", json={"elder_id": "hanh"}).json()["call_id"]
    r = client.post(f"/api/calls/{cid}/turns", json={"text": "Thôi để sau đi con, bà đang bận."}).json()
    assert r["end_call"] and r["event"] == "declined"
    out = client.post(f"/api/calls/{cid}/end").json()
    assert out["day"] == 91 and out["today"]["answered"] is False
    last = client.get("/api/elders/hanh/timeline?days=1").json()["records"][-1]
    assert last["answered"] is False and last["valid"] is False and last["mood"] is None
    assert last["speech_rate_sps"] is None and last["channel"] == "web" and last["simulated"] is False


def test_silence_only_call_is_unanswered(client):
    cid = client.post("/api/calls", json={"elder_id": "tu"}).json()["call_id"]
    client.post(f"/api/calls/{cid}/turns", json={"text": "", "start": 30, "end": 30})
    out = client.post(f"/api/calls/{cid}/end").json()
    assert out["today"]["answered"] is False


def test_call_without_elder_turns_appends_nothing(client):
    cid = client.post("/api/calls", json={"elder_id": "tu"}).json()["call_id"]
    out = client.post(f"/api/calls/{cid}/end").json()
    assert out["day"] is None and out["today"]["day"] == 90


def test_typed_web_call_is_stored_as_live_data(client):
    """A call whose elder side is not scripted is real data (simulated False); sim calls are flagged True."""
    cid = client.post("/api/calls", json={"elder_id": "control", "channel": "web"}).json()["call_id"]
    t = 0.0
    for text in ["Dạ con chào, bà khỏe", "Tối qua ngủ ngon lắm con, sáng ăn cháo với cá kho",
                 "Hôm qua đi chợ mua rau, gặp bà Tư hàng xóm nói chuyện lâu lắm",
                 "Ừ để tôi kể con nghe hồi xưa tôi làm ruộng ở Cần Thơ, cực mà vui lắm con",
                 "Dạ nhớ rồi, cảm ơn con nha"]:
        client.post(f"/api/calls/{cid}/turns", json={"text": text, "start": t, "end": t + 12, "pauses": [0.6]})
        t += 15
    out = client.post(f"/api/calls/{cid}/end").json()
    assert out["simulated"] is False
    sim = client.post("/api/calls", json={"elder_id": "control", "channel": "web", "simulated": True}).json()["call_id"]
    client.post(f"/api/calls/{sim}/turns", json={"text": "Dạ con chào", "start": 0, "end": 2, "pauses": []})
    assert client.post(f"/api/calls/{sim}/end").json()["simulated"] is True


def test_calendar_anchor_day_90_is_yesterday(client):
    from datetime import date, timedelta
    t = client.get("/api/elders/hanh/today").json()
    assert t["day"] == 90 and t["date"] == (date.today() - timedelta(days=1)).isoformat()
    notes = client.get("/api/elders/hanh/notes").json()
    assert all(n["date"] for n in notes if n["day"] is not None)
    n30 = next(n for n in notes if n["day"] == 30)
    assert n30["date"] == (date.today() - timedelta(days=61)).isoformat()


def test_contact_log_and_nudge(client):
    t = client.get("/api/elders/hanh/today").json()
    assert t["contact"]["days_since"] == 5 and t["contact"]["nudge"] is True
    assert client.get("/api/elders/tu/today").json()["contact"]["nudge"] is False
    cs = client.get("/api/elders/hanh/contacts").json()
    assert cs["contacts"][-1]["day"] == 85 and cs["contacts"][-1]["simulated"] is True
    r = client.post("/api/elders/hanh/contacts", json={"kind": "call", "member_id": "lan"})
    assert r.status_code == 200 and r.json()["member_name"] == "Lan"
    t = client.get("/api/elders/hanh/today").json()
    assert t["contact"]["days_since"] == 0 and not t["contact"]["nudge"]
    assert client.post("/api/elders/hanh/contacts", json={"kind": "telepathy"}).status_code == 422
    d = client.get("/api/elders/hanh/dmaic").json()
    assert d["contact"]["post_per_week"] > d["contact"]["pre_per_week"]


def test_dmaic_phase_status(client):
    st = {p["phase"]: p for p in client.get("/api/elders/tu/dmaic").json()["phases"]}
    assert st["analyze"]["status"] == "current"
    assert st["improve"]["status"] == "not_started" and st["improve"]["day_from"] is None
    st = {p["phase"]: p["status"] for p in client.get("/api/elders/hanh/dmaic").json()["phases"]}
    assert st == {"define": "done", "measure": "done", "analyze": "done", "improve": "done", "control": "current"}


def test_timeline_baseline_history(client):
    tl = client.get("/api/elders/hanh/timeline?days=90").json()
    b = tl["baselines"]
    assert len(b) == 2 and b[0]["window"] == [1, 21] and b[1]["from_day"] == 77 and b[0]["to_day"] == 76
    assert b[1]["metrics"]["speech_rate_sps"]["center"] == tl["baseline"]["speech_rate_sps"]["center"]
    assert len(client.get("/api/elders/tu/timeline?days=90").json()["baselines"]) == 1


def test_alert_severity_level(client):
    for a in client.get("/api/elders/hanh/alerts").json():
        assert a["severity_level"] == {"red": "critical", "yellow": "warning"}[a["severity"]]


def test_access_log_dedupes_reads(client):
    h = {"X-Actor": "Lan", "X-Role": "primary"}
    for _ in range(5):
        client.get("/api/elders/hanh/today", headers=h)
    client.post("/api/elders/hanh/notes", json={"author": "Lan", "text": "a"}, headers=h)
    client.post("/api/elders/hanh/notes", json={"author": "Lan", "text": "b"}, headers=h)
    log = client.get("/api/elders/hanh/privacy", headers=h).json()["access_log"]
    reads = [x for x in log if x["action"] == "read_today" and x["actor"] == "Lan"]
    assert len(reads) == 1 and reads[0]["count"] == 5
    assert len([x for x in log if x["action"] == "write_note"]) == 2


def test_consent_withdraw_and_regrant(client):
    r = client.post("/api/elders/control/consents/daily_call/withdraw", headers={"X-Actor": "Th%E1%BA%A3o"})
    assert r.status_code == 400 and r.json()["detail"]["field"] == "confirmed_by_elder_or_proxy"
    r = client.post("/api/elders/control/consents/daily_call/withdraw", headers={"X-Actor": "Th%E1%BA%A3o"},
                    json={"confirmed_by_elder_or_proxy": True})
    assert r.status_code == 200 and r.json()["scheduling_active"] is False and r.json()["requested_by"] == "Thảo"
    pr = client.get("/api/elders/control/privacy").json()
    dc = next(c for c in pr["consents"] if c["kind"] == "daily_call")
    assert dc["status"] == "withdrawn" and pr["scheduling_active"] is False
    assert dc["requested_by"] == "Thảo" and dc["confirmed_by_elder_or_proxy"] is True
    assert len([c for c in pr["consents"] if c["kind"] == "daily_call"]) == 1 and len(pr["consent_history"]) == 6
    assert client.post("/api/calls", json={"elder_id": "control"}).status_code == 409
    client.post("/api/elders/control/resume")
    assert client.post("/api/calls", json={"elder_id": "control"}).status_code == 200
    # family_sharing: the family app stops receiving health data until re-granted
    client.post("/api/elders/control/consents/family_sharing/withdraw", json={"confirmed_by_elder_or_proxy": True})
    t = client.get("/api/elders/control/today").json()
    assert t["sharing_paused"] and t["light"] == "gray" and t["summary_vi"] == ""
    assert client.get("/api/elders/control/timeline").json()["records"] == []
    assert client.get("/api/elders/control/alerts").json() == []
    assert next(e for e in client.get("/api/elders").json() if e["id"] == "control")["light"] == "gray"
    client.post("/api/elders/control/consents/family_sharing/grant")
    assert client.get("/api/elders/control/timeline").json()["records"]
    assert client.post("/api/elders/control/consents/nope/withdraw").status_code == 404


def test_voice_metrics_withdrawn_stores_no_speech_metrics(client):
    client.post("/api/elders/hanh/consents/voice_metrics/withdraw", headers={"X-Role": "elder_self"})
    cid, _ = run_simulated_call(client)
    client.post(f"/api/calls/{cid}/end")
    last = client.get("/api/elders/hanh/timeline?days=1").json()["records"][-1]
    assert last["day"] == 91 and last["answered"] and last["speech_rate_sps"] is None and last["mattr"] is None


def test_percent_encoded_actor_is_decoded(client):
    client.get("/api/elders/control/today", headers={"X-Actor": "Th%E1%BA%A3o", "X-Role": "primary"})
    log = client.get("/api/elders/control/privacy").json()["access_log"]
    assert any(x["actor"] == "Thảo" and x["action"] == "read_today" for x in log)
