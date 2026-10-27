"""Relay of family cards in the morning call (relay.py + orchestrator slot + simulator)."""
from agent_helpers import make_ctx

from chaoba.agent import relay
from chaoba.agent.orchestrator import Orchestrator, ScriptedEngine
from chaoba.agent.prompts import PHASE_DIRECTIVES, build_context_block
from chaoba.agent.relay import RelayItem
from chaoba.agent.simulator import next_elder_line
from chaoba.core.metrics import compute_call_metrics

ADV = RelayItem(1, "advice", "canh_chua", "Lan", "chị Lan", "{s} hỏi {h} nấu canh chua sao cho ngon, {h} chỉ giùm với?")
ATE = RelayItem(2, "checkin", "ate", "Minh", "anh Minh", "{s} hỏi {h} ăn cơm chưa {h}?", topic="food")
LOVE = RelayItem(3, "love", "love", "Vy", "cháu Vy", "")
TIP = RelayItem(4, "care_tip", "water", "Lan", "chị Lan", "{s} dặn trời nóng {h} nhớ uống nước nha.")


def run(items, n=25):
    ctx = make_ctx()
    ctx.relay = list(items)
    o = Orchestrator(ScriptedEngine())
    st, _ = o.start(ctx, "relay-test")
    t, out = 5.0, []
    for _ in range(n):
        line = next_elder_line(st, 3.6, 0.12)
        r = o.handle_turn(st, line["text"], t, t + line["duration_sec"], line["pauses"])
        t += line["duration_sec"] + 5
        out.append((line["text"], r.reply_text, st.step))
        if r.end_call:
            break
    return st, out


def test_parse_choice_for_each_checkin():
    assert relay.parse_choice("ate", "Ăn rồi con, ăn cháo") == "ate"
    assert relay.parse_choice("ate", "Chưa ăn con, chưa đói") == "not_yet"
    assert relay.parse_choice("ate", "Dạ chưa") == "not_yet"
    assert relay.parse_choice("slept", "Tối qua thức hoài à con") == "awake"
    assert relay.parse_choice("slept", "Ngủ hổng ngon lắm") == "meh"
    assert relay.parse_choice("slept", "Ngủ ngon lắm con") == "good"
    assert relay.parse_choice("feeling", "Hổng khỏe lắm con") == "tired"
    assert relay.parse_choice("feeling", "Cũng bình thường") == "ok"
    assert relay.parse_choice("feeling", "Khỏe re con") == "well"
    assert relay.parse_choice("meds", "Uống rồi con") == "yes" and relay.parse_choice("meds", "Quên mất") == "no"
    assert relay.parse_choice("ate", "Hôm nay trời đẹp") is None


def test_advice_call_back_and_announcements():
    assert relay.parse_answer(ADV, "Để bà gọi lại nói cho nó nghe")["choice"] == "call_back"
    long = relay.parse_answer(ADV, "Phải có me chín, cá lóc chiên sơ, nước sôi mới bỏ thơm với cà chua, rồi gọi lại "
                                   "cho bà nếu hổng được")
    assert "choice" not in long and long["text"]
    qs, ann = relay.plan([LOVE, ATE, ADV, TIP])
    assert [q.id for q in qs] == [1, 2] and [a.id for a in ann] == [3, 4]          # advice first
    first = relay.first_text(qs, ann, "bà")
    assert first.startswith("Cháu Vy gửi thương bà nè. Chị Lan dặn trời nóng bà nhớ uống nước nha.")
    assert first.endswith("Chị Lan hỏi bà nấu canh chua sao cho ngon, bà chỉ giùm với?")
    only = relay.first_text([], [LOVE], "bà")
    assert only == "Cháu Vy gửi thương bà nè. Bà có muốn nhắn gì lại cho cháu Vy hông bà?"
    assert relay.ack_text(ATE, {"text": "Ăn rồi"}, "bà") == "Dạ, con nhắn lại cho anh Minh liền nha."
    assert "gọi bà" in relay.ack_text(ADV, {"choice": "call_back"}, "bà")


def test_scripted_call_relays_after_consent_and_records_answers():
    st, out = run([ADV, ATE, LOVE])
    assert "gửi thương bà nè" in out[0][1] and "canh chua" in out[0][1] and out[0][2] == "relay"
    assert out[1][1].startswith("Dạ, bà chỉ kỹ quá, con nhắn lại cho chị Lan liền nha. Anh Minh hỏi bà ăn cơm chưa")
    assert out[2][1].startswith("Dạ, con nhắn lại cho anh Minh liền nha.")
    a = st.relay_answers
    assert a[0]["item_id"] == 1 and a[0]["announced"] == [3] and "me chín" in a[0]["text"]
    assert a[1]["item_id"] == 2 and a[1]["choice"] == "ate"
    assert "food" in st.wellbeing_done and not any(s == "ask_food" for _, _, s in out)   # not asked twice
    assert out[-1][2] == "closing" and st.recall_stage == "done"                          # the rest of the call runs
    m = compute_call_metrics(st.turns)
    assert m.valid and m.elder_speech_sec >= 45


def test_announcement_only_relay_asks_if_she_wants_to_reply():
    st, out = run([LOVE])
    assert out[0][1] == "Dạ. Cháu Vy gửi thương bà nè. Bà có muốn nhắn gì lại cho cháu Vy hông bà?"
    assert st.relay_answers[0]["item_id"] is None and st.relay_answers[0]["announced"] == [3]
    assert out[1][1].startswith("Dạ, con nhắn lại cho cháu Vy liền nha.")


def test_no_cards_no_relay_slot():
    st, out = run([])
    assert st.relay_stage == "none" and out[0][2] == "ask_sleep"


def test_relay_for_ong_uses_his_voice():
    ctx_items = [RelayItem(9, "checkin", "slept", "Khoa", "anh Khoa", "{s} hỏi tối qua {h} ngủ ngon hông {h}?",
                           topic="sleep")]
    from agent_helpers import PROFILE
    p = dict(PROFILE, honorific="ông", display_name="Ông Tư")
    ctx = make_ctx(p)
    ctx.relay = ctx_items
    o = Orchestrator(ScriptedEngine())
    st, _ = o.start(ctx, "tu")
    r = o.handle_turn(st, "Ừ, được con.", 1, 3, [])
    assert "Anh Khoa gửi thương ông nè. Anh Khoa hỏi tối qua ông ngủ ngon hông ông?" in r.reply_text


def test_prompt_mentions_relay():
    ctx = make_ctx()
    ctx.relay = [ADV]
    assert "Family cards to relay" in build_context_block(ctx) and "relay" in PHASE_DIRECTIVES


def test_claude_directive_gives_the_exact_relay_sentence():
    from chaoba.agent.orchestrator import CallState, ClaudeEngine
    ctx = make_ctx()
    ctx.relay = [ATE]
    st = CallState(call_id="c", ctx=ctx, step="relay")
    d = ClaudeEngine(client=object())._directive(st)
    assert "Phase: relay" in d and 'Say exactly: "Anh Minh gửi thương bà nè. Anh Minh hỏi bà ăn cơm chưa bà?"' in d
