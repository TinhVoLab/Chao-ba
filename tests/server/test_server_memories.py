"""Memory book + prevention activities API: seed, privacy filtering by role, per-story consent, export, activity
summary, and the end-to-end call hook."""
import pytest
from fastapi.testclient import TestClient

from chaoba.server.app import create_app
from test_server_api import run_simulated_call

ELDER = {"X-Role": "elder_self", "X-Actor": "Hanh"}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with TestClient(create_app(str(tmp_path / "m.db"))) as c:
        yield c


def mem(c, elder="hanh", headers=None):
    r = c.get(f"/api/elders/{elder}/memories", headers=headers or {})
    assert r.status_code == 200
    return r.json()


def test_seeded_stories_are_simulated_mixed_and_tu_narratives_shorten(client):
    for e in ("hanh", "tu", "control"):
        m = mem(client, e, ELDER)
        n = len(m["stories"])
        assert 8 <= n <= 12 and m["simulated"] and all(s["simulated"] for s in m["stories"])
        assert 0 < m["private_count"] < n and m["shared_count"] + m["private_count"] == n
        for s in m["stories"]:
            assert s["text_vi"] and s["text_en"] and s["title_vi"] and s["title_en"] and s["era"]["label_vi"]
    tu = mem(client, "tu", ELDER)["stories"]
    words = [s["word_count"] for s in tu]
    assert sum(words[-4:]) / 4 < 0.7 * (sum(words[:4]) / 4)        # later stories shorter (drift), not abrupt
    assert min(words[-4:]) >= 12


def test_family_sees_only_shared_stories_and_a_private_count(client):
    fam = mem(client)
    me = mem(client, headers=ELDER)
    private = [s for s in me["stories"] if not s["shared"]]
    assert fam["viewer"] == "family" and me["viewer"] == "elder"
    assert all(s["shared"] for s in fam["stories"]) and len(fam["stories"]) == me["shared_count"]
    assert fam["private_count"] == len(private) > 0
    raw = client.get("/api/elders/hanh/memories").text
    for s in private:                                             # no title, no text of a private story leaks
        assert s["text_vi"][:40] not in raw and s["title_vi"] not in raw
    assert fam["audio"]["stored"] is False
    assert sum(t["count"] for t in fam["themes"]) == len(fam["stories"])


def test_withdrawn_family_sharing_hides_the_memory_book_from_family(client):
    client.post("/api/elders/hanh/consents/family_sharing/withdraw", json={"confirmed_by_elder_or_proxy": True})
    fam = mem(client)
    assert fam["sharing_paused"] and fam["stories"] == []
    assert len(mem(client, headers=ELDER)["stories"]) > 0
    assert client.get("/api/elders/hanh/activities").json() == {"sharing_paused": True, "simulated": True}
    assert "Chưa có câu chuyện" in client.get("/api/elders/hanh/memories/export").text


def test_share_and_unshare_need_the_elder(client):
    me = mem(client, headers=ELDER)
    private = next(s for s in me["stories"] if not s["shared"])
    url = f"/api/elders/hanh/memories/{private['id']}"
    r = client.post(f"{url}/share")                                  # family member, no confirmation
    assert r.status_code == 400 and r.json()["detail"]["error"] == "confirmation_required"
    assert private["id"] not in [s["id"] for s in mem(client)["stories"]]
    r = client.post(f"{url}/share", json={"confirmed_by_elder_or_proxy": True, "requested_by": "Lan"})
    assert r.status_code == 200 and r.json()["shared"] is True
    assert private["id"] in [s["id"] for s in mem(client)["stories"]]
    r = client.post(f"{url}/unshare", headers=ELDER)                  # the elder herself needs no confirmation
    assert r.status_code == 200 and r.json()["shared"] is False
    hist = r.json()["consent"]["history"]
    assert [h["shared"] for h in hist[-2:]] == [True, False] and hist[-2]["requested_by"] == "Lan"
    assert client.post("/api/elders/hanh/memories/99999/share", headers=ELDER).status_code == 404
    log = client.get("/api/elders/hanh/privacy").json()["access_log"]
    assert any(x["action"] == "share_memory" for x in log) and any(x["action"] == "unshare_memory" for x in log)


def test_export_is_a_printable_memoir_of_shared_stories_only(client):
    me = mem(client, headers=ELDER)
    r = client.get("/api/elders/hanh/memories/export")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/html")
    h = r.text
    assert "Sổ ký ức của Bà Hạnh" in h and "@media print" in h and "Dữ liệu mô phỏng" in h
    for s in me["stories"]:
        assert (s["text_vi"][:50] in h) == s["shared"]
    assert "Chương 1" in h and "<script" not in h.lower()
    en = client.get("/api/elders/hanh/memories/export?lang=en").text
    assert "Memory book of Mrs Hanh" in en and "Chapter 1" in en
    both = client.get("/api/elders/hanh/memories/export?lang=both").text
    shared = next(s for s in me["stories"] if s["shared"])
    assert shared["text_vi"][:40] in both and shared["text_en"][:40] in both


def test_activities_summary(client):
    tu = client.get("/api/elders/tu/activities").json()
    g = tu["games"]
    assert g["played"] > 40 and g["trend"] and g["by_category"]
    assert g["success_rate_last_4_weeks"] < g["success_rate_first_4_weeks"]      # simulated drift
    assert g["current_level"] in (1, 2, 3) and tu["nudges"]["delivered"] > 60
    assert "not causation" in tu["association_note_en"] and "không phải nhân quả" in tu["association_note_vi"]
    for a in tu["associations"]:
        assert a["days_with"] >= 5 and a["days_without"] >= 5
    assert tu["narrative"]["words_recent"] < tu["narrative"]["words_early"]
    hanh = client.get("/api/elders/hanh/activities").json()
    imp = hanh["improve"]
    assert imp["day"] == 44 and "walk_sun" in imp["focus"] and imp["plan_nudges_delivered"] > 10
    assert client.get("/api/elders/control/activities").json()["improve"] is None
    # games played by tapping on the standing screen are folded in (stored by elder_ui.py)
    assert client.post("/api/elders/hanh/game_plays", json={"game": "ca_dao", "item_id": "x", "correct": True}).status_code == 200
    sg = client.get("/api/elders/hanh/activities").json()["screen_games"]
    assert sg["played"] == 1 and sg["correct_rate"] == 1.0


def test_live_call_adds_a_story_with_consent_and_logs_activities(client):
    before = mem(client, headers=ELDER)
    asked_before = {s["question_id"] for s in before["stories"]}
    acts_before = client.get("/api/elders/hanh/activities").json()
    cid, replies = run_simulated_call(client)
    texts = " ".join(r["reply_text"] for r in replies)
    assert "cho chị Lan nghe được hông" in texts
    out = client.post(f"/api/calls/{cid}/end").json()
    mb = out["memory_book"]
    assert mb["story_id"] and mb["nudge"]
    after = mem(client, headers=ELDER)
    new = next(s for s in after["stories"] if s["id"] == mb["story_id"])
    assert new["source"] == "call" and new["simulated"] is True and new["day"] == 91
    assert new["question_id"] not in asked_before                   # never re-asked
    assert new["shared"] == mb["shared"] and new["consent"]["asked_in_call"] is True
    assert (new["id"] in [s["id"] for s in mem(client)["stories"]]) == new["shared"]
    acts = client.get("/api/elders/hanh/activities").json()
    assert acts["nudges"]["delivered"] == acts_before["nudges"]["delivered"] + 1
    assert acts["life_questions"]["asked"] == acts_before["life_questions"]["asked"] + 1
    # the next call asks a different question
    cid2, replies2 = run_simulated_call(client)
    client.post(f"/api/calls/{cid2}/end")
    ids = [s["question_id"] for s in mem(client, headers=ELDER)["stories"]]
    assert len(ids) == len(set(ids))


def test_demo_reset_reseeds_memory_book(client):
    cid, _ = run_simulated_call(client)
    client.post(f"/api/calls/{cid}/end")
    n = mem(client, headers=ELDER)["total"]
    client.post("/api/demo/reset?elder=hanh")
    assert mem(client, headers=ELDER)["total"] == n - 1
