"""Family together on the big screen ("Cả nhà ghé thăm"): photo wall, who dropped by today, the family moment and its
heart back, Út Thương's invitation on a quiet day and the photo mentioned in the morning call."""
import pytest
from fastapi.testclient import TestClient

from chaoba.server.app import create_app
from test_server_api import run_simulated_call

LAN = {"X-Actor": "Lan", "X-Role": "primary"}
MINH = {"X-Actor": "Minh", "X-Role": "viewer"}
ELDER = {"X-Role": "elder_self", "X-Actor": "elder:hanh"}
STATION = {"X-Role": "health_station", "X-Actor": "Tram"}
JPEG = "data:image/jpeg;base64," + "A" * 400


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with TestClient(create_app(str(tmp_path / "t.db"))) as c:
        yield c


def together(c, headers=ELDER):
    r = c.get("/api/elders/hanh/together", headers=headers)
    assert r.status_code == 200
    return r.json()


def test_seeded_day_shows_who_dropped_by_and_the_photo_wall(client):
    t = together(client)
    who = {m["member_id"]: m for m in t["members"]}
    assert t["total"] == 3 and who["lan"]["visited"] and who["vy"]["visited"] and not who["minh"]["visited"]
    assert "photo" in who["lan"]["via"] and not t["all_here"] and t["companion"] is None
    assert t["line_vi"] == "Lan, Vy đã ghé thăm má hôm nay." and t["screen_vi"] == "Hôm nay Lan, Vy đã ghé thăm."
    assert len(t["photos"]) == 5 and t["photos"][0]["image"].startswith("data:image/svg+xml")
    assert all(p["simulated"] for p in t["photos"]) and t["simulated"]
    me = together(client, MINH)["me"]
    assert me == {"visited": False, "via": []}


def test_last_child_completes_the_family_moment_and_the_elder_hearts_it(client):
    assert client.post("/api/elders/hanh/together/heart", headers=ELDER).status_code == 409   # Minh has not come yet
    assert client.post("/api/elders/hanh/kudos", json={"kind": "love", "template_id": "miss"}, headers=MINH).status_code == 200
    t = together(client)
    assert t["all_here"] and t["line_vi"].startswith("Cả nhà đã ghé thăm") and t["moment"]["title_vi"] == "Cả nhà nhớ má"
    assert not t["moment"]["hearted"]
    assert client.post("/api/elders/hanh/together/heart", headers=LAN).status_code == 403   # only the elder
    r = client.post("/api/elders/hanh/together/heart", headers=ELDER)
    assert r.status_code == 200 and r.json()["moment"]["hearted"]
    assert together(client, LAN)["moment"]["hearted"]                                       # the family sees it


def test_send_photo_checks_image_caption_role_and_daily_limit(client):
    url = "/api/elders/hanh/photos"
    assert client.post(url, json={"image": "data:image/svg+xml;base64,PHN2Zz4="}, headers=MINH).status_code == 422
    assert client.post(url, json={"image": JPEG, "caption": "Má nhớ tăng liều thuốc 2 viên"}, headers=MINH).status_code == 422
    assert client.post(url, json={"image": JPEG}, headers=ELDER).status_code == 403
    assert client.post(url, json={"image": JPEG}, headers=STATION).status_code == 403
    for i in range(3):
        r = client.post(url, json={"image": JPEG, "caption": f"Ảnh {i}"}, headers=MINH)
        assert r.status_code == 200
    assert r.json()["remaining_today"] == 0
    assert client.post(url, json={"image": JPEG}, headers=MINH).status_code == 429
    t = together(client)
    assert t["photos"][0]["sender_name"] == "Minh" and t["all_here"]
    pid = t["photos"][0]["id"]
    assert client.post(f"{url}/{pid}/heart", headers=MINH).status_code == 403
    assert client.post(f"{url}/{pid}/heart", headers=ELDER).json()["photo"]["hearted"]
    feed = client.get("/api/elders/hanh/family/timeline", headers=LAN).json()
    rows = [i for i in feed["items"] if i["kind"] == "photo"]
    assert rows and any("Minh gửi má một tấm ảnh" in i["title_vi"] for i in rows)


def test_photo_is_mentioned_once_in_the_morning_call(client):
    client.post("/api/elders/hanh/photos", json={"image": JPEG, "caption": "Hà Nội mưa rồi má"}, headers=MINH)
    cid, replies = run_simulated_call(client)
    assert "gửi hình lên màn hình cho bà nè: Hà Nội mưa rồi má." in replies[0]["reply_text"]
    client.post(f"/api/calls/{cid}/end")
    _, again = run_simulated_call(client)
    assert "gửi hình" not in again[0]["reply_text"]


def test_quiet_day_gets_an_invitation_from_ut_thuong(client):
    st = client.app.state.svc.store
    st.x("DELETE FROM kudos WHERE elder_id='hanh'")
    st.x("DELETE FROM family_photo WHERE elder_id='hanh'")
    st.x("DELETE FROM family_contact WHERE elder_id='hanh'")
    t = together(client)
    assert t["visited_count"] == 0 and "Út Thương" in t["companion"]["line_vi"]
