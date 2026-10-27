import itertools

import pytest

from chaoba.core.explain import BLOCKLIST, contains_blocked, explain, postcheck, template_explain
from chaoba.core.models import DailyLight, SYMPTOMS
from chaoba.core.synth import generate_persona


def L(light, reasons):
    return DailyLight(elder_id="x", day=40, date="2026-01-01", light=light, reasons=reasons, z={}, baseline_ready=True)


REASONS = [
    {"code": "metric_trend", "metric": "speech_rate_sps", "days": 9, "change_pct": -15.24, "level": "yellow"},
    {"code": "metric_shift", "metric": "recall_score", "days": 6, "change_pct": -30.0, "level": "red"},
    {"code": "multi_metric", "metrics": ["pause_ratio", "mattr"], "days": 5,
     "details": [{"metric": "pause_ratio", "days": 6, "change_pct": 40.2}, {"metric": "mattr", "days": 5, "change_pct": -4.1}]},
    {"code": "symptom_repeat", "symptom": "dizziness", "quotes": 3, "days": 7, "level": "yellow"},
    {"code": "multi_symptom", "symptoms": ["pain", "insomnia", "dizziness"], "count": 3, "quotes": 4, "days": 7},
    {"code": "fall", "symptom": "fall", "quotes": 1, "days": 1},
    {"code": "unanswered", "days": 3},
    {"code": "low_mood", "days": 4, "window": 7},
    {"code": "recovering", "days": 1, "needed": 3},
]


def test_example_sentence_shape():
    vi, en = explain(L("red", [REASONS[0], {**REASONS[3]}]), "Bà Hạnh", "Mrs Hanh")
    assert "bà nói chậm hơn khoảng 15%" in vi
    assert "3 lần nhắc chóng mặt" in vi
    assert "đi khám" in vi
    assert "15%" in en and "she" in en


@pytest.mark.parametrize("light", ["yellow", "red"])
def test_all_reason_combos_safe(light):
    for k in (1, 2, 3):
        for combo in itertools.combinations(REASONS, k):
            for names in (("Bà Hạnh", "Mrs Hanh"), ("Ông Tư", "Mr Tu")):
                vi, en = explain(L(light, list(combo)), *names)
                assert vi and en
                assert not contains_blocked(vi) and not contains_blocked(en)


def test_gray_and_green():
    vi, en = explain(L("gray", [{"code": "building_baseline", "days": 5, "needed": 14}]), "Ông Bảy", "Mr Bay")
    assert "5/14" in vi and "ông" in vi and "his" in en
    vi, _ = explain(L("gray", [{"code": "missed_call"}]), "Bà Hạnh", "Mrs Hanh")
    assert "bắt máy" in vi
    vi, en = explain(L("green", []), "Bà Hạnh", "Mrs Hanh")
    assert "bình thường" in vi


def test_personas_explanations_blocklist_clean():
    for key in ("hanh", "tu", "control"):
        p = generate_persona(key)
        for l in p["lights"]:
            assert l["explanation_vi"] and l["explanation_en"]
            assert not contains_blocked(l["explanation_vi"]) and not contains_blocked(l["explanation_en"])
        for r in p["records"]:
            assert not contains_blocked(r["summary_vi"]) and not contains_blocked(r["summary_en"])


def test_blocklist_detection_and_postcheck():
    for w in BLOCKLIST:
        assert contains_blocked(f"abc {w.upper()} xyz")
    tpl = "Hai tuần nay bà nói chậm hơn khoảng 15% và 3 lần nhắc chóng mặt."
    assert postcheck("Hai tuần nay bà nói chậm hơn chừng 15%, có 3 lần kêu chóng mặt.", tpl)
    assert not postcheck("Bà nói chậm hơn 20%.", tpl)               # new number
    assert not postcheck("Bà có dấu hiệu trầm cảm.", tpl)           # blocklisted
    assert not postcheck("", tpl)


def test_use_llm_without_key_falls_back(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    light = L("yellow", [REASONS[0]])
    assert explain(light, "Bà Hạnh", "Mrs Hanh", use_llm=True) == template_explain(light, "Bà Hạnh", "Mrs Hanh")


def test_llm_failure_falls_back(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-invalid")
    import chaoba.core.explain as ex

    class Boom:
        def __init__(self, *a, **k):
            raise RuntimeError("network down")

    import anthropic
    monkeypatch.setattr(anthropic, "Anthropic", Boom)
    light = L("red", [REASONS[5]])
    assert ex.explain(light, "Bà Hạnh", "Mrs Hanh", use_llm=True) == template_explain(light, "Bà Hạnh", "Mrs Hanh")


def test_llm_output_rejected_if_unsafe(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    import anthropic

    class Msg:
        content = [type("B", (), {"text": "VI: Bà có thể bị sa sút trí tuệ 99%.\nEN: She may have dementia."})()]

    class Client:
        def __init__(self, *a, **k):
            self.messages = self

        def create(self, **k):
            return Msg()

    monkeypatch.setattr(anthropic, "Anthropic", Client)
    light = L("yellow", [REASONS[0]])
    assert explain(light, "Bà Hạnh", "Mrs Hanh", use_llm=True) == template_explain(light, "Bà Hạnh", "Mrs Hanh")
