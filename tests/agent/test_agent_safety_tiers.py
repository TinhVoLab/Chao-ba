"""Emergency tiers (acute / non-acute / third-party), diagnosis guardrail, symptom follow-ups, story coherence and
family honorifics."""
import pytest

from agent_helpers import make_ctx, PROFILE
from chaoba.agent.analysis import extract_symptoms
from chaoba.agent.emergency import spot, emergency_reply
from chaoba.agent.guardrails import detect_diagnosis_request, opt_out_done
from chaoba.agent.orchestrator import Orchestrator, ScriptedEngine, time_frame
from chaoba.agent.persona import ElderView, family_ref, with_family_honorifics
from chaoba.agent.prompts import default_family_greeting
from chaoba.agent.simulator import calibrated_timing
from chaoba.core.metrics import count_syllables


def new_call(ctx=None):
    orch = Orchestrator(ScriptedEngine())
    st, _ = orch.start(ctx or make_ctx(), "tier1")
    return orch, st


def say(orch, st, text, t):
    return orch.handle_turn(st, text, start=t, end=t + 6, pauses=[0.5])


# ------------------------------------------------------------------ spotter tiers
@pytest.mark.parametrize("text,cat,tier", [
    ("Hôm qua thằng cháu té xe trầy chân", "fall", "third_party"),
    ("Tui bị ngã cầu thang hôm qua", "fall", "non_acute"),
    ("đang đau ngực", "chest_pain", "acute"),
    ("tui té hổng dậy được", "fall", "acute"),
    ("hôm qua tui hơi tức ngực", "chest_pain", "non_acute"),
    ("Sáng nay tui bị té trong nhà tắm", "fall", "acute"),          # today = acute (safety first)
    ("Hôm qua tui té, giờ còn đau lắm", "fall", "acute"),           # past event, still going on
    ("Ông nhà tui hôm qua bị té", "fall", "third_party"),           # possessive "tui"
    ("Bà Tư hàng xóm bị ngã", "fall", "third_party"),
    ("Con Lan nó té xe", "fall", "third_party"),
    ("Thằng cháu tới chơi rồi tui bị té", "fall", "acute"),         # last subject = the elder
    ("Hôm qua tui muốn chết cho rồi", "self_harm", "acute"),        # self-harm: acute regardless of tense
    ("Hồi xưa tui hổng muốn sống nữa", "self_harm", "acute"),
])
def test_spotter_tiers(text, cat, tier):
    hit = spot(text, "bà")
    assert hit is not None and hit.category == cat and hit.tier == tier, (text, hit)


def test_acute_fall_now_ends_call_with_115():
    orch, st = new_call()
    say(orch, st, "Dạ được con.", 1)
    r = say(orch, st, "Tui té hổng dậy được con ơi", 10)
    assert r.emergency and r.end_call and "115" in r.reply_text and r.event == "emergency"
    assert "chị Lan" in r.reply_text and "cô Lan" not in r.reply_text


def test_acute_chest_pain_now():
    orch, st = new_call()
    say(orch, st, "Dạ được con.", 1)
    r = say(orch, st, "Con ơi tui đang đau ngực", 10)
    assert r.emergency and "115" in r.reply_text


@pytest.mark.parametrize("first", ["Tui bị ngã cầu thang hôm qua", "hôm qua tui hơi tức ngực"])
def test_non_acute_asks_one_confirming_question_no_115(first):
    orch, st = new_call()
    say(orch, st, "Dạ được con.", 1)
    r = say(orch, st, first, 10)
    assert r.event == "health_concern" and not r.emergency and not r.end_call
    assert "115" not in r.reply_text and r.reply_text.count("?") == 1
    assert "đang đau hay chảy máu" in r.reply_text
    assert st.concern_hits and st.awaiting_confirm
    # "no" -> reassure, family will check in today, conversation goes on
    r2 = say(orch, st, "Dạ hổng có, hết đau rồi con", 20)
    assert not r2.emergency and not r2.end_call and "115" not in r2.reply_text
    assert "hỏi thăm" in r2.reply_text and "chị Lan" in r2.reply_text
    assert r2.event == "health_concern_settled" and not st.emergency


def test_non_acute_confirmed_now_escalates_to_acute():
    orch, st = new_call()
    say(orch, st, "Dạ được con.", 1)
    say(orch, st, "hôm qua tui hơi tức ngực", 10)
    r = say(orch, st, "Dạ có, giờ còn đau", 20)
    assert r.emergency and r.end_call and "115" in r.reply_text and st.emergency
    assert st.emergency_hits[-1]["category"] == "chest_pain"


def test_non_acute_in_first_answer_does_not_turn_no_into_declined_consent():
    orch, st = new_call()
    say(orch, st, "Tui bị ngã cầu thang hôm qua", 1)
    r = say(orch, st, "Hổng có", 10)
    assert r.event != "declined" and not r.end_call


def test_third_party_gets_empathy_not_an_alert():
    orch, st = new_call()
    say(orch, st, "Dạ được con.", 1)
    r = say(orch, st, "Hôm qua thằng cháu té xe trầy chân", 10)
    assert not r.emergency and not r.end_call and "115" not in r.reply_text
    assert r.event == "third_party" and "tội nghiệp" in r.reply_text
    assert not st.concern_hits and st.third_party_hits
    # and the elder's own symptoms do not include the grandchild's fall
    assert "fall" not in extract_symptoms(["Hôm qua thằng cháu té xe trầy chân"], "bà")
    assert "fall" in extract_symptoms(["Tui bị ngã cầu thang hôm qua"], "bà")


# ------------------------------------------------------------------ diagnosis guardrail
@pytest.mark.parametrize("text", ["Tui bị bệnh tiểu đường hả con?", "Vậy là bệnh gì con?",
                                  "Có phải tui bị lẫn rồi không?", "Bà bị tim phải hông con", "Tui bị gì vậy con"])
def test_diagnosis_questions(text):
    assert detect_diagnosis_request(text), text


@pytest.mark.parametrize("text", ["Tui bị đau lưng chút xíu", "Hổng có bệnh gì hết con", "Sáng nay ăn cháo"])
def test_not_diagnosis_questions(text):
    assert detect_diagnosis_request(text) is None, text


def test_diagnosis_reply_points_to_doctor_and_family():
    orch, st = new_call()
    say(orch, st, "Dạ được con.", 1)
    r = say(orch, st, "Tui bị bệnh tiểu đường hả con?", 10)
    assert r.event == "diagnosis" and "bác sĩ" in r.reply_text and "chị Lan" in r.reply_text
    assert "tiểu đường" not in r.reply_text


# ------------------------------------------------------------------ scripted engine: content-aware
def test_symptom_followup_once():
    orch, st = new_call()
    say(orch, st, "Dạ được con.", 1)
    say(orch, st, "Ngủ ngon con.", 10)
    r = say(orch, st, "Sáng nay ăn cháo, mà hơi mỏi cái lưng chút xíu.", 20)
    assert r.event == "symptom_followup" and "mỏi cái lưng" in r.reply_text and "từ hồi nào" in r.reply_text
    assert r.reply_text.count("?") == 1
    r = say(orch, st, "Mấy bữa nay rồi con, mà đỡ rồi.", 30)
    assert r.event is None and st.step == "ask_feel"   # plan resumes
    r = say(orch, st, "Cũng còn mỏi cái lưng.", 40)
    assert r.event != "symptom_followup"                # once per symptom


def test_no_followup_for_negated_or_third_party_symptom():
    orch, st = new_call()
    say(orch, st, "Dạ được con.", 1)
    assert say(orch, st, "Hổng đau gì hết con, ngủ ngon.", 10).event is None
    assert say(orch, st, "Thằng cháu nó bị đau bụng.", 20).event is None


def test_story_followup_matches_what_was_said():
    assert time_frame("Chủ nhật này con Lan về thăm, bà tính nấu canh chua") == "future"
    assert time_frame("Hồi nhỏ ở quê bà hay đi bắt cá") == "past"
    eng = ScriptedEngine()
    orch, st = new_call()
    st.step, st.phase = "story_follow", "story"
    reply, _, _ = eng.reply(st, "Chủ nhật này con Lan về thăm, bà tính nấu canh chua cá lóc.")
    assert "Hồi đó" not in reply and "nhớ lại" not in reply


# ------------------------------------------------------------------ honorifics
def test_family_honorifics():
    assert family_ref({"name": "Lan", "relation": "daughter"}) == "chị Lan"
    assert family_ref({"name": "Khoa", "relation": "son"}) == "anh Khoa"
    assert family_ref({"name": "Bà Tư", "relation": "wife"}) == "bà Tư"          # never "cô Bà Tư"
    assert family_ref({"name": "Thảo", "relation": "daughter", "honorific": "cô"}) == "cô Thảo"
    p = with_family_honorifics({"family": [{"name": "Bà Tư", "relation": "wife"}]})
    assert p["family"][0]["honorific"] == "bà"
    tu = {"id": "tu", "display_name": "Ông Tư", "honorific": "ông",
          "family": [{"id": "ba_tu", "name": "Bà Tư", "relation": "wife", "role": "primary"}]}
    ev = ElderView.from_profile(tu)
    assert "cô Bà Tư" not in emergency_reply("fall", "ông", ev.family_ref) and "bà Tư" in emergency_reply("fall", "ông", ev.family_ref)
    assert "bà Tư" in opt_out_done("ông", ev.family_ref)
    assert "tui nè" in default_family_greeting(ev)


# ------------------------------------------------------------------ simulator calibration
def test_simulator_timing_hits_target_rate_and_pause_ratio():
    text = "Chủ nhật này con Lan về thăm, bà tính nấu nồi canh chua cá lóc với kho tộ cho nó ăn."
    pauses, dur = calibrated_timing(text, 4.64, 0.115, "s")
    voiced = dur - sum(pauses)
    assert abs(count_syllables(text) / voiced - 4.64) < 0.01
    assert abs(sum(pauses) / dur - 0.115) < 0.01 and all(0.4 <= p <= 3 for p in pauses)
