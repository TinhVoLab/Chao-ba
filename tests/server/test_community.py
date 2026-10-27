"""Community (health-station) dashboard: role gate, prioritisation, pseudonymisation, aggregates."""
from datetime import date

import pytest
from fastapi.testclient import TestClient

from chaoba.core.explain import contains_blocked
from chaoba.server import community
from chaoba.server.app import create_app

STATION = {"X-Actor": "Tr%E1%BA%A1m%20y%20t%E1%BA%BF", "X-Role": "health_station"}


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    with TestClient(create_app(str(tmp_path_factory.mktemp("c") / "c.db"))) as c:
        yield c


@pytest.fixture(scope="module")
def ov(client):
    r = client.get("/api/community/overview", headers=STATION)
    assert r.status_code == 200
    return r.json()


def test_family_roles_are_refused(client):
    for h in ({}, {"X-Actor": "Lan", "X-Role": "primary"}, {"X-Actor": "Minh", "X-Role": "viewer"}):
        r = client.get("/api/community/overview", headers=h)
        assert r.status_code == 403 and r.json()["detail"]["error"] == "clinician_only"
    assert client.get("/api/community/overview", headers={"X-Role": "clinician"}).status_code == 200


def test_ward_counts_and_trend(ov):
    w = ov["ward"]
    assert w["elders"] == community.COHORT_N + 3 and w["sharing"] + w["not_sharing"] == w["elders"]
    assert "mô phỏng" in w["name_vi"] and "simulated" in w["name_en"] and ov["simulated"] is True
    assert sum(ov["counts"].values()) == w["sharing"]
    assert len(ov["trend"]) == community.TREND_DAYS
    assert all(sum(d[k] for k in ("red", "yellow", "green", "gray")) == w["sharing"] for d in ov["trend"])
    dates = [d["date"] for d in ov["trend"]]
    assert dates == sorted(dates) and date.fromisoformat(dates[-1]) <= date.today()


def test_visit_list_is_prioritised(ov):
    vl = ov["visit_list"]
    groups = [r["group"] for r in vl]
    order = {"red": 0, "yellow": 1, "check_in": 2}
    assert groups == sorted(groups, key=order.get), "red first, then yellow, then check-in"
    assert [r["rank"] for r in vl] == list(range(1, len(vl) + 1))
    assert sum(1 for r in vl if r["group"] == "red") == ov["counts"]["red"]
    assert sum(1 for r in vl if r["group"] == "yellow") == ov["counts"]["yellow"]
    for g in ("red", "yellow"):
        rows = [r for r in vl if r["group"] == g]
        assert [r["days_in_state"] for r in rows] == sorted((r["days_in_state"] for r in rows), reverse=True)
    for r in vl:
        if r["group"] == "check_in":
            assert r["lives_alone"] and r["days_since_contact"] >= community.CHECKIN_NO_CONTACT_DAYS


def test_priority_tie_breaks():
    base = {"days_in_state": 4, "missed_contact": False, "lives_alone": False, "light": "yellow",
            "days_since_contact": 1}
    rows = [dict(base, pid="a"), dict(base, pid="b", lives_alone=True), dict(base, pid="c", missed_contact=True),
            dict(base, pid="d", days_in_state=9), dict(base, pid="e", light="red", days_in_state=1)]
    assert [r["pid"] for r in community.visit_list(rows)] == ["e", "d", "c", "b", "a"]


def test_rows_are_pseudonymised_and_non_diagnostic(client, ov):
    names = [(client.app.state.svc.store.elder(e) or {}).get("display_name") for e in ("hanh", "tu", "control")]
    for r in ov["visit_list"]:
        assert set(r) >= {"label", "initials", "age", "area", "light", "reasons_vi", "reasons_en"}
        assert r["label"].startswith(r["initials"]) and r["area"].startswith("Khu phố")
        assert r["pid"] not in ("hanh", "tu", "control")
        assert not any(n and n in r["label"] for n in names)
        assert not any(contains_blocked(x) for x in r["reasons_vi"] + r["reasons_en"])
    assert "không phải chẩn đoán" in ov["disclaimer_vi"] and "not a diagnosis" in ov["disclaimer_en"]


def test_interventions_are_association_only(ov):
    iv = {x["intervention"]: x for x in ov["interventions"]}
    assert set(iv) == set(community.INTERVENTIONS)
    for x in iv.values():
        assert x["recovered"] <= x["episodes"]
        assert x["rate"] is None or 0 <= x["rate"] <= 1
        assert x["enough"] == (x["episodes"] >= 5)
    assert "không chứng minh nguyên nhân" in ov["association_note_vi"] and "not cause" in ov["association_note_en"]


def test_episode_detection_and_censoring():
    end = date(2026, 10, 27)
    series = [("2026-09-01", "green"), ("2026-09-02", "yellow"), ("2026-09-03", "red"), ("2026-09-06", "green"),
              ("2026-10-20", "yellow"), ("2026-10-27", "yellow")]
    eps = community.episodes(series, end, lambda s: "none")
    assert eps[0]["peak"] == "red" and eps[0]["days_to_green"] == 4 and eps[0]["recovered"] and not eps[0]["open"]
    assert eps[1]["open"] and not eps[1]["recovered"]        # outcome window not over yet: open, not a failure


def test_withdrawn_clinician_sharing_removes_persona(tmp_path):
    with TestClient(create_app(str(tmp_path / "w.db"))) as c:
        before = c.get("/api/community/overview", headers=STATION).json()["ward"]
        c.post("/api/elders/hanh/consents/clinician_sharing/withdraw", json={"confirmed_by_elder_or_proxy": True})
        after = c.get("/api/community/overview", headers=STATION).json()["ward"]
        assert after["sharing"] == before["sharing"] - 1 and after["demo_personas"] == 2
        log = c.get("/api/elders/tu/privacy").json()["access_log"]
        assert any(x["role"] == "health_station" and x["action"] == "read_community" for x in log)
