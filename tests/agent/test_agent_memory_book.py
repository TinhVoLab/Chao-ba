"""Memory book (life-story questions, per-story consent, story extraction) and prevention activities (games with
adaptive difficulty, habit nudges) in the agent layer."""
import json
from types import SimpleNamespace

from agent_helpers import make_ctx, PROFILE
from chaoba.agent import activities as act
from chaoba.agent import lifestory as ls
from chaoba.agent.orchestrator import Orchestrator, ScriptedEngine, ClaudeEngine
from chaoba.agent.persona import MAX_WORDS_PER_TURN
from chaoba.agent.prompts import build_context_block, SYSTEM_PROMPT, PROMPT_VERSION
from chaoba.agent.textnorm import word_count

TU = {"id": "tu", "display_name": "Ông Tư", "name_en": "Mr Tu", "honorific": "ông", "age": 76,
      "family": [{"id": "ba_tu", "name": "Bà Tư", "relation": "wife", "role": "primary"},
                 {"id": "khoa", "name": "Khoa", "relation": "son", "role": "secondary"}],
      "memory_facts": ["Từng dạy Văn ở trường Lê Quý Đôn 30 năm"]}


# ------------------------------------------------------------------------------------------- question bank
def test_bank_has_about_40_questions_across_all_themes_and_fits_a_turn():
    assert len(ls.QUESTION_BANK) >= 40
    assert len({q.id for q in ls.QUESTION_BANK}) == len(ls.QUESTION_BANK)
    for t in ls.THEMES:
        assert sum(q.theme == t for q in ls.QUESTION_BANK) >= 4, t
    for prof in (PROFILE, TU):
        for q in ls.QUESTION_BANK:
            r = ls.render(q, prof)
            for text in (r.question_vi, r.follow_up_vi):
                assert word_count(text) <= MAX_WORDS_PER_TURN - 4 and text.count("?") <= 1, text
                assert "{" not in text


def test_render_adapts_spouse_and_child_to_profile():
    assert "ông nhà" in ls.render(ls.BANK_BY_ID["l1"], PROFILE).question_vi
    assert "bà nhà" in ls.render(ls.BANK_BY_ID["l1"], TU).question_vi
    assert "chị Lan" in ls.render(ls.BANK_BY_ID["p1"], PROFILE).question_vi
    assert "anh Khoa" in ls.render(ls.BANK_BY_ID["p1"], TU).question_vi
    assert "về làm dâu" in ls.render(ls.BANK_BY_ID["d4"], PROFILE).question_vi


def test_selection_never_repeats_and_rotates_themes():
    asked, themes = [], []
    eligible = [q for q in ls.QUESTION_BANK if q.requires is None]   # Bà Hạnh is not a teacher
    for day in range(1, len(eligible) + 1):
        q = ls.choose_question(PROFILE, asked, [4, 4], day)
        if q is None:
            break
        assert q.id not in asked
        if themes:
            assert q.theme != themes[-1]
        asked.append(q.id)
        themes.append(q.theme)
    assert len(asked) == len(eligible) and "w5" not in asked
    # exhausted: cycles back to the least recently asked
    assert ls.choose_question(PROFILE, asked, [4], 99).id == asked[0]


def test_selection_adapts_to_profile_and_mood():
    # teacher-specific question preferred in the work theme for Ông Tư
    asked = [q.id for q in ls.QUESTION_BANK if q.theme not in ("work",)]
    assert ls.choose_question(TU, asked, [4], 5).id == "w5"
    # sensitive themes skipped when recent mood is low, and when the profile avoids them
    only_hard = [q.id for q in ls.QUESTION_BANK if q.theme != "hardship"]
    assert ls.choose_question(PROFILE, only_hard, [2, 2, 3], 5).theme != "hardship"
    assert ls.choose_question(PROFILE, only_hard, [4, 4], 5).theme == "hardship"
    assert ls.choose_question(dict(PROFILE, avoid_themes=["hardship"]), only_hard, [4], 5).theme != "hardship"


# ------------------------------------------------------------------------------------------- consent per story
def test_share_answer_parsing():
    for yes in ("Ừ, được con, kể cho nó nghe đi.", "Dạ được.", "Ừ kể đi con"):
        assert ls.parse_share_answer(yes) == "yes", yes
    for no in ("Thôi, chuyện đó con giữ riêng giùm bà nha.", "Hổng được đâu con.", "Đừng kể nghen con.",
               "Dạ không."):
        assert ls.parse_share_answer(no) == "no", no
    assert ls.parse_share_answer("Ờ... để bà coi lại đã") == "unclear"
    assert ls.parse_share_answer("") == "unclear"
    q = ls.share_question(PROFILE)
    assert "chị Lan" in q and q.endswith("?") and word_count(q) <= MAX_WORDS_PER_TURN
    assert "giữ riêng" in ls.share_ack("no", PROFILE) and "giữ riêng" in ls.share_ack("unclear", PROFILE)


# ------------------------------------------------------------------------------------------- extraction
def test_rule_based_extraction_keeps_the_elders_voice():
    q = ls.render(ls.BANK_BY_ID["l1"], PROFILE)
    texts = ["Ờ... bà gặp ông nhà ở đám cưới bên Mỏ Cày năm 1972, ổng đờn hay lắm con.",
             "Lúc đó thấy ổng hiền, ít nói, mà hát vọng cổ nghe mùi lắm.",
             "Ừ, vậy đó con, chuyện xưa kể hoài hổng hết."]
    st = ls.extract_story(q, texts, PROFILE, use_llm=False)
    assert st["title_vi"] == "Lần đầu gặp nhau" and st["theme"] == "love"
    assert st["text_vi"].startswith("Bà gặp ông nhà") and "Ờ" not in st["text_vi"]
    assert "kể hoài hổng hết" not in st["text_vi"]                 # closers are not part of the story
    assert 2 <= len([x for x in st["text_vi"].split(".") if x.strip()]) <= 5
    assert st["era"]["decade"] == 1970 and "1972" in st["era"]["label_en"]
    assert "Mỏ Cày" in st["places"] and any(p["vi"] == "ông nhà" for p in st["people"])
    assert st["translation"] == "gist" and "Mrs Hanh" in st["text_en"]
    assert ls.extract_story(q, ["Hổng nhớ nữa con."], PROFILE, use_llm=False) is None   # too little to retell


def test_claude_extraction_with_fake_client_and_fallback():
    out = {"title_vi": "Gặp ông nhà", "title_en": "Meeting my husband", "text_vi": "Bà gặp ông nhà ở Mỏ Cày.",
           "text_en": "I met my husband in Mỏ Cày.", "people": [{"vi": "ông nhà", "en": "my husband"}],
           "places": ["Mỏ Cày"], "era_vi": "Năm 1972", "era_en": "1972", "decade": 1970}
    calls = []

    class FakeMessages:
        def create(self, **kw):
            calls.append(kw)
            return SimpleNamespace(stop_reason="end_turn", content=[SimpleNamespace(type="text", text=json.dumps(out))])
    client = SimpleNamespace(beta=SimpleNamespace(messages=FakeMessages()))
    q = ls.render(ls.BANK_BY_ID["l1"], PROFILE)
    texts = ["Bà gặp ông nhà ở đám cưới bên Mỏ Cày năm 1972, ổng đờn hay lắm con."] * 2
    st = ls.extract_story(q, texts, PROFILE, use_llm=True, client=client)
    assert st["translation"] == "llm" and st["text_en"] == out["text_en"] and st["era"]["decade"] == 1970
    assert calls[0]["model"] == ls.STORY_MODEL and calls[0]["output_config"]["format"]["type"] == "json_schema"

    class Broken:
        def create(self, **kw):
            raise RuntimeError("down")
    st2 = ls.extract_story(q, texts, PROFILE, use_llm=True, client=SimpleNamespace(beta=SimpleNamespace(messages=Broken())))
    assert st2["engine"] == "rules"


# ------------------------------------------------------------------------------------------- games + difficulty
def test_adaptive_difficulty():
    assert act.next_level([]) == 2
    assert act.next_level(["miss"]) == 1                           # easier right after a miss
    assert act.next_level(["miss", "miss", "miss"]) == 1           # floor
    assert act.next_level(["success", "success"]) == 3
    assert act.next_level(["success"] * 10) == 3                   # ceiling
    assert act.next_level(["success", "partial", "success"]) == 2  # partial breaks the streak
    assert act.next_level(["success", "success", "miss"]) == 2
    hist = [{"outcome": "miss", "category": "ca_dao", "activity_id": "cd_vi_dau"}]
    assert act.choose_game(PROFILE, hist, 10).level == 1
    assert act.choose_game(PROFILE, hist, 10).category != "ca_dao"  # no same game twice in a row


def test_game_prompts_fit_and_scoring_is_kind():
    for level in act.LEVELS:
        for kind in act.GAME_KINDS:
            g = act.build_game(kind, level, PROFILE, [], seed="x")
            assert g.level == level and word_count(g.prompt_vi) <= MAX_WORDS_PER_TURN and g.prompt_vi.count("?") == 1
    cd = act.build_game("ca_dao", 1, PROFILE, [], seed="a")
    full = next(c for c in act.CA_DAO if c[0] == cd.id)[5]
    assert act.score_game(cd, full) == "success"
    assert act.score_game(cd, "Hổng nhớ con ơi") == "miss"
    naming = act.Activity(kind="game", id="nm_fruit", category="naming", prompt_vi="", level=2,
                          expected=[["xoài"], ["mận"], ["chôm chôm"], ["bưởi"]], need=3)
    assert act.score_game(naming, "Xoài, mận, chôm chôm đó con") == "success"
    assert act.score_game(naming, "Ờ... xoài") == "partial"
    assert act.score_game(naming, "xoai, man, chom chom") == "success"     # accent-free speech recognition output
    fam = act.build_game("family", 3, PROFILE, [])
    assert fam.need == 1 and act.score_game(fam, "Con Lan đó") == "success"
    for outcome in ("success", "partial", "miss"):
        r = act.game_reaction(cd, outcome, "bà", "s")
        assert "sai" not in r.lower().split() and r.startswith("Dạ")
    assert full in act.game_reaction(cd, "miss", "bà")             # gentle reveal


def test_family_game_needs_children():
    no_kids = dict(PROFILE, family=[{"id": "x", "name": "Bà Tư", "relation": "wife", "role": "primary"}])
    assert act.build_game("family", 2, no_kids, []) is None
    cats = {act.choose_game(no_kids, [{"outcome": "success", "category": c, "activity_id": c}], 1).category
            for c in ("ca_dao", "naming")}
    assert "family" not in cats


def test_nudges_follow_signals_and_do_not_repeat():
    n = act.choose_nudge(PROFILE, [], [{"symptoms": {"insomnia": 1}, "mood": 4}], 3)
    assert n.category == "sleep" and n.kind == "nudge" and "bà" in n.prompt_vi
    assert act.choose_nudge(PROFILE, ["sleep"], [{"symptoms": {"insomnia": 1}}], 3).category != "sleep"
    assert act.choose_nudge(PROFILE, [], [], 3, focus=["walk_sun"]).category == "walk_sun"
    low = [{"mood": 2}, {"mood": 2}, {"mood": 3}]
    assert act.choose_nudge(PROFILE, [], low, 3).category in ("friend", "club")
    recent = []
    for d in range(12):
        recent.append(act.choose_nudge(PROFILE, recent, [], d).category)
        assert len(recent) < 2 or recent[-1] != recent[-2]


# ------------------------------------------------------------------------------------------- call flow
def _ctx(game=True, hooks=None):
    ctx = make_ctx(hooks=hooks)
    ctx.life_question = ls.render(ls.BANK_BY_ID["c1"], PROFILE)
    ctx.game = act.build_game("ca_dao", 1, PROFILE, [], seed="t") if game else None
    ctx.nudge = act.choose_nudge(PROFILE, [], [], 91, focus=["water"])
    return ctx


def _run(ctx, script):
    orch = Orchestrator(ScriptedEngine())
    st, _ = orch.start(ctx, "mb1")
    t, out = 5.0, []
    for line in script:
        r = orch.handle_turn(st, line, start=t, end=t + 6, pauses=[0.5])
        out.append((st.step, r.reply_text))
        t += 10
        if r.end_call:
            break
    return st, out


STORY = ["Hồi nhỏ bà hay theo mấy đứa trong xóm ra ruộng bắt cá lia thia vui lắm.",
         "Chơi thân nhất là con Tư nhà kế bên, hai đứa đi đâu cũng có nhau.",
         "Tối về bị má rầy quá trời mà bữa sau cũng đi nữa.",
         "Giờ nghĩ lại thấy hồi đó nghèo mà vui lắm con."]
HEAD = ["Dạ rảnh chớ con.", "Đêm qua bà ngủ ngon lắm con.", "Sáng nay bà ăn cháo với hột vịt muối.",
        "Trong người cũng khỏe con.", "Cây mai trước nhà sắp ra nụ đó con."]


def test_call_asks_life_question_then_consent_then_game_then_nudge():
    ctx = _ctx()
    st, out = _run(ctx, HEAD + STORY + ["Thôi, chuyện đó con giữ riêng giùm bà nha.",
                                        "Nghĩa mẹ như nước trong nguồn chảy ra.", "Ừ chào con."])
    steps = [s for s, _ in out]
    texts = dict(out)
    assert ctx.life_question.question_vi in " ".join(t for _, t in out)
    assert ctx.life_question.follow_up_vi in " ".join(t for _, t in out)
    assert "story_share" in steps and "activity_game" in steps and steps[-1] == "closing"
    assert st.share_answer == "no" and len(st.story_texts) == 4
    assert texts["activity_game"].startswith("Dạ, con giữ riêng cho bà nha.")   # consent acknowledged first
    assert st.game_outcome == "success"
    closing = out[-1][1]
    assert closing.startswith("Dạ") and ctx.nudge.prompt_vi in closing and "Amlodipine" in closing and st.nudge_said
    for step, text in out[:-1]:
        limit = MAX_WORDS_PER_TURN + 8 if step == "activity_game" else MAX_WORDS_PER_TURN
        assert word_count(text) <= limit and text.count("?") <= 1, text


def test_hook_first_then_life_question_and_yes_shares():
    ctx = _ctx(game=False, hooks=["Chủ nhật này con Lan về thăm"])
    st, out = _run(ctx, HEAD + ["Dạ, nó về ăn cơm với bà."] + STORY[:3] + ["Ừ được, kể cho nó nghe đi.", "Chào con."])
    joined = " ".join(t for _, t in out)
    assert "Bữa trước bà có nói" in joined and ctx.life_question.question_vi in joined
    assert "Dạ, nó về ăn cơm với bà." not in st.story_texts          # the hook answer is not part of the memoir
    assert st.share_answer == "yes" and "activity_game" not in [s for s, _ in out]
    assert out[-1][1].startswith("Dạ, con sẽ kể chị Lan nghe.")


def test_no_consent_question_when_time_runs_out():
    ctx = _ctx()
    orch = Orchestrator(ScriptedEngine())
    st, _ = orch.start(ctx, "mb2")
    for i, line in enumerate(HEAD + STORY[:1]):
        orch.handle_turn(st, line, start=5 + 10 * i, end=11 + 10 * i)
    r = orch.handle_turn(st, STORY[1], start=280, end=286)
    assert st.step == "closing" and r.end_call and st.share_stage == "none" and st.share_answer is None


def test_prompt_and_context_carry_memory_book():
    assert PROMPT_VERSION == "ut-thuong-2026.10.4"
    assert "life-story" in SYSTEM_PROMPT.lower() and "never as a test" in SYSTEM_PROMPT
    block = build_context_block(_ctx())
    assert "life-story question" in block and "Closing game" in block and "Habit nudge" in block
    eng = ClaudeEngine(client=SimpleNamespace())
    st = SimpleNamespace(step="story_open", ctx=_ctx(), life_q_asked=False, life_q_follow_used=False, story_turns=1,
                         pending_ack=None, recall_result=None, nudge_said=False, ev=_ctx().elder, elapsed=lambda: 120)
    assert _ctx().life_question.question_vi in eng._directive(st) and st.life_q_asked
    st.step = "story_share"
    assert "chị Lan" in eng._directive(st)
