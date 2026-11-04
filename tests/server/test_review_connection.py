"""Clinician review of red alerts (care_review.py) and the weekly family-connection series (connection.py)."""
import pytest
from fastapi.testclient import TestClient

from chaoba.server.app import create_app

STATION = {"X-Role": "health_station", "X-Actor": "Tram%20y%20te"}
FAMILY = {"X-Role": "primary", "X-Actor": "Lan"}


@pytest.fixture()
def client(tmp_path):
    with TestClient(create_app(str(tmp_path / "t.db"))) as c:
        yield c


def red_alerts(client, eid="hanh"):
    return [a for a in client.get(f"/api/elders/{eid}/alerts", headers=FAMILY).json() if a["severity"] == "red"]


def test_seeded_red_alert_is_reviewed_and_others_wait(client):
    reds = red_alerts(client)
    seeded = [a for a in reds if a["day"] == 43]
    assert seeded and seeded[0]["review"]["outcome"] == "gp_referral" and not seeded[0]["needs_review"]
    assert seeded[0]["review"]["outcome_en"] == "Referred to a doctor"
    assert all(a["needs_review"] == (a["review"] is None) for a in reds)
    for a in client.get("/api/elders/tu/alerts", headers=FAMILY).json():
        assert a["needs_review"] is False or a["severity"] == "red"


def test_only_clinical_roles_with_consent_can_review(client):
    aid = red_alerts(client)[0]["id"]
    url = f"/api/elders/hanh/alerts/{aid}/review"
    assert client.post(url, json={"outcome": "home_visit"}, headers=FAMILY).status_code == 403
    assert client.post(url, json={"outcome": "cure"}, headers=STATION).status_code == 422
    assert client.post(url, json={"outcome": "home_visit", "note": "x" * 281}, headers=STATION).status_code == 422
    r = client.post(url, json={"outcome": "home_visit", "note": "Đến thăm chiều nay"}, headers=STATION)
    assert r.status_code == 200 and r.json()["review"]["outcome"] == "home_visit" and not r.json()["needs_review"]
    assert r.json()["review"]["by"] == "Tram y te"
    log = client.get("/api/elders/hanh/privacy", headers=FAMILY).json()["access_log"]
    assert any(e["action"] == "review_alert" for e in log)
    client.post("/api/elders/hanh/consents/clinician_sharing/withdraw", json={"confirmed_by_elder_or_proxy": True})
    assert client.post(url, json={"outcome": "no_action"}, headers=STATION).status_code == 403


def test_non_red_alert_cannot_be_reviewed(client):
    yellow = next(a for a in client.get("/api/elders/tu/alerts", headers=FAMILY).json() if a["severity"] == "yellow")
    r = client.post(f"/api/elders/tu/alerts/{yellow['id']}/review", json={"outcome": "no_action"}, headers=STATION)
    assert r.status_code == 409


def test_station_board_lists_red_alerts_pseudonymised(client):
    q = client.get("/api/community/overview", headers=STATION).json()["review_queue"]
    assert q and all("Hạnh" not in r["label"] for r in q)
    assert [r["needs_review"] for r in q] == sorted((r["needs_review"] for r in q), reverse=True)


def test_connection_series_counts_family_touches_and_stays_out_of_the_light(client):
    before = client.get("/api/elders/hanh/today", headers=FAMILY).json()
    c = client.get("/api/elders/hanh/connection?weeks=12", headers=FAMILY).json()
    assert len(c["weeks"]) == 12 and c["in_light"] is False and c["simulated"]
    last = c["weeks"][-1]
    assert last["micro"] >= 1 and 1 <= last["members"] <= 7 and 0 <= last["days_in_touch"] <= 7
    assert c["summary"]["circle_size"] >= 2
    r = client.post("/api/elders/hanh/kudos", json={"kind": "love", "template_id": "miss"},
                    headers={"X-Role": "viewer", "X-Actor": "Minh"})
    assert r.status_code == 200
    c2 = client.get("/api/elders/hanh/connection?weeks=12", headers=FAMILY).json()
    assert c2["weeks"][-1]["micro"] == last["micro"] + 1
    after = client.get("/api/elders/hanh/today", headers=FAMILY).json()
    assert after.get("light") == before.get("light")


def test_connection_respects_sharing_pause(client):
    client.post("/api/elders/hanh/consents/family_sharing/withdraw", json={"confirmed_by_elder_or_proxy": True})
    c = client.get("/api/elders/hanh/connection", headers=FAMILY).json()
    assert c["sharing_paused"] and c["weeks"] == []


def test_help_button_raises_one_red_alert_for_review(client):
    ELDER = {"X-Role": "elder_self", "X-Actor": "elder:hanh"}
    r = client.post("/api/elders/hanh/help", json={}, headers=ELDER)
    assert r.status_code == 200 and not r.json()["duplicate"]
    again = client.post("/api/elders/hanh/help", json={"pressed_at": "not a date"}, headers=ELDER).json()
    assert again["duplicate"] and again["alert_id"] == r.json()["alert_id"]
    a = next(x for x in client.get("/api/elders/hanh/alerts", headers=FAMILY).json() if x["type"] == "help_button")
    assert a["severity"] == "red" and a["needs_review"] and "Cần giúp" in a["explanation_vi"]
    client.post(f"/api/elders/hanh/alerts/{a['id']}/ack", headers=FAMILY)
    assert not client.post("/api/elders/hanh/help", headers=ELDER).json()["duplicate"]   # seen -> a new press is new


def test_repeat_check_and_specialty_referrals_are_review_outcomes(client):
    from chaoba.server.care_review import OUTCOMES
    aid = red_alerts(client)[0]["id"]
    url = f"/api/elders/hanh/alerts/{aid}/review"
    want = {"repeat_assessment": "Repeat check in 2 weeks", "geriatrics": "Referred to geriatrics",
            "neurology": "Referred to neurology", "mental_health": "Referred to mental-health services"}
    for key, en in want.items():
        r = client.post(url, json={"outcome": key}, headers=STATION)
        assert r.status_code == 200 and r.json()["review"]["outcome_en"] == en and r.json()["review"]["outcome_vi"]
    assert set(want) <= set(OUTCOMES)


def test_review_queue_buttons_match_server_outcomes():
    """The station's buttons (ReviewQueue.tsx) and the TS union (types.ts) list exactly the server's outcomes."""
    import re
    from pathlib import Path
    from chaoba.server.care_review import OUTCOMES
    web = Path(__file__).resolve().parents[2] / "web"
    ui = set(re.findall(r'key: "([a-z_]+)"', (web / "components/community/ReviewQueue.tsx").read_text()))
    types = (web / "lib/types.ts").read_text()
    union = set(re.findall(r'\| "([a-z_]+)"', types[types.index("export type ReviewOutcome"):types.index("export interface AlertReview")]))
    assert ui == set(OUTCOMES) == union
