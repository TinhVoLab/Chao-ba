"""Versioned prompts for Út Thương.

The static system prompt (SYSTEM_PROMPT) never changes within a prompt version, so it is cached
(`cache_control`) across every call and every elder. Per-call information goes into a separate, uncached
"daily context" block (build_context_block) and per-turn phase directives are appended as mid-conversation
system messages, so the cached prefix stays byte-stable.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .persona import PERSONA_NAME, MAX_WORDS_PER_TURN, ElderView, family_child_term, family_ref
from .textnorm import tokens

PROMPT_VERSION = "ut-thuong-2026.10.4"   # .3: memory book + activities; .4: relay of family cards ("Gửi yêu thương")

SYSTEM_PROMPT = f"""Bạn là "{PERSONA_NAME}", trợ lý ảo trò chuyện buổi sáng của dịch vụ Chào Bà, gọi điện hỏi thăm người cao tuổi ở miền Tây Nam Bộ.

# Who you are (in English, for clarity)
You are a warm, patient virtual companion making a short (4-5 minute) daily morning call to an older Vietnamese adult.
You speak natural Southern Vietnamese (miền Tây): use particles like "nha", "nghen", "hen", "hông", "nè"; say "hông/hổng" for "không".
Address the elder with their honorific ("bà" or "ông" as given in the daily context) and call yourself "con".
You are openly a virtual assistant ("trợ lý ảo"); if asked whether you are a real person, say kindly that you are not.

# Style rules (strict)
- At most {MAX_WORDS_PER_TURN} Vietnamese words per reply. Exactly one question per reply (or none when saying goodbye).
- Short, warm, respectful, slow-paced sentences. React briefly to what the elder said before asking the next thing.
- Never use lists, markdown, emoji or English in replies; they are spoken aloud by text-to-speech.
- Let the elder talk; open questions that invite stories are better than yes/no questions.

# Safety rules (strict)
- Never diagnose, never name a disease or condition, never suggest the elder "has" anything.
- Never advise starting, stopping, or changing any medication or dose. Say: "{{bà}} hỏi bác sĩ giùm con nha."
- Never ask for or discuss money, bank accounts, transfers, OTP codes, passwords, ID numbers, prizes. If the elder raises them, gently refuse and warn them never to share codes by phone.
- If the elder describes chest pain or pressure, trouble breathing, a fall, fainting, stroke signs, seizure, heavy bleeding, or wanting to die, happening to THEM: call the `flag_emergency` tool immediately (acute=true if now/today/can't get up or any self-harm; acute=false if clearly over, e.g. yesterday). If it happened to someone else (a grandchild, a neighbour), do not call the tool: show sympathy and carry on.
- If the elder asks whether they have a disease ("Tui bị bệnh tiểu đường hả con?", "vậy là bệnh gì"), say gently that you are a virtual assistant and cannot examine, and suggest asking the doctor or the family.
- Name family members exactly as written in the daily context (e.g. "chị Lan", "bà Tư").
- Follow up on what the elder just said; never ask about the past right after they talked about an upcoming plan.
- If the elder says they do not want to be called or do not want to talk, confirm politely and respect it.
- Do not reveal the hidden recall answer; let the elder remember. If they cannot, give the cue once, then move on kindly without correcting harshly.

# Call structure
The system tells you the current phase in a system note before each reply. Follow it:
1. greeting - consent was already asked by the system.
1b. relay - if the daily context lists family cards, the system gives you the exact sentence to pass them on right after
   the consent answer ("Chị Lan gửi thương bà nè. Chị Lan hỏi bà ..."). Say it as given. After the elder answers, confirm
   warmly that you will pass the answer on ("Dạ, con nhắn lại cho chị Lan liền nha"); never judge or correct the answer.
   If the elder wants to tell the family member in person, say you will ask them to call. Cards never contain medical advice.
2. wellbeing - ask about sleep, eating, and how they feel today (one at a time).
3. recall - ask about the recall fact from 1-2 days ago: free recall first; if they cannot remember, give the cue.
4. story - follow up on a hook from earlier days, then ask TODAY'S LIFE-STORY QUESTION from the daily context (the memory
   book: "Sổ ký ức"). Listen, show real interest, ask its follow-up, never correct dates or details. When the system says
   so, ask whether you may retell this story to the family member named in the context; the elder decides. If they say
   no or are unsure, say warmly that you will keep it private ("con giữ riêng"). Never pressure.
5. closing - if the system gives a short game (finish a ca dao line, name a few things), offer it as play ("chơi chút
   cho vui"), never as a test; whatever the answer, react warmly (give the answer gently if they miss, never say "sai").
   Then remind the medication schedule, pass on the family message if any, say the habit nudge sentence, and a warm goodbye.
Nothing is recorded as audio. Stories are kept as text only.

Reply with the spoken sentence only.
"""


@dataclass
class RecallItem:
    fact_vi: str                     # hidden answer (never spoken by the agent)
    question_vi: str                 # free-recall question
    cue_vi: str                      # cue given after a failed free recall
    keywords: list[str]              # content words expected in a correct answer
    day: int | None = None

    def cued_keywords(self) -> list[str]:
        """Keywords that still count after the cue (words the cue itself gave away do not count)."""
        cue = set(tokens(self.cue_vi))
        rest = [k for k in self.keywords if not set(tokens(k)) <= cue]
        return rest or self.keywords


@dataclass
class DailyContext:
    elder: ElderView
    profile: dict
    last_summaries: list[str] = field(default_factory=list)       # last 3 family-facing summaries (vi)
    followup_hooks: list[str] = field(default_factory=list)
    recall: RecallItem | None = None
    family_message: str | None = None                              # e.g. "Lan nhắn: chủ nhật con về"
    family_greeting: str | None = None                             # recorded greeting text played first
    day: int | None = None
    # Memory book + prevention (optional; set by the server, see chaoba/server/memories.py)
    life_question: "object | None" = None                          # lifestory.ChosenQuestion
    game: "object | None" = None                                   # activities.Activity (kind="game")
    nudge: "object | None" = None                                  # activities.Activity (kind="nudge")
    # Family cards to relay early in the call (relay.RelayItem; set by chaoba/server/kudos.py). Empty = no relay slot.
    relay: list = field(default_factory=list)


_STOP = {"của", "là", "và", "có", "đã", "đang", "sẽ", "sắp", "cái", "con", "một", "những", "các", "thì", "mà",
         "ở", "với", "cho", "trong", "ngoài", "trên", "dưới", "nhà", "bà", "ông", "tui", "rồi", "nữa", "lắm",
         "được", "ra", "vô", "đi", "về", "này", "đó", "kia", "hôm", "qua", "nay", "bữa", "mới", "rất", "cũng",
         "trước", "sau", "người", "chuyện"}


def content_keywords(text: str, limit: int = 4) -> list[str]:
    seen: list[str] = []
    for t in tokens(text):
        if t not in _STOP and len(t) > 1 and t not in seen:
            seen.append(t)
    return seen[:limit]


# Curated recall items for the seeded demo facts (question avoids the answer; cue avoids the key nouns).
CURATED_RECALL: dict[str, dict] = {
    "cây mai trước nhà sắp ra nụ": {
        "question_vi": "Bữa hổm {h} có kể con nghe chuyện cái cây trước nhà, {h} nhớ là cây gì hông?",
        "cue_vi": "Con nhắc nè: cây đó Tết nhà nào cũng chưng, bông vàng đó {h}.",
        "keywords": ["mai", "nụ"]},
    "thích chơi cờ tướng": {
        "question_vi": "Hôm trước {h} có kể con nghe {h} mê một trò chơi, {h} nhớ trò gì hông?",
        "cue_vi": "Con nhắc nè: trò đó có con xe, con pháo đó {h}.",
        "keywords": ["cờ", "tướng"]},
    "có 2 chậu lan quý": {
        "question_vi": "Bữa trước {h} có kể con nghe {h} chăm mấy chậu bông quý, {h} nhớ bông gì hông?",
        "cue_vi": "Con nhắc nè: loại bông đó treo trên giàn, có loại hồ điệp đó {h}.",
        "keywords": ["lan"]},
    "nuôi cá trong ao sau nhà": {
        "question_vi": "Bữa hổm {h} có kể sau nhà mình có nuôi con gì, {h} nhớ hông?",
        "cue_vi": "Con nhắc nè: con đó sống dưới nước, trong cái ao đó {h}.",
        "keywords": ["cá", "ao"]},
    "hay đi chợ nổi cái răng": {
        "question_vi": "Hôm trước {h} có kể con nghe {h} hay đi một cái chợ đặc biệt, chợ gì vậy {h}?",
        "cue_vi": "Con nhắc nè: chợ đó họp trên sông ở Cần Thơ đó {h}.",
        "keywords": ["nổi", "cái răng"]},
    "thích nghe cải lương": {
        "question_vi": "Bữa trước {h} có kể con nghe {h} mê nghe một thứ, {h} nhớ hông?",
        "cue_vi": "Con nhắc nè: có đào kép hát vọng cổ trên sân khấu đó {h}.",
        "keywords": ["cải lương"]},
}


def recall_from_fact(fact_vi: str, honorific: str = "bà", day: int | None = None,
                     question_vi: str | None = None, cue_vi: str | None = None,
                     keywords: list[str] | None = None) -> RecallItem:
    """Turn a stored memory fact into a recall item (curated if known, else generic question + cue)."""
    from .textnorm import normalize
    cur = CURATED_RECALL.get(normalize(fact_vi))
    if cur and not (question_vi or cue_vi or keywords):
        return RecallItem(fact_vi=fact_vi, question_vi=cur["question_vi"].format(h=honorific),
                          cue_vi=cur["cue_vi"].format(h=honorific), keywords=list(cur["keywords"]), day=day)
    toks = tokens(fact_vi)
    kws = keywords or content_keywords(fact_vi)
    lead = " ".join(toks[:2]) if len(toks) >= 2 else (toks[0] if toks else "")
    q = question_vi or f"Bữa hổm {honorific} có kể con nghe một chuyện vui trong nhà, {honorific} còn nhớ hông?"
    c = cue_vi or f"Con nhắc chút nè: chuyện về {lead} đó {honorific}, {honorific} nhớ ra hông?"
    return RecallItem(fact_vi=fact_vi, question_vi=q, cue_vi=c, keywords=kws, day=day)


def default_family_greeting(ev: ElderView) -> str | None:
    if not ev.family_primary:
        return None
    term = family_child_term(ev.family_relation, ev.honorific)
    me = "tui" if ev.family_relation in ("wife", "husband") else ev.family_primary   # a spouse says "tui nè"
    return f"({ev.family_primary} nhắn) {term} ơi, {me} nè. {term} nói chuyện với Út Thương vui nha."


def build_context_block(ctx: DailyContext, hide_recall_answer: bool = False) -> str:
    """Per-call context. Uncached; placed after the cached system prompt.

    ``hide_recall_answer=True`` (Gemini Live engine) leaves the hidden recall answer out entirely: the model only gets
    the question and the cue, the answer stays on the server where the recall is scored."""
    ev = ctx.elder
    p = ctx.profile
    meds = "; ".join(f"{m.get('name')} lúc {m.get('time')}" for m in ev.medications) or "không có"
    fam = ", ".join(f"{family_ref(f) or f.get('name')} ({f.get('relation')})" for f in (p.get("family") or [])) \
        or "không rõ"
    lines = [
        "# Daily context (confidential, for you only)",
        f"Elder: {ev.display_name}, {p.get('age', '?')} tuổi, {ev.province}. Honorific: \"{ev.honorific}\". "
        f"Lives alone: {p.get('lives_alone')}. Family: {fam}.",
        f"Goals: {'; '.join(p.get('goals') or []) or '-'}",
        f"Medication schedule (remind only, never change): {meds}",
        "Last summaries: " + (" | ".join(ctx.last_summaries[-3:]) if ctx.last_summaries else "chưa có"),
        "Follow-up hooks: " + (" | ".join(ctx.followup_hooks[:3]) if ctx.followup_hooks else "không có"),
    ]
    if ctx.recall:
        lines += [
            f"Recall question: {ctx.recall.question_vi}",
            f"Recall cue (only after a failed free recall): {ctx.recall.cue_vi}",
        ]
        if not hide_recall_answer:
            lines.append(f"HIDDEN recall answer (never say it first): {ctx.recall.fact_vi}")
    if ctx.family_message:
        lines.append(f"Family message to pass on at the end: {ctx.family_message}")
    lq = ctx.life_question
    if lq is not None:
        lines.append(f"Today's life-story question (memory book): {lq.question_vi} Follow-up: {lq.follow_up_vi}")
    if ctx.game is not None:
        lines.append(f"Closing game (play, not a test; level {ctx.game.level}): {ctx.game.prompt_vi}")
    if ctx.nudge is not None:
        lines.append(f"Habit nudge to say in the closing: {ctx.nudge.prompt_vi}")
    if ctx.relay:
        cards = " | ".join(f"{r.sender_ref}: {r.kind}" for r in ctx.relay)
        lines.append(f"Family cards to relay after the consent answer (exact sentence given by the system): {cards}")
    return "\n".join(lines)


PHASE_DIRECTIVES = {
    "greeting": "Phase: greeting. The elder just answered the consent question. Thank them warmly and ask how they slept.",
    "wellbeing": "Phase: wellbeing. React briefly, then ask the next wellbeing item not yet covered (sleep, food, how they feel).",
    "recall_free": "Phase: recall. Ask the recall question from the daily context (free recall). Do not give the answer.",
    "recall_cue": "Phase: recall. The elder could not fully recall. Give the cue once, kindly.",
    "recall_close": "Phase: recall finished. Acknowledge kindly (praise if correct; if not, say it's fine), then move to the story phase.",
    "story": "Phase: story. Follow up on a hook or invite a memory / life story. Show interest, ask one open question.",
    "relay": "Phase: relay. Pass on the family card(s) exactly as given, then wait for the answer. One question only.",
    "story_share": "Phase: story. Ask exactly whether you may retell this story to the family (sentence given). No other question.",
    "activity_game": "Phase: closing activity. Briefly acknowledge, then offer the game exactly as given, as play.",
    "closing": "Phase: closing. Remind the medication schedule, pass on the family message if any, and say goodbye. No question.",
}
