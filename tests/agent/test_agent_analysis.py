import json
from types import SimpleNamespace

from agent_helpers import PROFILE
from chaoba.agent.analysis import (analyze_rule_based, analyze_call, extract_symptoms, mood_score, score_recall,
                                   ANALYSIS_SCHEMA)
from chaoba.agent.prompts import recall_from_fact, PROMPT_VERSION
from chaoba.core.models import Turn, SYMPTOMS

RECALL = recall_from_fact("Cây mai trước nhà sắp ra nụ", "bà")
FORBIDDEN = ("sa sút trí tuệ", "trầm cảm", "dementia", "depression", "alzheimer", "chẩn đoán", "diagnos")


def turns(*elder_lines):
    out, t = [], 0.0
    for line in elder_lines:
        out.append(Turn("agent", "Dạ, bà kể con nghe với?", t, t + 3))
        out.append(Turn("elder", line, t + 3.5, t + 10, [0.5]))
        t += 11
    return out


def test_symptoms_with_verbatim_quotes_and_negation():
    s = extract_symptoms(["Đêm qua bà mất ngủ, trằn trọc hoài.", "Hổng đau gì hết con.",
                          "Sáng nay chóng mặt chút xíu.", "Bà quên uống thuốc hồi sáng.", "Buồn cười quá con."])
    assert s["insomnia"] == ["Đêm qua bà mất ngủ, trằn trọc hoài."]
    assert "dizziness" in s and "missed_medication" in s
    assert "pain" not in s            # negated
    assert "sadness" not in s         # "buồn cười" = funny
    assert set(s) <= set(SYMPTOMS)


def test_mood_heuristic_range_and_direction():
    happy = mood_score(["Bà vui lắm, khỏe re, ăn ngon ngủ ngon."], {})
    sad = mood_score(["Bà buồn quá, cô đơn, mệt mỏi lắm con."], {"sadness": ["x"]})
    assert 1 <= sad < 3 < happy <= 5


def test_recall_scoring_levels():
    assert score_recall(RECALL, "Cây mai trước nhà sắp ra nụ đó con.", "") == (3, "free")
    assert score_recall(RECALL, "Hình như cây mai gì đó.", "") == (2, "free")
    assert score_recall(RECALL, "Bà quên rồi.", "À, cây mai ra nụ!") == (1, "cued")
    assert score_recall(RECALL, "Bà quên rồi.", "Hổng nhớ con ơi.") == (0, "failed")
    assert score_recall(None, "", "") == (None, None)
    # "lắm" must not match "làm"-style keywords through accent stripping
    r2 = recall_from_fact("Con gái Lan làm ở TP.HCM", "bà")
    assert score_recall(r2, "Vui lắm con.", "")[0] == 0


def test_rule_based_analysis_full():
    t = turns("Dạ rảnh con.", "Đêm qua mất ngủ con ơi.", "Bà quên rồi.", "À cây mai ra nụ.",
              "Chủ nhật này con Lan về thăm, bà tính nấu canh chua cá lóc cho nó ăn.")
    a = analyze_rule_based(t, PROFILE, RECALL, "Bà quên rồi.", "À cây mai ra nụ.")
    assert a.recall_score == 1 and a.recall_cue_level == "cued"
    assert "insomnia" in a.symptoms
    assert a.followup_hooks and "Chủ nhật" in a.followup_hooks[0]
    assert a.memory_facts_new
    assert a.prompt_version == PROMPT_VERSION and not a.emergency
    text = (a.summary_vi + a.summary_en).lower()
    assert "bà hạnh" in text and "mrs hanh" in text
    for bad in FORBIDDEN:
        assert bad not in text


def test_emergency_and_opt_out_summaries():
    a = analyze_rule_based(turns("Tui tức ngực quá"), PROFILE, emergency=True)
    assert a.emergency and "115" in a.summary_vi
    b = analyze_rule_based(turns("Đừng gọi nữa"), PROFILE, opted_out=True)
    assert "ngưng" in b.summary_vi


def test_analyze_call_without_key_is_rule_based(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    a = analyze_call(turns("Bà khỏe con."), PROFILE, RECALL)
    assert a.prompt_version == PROMPT_VERSION


def test_analyze_call_with_fake_claude_structured_output():
    payload = {"summary_vi": "Bà vui vẻ.", "summary_en": "She was cheerful.", "mood": 4,
               "symptoms": {s: [] for s in SYMPTOMS} | {"pain": ["mỏi lưng"]}, "recall_score": 3,
               "recall_cue_level": "free", "memory_facts_new": ["Cháu sắp cưới"], "followup_hooks": ["Đám cưới cháu"],
               "emergency": False}
    calls = []

    def create(**kw):
        calls.append(kw)
        return SimpleNamespace(stop_reason="end_turn", content=[SimpleNamespace(type="text", text=json.dumps(payload))])
    fc = SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(create=create)))
    a = analyze_call(turns("Bà khỏe."), PROFILE, RECALL, use_llm=True, client=fc)
    assert a.mood == 4 and a.symptoms == {"pain": ["mỏi lưng"]} and a.recall_score == 3
    kw = calls[0]
    assert kw["model"] == "claude-opus-5-5"
    assert kw["output_config"]["format"]["schema"] == ANALYSIS_SCHEMA
    # failure -> rule-based
    def boom(**kw):
        raise RuntimeError("x")
    fc2 = SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(create=boom)))
    assert analyze_call(turns("Bà khỏe."), PROFILE, RECALL, use_llm=True, client=fc2).prompt_version == PROMPT_VERSION


def test_livekit_adapter_import_guard_and_timer():
    from chaoba.agent import livekit_agent as lk
    assert lk.LIVEKIT_AVAILABLE is False
    tt = lk.TurnTimer(call_t0=100.0)
    tt.speech_start(110.0); tt.speech_end(112.0); tt.speech_start(112.8); tt.speech_end(115.0)
    s, e, p = tt.take()
    assert (s, e) == (10.0, 15.0) and p == [0.8]
