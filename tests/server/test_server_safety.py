"""Calendar (no future dates, same-day sub-calls), rehearsal exclusion, persisted emergency, tiered alerts,
/today labels, demo reset, CORS, quote retention."""
from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from chaoba.server.app import create_app
from chaoba.server.service import merge_day

from test_server_api import run_simulated_call  # noqa: E402  (same directory)

TODAY = date.today().isoformat()


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("CHAOBA_CORS_ORIGINS", raising=False)
    monkeypatch.delenv("CHAOBA_DEMO", raising=False)
    with TestClient(create_app(str(tmp_path / "s.db"))) as c:
        yield c


def typed_call(c, elder, lines, sim=False):
    cid = c.post("/api/calls", json={"elder_id": elder, "channel": "web", "simulated": sim}).json()["call_id"]
    outs, t = [], 0.0
    for text in lines:
        r = c.post(f"/api/calls/{cid}/turns", json={"text": text, "start": t, "end": t + 8, "pauses": [0.6]}).json()
        outs.append(r)
        t += 10
        if r["end_call"]:
            break
    return cid, outs, c.post(f"/api/calls/{cid}/end").json()


def records(c, elder, days=5):
    return c.get(f"/api/elders/{elder}/timeline?days={days}").json()["records"]


def test_no_future_dates_and_same_day_calls_merge(client):
    for _ in range(3):
        cid, _ = run_simulated_call(client)
        client.post(f"/api/calls/{cid}/end")
    typed_call(client, "hanh", ["Dạ được con", "Ngủ ngon lắm con"])
    recs = records(client, "hanh", 3)
    assert recs[-1]["day"] == 91 and recs[-1]["date"] == TODAY
    assert all(r["date"] <= TODAY for r in records(client, "hanh", 400))
    assert recs[-1]["simulated"] is False and recs[-1]["calls"] == 1   # a real call replaces the rehearsals
    for a in client.get("/api/elders/hanh/alerts").json():
        assert a["date"] <= TODAY


def test_rehearsals_do_not_change_hanh_light(client):
    before = client.get("/api/elders/hanh/today").json()
    assert before["light"] == "green"
    for _ in range(3):
        cid, _ = run_simulated_call(client)
        out = client.post(f"/api/calls/{cid}/end").json()
        assert out["rehearsal"] is True
    t = client.get("/api/elders/hanh/today").json()
    assert t["light"] == "green" and t["rehearsal"] is True and t["calls"] == 3
    assert t["reasons"][-1]["code"] == "rehearsal_not_scored" and "diễn tập" in t["explanation_vi"]
    # and the stored record is still displayed (timeline), with the rehearsal's metrics
    last = records(client, "hanh", 1)[-1]
    assert last["simulated"] is True and last["channel"] == "web" and last["speech_rate_sps"]


def test_simulate_endpoint_is_calibrated_to_baseline(client):
    base = client.get("/api/elders/hanh/timeline?days=1").json()["baseline"]["speech_rate_sps"]["center"]
    cid = client.post("/api/calls", json={"elder_id": "hanh", "simulated": True}).json()["call_id"]
    line = client.get(f"/api/calls/{cid}/simulate").json()
    assert abs(line["target_sps"] - base) < 0.01 and line["duration_sec"] > 0 and line["simulated"]


def test_emergency_persists_after_a_later_call(client):
    _, outs, end = typed_call(client, "control", ["Dạ được con", "Sáng nay tui bị té trong nhà tắm"])
    assert outs[-1]["emergency"] and outs[-1]["tier"] == "acute"
    assert end["today"]["light"] == "red" and end["today"]["reasons"][0]["code"] == "emergency"
    rec = records(client, "control", 1)[-1]
    assert rec["emergency"] is True
    # a later ordinary call the same day: still red, emergency kept on the record and in the reasons
    _, _, end2 = typed_call(client, "control", ["Dạ được con", "Ngủ ngon lắm con", "Ăn cháo rồi con"])
    t = end2["today"]
    assert t["day"] == 91 and t["calls"] == 2 and t["light"] == "red" and t["emergency"] is True
    assert "emergency" in {r["code"] for r in t["reasons"]}
    assert len([a for a in client.get("/api/elders/control/alerts").json() if a["type"] == "emergency"]) == 1


def test_non_acute_concern_red_check_in_today_no_115(client):
    _, outs, end = typed_call(client, "control", ["Dạ được con", "hôm qua tui hơi tức ngực", "Dạ hổng có"])
    assert outs[1]["tier"] == "non_acute" and not outs[1]["emergency"] and "115" not in outs[1]["reply_text"]
    alerts = client.get("/api/elders/control/alerts").json()
    hc = [a for a in alerts if a["type"] == "health_concern"]
    assert len(hc) == 1 and hc[0]["severity"] == "red" and "115" in hc[0]["explanation_vi"]  # "không ... gọi 115"
    assert "hôm nay" in hc[0]["explanation_vi"] and not [a for a in alerts if a["type"] == "emergency"]
    t = end["today"]
    assert t["light"] == "red" and t["reasons"][0]["code"] == "health_concern" and not t["emergency"]
    assert records(client, "control", 1)[-1]["symptoms"].get("concern:chest_pain") == 1


def test_non_acute_fall_confirmed_becomes_emergency(client):
    _, outs, end = typed_call(client, "control", ["Dạ được con", "Tui bị ngã cầu thang hôm qua", "Dạ có, còn đau lắm"])
    assert outs[1]["tier"] == "non_acute" and outs[2]["emergency"] and "115" in outs[2]["reply_text"]
    types = [a["type"] for a in client.get("/api/elders/control/alerts").json()]
    assert "emergency" in types and "health_concern" in types


def test_third_party_fall_leaves_the_elder_alone(client):
    before = client.get("/api/elders/control/alerts").json()
    _, outs, end = typed_call(client, "control", ["Dạ được con", "Hôm qua thằng cháu té xe trầy chân",
                                                  "Ngủ ngon lắm con"])
    assert outs[1]["tier"] == "third_party" and not outs[1]["emergency"] and "115" not in outs[1]["reply_text"]
    assert client.get("/api/elders/control/alerts").json() == before
    assert end["today"]["light"] != "red" and "fall" not in end["analysis"]["symptoms"]


def test_today_label(client):
    t = client.get("/api/elders/hanh/today").json()
    yday = date.today() - timedelta(days=1)
    assert t["is_today"] is False and t["label_vi"] == f"Cuộc gọi hôm qua ({yday.day:02d}/{yday.month:02d})"
    assert t["label_en"].startswith("Yesterday's call (")
    typed_call(client, "hanh", ["Dạ được con", "Ngủ ngon lắm con"])
    t = client.get("/api/elders/hanh/today").json()
    assert t["is_today"] is True and t["label_vi"] == "Cuộc gọi sáng nay" and t["label_en"] == "This morning's call"


def test_demo_reset(client, monkeypatch):
    typed_call(client, "hanh", ["Dạ được con", "Ngủ ngon lắm con"])
    assert records(client, "hanh", 1)[-1]["day"] == 91
    r = client.post("/api/demo/reset?elder=hanh")
    assert r.status_code == 200 and r.json()["reset"] == "hanh"
    assert records(client, "hanh", 1)[-1]["day"] == 90
    assert client.get("/api/elders/hanh/today").json()["light"] == "green"
    assert client.post("/api/demo/reset").json()["reset"] == "all"
    monkeypatch.setenv("CHAOBA_DEMO", "0")
    assert client.post("/api/demo/reset").status_code == 403


def test_cors_any_localhost_port_by_default(client):
    for origin in ("http://localhost:3000", "http://localhost:3001", "http://127.0.0.1:5173"):
        r = client.get("/api/elders", headers={"Origin": origin})
        assert r.headers.get("access-control-allow-origin") == origin
    assert "access-control-allow-origin" not in client.get("/api/elders", headers={"Origin": "https://evil.example"}).headers


def test_cors_from_env(tmp_path, monkeypatch):
    monkeypatch.setenv("CHAOBA_CORS_ORIGINS", "https://app.chaoba.vn, https://demo.chaoba.vn")
    with TestClient(create_app(str(tmp_path / "c.db"))) as c:
        ok = c.get("/api/elders", headers={"Origin": "https://demo.chaoba.vn"})
        assert ok.headers.get("access-control-allow-origin") == "https://demo.chaoba.vn"
        assert "access-control-allow-origin" not in c.get("/api/elders", headers={"Origin": "http://localhost:3000"}).headers


def test_quotes_purged_after_30_days(client):
    typed_call(client, "control", ["Dạ được con", "Sáng nay tui bị té trong nhà tắm"])
    store = client.app.state.svc.store
    assert store.purge_quotes() == 0                           # fresh quotes are kept
    later = datetime.now(timezone.utc) + timedelta(days=31)
    assert store.purge_quotes(now=later) >= 2
    a = next(x for x in client.get("/api/elders/control/alerts").json() if x["type"] == "emergency")
    assert "nhà tắm" not in a["explanation_vi"] and "[đã xoá sau 30 ngày]" in a["explanation_vi"]
    an = store.last_analyses("control", 1)[0]
    assert an["quotes_purged"] and all(v == ["[đã xoá sau 30 ngày]"] * len(v) for v in an["symptoms"].values())
    assert store.purge_quotes(now=later) == 0                  # idempotent
    assert client.get("/api/elders/control/privacy").json()["data_retention"]["quote_days"] == 30


def test_consent_withdraw_by_elder_needs_no_proxy_confirmation(client):
    r = client.post("/api/elders/tu/consents/research_use/withdraw", headers={"X-Role": "elder_self"})
    assert r.status_code == 200 and r.json()["confirmed_by_elder_or_proxy"] is True


def test_merge_day_rules():
    real = {"elder_id": "x", "day": 91, "date": TODAY, "channel": "web", "simulated": False, "answered": True,
            "valid": True, "speech_rate_sps": 4.0, "symptoms": {"pain": 1}, "emergency": True, "mood": 3,
            "summary_vi": "A", "summary_en": "A"}
    sim = dict(real, simulated=True, speech_rate_sps=3.0, emergency=False, symptoms={})
    assert merge_day(real, sim) is real                      # rehearsal never overwrites real data
    assert merge_day(sim, real)["speech_rate_sps"] == 4.0    # real replaces rehearsal
    later = dict(real, valid=False, speech_rate_sps=None, emergency=False, symptoms={"pain": 1, "insomnia": 1},
                 mood=4, summary_vi="B")
    m = merge_day(real, later)
    assert m["speech_rate_sps"] == 4.0 and m["valid"] and m["emergency"] and m["calls"] == 2
    assert m["symptoms"] == {"pain": 1, "insomnia": 1} and m["mood"] == 4 and "A" in m["summary_vi"]
