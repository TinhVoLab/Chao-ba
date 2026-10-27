"""Family micro-interactions ("Gửi yêu thương"): catalog, sending, free-text post-check, throttling, roles, the elder's
reply on the screen, relay in the morning call, saving an advice answer to the memory book, consent, the timeline, the
separate micro-contact count (never a call) and the DMAIC series."""
import pytest
from fastapi.testclient import TestClient

from chaoba.server.app import create_app
from test_server_api import run_simulated_call

LAN = {"X-Actor": "Lan", "X-Role": "primary"}
MINH = {"X-Actor": "Minh", "X-Role": "primary"}     # stored as viewer in the care circle: the header cannot raise it
VY = {"X-Actor": "Vy", "X-Role": "viewer"}
ELDER = {"X-Role": "elder_self", "X-Actor": "elder:hanh"}
STATION = {"X-Role": "health_station", "X-Actor": "Tram"}
BASE = "/api/elders/hanh/kudos"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with TestClient(create_app(str(tmp_path / "k.db"))) as c:
        yield c


def send(c, body, headers=LAN):
    return c.post(BASE, json=body, headers=headers)


def inbox(c):
    r = c.get(BASE + "?box=inbox&pending=1", headers=ELDER)
    assert r.status_code == 200
    return r.json()["items"]


def test_catalog_is_personal_to_the_sender_and_has_eight_quick_cards(client):
    lan = client.get(BASE + "/catalog", headers=LAN).json()
    vy = client.get(BASE + "/catalog", headers=VY).json()
    quick = [t for t in lan["templates"] if t["kind"] in ("checkin", "love")]
    assert len(quick) == 8 and all(t["icon"] and t["label_vi"] and t["label_en"] for t in quick)
    ate = next(t for t in lan["templates"] if t["id"] == "ate")
    assert ate["label_vi"] == "Má ăn cơm chưa?" and [c["id"] for c in ate["choices"]] == ["ate", "not_yet"]
    assert next(t for t in vy["templates"] if t["id"] == "miss")["text_vi"] == "Cháu nhớ bà quá"   # grandchild voice
    assert {g["kind"] for g in lan["groups"]} == {"checkin", "love", "advice", "care_tip", "message"}
    assert lan["limit_per_day"] == 6 and lan["voice_note"]["available"] is False
    tu = client.get("/api/elders/tu/kudos/catalog", headers={"X-Actor": "Khoa", "X-Role": "viewer"}).json()
    assert next(t for t in tu["templates"] if t["id"] == "ate")["label_vi"] == "Ba ăn cơm chưa?"


def test_seeded_history_is_simulated_answered_and_has_a_saved_canh_chua_lesson(client):
    fam = client.get(BASE + "?box=family&days=60", headers=LAN).json()
    items = fam["items"]
    assert len(items) >= 12 and all(i["simulated"] for i in items)
    assert {i["sender_name"] for i in items} == {"Lan", "Minh", "Vy"}
    assert all(i["status"] == "replied" for i in items)                    # nothing seeded is relayed in a call
    assert inbox(client) == []
    canh = next(i for i in items if i["template_id"] == "canh_chua")
    assert canh["story"]["saved"] and "me chín" in canh["reply"]["text"]
    stories = client.get("/api/elders/hanh/memories").json()
    advice = [s for s in stories["stories"] if s["theme"] == "advice"]
    assert len(advice) == 1 and advice[0]["title_vi"] == "Lời má dạy: nấu canh chua" and advice[0]["shared"]
    assert advice[0]["theme_vi"] == "Lời má dạy" and advice[0]["text_en"]
    for e in ("tu", "control"):
        assert client.get(f"/api/elders/{e}/kudos?box=family", headers={"X-Role": "primary"}).json()["items"]


def test_family_sends_screen_answers_and_family_sees_the_reply(client):
    r = send(client, {"kind": "checkin", "template_id": "ate"})
    assert r.status_code == 200 and r.json()["kudos"]["status"] == "sent" and r.json()["remaining_today"] == 5
    kid = r.json()["kudos"]["id"]
    q = inbox(client)
    assert [k["id"] for k in q] == [kid] and q[0]["sender_name"] == "Lan"
    assert client.post(f"{BASE}/{kid}/seen", json={}, headers=ELDER).json()["kudos"]["status"] == "seen"
    assert client.get(BASE + "?box=sent", headers=LAN).json()["items"][0]["status_vi"] == "Má đã xem"
    r = client.post(f"{BASE}/{kid}/reply", json={"choice": "ate", "via": "screen"}, headers=ELDER)
    assert r.status_code == 200 and r.json()["kudos"]["status"] == "replied"
    mine = client.get(BASE + "?box=sent", headers=LAN).json()["items"][0]
    assert mine["reply"]["choice"] == "ate" and mine["reply_vi"].startswith("Má trả lời: Ăn rồi con · ")
    assert inbox(client) == []
    r = client.post(f"{BASE}/{kid}/reply", json={"heart": True}, headers=ELDER)      # heart on top of the answer
    assert r.json()["kudos"]["heart"] and r.json()["kudos"]["reply"]["choice"] == "ate"
    assert client.post(f"{BASE}/{kid}/reply", json={"choice": "pizza"}, headers=ELDER).status_code == 422
    assert client.post(f"{BASE}/{kid}/reply", json={}, headers=ELDER).status_code == 422


def test_roles(client):
    kid = send(client, {"kind": "love", "template_id": "love"}).json()["kudos"]["id"]
    assert client.get(BASE + "?box=inbox", headers=LAN).status_code == 403               # family: no inbox
    assert client.post(f"{BASE}/{kid}/reply", json={"heart": True}, headers=LAN).status_code == 403
    assert client.post(f"{BASE}/{kid}/seen", json={}, headers=MINH).status_code == 403
    assert send(client, {"kind": "love", "template_id": "love"}, ELDER).status_code == 403  # the elder replies
    assert client.get(BASE + "?box=sent", headers=ELDER).status_code == 403
    assert client.get(BASE + "/catalog", headers=STATION).status_code == 403
    assert send(client, {"kind": "love", "template_id": "love", "from": "minh"}).status_code == 403  # as yourself
    minh = client.get(BASE + "?box=sent", headers=MINH).json()["items"]
    assert minh and all(i["sender_name"] == "Minh" for i in minh)
    # a viewer sees other people's free text redacted in the family box; the primary carer sees it
    send(client, {"kind": "message", "text": "Chủ nhật con về ăn cơm với má nha"})
    vy = client.get(BASE + "?box=family", headers=VY).json()["items"][0]
    assert vy["redacted"] and "Chủ nhật" not in vy["text_vi"]
    assert not client.get(BASE + "?box=family", headers=MINH).json()["items"][0]["text_vi"].startswith("Chủ nhật")
    assert client.get(BASE + "?box=family", headers=LAN).json()["items"][0]["text_vi"].startswith("Chủ nhật")
    assert client.get(BASE + "?box=nope", headers=LAN).status_code == 422


@pytest.mark.parametrize("text,error", [
    ("Má uống thêm 1 viên thuốc huyết áp nha", "medical_advice"),
    ("Má giảm liều thuốc ngủ đi", "medical_advice"),
    ("Má uống 5mg thôi", "medical_advice"),
    ("Má bỏ thuốc đi nha", "medical_advice"),
    ("Hình như má bị sa sút trí tuệ", "diagnosis_words"),
    ("Má gửi con mã OTP nha", "money_topic"),
])
def test_free_text_post_check_refuses_medical_advice(client, text, error):
    for kind in ("message", "care_tip", "advice"):
        r = send(client, {"kind": kind, "text": text})
        assert r.status_code == 422 and r.json()["detail"]["error"] == error
        assert r.json()["detail"]["message_vi"] and r.json()["detail"]["message_en"]


def test_free_text_validation_and_templates(client):
    assert send(client, {"kind": "care_tip", "text": "Trời nóng má nhớ đội nón khi ra vườn nha"}).status_code == 200
    assert send(client, {"kind": "message", "text": "  "}).status_code == 422
    assert send(client, {"kind": "message", "text": "x" * 161}).status_code == 422
    assert send(client, {"kind": "checkin", "text": "Má khỏe không"}).status_code == 422   # check-ins: presets only
    assert send(client, {"kind": "checkin", "template_id": "love"}).status_code == 422
    assert send(client, {"kind": "hug"}).status_code == 422


def test_daily_limit_per_sender(client):
    for i in range(6):
        assert send(client, {"kind": "love", "template_id": "love"}).status_code == 200
    r = send(client, {"kind": "love", "template_id": "love"})
    assert r.status_code == 429 and r.json()["detail"]["error"] == "daily_limit"
    assert "gọi má" in r.json()["detail"]["message_vi"]
    assert send(client, {"kind": "love", "template_id": "love"}, VY).status_code == 200    # per sender
    assert client.get(BASE + "/catalog", headers=LAN).json()["remaining_today"] == 0


def test_micro_contacts_never_count_as_calls(client):
    before = client.get("/api/elders/hanh/today").json()["contact"]
    for t in ("love", "miss", "thanks"):
        send(client, {"kind": "love", "template_id": t})
    after = client.get("/api/elders/hanh/today").json()["contact"]
    assert after["days_since"] == before["days_since"] and after["nudge"] is True        # Lan has not called: 5 days
    assert after["micro_7d"] == before["micro_7d"] + 3 >= 3
    assert client.get("/api/elders/hanh/family/rota", headers=LAN).json()["gap"]["nudge"] is True
    dm = client.get("/api/elders/hanh/dmaic").json()["contact"]
    assert dm["micro_recent_per_week"] > 0 and dm["recent_per_week"] is not None
    assert len(dm["weekly"]) == 6 and dm["weekly"][-1]["micro"] >= 3
    assert all({"calls_visits", "micro"} <= set(w) for w in dm["weekly"])


def test_advice_answer_saved_to_memory_book_only_with_consent(client):
    kid = send(client, {"kind": "advice", "template_id": "mai"}).json()["kudos"]["id"]
    assert client.post(f"{BASE}/{kid}/save", json={}, headers=ELDER).status_code == 409   # no answer yet
    r = client.post(f"{BASE}/{kid}/reply", json={"text": "Rằm tháng chạp lặt hết lá, tưới đều là kịp Tết."},
                    headers=ELDER)
    assert r.json()["can_save"] is True
    assert client.post(f"{BASE}/{kid}/save", json={}, headers=LAN).status_code == 400       # the elder decides
    r = client.post(f"{BASE}/{kid}/save", json={}, headers=ELDER)
    assert r.status_code == 200 and r.json()["title_vi"] == "Lời má dạy: chăm mai ra nụ đúng Tết"
    again = client.post(f"{BASE}/{kid}/save", json={}, headers=ELDER).json()
    assert again["story_id"] == r.json()["story_id"]                                        # idempotent
    fam = client.get("/api/elders/hanh/memories").json()
    assert any(s["id"] == r.json()["story_id"] and s["shared"] for s in fam["stories"])
    # family with the elder's confirmation; and the elder can decline
    k2 = send(client, {"kind": "advice", "text": "Làm bánh xèo sao cho giòn hả má?"}).json()["kudos"]["id"]
    client.post(f"{BASE}/{k2}/reply", json={"text": "Bột phải pha với nước cốt dừa, chảo thiệt nóng."}, headers=ELDER)
    assert client.post(f"{BASE}/{k2}/save", json={"confirmed_by_elder_or_proxy": True}, headers=LAN).status_code == 200
    k3 = send(client, {"kind": "advice", "template_id": "canh_chua"}).json()["kudos"]["id"]
    client.post(f"{BASE}/{k3}/reply", json={"text": "Phải có me chín."}, headers=ELDER)
    assert client.post(f"{BASE}/{k3}/save", json={"decline": True}, headers=ELDER).json()["declined"]
    assert client.get(BASE + "?box=sent", headers=LAN).json()["items"][0]["story"]["declined"]
    k4 = send(client, {"kind": "advice", "template_id": "cough"}).json()["kudos"]["id"]
    r = client.post(f"{BASE}/{k4}/reply", json={"choice": "call_back"}, headers=ELDER).json()
    assert r["kudos"]["reply_vi"].startswith("Má muốn gọi lại") and r["can_save"] is False


def test_withdrawn_family_sharing_hides_health_answers_not_hearts(client):
    k1 = send(client, {"kind": "checkin", "template_id": "slept"}).json()["kudos"]["id"]
    k2 = send(client, {"kind": "love", "template_id": "love"}).json()["kudos"]["id"]
    client.post(f"{BASE}/{k1}/reply", json={"choice": "awake"}, headers=ELDER)
    client.post(f"{BASE}/{k2}/reply", json={"heart": True}, headers=ELDER)
    client.post("/api/elders/hanh/consents/family_sharing/withdraw", json={"confirmed_by_elder_or_proxy": True})
    items = {i["id"]: i for i in client.get(BASE + "?box=sent", headers=LAN).json()["items"]}
    assert items[k1]["reply"] is None and items[k1]["reply_hidden"] and "Thức nhiều" not in items[k1]["reply_vi"]
    assert items[k2]["reply"]["heart"] and not items[k2]["reply_hidden"]
    tl = client.get("/api/elders/hanh/family/timeline", headers=LAN).json()["items"]
    row = next(i for i in tl if i.get("kudos_id") == k1)
    assert "Thức nhiều" not in row["text_vi"] and "tạm dừng" in row["text_vi"]
    mine = {i["id"]: i for i in client.get(BASE + "?box=inbox", headers=ELDER).json()["items"]}
    assert mine[k1]["reply"]["choice"] == "awake"                            # the elder still sees her own answer


def test_timeline_shows_cards_and_replies(client):
    kid = send(client, {"kind": "checkin", "template_id": "feeling"}).json()["kudos"]["id"]
    client.post(f"{BASE}/{kid}/reply", json={"choice": "well"}, headers=ELDER)
    tl = client.get("/api/elders/hanh/family/timeline", headers=VY).json()["items"]
    row = next(i for i in tl if i["kind"] == "kudos" and i["kudos_id"] == kid)
    assert row["title_vi"] == "Lan gửi má: “Hôm nay má thấy trong người sao?”"
    assert row["text_vi"].startswith("Má trả lời: Khỏe con")
    assert sum(i["kind"] == "kudos" for i in tl) >= 4                                        # seeded history too


def test_simulated_call_relays_pending_cards_and_records_the_replies(client):
    adv = send(client, {"kind": "advice", "template_id": "canh_chua"}).json()["kudos"]["id"]
    ate = send(client, {"kind": "checkin", "template_id": "ate"}, VY).json()["kudos"]["id"]
    love = send(client, {"kind": "love", "template_id": "miss"}, MINH).json()["kudos"]["id"]
    cid, replies = run_simulated_call(client)
    first = replies[0]["reply_text"]
    assert "Anh Minh gửi thương bà nè" in first and "Chị Lan hỏi bà nấu canh chua" in first
    assert replies[1]["reply_text"].startswith("Dạ, bà chỉ kỹ quá, con nhắn lại cho chị Lan liền nha.")
    assert "Cháu Vy hỏi bà ăn cơm chưa" in replies[1]["reply_text"]
    assert replies[2]["reply_text"].startswith("Dạ, con nhắn lại cho cháu Vy liền nha.")
    texts = " ".join(r["reply_text"] for r in replies)
    assert "ăn gì chưa" not in texts and "ăn sáng món gì" not in texts       # the food question is not asked twice
    end = client.post(f"/api/calls/{cid}/end").json()
    assert end["metrics"]["valid"] and end["metrics"]["elder_speech_sec"] >= 45
    got = {k["id"]: k for k in end["kudos_relay"]}
    assert got[adv]["text"] and got[ate]["choice"] == "ate" and got[love]["seen"]
    items = {i["id"]: i for i in client.get(BASE + "?box=family", headers=LAN).json()["items"]}
    assert items[adv]["reply"]["via"] == "call" and "me chín" in items[adv]["reply"]["text"]
    assert items[adv]["reply"]["simulated"] and "diễn tập" in items[adv]["reply_vi"]
    assert items[ate]["reply"]["choice"] == "ate" and items[love]["status"] == "seen"
    assert items[love]["seen_via"] == "call"
    assert inbox(client) == []                                                # nothing left for the screen
    # the next call has nothing to relay
    _, again = run_simulated_call(client)
    assert "gửi thương" not in again[0]["reply_text"]


def test_cards_seen_on_the_screen_are_not_relayed(client):
    kid = send(client, {"kind": "checkin", "template_id": "slept"}).json()["kudos"]["id"]
    client.post(f"{BASE}/{kid}/seen", json={"snooze_minutes": 120}, headers=ELDER)
    assert inbox(client) == []                                                # snoozed ("Để sau")
    _, replies = run_simulated_call(client)
    assert "Chị Lan" not in replies[0]["reply_text"]


def test_demo_reset_clears_and_reseeds(client):
    send(client, {"kind": "love", "template_id": "love"})
    n = len(client.get(BASE + "?box=family&days=60", headers=LAN).json()["items"])
    assert client.post("/api/demo/reset?elder=hanh").status_code == 200
    items = client.get(BASE + "?box=family&days=60", headers=LAN).json()["items"]
    assert len(items) == n - 1 and all(i["simulated"] for i in items)
    advice = [s for s in client.get("/api/elders/hanh/memories").json()["stories"] if s["theme"] == "advice"]
    assert len(advice) == 1
