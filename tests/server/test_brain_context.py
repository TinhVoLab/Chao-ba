"""Brain-health context beside the light (brain_context.py): existing signals only, never a score."""
import pytest
from fastapi.testclient import TestClient

from chaoba.core.explain import contains_blocked
from chaoba.server.app import create_app

FAMILY = {"X-Role": "primary", "X-Actor": "Lan"}
KEYS = ["recall", "speech_rate", "sleep", "mood", "symptoms", "medication", "connection", "games"]


@pytest.fixture()
def client(tmp_path):
    with TestClient(create_app(str(tmp_path / "t.db"))) as c:
        yield c


def ctx(client, eid="hanh", days=14):
    r = client.get(f"/api/elders/{eid}/brain_context?days={days}", headers=FAMILY)
    assert r.status_code == 200
    return r.json()


def items(c):
    return {i["key"]: i for i in c["items"]}


def test_lists_existing_signals_beside_the_light(client):
    for days in (14, 28):
        c = ctx(client, days=days)
        assert [i["key"] for i in c["items"]] == KEYS and c["days"] == days and c["simulated"]
        assert sum(c["light"]["counts"].values()) <= days
        it = items(c)
        assert it["recall"]["compare"] == it["speech_rate"]["compare"] == "baseline"     # vs the person's own usual
        assert it["sleep"]["compare"] == "previous"
        assert it["connection"]["in_light"] is False and it["games"]["in_light"] is False
        assert it["recall"]["in_light"] and it["speech_rate"]["in_light"]
        assert 0 <= it["recall"]["free"] <= it["recall"]["asked"] and "%" not in str(it["recall"])
        assert "wearable" in c["future_en"] and "not in this prototype" in c["future_en"]
        for text in (c["note_vi"], c["note_en"], c["future_vi"], c["future_en"]):
            assert not contains_blocked(text)
    assert client.get("/api/elders/hanh/brain_context?days=7", headers=FAMILY).status_code == 422
    log = client.get("/api/elders/hanh/privacy", headers=FAMILY).json()["access_log"]
    assert any(e["action"] == "read_brain_context" for e in log)


def test_recall_change_is_flagged_only_where_the_light_flagged_it(client):
    tu = items(ctx(client, "tu", 28))["recall"]          # slow cognitive-type drift persona, yellow at the end
    assert tu["flagged_days"] > 0 and tu["usual"] > tu["free"]
    control = items(ctx(client, "control", 28))
    assert control["recall"]["flagged_days"] == 0 and control["speech_rate"]["flagged_days"] == 0


def test_screen_taps_and_games_are_counted(client):
    before = items(ctx(client))
    assert before["medication"]["available"] is False and before["medication"]["reason"] == "not_logged"
    elder = {"X-Role": "elder_self", "X-Actor": "elder:hanh"}
    client.post("/api/elders/hanh/medication_log", json={"status": "not_yet"}, headers=elder)
    client.post("/api/elders/hanh/medication_log", json={"status": "taken"}, headers=elder)   # latest tap of the day wins
    client.post("/api/elders/hanh/game_plays", json={"game": "ca_dao", "item_id": "x1", "correct": True}, headers=elder)
    after = items(ctx(client))
    assert (after["medication"]["taken_days"], after["medication"]["answered_days"]) == (1, 1)
    assert after["games"]["plays"] == before["games"]["plays"] + 1 and after["games"]["days_played"] >= 1


def test_sharing_pause_hides_everything(client):
    client.post("/api/elders/hanh/consents/family_sharing/withdraw", json={"confirmed_by_elder_or_proxy": True})
    c = ctx(client)
    assert c["sharing_paused"] is True and c["items"] == [] and c["light"] is None
    assert "wearable" in c["future_en"]
