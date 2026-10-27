from types import SimpleNamespace

from agent_helpers import make_ctx, PROFILE
from chaoba.agent.orchestrator import Orchestrator, ScriptedEngine, ClaudeEngine, CLOSING_AT_SEC
from chaoba.agent.persona import MAX_WORDS_PER_TURN
from chaoba.agent.prompts import SYSTEM_PROMPT, PROMPT_VERSION, build_context_block
from chaoba.agent.textnorm import word_count


def new_call(ctx=None, engine=None, cid="t1"):
    orch = Orchestrator(engine or ScriptedEngine())
    state, greeting = orch.start(ctx or make_ctx(), cid)
    return orch, state, greeting


def say(orch, state, text, t):
    return orch.handle_turn(state, text, start=t, end=t + 6, pauses=[0.5])


def test_greeting_has_family_greeting_consent_and_virtual_assistant():
    _, state, g = new_call()
    assert "Lan" in g and "Út Thương" in g and "trợ lý ảo" in g and "hông" in g
    assert "ghi âm" in g
    assert state.phase == "greeting"


def test_full_phase_flow_scripted():
    orch, st, _ = new_call()
    t = 5.0
    seen = []
    script = [
        "Dạ rảnh chớ con.",
        "Đêm qua bà ngủ ngon lắm con.",
        "Sáng nay bà ăn cháo với hột vịt muối.",
        "Trong người cũng khỏe con.",
        "Ờ... bà quên mất rồi con.",              # free recall fails -> cue
        "À cây mai, cây mai ra nụ đó con.",        # cued success
        "Hồi nhỏ bà hay đi bắt cá ngoài ruộng.",
        "Đi với mấy đứa trong xóm vui lắm.",
        "Tối về bị má rầy quá trời.",
        "Ừ, vui lắm con.",
        "Ừ chào con.",
    ]
    res = None
    for line in script:
        res = say(orch, st, line, t)
        t += 10
        seen.append((st.step, res.phase))
        if res.end_call:
            break
    steps = [s for s, _ in seen]
    assert steps[:6] == ["ask_sleep", "ask_food", "ask_feel", "recall_free", "recall_cue", "recall_close"]
    assert "story_follow" in steps
    assert res.end_call and steps[-1] == "closing"
    assert st.recall_result == "cued"
    closing = st.turns[-1].text
    assert "Amlodipine 5mg" in closing and "07:00" in closing   # medication reminder
    assert "chủ nhật" in closing                                 # family message passed on
    # style: every non-greeting, non-closing agent turn <= 20 words and at most one question
    agent_turns = [x.text for x in st.turns if x.speaker == "agent"][1:-1]
    for a in agent_turns:
        assert word_count(a) <= MAX_WORDS_PER_TURN, a
        assert a.count("?") <= 1, a
        assert " con " in f" {a} " or "Dạ" in a or "bà" in a


def test_exact_free_recall_skips_cue():
    orch, st, _ = new_call()
    t = 0
    for line in ["Dạ được.", "Ngủ ngon.", "Ăn cơm rồi.", "Khỏe con."]:
        say(orch, st, line, t); t += 8
    assert st.step == "recall_free"
    r = say(orch, st, "Cây mai trước nhà sắp ra nụ đó con.", t)
    assert st.recall_result == "exact" and st.step == "recall_close" and r.phase == "story"


def test_time_based_closing():
    orch, st, _ = new_call()
    say(orch, st, "Dạ được con.", 5)
    r = orch.handle_turn(st, "Bà ngủ cũng được.", start=CLOSING_AT_SEC, end=CLOSING_AT_SEC + 4)
    assert st.step == "closing" and r.end_call


def test_scripted_replies_vary_between_calls():
    texts = set()
    for i in range(6):
        orch, st, _ = new_call(cid=f"c{i}")
        texts.add(say(orch, st, "Dạ rảnh con.", 3).reply_text)
    assert len(texts) >= 2


def test_keyword_reactions():
    orch, st, _ = new_call()
    say(orch, st, "Dạ được.", 1)                   # -> ask sleep
    r = say(orch, st, "Đêm qua bà mất ngủ, trằn trọc hoài.", 10)
    assert "ngủ" in r.reply_text or "thức" in r.reply_text
    r = say(orch, st, "Bà chưa ăn gì hết, ăn hổng vô.", 20)
    assert "ăn" in r.reply_text


def test_consent_declined_ends_politely():
    orch, st, _ = new_call()
    r = say(orch, st, "Thôi để sau đi con, bà đang bận.", 3)
    assert r.end_call and st.declined and r.event == "declined"


def test_opt_out_flow_confirm_and_record():
    orch, st, _ = new_call()
    say(orch, st, "Dạ được.", 1)
    r = say(orch, st, "Thôi con đừng gọi nữa, tui không muốn nói chuyện.", 10)
    assert r.event == "opt_out_confirm" and not r.end_call and "ngưng" in r.reply_text
    r = say(orch, st, "Ừ, đúng rồi.", 20)
    assert r.event == "opt_out" and r.end_call and st.opted_out


def test_opt_out_cancelled():
    orch, st, _ = new_call()
    say(orch, st, "Dạ được.", 1)
    say(orch, st, "Đừng gọi nữa.", 10)
    r = say(orch, st, "Thôi hổng phải, con cứ gọi.", 20)
    assert r.event == "opt_out_cancelled" and not st.opted_out and not r.end_call


def test_scam_refusal_and_flag():
    orch, st, _ = new_call()
    say(orch, st, "Dạ được.", 1)
    r = say(orch, st, "Có người gọi kêu tui đọc mã OTP ngân hàng, con giúp tui chuyển tiền nha.", 10)
    assert r.event == "scam" and "đừng" in r.reply_text and not r.end_call
    assert st.flags and st.flags[0]["type"] == "scam"
    assert "OTP" not in r.reply_text


def test_medication_change_and_diagnosis_deferred_to_doctor():
    orch, st, _ = new_call()
    say(orch, st, "Dạ được.", 1)
    r = say(orch, st, "Tui tính bỏ thuốc huyết áp luôn được hông con?", 10)
    assert r.event == "medication" and "bác sĩ" in r.reply_text
    r = say(orch, st, "Con coi tui bị bệnh gì vậy?", 20)
    assert r.event == "diagnosis" and "bác sĩ" in r.reply_text


def test_emergency_ends_call():
    orch, st, _ = new_call()
    say(orch, st, "Dạ được.", 1)
    r = say(orch, st, "Con ơi tui tức ngực quá, khó thở.", 10)
    assert r.emergency and r.end_call and "115" in r.reply_text and st.emergency
    assert say(orch, st, "alo", 20).end_call   # further turns are ignored


def test_prompt_versioned_and_context_block():
    assert PROMPT_VERSION and "Út Thương" in SYSTEM_PROMPT and "flag_emergency" in SYSTEM_PROMPT
    block = build_context_block(make_ctx())
    assert "Amlodipine" in block and "HIDDEN recall answer" in block and "Lan nhắn" in block


# ------------------------------------------------------------------ ClaudeEngine with a fake client
class FakeMessages:
    def __init__(self, responses, calls):
        self.responses, self.calls = responses, calls

    def create(self, **kw):
        self.calls.append(kw)
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


class FakeClient:
    def __init__(self, beta_responses, plain_responses=()):
        self.calls = []
        self.beta = SimpleNamespace(messages=FakeMessages(list(beta_responses), self.calls))
        self.messages = FakeMessages(list(plain_responses), self.calls)


def text_resp(t):
    return SimpleNamespace(content=[SimpleNamespace(type="text", text=t)], stop_reason="end_turn")


def test_claude_engine_uses_cache_and_phase_directive():
    fc = FakeClient([text_resp("Dạ, bà ngủ có ngon hông bà?")])
    orch, st, _ = new_call(engine=ClaudeEngine(client=fc))
    r = say(orch, st, "Dạ rảnh con.", 2)
    assert r.reply_text == "Dạ, bà ngủ có ngon hông bà?"
    kw = fc.calls[0]
    assert kw["model"] == "claude-sonnet-5-5"
    assert kw["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert kw["system"][0]["text"] == SYSTEM_PROMPT
    assert kw["tools"][0]["name"] == "flag_emergency"
    assert kw["messages"][-1]["role"] == "system" and "sleep" in kw["messages"][-1]["content"]
    assert kw["fallbacks"] == "default"


def test_claude_engine_layer2_emergency_tool():
    tool = SimpleNamespace(type="tool_use", name="flag_emergency", id="t1",
                           input={"category": "other", "quote": "Tui thấy trong người lạ lắm, mắt mờ hết"})
    fc = FakeClient([SimpleNamespace(content=[tool], stop_reason="tool_use")])
    orch, st, _ = new_call(engine=ClaudeEngine(client=fc))
    r = say(orch, st, "Tui thấy trong người lạ lắm, mắt mờ hết", 2)
    assert r.emergency and r.end_call and "115" in r.reply_text
    assert st.emergency_hits[-1]["layer"] == 2


def test_claude_engine_falls_back_to_haiku_then_scripted():
    fc = FakeClient([RuntimeError("boom")], [text_resp("Dạ, đêm qua bà ngủ sao bà?")])
    orch, st, _ = new_call(engine=ClaudeEngine(client=fc))
    r = say(orch, st, "Dạ rảnh con.", 2)
    assert fc.calls[1]["model"] == "claude-haiku-5-5" and "ngủ" in r.reply_text
    fc2 = FakeClient([RuntimeError("down")], [RuntimeError("down")])
    orch, st, _ = new_call(engine=ClaudeEngine(client=fc2), cid="t2")
    r = say(orch, st, "Dạ rảnh con.", 2)
    assert r.reply_text and st.engine_used == "scripted-fallback"


def test_claude_engine_output_scrubbed():
    fc = FakeClient([text_resp("Bà có thể bị sa sút trí tuệ đó.")])
    orch, st, _ = new_call(engine=ClaudeEngine(client=fc))
    r = say(orch, st, "Dạ rảnh con.", 2)
    assert "sa sút" not in r.reply_text
