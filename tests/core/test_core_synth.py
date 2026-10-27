import pytest

from chaoba.core.synth import generate_cohort, generate_persona

PROFILE_KEYS = {"id", "display_name", "name_en", "honorific", "self_ref", "age", "province", "dialect", "lives_alone",
                "channel_pref", "conditions", "medications", "family", "goals", "memory_facts"}


@pytest.fixture(scope="module")
def personas():
    return {k: generate_persona(k) for k in ("hanh", "tu", "control")}


def first(p, color, after=21):
    return next((l["day"] for l in p["lights"] if l["light"] == color and l["day"] > after), None)


def test_shape(personas):
    for k, p in personas.items():
        assert p["simulated"] is True
        assert PROFILE_KEYS <= set(p["elder"])
        assert len(p["records"]) == 90 and len(p["lights"]) == 90
        assert all(r["simulated"] for r in p["records"])
        assert {"phases", "effect", "new_baseline_day"} <= set(p["dmaic"])
        assert [ph["phase"] for ph in p["dmaic"]["phases"]] == ["define", "measure", "analyze", "improve", "control"]
        assert p["consents"] and p["events"]
        for e in p["events"]:
            assert {"day", "type", "label_vi", "label_en"} <= set(e)
        assert all(r["summary_vi"] and r["summary_en"] for r in p["records"])


def test_hanh_timeline(personas):
    p = personas["hanh"]
    assert all(l["light"] in ("gray", "green") for l in p["lights"] if l["day"] < 33)
    assert 36 <= first(p, "yellow") <= 40
    assert 41 <= first(p, "red") <= 45
    assert 53 <= p["dmaic"]["green_day"] <= 59
    assert p["dmaic"]["new_baseline_day"] == 77
    assert all(l["light"] in ("gray", "green") for l in p["lights"] if l["day"] >= p["dmaic"]["green_day"])
    days = {e["type"]: e["day"] for e in p["events"]}
    assert days["medication_change"] == 30 and days["doctor_visit"] == 44 and days["rebaseline"] == 77
    assert sum(r["symptoms"].get("dizziness", 0) for r in p["records"] if 33 <= r["day"] <= 45) == 4
    assert p["dmaic"]["effect"]["speech_rate_sps"]["change_pct"] > 0


def test_tu_timeline(personas):
    p = personas["tu"]
    y = first(p, "yellow")
    assert y is not None and y >= 55
    assert first(p, "red") is None
    assert p["lights"][-1]["light"] == "yellow"
    imp = next(ph for ph in p["dmaic"]["phases"] if ph["phase"] == "improve")
    assert "thần kinh" in imp["summary_vi"]


def test_control_all_green(personas):
    p = personas["control"]
    assert all(l["light"] in ("green", "gray") for l in p["lights"])


def test_cohort():
    c = generate_cohort(n=30, days=60, seed=3)
    assert len(c) == 30
    for p in c:
        assert p["simulated"] and len(p["records"]) == 60
        t = p["truth"]
        assert set(t) >= {"decline", "onset_day", "type"}
        assert (t["onset_day"] is None) == (not t["decline"])
        assert p["elder"]["dialect"] in ("south", "central", "north")
        assert p["elder"]["channel_pref"] in ("pstn", "web")
    assert generate_cohort(n=5, days=30, seed=3)[0]["records"] == generate_cohort(n=5, days=30, seed=3)[0]["records"]
