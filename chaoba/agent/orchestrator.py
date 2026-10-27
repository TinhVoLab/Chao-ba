"""Call orchestrator: phases, safety layers, and the two conversation engines.

Flow of one elder turn (`Orchestrator.handle_turn`):
  1. record the elder Turn (text + VAD timings; never audio)
  2. Layer-1 emergency spotter, three tiers (emergency.py):
       acute       -> calm 115 instruction, family notified now, end call
       non_acute   -> calm reply + ONE confirming question; "yes" escalates to acute, "no" -> reassure and continue
                      (the family still gets a red "check in today" alert)
       third_party -> empathetic reaction, nothing recorded against the elder, conversation continues
  3. opt-out confirmation flow             -> record opt-out, stop scheduling
  4. consent answer (greeting phase)       -> declined today -> polite goodbye
  5. deterministic guardrails              -> anti-scam / no medication change / no diagnosis
  6. phase planner (`plan_step`)           -> decides the next conversational step (time + turn based)
  6b. symptom follow-up (scripted engine)  -> "Dạ bà mỏi lưng từ hồi nào vậy bà, có đỡ chưa?" once per symptom
  7. engine.reply(state, elder_text)       -> ClaudeEngine (if ANTHROPIC_API_KEY) or ScriptedEngine
  8. output scrub (no disease names, no money talk)

Phases: greeting (family greeting + consent) -> wellbeing (sleep, food, feeling) -> recall (free, then cue)
-> story (follow-up hook, then today's life-story question for the memory book, its follow-up, and the per-story
   consent question "Bà cho con kể lại chuyện này cho chị Lan nghe được hông?")
-> closing (optional short memory game, medication reminder, family message, habit nudge, goodbye, ~4:30).
The memory-book question, the game and the nudge are optional (DailyContext.life_question / game / nudge); without
them the call runs exactly as before. See lifestory.py and activities.py.
"""
from __future__ import annotations

import hashlib
import logging
import os
import random
import time
from dataclasses import dataclass, field
from typing import Protocol

from chaoba.core.models import Turn

from . import guardrails as g
from .emergency import (spot, emergency_reply, non_acute_reply, non_acute_settled, third_party_reply, confirms_now,
                        is_third_party, EmergencyHit, FLAG_EMERGENCY_TOOL)
from .persona import ElderView, MAX_WORDS_PER_TURN
from .prompts import (SYSTEM_PROMPT, PROMPT_VERSION, PHASE_DIRECTIVES, DailyContext, build_context_block,
                      default_family_greeting)
from .textnorm import (normalize, contains_phrase, find_phrase, word_count, strip_diacritics,
                       has_vietnamese_diacritics)
from .lifestory import share_question, parse_share_answer, share_ack
from .activities import score_game, game_reaction

log = logging.getLogger("chaoba.agent")

CLOSING_AT_SEC = 270.0       # ~4:30 -> medication reminder + goodbye
HARD_STOP_SEC = 330.0        # never run past 5:30
MAX_STORY_TURNS = 4
MAX_ELDER_TURNS = 16
WELLBEING_TOPICS = ("sleep", "food", "feel")

PHASES = ("greeting", "wellbeing", "recall", "story", "closing", "ended")


@dataclass
class CallState:
    call_id: str
    ctx: DailyContext
    channel: str = "web"
    started_wall: float = field(default_factory=time.time)
    turns: list[Turn] = field(default_factory=list)
    phase: str = "greeting"
    step: str = "consent"
    wellbeing_done: list[str] = field(default_factory=list)
    recall_stage: str = "none"              # none | asked_free | asked_cue | done | skipped
    recall_free_text: str = ""
    recall_cued_text: str = ""
    recall_result: str | None = None         # exact | partial | cued | failed
    story_turns: int = 0
    used_story_prompts: list[int] = field(default_factory=list)
    used_texts: list[str] = field(default_factory=list)
    emergency: bool = False                  # acute tier only (115 advised)
    emergency_hits: list[dict] = field(default_factory=list)
    concern_hits: list[dict] = field(default_factory=list)      # non-acute tier (red light + "check in today")
    third_party_hits: list[dict] = field(default_factory=list)  # events that happened to someone else
    awaiting_confirm: dict | None = None     # non-acute hit waiting for the answer to "có đang đau...?"
    react_override: str | None = None        # reaction the engine must use instead of a keyword reaction
    followed_up: list[str] = field(default_factory=list)        # symptoms already followed up in this call
    opt_out_pending: bool = False
    opted_out: bool = False
    declined: bool = False
    consent_given: bool | None = None
    flags: list[dict] = field(default_factory=list)   # guardrail events (scam / medication / diagnosis)
    history: list[dict] = field(default_factory=list)  # Claude message history (user/assistant text only)
    ended: bool = False
    end_reason: str | None = None
    engine_used: str = "scripted"
    last_client_end: float = 0.0
    # memory book (life story) + prevention activities
    life_q_asked: bool = False
    life_q_follow_used: bool = False
    story_texts: list[str] = field(default_factory=list)   # elder answers to the life-story question (memoir source)
    share_stage: str = "none"                # none | asked | done
    share_answer: str | None = None          # yes | no | unclear  (unclear -> private)
    game_stage: str = "none"                 # none | asked | done
    game_text: str = ""
    game_outcome: str | None = None          # success | partial | miss
    pending_ack: str | None = None           # share / game acknowledgement said before the next line
    nudge_said: bool = False

    @property
    def ev(self) -> ElderView:
        return self.ctx.elder

    def elapsed(self) -> float:
        return max(self.last_client_end, time.time() - self.started_wall)

    def elder_turns(self) -> list[Turn]:
        return [t for t in self.turns if t.speaker == "elder"]

    def transcript(self) -> list[dict]:
        return [{"speaker": t.speaker, "text": t.text, "start": t.start, "end": t.end, "pauses": t.pauses}
                for t in self.turns]


@dataclass
class TurnResult:
    reply_text: str
    phase: str
    emergency: bool = False
    end_call: bool = False
    emergency_hit: dict | None = None
    # "emergency" | "health_concern" | "health_concern_settled" | "third_party" | "symptom_followup" | "opt_out" |
    # "declined" | "scam" | "medication" | "diagnosis"
    event: str | None = None


class Engine(Protocol):
    name: str

    def reply(self, state: CallState, elder_text: str) -> tuple[str, str, bool]: ...


# --------------------------------------------------------------------------------------------- recall scoring
def recall_match(text: str, keywords: list[str]) -> float:
    """Fraction of recall keywords present in the elder's answer (diacritic-aware with accent-free fallback)."""
    if not keywords:
        return 0.0
    n = normalize(text)
    # Accent-free matching only when the answer itself has no diacritics ("lắm" must not match "làm").
    accentless = not has_vietnamese_diacritics(text)
    s = strip_diacritics(n)
    hit = 0
    for k in keywords:
        kn = normalize(k)
        if contains_phrase(n, kn) or (accentless and contains_phrase(s, strip_diacritics(kn))):
            hit += 1
    return hit / len(keywords)


_DONT_KNOW = ["hổng nhớ", "không nhớ", "hông nhớ", "quên rồi", "quên mất", "chịu", "hổng biết", "không biết",
              "nhớ hổng ra", "nhớ không ra"]


def _dont_know(text: str) -> bool:
    n = normalize(text)
    return any(contains_phrase(n, p) for p in _DONT_KNOW)


# --------------------------------------------------------------------------------------------- planner
def plan_step(state: CallState, elder_text: str) -> str:
    """Advance phase/step after an elder turn. Returns the step the engine must voice next."""
    el = state.elapsed()
    n_elder = len(state.elder_turns())

    # Memory book: collect the answers to the life-story question; then the per-story consent answer.
    if (state.phase == "story" and state.life_q_asked and state.share_stage == "none"
            and state.step in ("story_open", "story_follow", "recall_close")):
        state.story_texts.append(elder_text)
    if state.share_stage == "asked":
        state.share_answer = parse_share_answer(elder_text)
        state.share_stage = "done"
        state.pending_ack = share_ack(state.share_answer, state.ctx.profile)
        return _after_story(state, el)
    if state.game_stage == "asked":
        state.game_text = elder_text
        state.game_outcome = score_game(state.ctx.game, elder_text)
        state.game_stage = "done"
        state.pending_ack = game_reaction(state.ctx.game, state.game_outcome, state.ev.honorific,
                                          f"{state.call_id}:game")
        state.phase = "closing"
        return "closing"

    # Recall answer bookkeeping
    if state.recall_stage == "asked_free" and state.ctx.recall:
        state.recall_free_text = elder_text
        frac = 0.0 if _dont_know(elder_text) and recall_match(elder_text, state.ctx.recall.keywords) < 0.5 \
            else recall_match(elder_text, state.ctx.recall.keywords)
        if frac >= 0.67:
            state.recall_result, state.recall_stage = "exact", "done"
        elif frac > 0:
            state.recall_result, state.recall_stage = "partial", "done"
        else:
            state.recall_stage = "asked_cue"
            if el < CLOSING_AT_SEC:
                state.phase = "recall"
                return "recall_cue"
            state.recall_result, state.recall_stage = "failed", "done"
    elif state.recall_stage == "asked_cue" and state.ctx.recall:
        state.recall_cued_text = elder_text
        frac = recall_match(elder_text, state.ctx.recall.cued_keywords())
        state.recall_result = "cued" if frac > 0 else "failed"
        state.recall_stage = "done"
        if el < CLOSING_AT_SEC:
            state.phase = "story"
            return "recall_close"

    if state.recall_stage == "done" and state.phase == "recall":
        if el < CLOSING_AT_SEC:
            state.phase = "story"
            return "recall_close"

    if el >= CLOSING_AT_SEC or n_elder >= MAX_ELDER_TURNS:
        state.phase = "closing"
        return "closing"

    if state.phase in ("greeting", "wellbeing"):
        remaining = [t for t in WELLBEING_TOPICS if t not in state.wellbeing_done]
        if remaining:
            state.phase = "wellbeing"
            topic = remaining[0]
            state.wellbeing_done.append(topic)
            return f"ask_{topic}"
        if state.ctx.recall and state.recall_stage == "none":
            state.phase = "recall"
            state.recall_stage = "asked_free"
            return "recall_free"
        state.recall_stage = state.recall_stage if state.ctx.recall else "skipped"
        state.phase = "story"

    if state.phase == "story":
        # leave room for the consent question and the game when time runs short
        near_end = state.life_q_asked and state.story_texts and el >= CLOSING_AT_SEC - 45
        if state.story_turns >= MAX_STORY_TURNS or (near_end and state.story_turns >= 2):
            return _after_story(state, el)
        state.story_turns += 1
        return "story_open" if state.story_turns == 1 else "story_follow"

    state.phase = "closing"
    return "closing"


def _story_long_enough(state: CallState) -> bool:
    return sum(word_count(t) for t in state.story_texts) >= 12


def _after_story(state: CallState, el: float) -> str:
    """After the life story: ask the per-story consent (if there is a story), then the game (if any), then close."""
    if (state.ctx.life_question is not None and state.life_q_asked and state.share_stage == "none"
            and _story_long_enough(state) and el < CLOSING_AT_SEC):
        state.share_stage = "asked"
        state.phase = "story"
        return "story_share"
    if state.ctx.game is not None and state.game_stage == "none" and el < CLOSING_AT_SEC - 15:
        state.game_stage = "asked"
        state.phase = "closing"
        return "activity_game"
    state.phase = "closing"
    return "closing"


# --------------------------------------------------------------------------------------------- scripted engine
REACTIONS = [
    # (key, trigger phrases, reaction templates) -- order = priority
    ("pain", ["đau", "nhức", "mỏi", "ê ẩm", "tê"],
     ["Dạ, nghe {h} nhức mỏi con thương quá.", "Tội {h} quá, mỏi mệt vậy ha."]),
    ("sad", ["buồn", "cô đơn", "tủi", "chán", "nhớ con", "nhớ cháu", "một mình"],
     ["Dạ, có con nói chuyện với {h} nè.", "Dạ, con hiểu mà {h}, có con đây nè."]),
    ("insomnia", ["mất ngủ", "khó ngủ", "ngủ hổng được", "ngủ không được", "hổng ngủ", "thức trắng", "trằn trọc",
                  "ngủ ít", "thức hoài", "ngủ hông được"],
     ["Tội {h} ghê, ngủ hổng ngon mệt lắm ha.", "Dạ, thức đêm vậy chắc {h} mệt lắm."]),
    ("no_food", ["chưa ăn", "hổng ăn", "không ăn", "ăn hổng vô", "ăn không vô", "không muốn ăn", "hổng muốn ăn",
                 "bỏ bữa", "ăn ít"],
     ["Dạ, {h} ráng ăn chút cho có sức nha.", "Dạ, ăn ít vậy con lo cho {h} quá."]),
    ("slept_well", ["ngủ ngon", "ngủ được", "ngủ thẳng giấc", "ngủ say", "ngủ khỏe"],
     ["Dạ, ngủ ngon vậy con mừng ghê.", "Dạ, vậy là khỏe rồi {h} ha."]),
    ("ate", ["ăn cơm", "ăn cháo", "ăn sáng", "ăn rồi", "ăn bánh", "ăn hủ tiếu", "ăn xôi", "ăn ngon", "uống sữa"],
     ["Dạ, {h} ăn được là con mừng.", "Dạ, nghe ngon quá trời {h} ơi."]),
    ("family", ["con gái", "con trai", "cháu", "con dâu", "con rể", "tụi nhỏ", "sắp nhỏ", "ông nhà"],
     ["Dạ, nhắc tới con cháu là vui rồi ha.", "Dạ, nhà mình đông vui quá {h}."]),
    ("happy", ["vui", "khỏe", "ổn", "mừng", "thích", "sướng", "khoẻ"],
     ["Dạ, nghe {h} khỏe con mừng lắm.", "Dạ, vậy là tốt quá {h} ơi."]),
]
GENERIC_REACTIONS = ["Dạ.", "Dạ, con nghe nè.", "Vậy hả {h}.", "Dạ, hay quá {h}.", "Dạ, con hiểu rồi."]

QUESTIONS = {
    "ask_sleep": ["Đêm qua {h} ngủ có ngon hông {h}?", "Tối hôm qua {h} ngủ được mấy tiếng vậy {h}?",
                  "Đêm rồi {h} ngủ có thẳng giấc hông?"],
    "ask_food": ["Sáng nay {h} ăn gì chưa {h}?", "Bữa nay {h} ăn sáng món gì vậy {h}?",
                 "Hôm qua {h} ăn uống có ngon miệng hông?"],
    "ask_feel": ["Bữa nay {h} thấy trong người sao {h}?", "Sáng nay {h} thấy trong mình khỏe hông {h}?",
                 "Hôm nay {h} thấy tinh thần sao {h}?"],
    "story_open": ["Hồi nhỏ ở quê {h} hay chơi trò gì vậy {h}?", "Món {h} nấu ngon nhất là món gì vậy {h}?",
                   "Hồi trẻ {h} làm nghề gì vậy {h}?", "Mùa nước nổi hồi xưa ở quê {h} vui hông {h}?",
                   "Ngoài vườn nhà mình đang trồng cây gì vậy {h}?", "Tết năm nay {h} tính nấu món gì vậy {h}?"],
    "story_follow": ["Rồi sao nữa {h}, kể con nghe thêm với?", "Chuyện đó {h} nhớ nhất cái gì vậy {h}?",
                     "Hồi đó ai đi chung với {h} vậy?", "Nghe hay quá, rồi sau đó sao {h}?",
                     "Bây giờ nhớ lại {h} thấy sao {h}?"],
}
# Story follow-ups chosen from what the elder just said, so the hook never contradicts it (no "Hồi đó..." right after
# talk of an upcoming visit).
STORY_FOLLOW_BY_TIME = {
    "future": ["Vui quá, {h} tính chuẩn bị gì vậy {h}?", "Dạ, rồi {h} tính nấu món gì vậy {h}?",
               "Dạ, {h} mong tới bữa đó lắm ha {h}?", "Hay quá, bữa đó ai về nữa vậy {h}?"],
    "past": ["Hồi đó ai đi chung với {h} vậy?", "Chuyện đó {h} nhớ nhất cái gì vậy {h}?",
             "Bây giờ nhớ lại {h} thấy sao {h}?", "Rồi sao nữa {h}, kể con nghe thêm với?"],
    "present": ["Rồi sao nữa {h}, kể con nghe thêm với?", "Nghe hay quá, rồi sau đó sao {h}?",
                "Dạ, vậy {h} thấy vui hông {h}?", "Dạ, {h} kể con nghe thêm chút nha {h}?"],
}
_FUTURE_WORDS = ["sắp", "chủ nhật này", "chủ nhật", "ngày mai", "mai mốt", "tuần sau", "tuần tới", "tháng sau",
                 "bữa sau", "định", "tính", "sẽ", "về thăm", "hẹn", "chuẩn bị", "tết này", "năm nay"]
_PAST_WORDS = ["hồi đó", "hồi xưa", "hồi nhỏ", "hồi trẻ", "hồi trước", "ngày xưa", "năm đó", "hồi còn", "lúc trước",
               "hồi mới", "thời đó", "bữa đó"]


def time_frame(text: str) -> str:
    """future | past | present: what the elder's last utterance was about."""
    n = normalize(text)
    if any(contains_phrase(n, w) for w in _FUTURE_WORDS):
        return "future"
    if any(contains_phrase(n, w) for w in _PAST_WORDS):
        return "past"
    return "present"


# Symptom follow-up (one extra turn, once per symptom per call). Trigger phrases are matched outside negation and
# only when the elder is the subject (not "thằng cháu bị đau bụng").
SYMPTOM_FOLLOWUPS = [
    ("pain", ["đau", "nhức", "mỏi", "ê ẩm", "tê"], "Dạ, {h} {p} từ hồi nào vậy {h}, có đỡ chưa?"),
    ("dizziness", ["chóng mặt", "choáng", "xây xẩm", "hoa mắt"], "Dạ, {h} {p} từ hồi nào vậy {h}, giờ còn hông?"),
    ("insomnia", ["mất ngủ", "khó ngủ", "ngủ hổng được", "ngủ không được", "thức trắng", "trằn trọc", "ngủ ít",
                  "thức hoài", "ngủ hông được"], "Dạ, {h} khó ngủ vậy mấy bữa rồi {h}, có đỡ chưa?"),
    ("no_food", ["ăn hổng vô", "ăn không vô", "hổng muốn ăn", "không muốn ăn", "bỏ bữa", "biếng ăn"],
     "Dạ, {h} ăn hổng vô mấy bữa rồi {h}, trong người có mệt hông?"),
    ("sad", ["buồn", "cô đơn", "tủi"], "Dạ, {h} buồn chuyện gì, kể con nghe với {h}?"),
]
_SYM_NEG = {"không", "hổng", "hông", "chưa", "chẳng", "chả", "hết", "đỡ", "bớt"}
_SYM_STOP = {"chút", "xíu", "quá", "lắm", "hà", "nha", "con", "mà", "nữa", "rồi", "à", "ghê", "thôi", "đó", "nè",
             "hông", "hổng", "không", "trời", "thiệt", "vậy", "dữ", "cũng", "với", "hoài"}
_SYM_EXCL = ["buồn cười", "buồn ngủ", "hết buồn", "đỡ buồn", "đau lòng", "mỏi mắt chờ"]


def symptom_followup(text: str, done: list[str], h: str, honorific: str | None = None) -> tuple[str, str] | None:
    """(symptom key, follow-up question) for the first self-reported, non-negated symptom not yet followed up."""
    n = normalize(text)
    toks = n.split()
    excl = [(s, s + len(e)) for e in _SYM_EXCL for s in find_phrase(n, e)]
    for key, triggers, tmpl in SYMPTOM_FOLLOWUPS:
        if key in done:
            continue
        for trig in sorted(triggers, key=len, reverse=True):
            for st in find_phrase(n, trig):
                if any(a <= st < b for a, b in excl):
                    continue
                prefix = n[:st].split()
                if any(w in _SYM_NEG for w in prefix[-2:]) or is_third_party(text, st, honorific):
                    continue
                phrase = trig.split()
                j = len(prefix) + len(phrase)
                while j < len(toks) and len(phrase) < 3 and toks[j] not in _SYM_STOP:   # "mỏi" -> "mỏi cái lưng"
                    phrase.append(toks[j])
                    j += 1
                return key, tmpl.format(h=h, p=" ".join(phrase))
    return None


RECALL_LEADS = ["Giờ con hỏi chơi nè.", "Con đố {h} chút nha.", "Con hỏi thử trí nhớ nè."]
RECALL_PRAISE = {"exact": ["Đúng rồi đó {h}, {h} nhớ giỏi ghê!", "Dạ đúng y chang, {h} nhớ hay quá!"],
                 "partial": ["Dạ gần đúng rồi đó {h}, giỏi lắm!", "Dạ, {h} nhớ được vậy là hay rồi."],
                 "cued": ["Dạ đúng rồi, {h} nhớ ra rồi đó!", "Dạ phải rồi, giỏi quá {h}!"],
                 "failed": ["Dạ hổng sao đâu {h}, chuyện nhỏ mà.", "Dạ hổng sao, mai mốt mình nhớ tiếp nha {h}."]}


def _pick(options: list[str], seed: str) -> str:
    rnd = random.Random(int(hashlib.sha256(seed.encode()).hexdigest()[:12], 16))
    return rnd.choice(options)


def reaction_for(text: str, h: str, seed: str) -> tuple[str | None, str]:
    n = normalize(text)
    for key, triggers, templates in REACTIONS:
        if any(contains_phrase(n, t) for t in triggers):
            # don't react with "khỏe" to "hổng khỏe"
            if key in ("happy", "slept_well") and any(contains_phrase(n, x) for x in
                                                      ("hổng", "không", "hông", "chưa")):
                continue
            return key, _pick(templates, seed + key).format(h=h)
    return None, _pick(GENERIC_REACTIONS, seed + "gen").format(h=h)


def medication_reminder(ev: ElderView) -> str:
    meds = ev.medications
    if not meds:
        return ""
    if len(meds) == 1:
        m = meds[0]
        return f"Nhớ uống thuốc {m.get('name')} lúc {m.get('time')} nha {ev.honorific}."
    lst = ", ".join(f"{m.get('name')} lúc {m.get('time')}" for m in meds)
    return f"Nhớ uống thuốc đúng giờ nha {ev.honorific}: {lst}."


def closing_text(state: CallState) -> str:
    ev = state.ev
    h = ev.honorific
    parts = []
    if state.pending_ack:     # game reaction / "con giữ riêng" said first
        parts.append(state.pending_ack)
        state.pending_ack = None
        parts.append(f"Tới giờ con để {h} nghỉ ngơi rồi.")
    else:
        parts.append(f"Dạ, tới giờ con để {h} nghỉ ngơi rồi.")
    med = medication_reminder(ev)
    if med:
        parts.append(med)
    if state.ctx.family_message:
        parts.append(state.ctx.family_message.rstrip(".") + ".")
    if state.ctx.nudge is not None and not state.emergency:
        parts.append(state.ctx.nudge.prompt_vi)
        state.nudge_said = True
    parts.append(f"Con chào {h}, mai con gọi nữa nha {h}.")
    return " ".join(parts)


class ScriptedEngine:
    """Deterministic, keyless fallback. Varied, phase-aware Southern Vietnamese with light keyword reactions."""
    name = "scripted"

    def reply(self, state: CallState, elder_text: str) -> tuple[str, str, bool]:
        ev = state.ev
        h = ev.honorific
        seed = f"{state.call_id}:{len(state.turns)}"
        step = state.step
        if step == "closing":
            return closing_text(state), "closing", True
        _, react = reaction_for(elder_text, h, seed)
        # A safety acknowledgement (react_override) is never dropped for length. Branches that use it clear it;
        # otherwise the orchestrator prepends it to the reply.
        forced = bool(state.react_override)
        if forced:
            react = state.react_override
        if step == "recall_free" and state.ctx.recall:
            q = state.ctx.recall.question_vi
            lead = _pick(RECALL_LEADS, seed).format(h=h)
            text = f"{react} {lead} {q}" if word_count(f"{react} {lead} {q}") <= MAX_WORDS_PER_TURN else f"{lead} {q}"
            if word_count(text) > MAX_WORDS_PER_TURN:
                text = q
            if forced:
                text, state.react_override = f"{react} {q}", None
            return text, "recall", False
        if step == "recall_cue" and state.ctx.recall:
            return state.ctx.recall.cue_vi, "recall", False
        if step == "story_share":
            q = share_question(state.ctx.profile)
            if forced:
                q, state.react_override = f"{react} {q}", None
            return q, "story", False
        if step == "activity_game" and state.ctx.game is not None:
            q = state.ctx.game.prompt_vi
            # the consent acknowledgement ("con giữ riêng") is never dropped for length
            lead = state.pending_ack or (react if word_count(f"{react} {q}") <= MAX_WORDS_PER_TURN else "")
            state.pending_ack = None
            if forced:
                lead, state.react_override = f"{state.react_override or react} {lead}".strip(), None
            return f"{lead} {q}".strip(), "closing", False
        if step == "recall_close":
            praise = _pick(RECALL_PRAISE.get(state.recall_result or "failed", RECALL_PRAISE["failed"]),
                           seed).format(h=h)
            q = self._story_question(state, seed, opening=True)
            state.story_turns = max(state.story_turns, 1)
            return self._fit(praise, q), "story", False
        if step in ("story_open", "story_follow"):
            q = self._story_question(state, seed, opening=(step == "story_open"), last=elder_text)
            state.react_override = None
            return self._fit(react, q, forced), "story", False
        q = self._fresh(state, [x.format(h=h) for x in QUESTIONS.get(step, QUESTIONS["ask_feel"])], seed)
        state.react_override = None
        return self._fit(react, q, forced), state.phase, False

    @staticmethod
    def _fit(react: str, q: str, force: bool = False) -> str:
        if react.startswith("Dạ") and q.startswith("Dạ, "):   # no "Dạ. Dạ, ..."
            q = q[4:5].upper() + q[5:]
        text = f"{react} {q}"
        return text if force or word_count(text) <= MAX_WORDS_PER_TURN else q

    def _story_question(self, state: CallState, seed: str, opening: bool, last: str = "") -> str:
        h = state.ev.honorific
        hooks = state.ctx.followup_hooks
        lq = state.ctx.life_question
        if opening and hooks:
            hook = hooks[0].rstrip(".?! ")
            q = f"Bữa trước {h} có nói {hook[:1].lower() + hook[1:]}, giờ sao rồi {h}?"
            if word_count(q) <= MAX_WORDS_PER_TURN - 4:
                return q
        if lq is not None and not state.life_q_asked:      # memory book: today's life-story question
            state.life_q_asked = True
            state.used_texts.append(lq.question_vi)
            return lq.question_vi
        if lq is not None and not state.life_q_follow_used:
            state.life_q_follow_used = True
            state.used_texts.append(lq.follow_up_vi)
            return lq.follow_up_vi
        if opening:
            pool = [q.format(h=h) for q in QUESTIONS["story_open"]]
        else:
            # follow the content of what the elder just said (future plan / old memory / present)
            pool = [q.format(h=h) for q in STORY_FOLLOW_BY_TIME[time_frame(last)]]
        return self._fresh(state, pool, seed)

    @staticmethod
    def _fresh(state: CallState, pool: list[str], seed: str) -> str:
        """Pick a question not yet used in this call (deterministic per call/turn)."""
        options = [q for q in pool if q not in state.used_texts] or pool
        q = _pick(options, seed)
        state.used_texts.append(q)
        return q


# --------------------------------------------------------------------------------------------- Claude engine
CONVERSATION_MODEL = "claude-sonnet-5-5"
CONVERSATION_FALLBACK_MODEL = "claude-haiku-5-5"


class ClaudeEngine:
    """LLM engine (Claude Sonnet 5.5 -> Haiku 5.5 -> ScriptedEngine).

    - Static persona prompt is cached (cache_control on the first system block); per-call context is a second,
      uncached system block; the per-turn phase directive is a mid-conversation system message appended last,
      so the cached prefix (tools + system + earlier turns) stays byte-stable.
    - Layer-2 emergency detection via the `flag_emergency` tool (tool_choice auto; strict schema).
    - Server-side refusal fallback opted in (`fallbacks: "default"`).
    """
    name = "claude"

    def __init__(self, client=None, fallback: Engine | None = None):
        if client is None:
            import anthropic  # imported lazily; the package is installed but only used with a key
            client = anthropic.Anthropic()
        self.client = client
        self.fallback = fallback or ScriptedEngine()

    def _directive(self, state: CallState) -> str:
        step = state.step
        base = PHASE_DIRECTIVES.get(
            {"ask_sleep": "wellbeing", "ask_food": "wellbeing", "ask_feel": "wellbeing",
             "story_open": "story", "story_follow": "story"}.get(step, step), PHASE_DIRECTIVES["story"])
        extra = {
            "ask_sleep": "Ask about last night's sleep.",
            "ask_food": "Ask about eating (breakfast / meals).",
            "ask_feel": "Ask how they feel in body and spirit today.",
            "recall_close": f"Recall result: {state.recall_result}. Then invite a story or follow up on a hook.",
            "closing": f"Medication reminder to say exactly: \"{medication_reminder(state.ev)}\". "
                       f"Family message: \"{state.ctx.family_message or ''}\".",
        }.get(step, "")
        lq = state.ctx.life_question
        if step in ("story_open", "story_follow", "recall_close") and lq is not None:
            if not state.life_q_asked and (step != "story_open" or not state.ctx.followup_hooks or state.story_turns > 1):
                state.life_q_asked = True
                extra += f" Now ask today's life-story question: \"{lq.question_vi}\""
            elif state.life_q_asked and not state.life_q_follow_used:
                state.life_q_follow_used = True
                extra += f" Ask this follow-up (or a natural one about what they said): \"{lq.follow_up_vi}\""
        if step == "story_share":
            extra += f" Say exactly: \"{share_question(state.ctx.profile)}\""
        if step == "activity_game" and state.ctx.game is not None:
            extra += (f" Say first: \"{state.pending_ack or ''}\" then offer exactly: \"{state.ctx.game.prompt_vi}\"")
            state.pending_ack = None
        if step == "closing":
            if state.pending_ack:
                extra += f" Start with: \"{state.pending_ack}\"."
                state.pending_ack = None
            if state.ctx.nudge is not None:
                extra += f" Before goodbye say: \"{state.ctx.nudge.prompt_vi}\"."
                state.nudge_said = True
        return f"{base} {extra} Elapsed {int(state.elapsed())}s. Max {MAX_WORDS_PER_TURN} words, one question."

    def _call(self, model: str, state: CallState, messages: list[dict]):
        kwargs = dict(
            model=model,
            max_tokens=400,
            system=[
                {"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}},
                {"type": "text", "text": build_context_block(state.ctx)},
            ],
            tools=[FLAG_EMERGENCY_TOOL],
            tool_choice={"type": "auto"},
            messages=messages,
            output_config={"effort": "low"},
            timeout=12.0,
        )
        if model == CONVERSATION_MODEL:
            # Low-latency voice: no thinking before the spoken reply.
            kwargs["thinking"] = {"type": "between_tools"}
            return self.client.beta.messages.create(
                betas=["server-side-fallback-2026-07-01"], fallbacks="default", **kwargs)
        return self.client.messages.create(**kwargs)

    def reply(self, state: CallState, elder_text: str) -> tuple[str, str, bool]:
        state.history.append({"role": "user", "content": elder_text or "(im lặng)"})
        messages = list(state.history) + [{"role": "system", "content": self._directive(state)}]
        resp = None
        for model in (CONVERSATION_MODEL, CONVERSATION_FALLBACK_MODEL):
            try:
                resp = self._call(model, state, messages)
                if getattr(resp, "stop_reason", None) == "refusal":
                    resp = None
                    continue
                break
            except Exception as e:  # network / auth / rate-limit -> next model, then scripted
                log.warning("Claude %s failed: %s", model, e)
                resp = None
        if resp is None:
            state.history.pop()
            state.engine_used = "scripted-fallback"
            return self.fallback.reply(state, elder_text)

        for block in resp.content:
            if getattr(block, "type", None) == "tool_use" and block.name == "flag_emergency":
                inp = block.input if isinstance(block.input, dict) else {}
                cat = str(inp.get("category", "other"))
                acute = bool(inp.get("acute", True)) or cat == "self_harm"
                hit = EmergencyHit(category=cat, keyword="(llm)", quote=str(inp.get("quote") or elder_text),
                                   tier="acute" if acute else "non_acute", time="unknown" if acute else "past")
                if not acute:
                    state.concern_hits.append(hit.to_dict() | {"layer": 2})
                    state.awaiting_confirm = hit.to_dict() | {"layer": 2}
                    text = non_acute_reply(cat, state.ev.honorific)
                    state.history.append({"role": "assistant", "content": text})
                    return text, state.phase, False
                state.emergency = True
                state.emergency_hits.append(hit.to_dict() | {"layer": 2})
                text = emergency_reply(hit.category, state.ev.honorific, state.ev.family_ref)
                state.history.append({"role": "assistant", "content": text})
                return text, state.phase, True
        text = " ".join(b.text for b in resp.content if getattr(b, "type", None) == "text").strip()
        if not text:
            state.history.pop()
            return self.fallback.reply(state, elder_text)
        text = g.scrub_reply(text, state.ev.honorific)
        state.history.append({"role": "assistant", "content": text})
        end = state.step == "closing"
        return text, state.phase, end


def default_engine() -> Engine:
    if os.environ.get("ANTHROPIC_API_KEY"):
        try:
            return ClaudeEngine()
        except Exception as e:  # pragma: no cover
            log.warning("ClaudeEngine unavailable (%s); using ScriptedEngine", e)
    return ScriptedEngine()


# --------------------------------------------------------------------------------------------- orchestrator
class Orchestrator:
    def __init__(self, engine: Engine | None = None):
        self.engine = engine or default_engine()

    def start(self, ctx: DailyContext, call_id: str, channel: str = "web") -> tuple[CallState, str]:
        state = CallState(call_id=call_id, ctx=ctx, channel=channel, engine_used=self.engine.name)
        ev = ctx.elder
        fam = ctx.family_greeting or default_family_greeting(ev)
        intro = (f"Con chào {ev.address}! Con là Út Thương, trợ lý ảo của Chào Bà, con hổng ghi âm đâu. "
                 f"{ev.H} có rảnh nói chuyện với con chừng năm phút hông {ev.honorific}?")
        greeting = f"{fam} {intro}" if fam else intro
        self._agent_turn(state, greeting)
        if isinstance(self.engine, ClaudeEngine):
            # Seed history so Claude knows what was said (the API needs a user turn first).
            state.history.append({"role": "user", "content": "(cuộc gọi bắt đầu)"})
            state.history.append({"role": "assistant", "content": greeting})
        return state, greeting

    def _agent_turn(self, state: CallState, text: str) -> None:
        t0 = state.turns[-1].end if state.turns else 0.0
        dur = max(1.0, word_count(text) / 3.0)   # TTS at rate 0.9 ~ 3 syllables/s
        state.turns.append(Turn(speaker="agent", text=text, start=t0, end=t0 + dur))

    def _finish(self, state: CallState, text: str, event: str | None = None, end: bool = False,
                hit: EmergencyHit | None = None) -> TurnResult:
        self._agent_turn(state, text)
        if end:
            state.ended = True
            state.end_reason = state.end_reason or event or "completed"
            state.phase = "ended" if state.phase != "closing" else "closing"
        return TurnResult(reply_text=text, phase=state.phase, emergency=state.emergency, end_call=end,
                          emergency_hit=hit.to_dict() if hit else None, event=event)

    def handle_turn(self, state: CallState, text: str, start: float | None = None, end: float | None = None,
                    pauses: list[float] | None = None) -> TurnResult:
        if state.ended:
            return TurnResult(reply_text="", phase=state.phase, emergency=state.emergency, end_call=True)
        text = (text or "").strip()
        prev_end = state.turns[-1].end if state.turns else 0.0
        s = float(start) if start is not None else prev_end + 0.8
        e = float(end) if end is not None else s + max(1.0, word_count(text) / 3.0)
        state.turns.append(Turn(speaker="elder", text=text, start=s, end=e,
                                pauses=[float(p) for p in (pauses or [])]))
        state.last_client_end = max(state.last_client_end, e)
        ev = state.ev
        h = ev.honorific

        # 1. emergency (layer 1) -- always first; tiered (acute / non_acute / third_party)
        hit = spot(text, h)
        if state.awaiting_confirm is not None:
            # answer to the non-acute confirming question ("có đang đau hay chảy máu hông?")
            pending, state.awaiting_confirm = state.awaiting_confirm, None
            if (hit and hit.tier == "acute") or confirms_now(text):
                acute = hit if (hit and hit.tier == "acute") else EmergencyHit(
                    category=pending.get("category", "other"), keyword="(confirmed now)",
                    quote=f"{pending.get('quote', '')} / {text}".strip(" /"), tier="acute", time="now")
                return self._acute(state, acute)
            state.react_override = non_acute_settled(h, ev.family_ref)
            hit = None
            event_note = "health_concern_settled"
        else:
            event_note = None
        if hit and hit.tier == "acute":
            return self._acute(state, hit)
        if hit and hit.tier == "non_acute":
            state.concern_hits.append(hit.to_dict() | {"layer": 1})
            state.awaiting_confirm = hit.to_dict() | {"layer": 1}
            if state.phase == "greeting" and state.consent_given is None:
                state.consent_given = True       # she is talking to us; the next "hổng có" answers the question
            return self._finish(state, non_acute_reply(hit.category, h), "health_concern")
        if hit and hit.tier == "third_party":
            state.third_party_hits.append(hit.to_dict() | {"layer": 1})
            state.react_override = third_party_reply(h)
            event_note = "third_party"

        # 2. opt-out confirmation
        if state.opt_out_pending:
            state.opt_out_pending = False
            if g.is_yes(text) or g.detect_opt_out(text):
                state.opted_out = True
                state.end_reason = "opt_out"
                return self._finish(state, g.opt_out_done(h, ev.family_ref), "opt_out", True)
            return self._finish(state, g.opt_out_cancel(h), "opt_out_cancelled")
        if g.detect_opt_out(text):
            state.opt_out_pending = True
            return self._finish(state, g.opt_out_confirm(h), "opt_out_confirm")

        # 3. consent answer
        if state.phase == "greeting" and state.consent_given is None:
            if g.is_no(text) and not g.is_yes(text):
                state.consent_given = False
                state.declined = True
                state.end_reason = "declined"
                return self._finish(state, f"Dạ, vậy con hổng làm phiền {h}. Mai con gọi lại nha. Con chào {h}.",
                                    "declined", True)
            state.consent_given = True

        # 4. guardrails (deterministic; do not advance the conversation plan)
        for kind, det, rep in (("scam", g.detect_scam, g.scam_reply),
                               ("medication", g.detect_medication_change, g.medication_reply),
                               ("diagnosis", g.detect_diagnosis_request,
                                lambda hh: g.diagnosis_reply(hh, ev.family_ref))):
            m = det(text)
            if m:
                state.flags.append({"type": kind, "match": m, "quote": text})
                state.react_override = None
                return self._finish(state, rep(h), kind)

        # 4b. symptom follow-up (scripted engine; Claude follows up on its own). One extra turn per symptom; it does
        #     not advance the plan, and never interrupts the recall answers or the closing.
        if (isinstance(self.engine, ScriptedEngine) and state.recall_stage not in ("asked_free", "asked_cue")
                and state.phase in ("greeting", "wellbeing", "story") and state.step != "closing"
                and state.share_stage != "asked"
                and state.elapsed() < CLOSING_AT_SEC - 30 and not state.react_override):
            fu = symptom_followup(text, state.followed_up, h, h)
            if fu:
                state.followed_up.append(fu[0])
                state.step = "symptom_followup"
                return self._finish(state, fu[1], "symptom_followup")

        # 5. plan + engine
        state.step = plan_step(state, text)
        reply, phase, end_call = self.engine.reply(state, text)
        if state.emergency and not any(x.get("layer") == 1 for x in state.emergency_hits):
            state.end_reason = "emergency"
            return self._finish(state, reply, "emergency", True)
        if state.react_override:   # engine did not use it (e.g. Claude): say it first
            reply, state.react_override = f"{state.react_override} {reply}", None
        reply = g.scrub_reply(reply, h)
        state.phase = phase if phase in PHASES else state.phase
        if state.step == "closing":
            end_call = True
        if state.elapsed() >= HARD_STOP_SEC and not end_call:
            reply, end_call = closing_text(state), True
            state.phase = "closing"
        return self._finish(state, reply, event_note, end_call)

    def _acute(self, state: CallState, hit: EmergencyHit) -> TurnResult:
        state.emergency = True
        state.emergency_hits.append(hit.to_dict() | {"layer": 1})
        state.end_reason = "emergency"
        return self._finish(state, emergency_reply(hit.category, state.ev.honorific, state.ev.family_ref),
                            "emergency", True, hit)
