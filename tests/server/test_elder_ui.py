"""Elder standing-screen endpoints (chaoba/server/elder_ui.py)."""
import pytest
from fastapi.testclient import TestClient

from chaoba.server.app import create_app

ELDER = {"X-Actor": "elder%3Ahanh", "X-Role": "elder_self"}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with TestClient(create_app(str(tmp_path / "t.db"))) as c:
        yield c


def test_screen_bundle(client):
    r = client.get("/api/elders/hanh/screen", headers=ELDER)
    assert r.status_code == 200
    b = r.json()
    assert b["elder_id"] == "hanh" and b["date"] and b["simulated"] is True
    assert b["medications"] == [{"name": "Amlodipine 5mg", "time": "07:00", "timed": True, "status": None,
                                 "answered_at": None}]
    assert b["mood_today"] is None and b["game_plays_today"] == 0
    assert all(m["to_elder"] for m in b["messages"])
    # "as needed" medication is not a timed reminder
    meds = client.get("/api/elders/control/screen").json()["medications"]
    assert meds and meds[0]["timed"] is False
    assert client.get("/api/elders/nobody/screen").status_code == 404


def test_family_message_shows_on_screen(client):
    client.post("/api/elders/hanh/notes", json={"author": "Lan", "text": "Chiều con ghé má nha", "to_elder": True})
    client.post("/api/elders/hanh/notes", json={"author": "Lan", "text": "ghi chú nội bộ"})
    texts = [m["text"] for m in client.get("/api/elders/hanh/screen").json()["messages"]]
    assert texts[0] == "Chiều con ghé má nha" and "ghi chú nội bộ" not in texts


def test_medication_log(client):
    r = client.post("/api/elders/hanh/medication_log", json={"status": "not_yet"}, headers=ELDER)
    assert r.status_code == 200 and r.json()["medication"] == "Amlodipine 5mg" and r.json()["time"] == "07:00"
    assert r.json()["source"] == "elder_screen"
    r = client.post("/api/elders/hanh/medication_log", json={"status": "taken", "medication": "Amlodipine 5mg"},
                    headers=ELDER)
    assert r.json()["today"][0]["status"] == "taken"
    g = client.get("/api/elders/hanh/medication_log").json()
    assert [e["status"] for e in g["entries"]] == ["not_yet", "taken"] and g["today"][0]["status"] == "taken"
    assert client.get("/api/elders/hanh/screen").json()["medications"][0]["status"] == "taken"
    assert client.post("/api/elders/hanh/medication_log", json={"status": "maybe"}).status_code == 422
    # writes are in the access log with the elder as actor
    log = client.get("/api/elders/hanh/privacy").json()["access_log"]
    assert any(a["action"] == "log_medication" and a["role"] == "elder_self" for a in log)


def test_mood_checkin_is_self_report(client):
    r = client.post("/api/elders/hanh/mood_checkin", json={"mood": "happy"}, headers=ELDER)
    assert r.status_code == 200 and r.json()["label_vi"] == "vui" and r.json()["self_report"] is True
    g = client.get("/api/elders/hanh/mood_checkin").json()
    assert g["today"]["mood"] == "happy" and "not a clinical" in g["note_en"]
    assert client.get("/api/elders/hanh/screen").json()["mood_today"]["mood"] == "happy"
    assert client.post("/api/elders/hanh/mood_checkin", json={"mood": "depressed"}).status_code == 422
    # a mood tap never changes the daily light or the call record
    before = client.get("/api/elders/hanh/today").json()
    client.post("/api/elders/hanh/mood_checkin", json={"mood": "sad"}, headers=ELDER)
    after = client.get("/api/elders/hanh/today").json()
    assert (before["light"], before["mood"]) == (after["light"], after["mood"])


def test_game_plays(client):
    for item, ok in (("cong_cha", True), ("bau_bi", False)):
        r = client.post("/api/elders/hanh/game_plays", json={"game": "ca_dao", "item_id": item, "correct": ok},
                        headers=ELDER)
        assert r.status_code == 200 and r.json()["correct"] is ok
    g = client.get("/api/elders/hanh/game_plays").json()
    assert g["today"] == 2 and g["days_played"] == 1 and len(g["plays"]) == 2
    assert client.get("/api/elders/hanh/screen").json()["game_plays_today"] == 2
    assert client.post("/api/elders/hanh/game_plays", json={"game": "chess", "item_id": "x", "correct": True}
                       ).status_code == 422


def test_demo_reset_clears_screen_rows(client):
    client.post("/api/elders/hanh/mood_checkin", json={"mood": "neutral"})
    client.post("/api/elders/tu/mood_checkin", json={"mood": "happy"})
    client.post("/api/elders/hanh/medication_log", json={"status": "taken"})
    assert client.post("/api/demo/reset?elder=hanh").status_code == 200
    assert client.get("/api/elders/hanh/mood_checkin").json()["entries"] == []
    assert client.get("/api/elders/hanh/medication_log").json()["entries"] == []
    assert client.get("/api/elders/tu/mood_checkin").json()["today"]["mood"] == "happy"


def test_elder_initiated_video_call_is_a_contact(client):
    r = client.post("/api/elders/hanh/contacts", json={"kind": "call", "member_id": "lan"}, headers=ELDER)
    assert r.status_code == 200 and r.json()["member_name"] == "Lan"
    assert client.get("/api/elders/hanh/contacts").json()["last"]["member_id"] == "lan"
