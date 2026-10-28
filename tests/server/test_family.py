"""Family coordination: rota / nudge, weekly synthesis, suggestions, task CRUD, role-based filtering."""
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from chaoba.core.explain import contains_blocked
from chaoba.server import family
from chaoba.server.app import create_app

LAN = {"X-Actor": "Lan", "X-Role": "primary"}
MINH = {"X-Actor": "Minh", "X-Role": "viewer"}
VY = {"X-Actor": "Vy", "X-Role": "viewer"}
ELDER = {"X-Actor": "B%C3%A0%20H%E1%BA%A1nh", "X-Role": "elder_self"}
CLINIC = {"X-Actor": "Tram", "X-Role": "health_station"}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with TestClient(create_app(str(tmp_path / "f.db"))) as c:
        yield c


def test_overview_shape_and_members(client):
    r = client.get("/api/elders/hanh/family", headers=LAN)
    assert r.status_code == 200
    o = r.json()
    assert [m["id"] for m in o["members"]] == ["lan", "minh", "vy"]
    assert {m["role"] for m in o["members"]} == {"primary", "viewer"}
    assert o["viewer"] == {"member_id": "lan", "name": "Lan", "role": "primary",
                           "permissions": {"full_view": True, "edit_rota": True, "manage_tasks": True,
                                           "see_access_log": True}}
    assert o["simulated"] is True and {"rota", "tasks", "suggestions", "synthesis", "access"} <= set(o)


def test_header_cannot_raise_role(client):
    v = client.get("/api/elders/hanh/family", headers={"X-Actor": "Minh", "X-Role": "primary"}).json()["viewer"]
    assert v["role"] == "viewer" and not v["permissions"]["full_view"]


def test_non_family_roles_are_refused(client):
    r = client.get("/api/elders/hanh/family/timeline", headers=CLINIC)
    assert r.status_code == 403 and r.json()["detail"]["error"] == "family_only"
    assert client.get("/api/elders/nobody/family", headers=LAN).status_code == 404


# ------------------------------------------------------------------ synthesis
def test_weekly_synthesis_pieces_fragments_together(client):
    s = client.get("/api/elders/hanh/family/synthesis", headers=MINH).json()
    top = s["items"][0]
    assert top["topic"] == "pain" and top["label_vi"] == "đau lưng" and top["count"] == 3
    assert top["people"] == ["Lan", "Minh"] and top["ai"] == 1 and top["sources"] == 3
    assert {m["source"] for m in top["mentions"]} == {"note", "ai"}
    assert "3 lần" in s["summary_vi"] and "Út Thương" in s["summary_vi"] and "Lan, Minh" in s["summary_vi"]
    assert "3 times" in s["summary_en"] and s["engine"] == "rules"
    assert not contains_blocked(s["summary_vi"]) and not contains_blocked(s["summary_en"])
    assert s["days"] == 7 and s["simulated"] is True


def test_synthesis_counts_a_new_note(client):
    client.post("/api/elders/hanh/notes", json={"author": "Vy", "text": "Bà nói lưng còn đau, ngủ không được."},
                headers=VY)
    top = client.get("/api/elders/hanh/family/synthesis", headers=LAN).json()["items"][0]
    assert top["count"] == 4 and top["people"] == ["Lan", "Minh", "Vy"]


def test_synthesis_ignores_negated_and_messages_to_elder(client):
    client.post("/api/elders/hanh/notes", json={"author": "Vy", "text": "Bà nói hổng đau gì hết."}, headers=VY)
    client.post("/api/elders/hanh/notes", json={"author": "Lan", "text": "Má nhớ uống thuốc đau lưng nha",
                                                 "to_elder": True}, headers=LAN)
    top = client.get("/api/elders/hanh/family/synthesis", headers=LAN).json()["items"][0]
    assert top["count"] == 3


def test_synthesis_llm_reword_must_pass_postcheck(client, monkeypatch):
    from chaoba.core import explain
    monkeypatch.setattr(family, "llm_enabled", lambda: True)
    monkeypatch.setattr(explain, "_llm_reword", lambda vi, en: ("Má nhắc đau lưng 3 lần trong tuần.",
                                                                "Mom mentioned back pain 3 times this week."))
    s = client.get("/api/elders/hanh/family/synthesis", headers=LAN).json()
    assert s["engine"] == "claude" and s["summary_vi"].startswith("Má nhắc")
    monkeypatch.setattr(explain, "_llm_reword", lambda vi, en: None)   # post-check failed -> rules text
    s = client.get("/api/elders/hanh/family/synthesis", headers=LAN).json()
    assert s["engine"] == "rules" and "ghép lại" in s["summary_vi"]


def test_synthesis_hides_call_data_when_sharing_paused(client):
    client.post("/api/elders/hanh/consents/family_sharing/withdraw", json={"confirmed_by_elder_or_proxy": True},
                headers=LAN)
    s = client.get("/api/elders/hanh/family/synthesis", headers=LAN).json()
    assert s["sharing_paused"] and s["items"][0]["ai"] == 0 and s["items"][0]["count"] == 2
    t = client.get("/api/elders/hanh/family/timeline", headers=LAN).json()
    assert not any(i["kind"] in ("call", "alert") for i in t["items"])


# ------------------------------------------------------------------ rota / nudge
def test_rota_today_turn_and_gap_nudge(client):
    today = date.today()
    r = client.get("/api/elders/hanh/family/rota", headers=MINH).json()
    assert len(r["week"]) == 7 and r["today"]["weekday"] == today.weekday()
    assert r["today"]["member_id"] == family.ROTAS["hanh"][today.weekday()]
    assert r["gap"]["days_since"] == 5 and r["gap"]["nudge"] and r["gap"]["threshold"] == 3
    assert "5 ngày" in r["nudge_vi"] and r["today"]["member_name"] in r["nudge_vi"]
    assert set(r["mine"]["weekdays"]) == {1, 5}
    nxt = r["mine"]["next"]
    assert date.fromisoformat(nxt["date"]).weekday() in (1, 5) and 0 <= nxt["in_days"] <= 6
    assert r["mine"]["your_turn"] == (today.weekday() in (1, 5))
    assert len(r["history"]) == 7 and r["history"][-1]["date"] == today.isoformat()


def test_rota_your_turn_clears_after_logging_a_call(client):
    wd = date.today().weekday()
    assert client.post("/api/elders/hanh/family/rota", json={"assignments": {str(wd): "minh"}},
                       headers=LAN).status_code == 200
    r = client.get("/api/elders/hanh/family/rota", headers=MINH).json()
    assert r["mine"]["your_turn"] is True and r["gap"]["nudge"] is True
    client.post("/api/elders/hanh/contacts", json={"kind": "call", "member_id": "minh"}, headers=MINH)
    r = client.get("/api/elders/hanh/family/rota", headers=MINH).json()
    assert r["mine"]["your_turn"] is False and r["today"]["done"] and r["gap"]["nudge"] is False
    assert r["mine"]["next"] is None or r["mine"]["next"]["in_days"] > 0


def test_rota_edit_is_primary_only_and_validated(client):
    r = client.post("/api/elders/hanh/family/rota", json={"assignments": {"0": "minh"}}, headers=MINH)
    assert r.status_code == 403 and r.json()["detail"]["error"] == "primary_only"
    assert client.post("/api/elders/hanh/family/rota", json={"assignments": {"7": "lan"}}, headers=LAN).status_code == 422
    assert client.post("/api/elders/hanh/family/rota", json={"assignments": {"0": "bob"}}, headers=LAN).status_code == 422
    r = client.post("/api/elders/hanh/family/rota", json={"assignments": {"0": "vy", "6": None}}, headers=LAN).json()
    assert r["week"][0]["member_id"] == "vy" and r["week"][6]["member_id"] is None


# ------------------------------------------------------------------ tasks
def test_task_crud_and_permissions(client):
    due = (date.today() + timedelta(days=3)).isoformat()
    r = client.post("/api/elders/hanh/family/tasks", headers=MINH,
                    json={"kind": "medicine", "title": "Mua thuốc giảm đau", "assignee_id": "vy", "due_date": due})
    assert r.status_code == 200
    t = r.json()
    assert t["assignee_name"] == "Vy" and t["created_by"] == "Minh" and not t["done"] and t["simulated"] is False
    tid = t["id"]
    # Vy (assignee) can tick it off; Minh created it so he can edit; Lan (primary) can do anything
    r = client.post(f"/api/elders/hanh/family/tasks/{tid}", json={"done": True}, headers=VY).json()
    assert r["done"] and r["done_by"] == "Vy" and r["done_day"] is not None
    # a viewer cannot change a task that is neither theirs nor created by them
    lan_task = next(x for x in client.get("/api/elders/hanh/family/tasks").json()["tasks"] if x["assignee_id"] == "lan")
    assert client.post(f"/api/elders/hanh/family/tasks/{lan_task['id']}", json={"done": True},
                       headers=VY).status_code == 403
    assert client.delete(f"/api/elders/hanh/family/tasks/{lan_task['id']}", headers=VY).status_code == 403
    r = client.post(f"/api/elders/hanh/family/tasks/{lan_task['id']}", json={"assignee_id": "minh"}, headers=LAN)
    assert r.json()["assignee_name"] == "Minh"
    assert client.delete(f"/api/elders/hanh/family/tasks/{tid}", headers=MINH).json()["deleted"]
    assert all(x["id"] != tid for x in client.get("/api/elders/hanh/family/tasks").json()["tasks"])
    tl = client.get("/api/elders/hanh/family/timeline", headers=LAN).json()
    assert any(i["kind"] == "task" and i["title_vi"].startswith("Đã xong") for i in tl["items"])


def test_task_validation(client):
    post = lambda body: client.post("/api/elders/hanh/family/tasks", json=body, headers=LAN)  # noqa: E731
    assert post({"kind": "party", "title": "x"}).status_code == 422
    assert post({"kind": "visit", "title": "  "}).status_code == 422
    assert post({"kind": "visit", "title": "Về thăm", "assignee_id": "bob"}).status_code == 422
    assert post({"kind": "visit", "title": "Về thăm", "due_date": "31/10"}).status_code == 422
    assert client.post("/api/elders/hanh/family/tasks", json={"kind": "visit", "title": "x"},
                       headers=ELDER).status_code == 403
    assert client.post("/api/elders/hanh/family/tasks/99999", json={"done": True}, headers=LAN).status_code == 404


# ------------------------------------------------------------------ roles in the timeline
def test_viewer_sees_summaries_primary_sees_all(client):
    lan = client.get("/api/elders/hanh/family/timeline", headers=LAN).json()
    minh = client.get("/api/elders/hanh/family/timeline", headers=MINH).json()
    assert len(lan["items"]) == len(minh["items"])
    lan_note = next(i for i in lan["items"] if i["kind"] == "note" and i["actor"] == "Lan" and "đau lưng" in i["text_vi"])
    minh_view = next(i for i in minh["items"] if i["id"] == lan_note["id"])
    assert minh_view["redacted"] and "đau lưng" not in minh_view["text_vi"]
    own = next(i for i in minh["items"] if i["kind"] == "note" and i["actor"] == "Minh")
    assert not own["redacted"] and "lưng" in own["text_vi"]
    assert any(i["kind"] == "call" for i in minh["items"])          # AI summaries are summaries: visible
    assert any(i["kind"] == "gap" for i in minh["items"])           # nobody called for 5 days
    assert not any(i["redacted"] for i in lan["items"])
    assert lan["viewer"]["role"] == "primary" and minh["viewer"]["role"] == "viewer"


def test_viewer_does_not_see_verbatim_quotes_in_alerts(client):
    svc = client.app.state.svc
    day, d = svc.current_day("hanh")
    svc.store.add_alert("hanh", day, d, "health_concern", "red", "Bà kể: “tui bị té hôm qua”. Gọi hỏi thăm.",
                        "She said: “I fell yesterday”. Please call.")
    a_lan = next(i for i in client.get("/api/elders/hanh/family/timeline", headers=LAN).json()["items"]
                 if i["kind"] == "alert")
    a_minh = next(i for i in client.get("/api/elders/hanh/family/timeline", headers=MINH).json()["items"]
                  if i["kind"] == "alert")
    assert "tui bị té" in a_lan["text_vi"] and not a_lan["redacted"]
    assert "tui bị té" not in a_minh["text_vi"] and "“…”" in a_minh["text_vi"] and a_minh["redacted"]


def test_elder_sees_who_is_viewing(client):
    client.get("/api/elders/hanh/family/timeline", headers=MINH)
    client.get("/api/elders/hanh/family/timeline", headers=MINH)
    client.get("/api/elders/hanh/today", headers=LAN)
    acc = client.get("/api/elders/hanh/family/access", headers=ELDER).json()
    people = {p["actor"]: p for p in acc["people"]}
    assert people["Minh"]["views"] >= 2 and people["Minh"]["role"] == "viewer"
    assert "Lan" in people and people["Lan"]["role"] == "primary"
    assert people["Lan"]["label_vi"] == "Lan"


def test_access_names_the_elder_by_kin_not_actor_id(client):
    screen = {"X-Actor": "elder:hanh", "X-Role": "elder_self"}
    client.get("/api/elders/hanh/family/timeline", headers=screen)
    client.get("/api/elders/hanh/family", headers=ELDER)
    acc = client.get("/api/elders/hanh/family/access", headers=MINH).json()
    me = [p for p in acc["people"] if p["role"] == "elder_self"]
    assert len(me) == 1   # "elder:hanh" and "Bà Hạnh" are the same person: one row
    assert me[0]["label_vi"] == "Má (chính bà)" and me[0]["label_en"] == "Mom (herself)"
    assert all("elder:" not in p["label_vi"] for p in acc["people"])
    client.get("/api/elders/hanh/family", headers={"X-Actor": "family:primary", "X-Role": "primary"})
    acc = client.get("/api/elders/hanh/family/access", headers=MINH).json()
    assert [p["label_vi"] for p in acc["people"]].count("Lan") <= 1
    assert all(not p["label_vi"].startswith("family:") for p in acc["people"])


# ------------------------------------------------------------------ suggestions
def test_suggestions_avoid_what_a_sibling_already_asked(client):
    s = client.get("/api/elders/hanh/family/suggestions", headers=MINH).json()
    keys = [x["key"] for x in s["suggestions"]]
    assert keys[0] == "care:pain" and len(keys) <= 4
    assert "fact:cây mai trước nhà sắp ra nụ" not in keys
    mai = next(x for x in s["already_asked"] if x["key"] == "fact:cây mai trước nhà sắp ra nụ")
    assert mai["asked_by"][0]["name"] == "Lan" and mai["asked_by"][0]["how"] == "asked"
    assert any(k.startswith("act:") for k in keys)    # from yesterday's call summary
    first_act = next(k for k in keys if k.startswith("act:"))
    r = client.post("/api/elders/hanh/family/suggestions/asked", json={"topic_key": first_act}, headers=MINH)
    assert r.status_code == 200 and r.json()["member_name"] == "Minh"
    s2 = client.get("/api/elders/hanh/family/suggestions", headers=VY).json()
    assert first_act not in [x["key"] for x in s2["suggestions"]]
    done = next(x for x in s2["already_asked"] if x["key"] == first_act)
    assert done["asked_by"][0]["name"] == "Minh" and done["asked_by"][0]["you"] is False
    assert client.post("/api/elders/hanh/family/suggestions/asked", json={"topic_key": " "},
                       headers=MINH).status_code == 422


def test_demo_reset_reseeds_family(client):
    client.post("/api/elders/hanh/family/tasks", json={"kind": "visit", "title": "Về thăm"}, headers=LAN)
    n = len(client.get("/api/elders/hanh/family/tasks").json()["tasks"])
    client.post("/api/demo/reset?elder=hanh")
    assert len(client.get("/api/elders/hanh/family/tasks").json()["tasks"]) == n - 1
    assert client.get("/api/elders/hanh/family/synthesis", headers=LAN).json()["items"][0]["count"] == 3


def test_other_personas_have_circles(client):
    for eid, primary in (("tu", "Bà Tư"), ("control", "Thảo")):
        o = client.get(f"/api/elders/{eid}/family", headers={"X-Actor": "x", "X-Role": "primary"}).json()
        assert o["members"][0]["name"] == primary and len(o["members"]) >= 2
        assert len(o["rota"]["week"]) == 7


def test_elder_self_reports_appear_in_timeline_unscored(client):
    elder = {"X-Role": "elder_self"}
    assert client.post("/api/elders/hanh/medication_log", json={"status": "taken"}, headers=elder).status_code == 200
    assert client.post("/api/elders/hanh/mood_checkin", json={"mood": "sad"}, headers=elder).status_code == 200
    light_before = client.get("/api/elders/hanh/today").json()["light"]
    items = client.get("/api/elders/hanh/family/timeline", headers=MINH).json()["items"]
    rep = [i for i in items if i["kind"] == "self_report"]
    assert {i["report_kind"] for i in rep} == {"medication", "mood"}
    assert any("Đã uống thuốc" in i["title_vi"] for i in rep) and any("buồn" in i["title_vi"] for i in rep)
    assert all("không tính điểm" in i["text_vi"] for i in rep)
    assert client.get("/api/elders/hanh/today").json()["light"] == light_before
