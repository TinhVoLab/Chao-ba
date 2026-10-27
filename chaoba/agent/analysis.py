"""Post-call analysis -> CallAnalysis.

With ANTHROPIC_API_KEY: Claude Opus 5.5 with structured output (JSON schema) + server-side refusal fallback.
Without a key (or on any error): a transparent rule-based analyzer:
  - symptom lexicon with verbatim quotes (negation-aware: "hổng đau" is not pain)
  - mood heuristic 1..5 from positive/negative lexicons
  - recall scoring vs the hidden fact: exact 3 / partial 2 / cued 1 / failed 0
  - family-facing summaries vi/en, new memory facts, follow-up hooks
Wording rule: never diagnostic. Summaries describe what the elder said, not what they "have".
"""
from __future__ import annotations

import json
import logging
import os
import re

from chaoba.core.models import CallAnalysis, SYMPTOMS, Turn

from .guardrails import FORBIDDEN_IN_REPLY
from .prompts import PROMPT_VERSION, RecallItem, content_keywords
from .emergency import is_third_party, CATEGORY_VI, CATEGORY_EN
from .textnorm import normalize, contains_phrase, find_phrase, sentences, word_count

log = logging.getLogger("chaoba.analysis")

ANALYSIS_MODEL = "claude-opus-5-5"

SYMPTOM_LEXICON: dict[str, list[str]] = {
    "pain": ["đau", "nhức", "mỏi lưng", "mỏi gối", "ê ẩm", "nhức đầu", "đau lưng", "đau chân", "đau khớp",
             "nhức mỏi", "tê chân", "tê tay"],
    "insomnia": ["mất ngủ", "khó ngủ", "ngủ hổng được", "ngủ không được", "ngủ hông được", "thức trắng",
                 "trằn trọc", "ngủ ít", "thức hoài", "hổng ngủ", "không ngủ", "thức giấc hoài", "chập chờn"],
    "skipped_meal": ["bỏ bữa", "chưa ăn", "hổng ăn", "không ăn", "ăn hổng vô", "ăn không vô", "không muốn ăn",
                     "hổng muốn ăn", "ăn hổng nổi", "biếng ăn", "nhịn đói", "quên ăn"],
    "dizziness": ["chóng mặt", "choáng", "xây xẩm", "hoa mắt", "quay cuồng", "lảo đảo"],
    "fall": ["bị té", "té ngã", "té", "bị ngã", "ngã", "trượt chân"],
    "sadness": ["buồn", "cô đơn", "tủi thân", "chán", "nhớ con", "nhớ cháu", "hiu quạnh", "khóc"],
    "missed_medication": ["quên uống thuốc", "chưa uống thuốc", "hổng uống thuốc", "không uống thuốc", "quên thuốc",
                          "hết thuốc", "bỏ thuốc"],
}
SYMPTOM_EXCLUDE = {
    "pain": ["đau lòng"],
    "fall": ["té ra", "té nước", "sợ té", "coi chừng té", "ngã ba", "ngã tư", "ngã giá", "ngã bệnh"],
    "sadness": ["buồn cười", "buồn ngủ", "hết buồn", "đỡ buồn"],
    "insomnia": [],
}
# Phrases that already contain a negator as part of the symptom ("chưa ăn") must not be re-negated.
NEG = {"không", "hổng", "hông", "chưa", "chẳng", "chả", "đâu", "hết", "đỡ"}
POSITIVE = ["vui", "khỏe", "khoẻ", "ổn", "mừng", "ngon", "thích", "sướng", "khỏe re", "bình thường", "cười",
            "thoải mái", "ngủ ngon", "đỡ rồi", "hết đau"]
NEGATIVE = ["buồn", "mệt", "cô đơn", "chán", "lo", "khóc", "tủi", "đau", "nhức", "khổ", "mệt mỏi", "hổng khỏe",
            "không khỏe", "yếu"]
NEWS_MARKERS = ["hôm qua", "bữa qua", "hồi hôm", "mới", "sắp", "tuần sau", "tuần tới", "chủ nhật", "ngày mai",
                "bữa nay", "sáng nay", "đám giỗ", "đám cưới", "về thăm", "trồng", "ra nụ", "ra hoa", "nuôi",
                "đi chợ", "đi chùa", "nấu", "cháu", "con gái", "con trai"]
# Sentences about routine sleep/food/feeling are wellbeing answers, not life facts worth recalling later.
WELLBEING_ONLY = ["ngủ", "ăn sáng", "ăn cháo", "ăn cơm", "trong người", "trong mình", "uống thuốc", "khỏe"]
FUTURE_MARKERS = ["sắp", "tuần sau", "tuần tới", "chủ nhật", "ngày mai", "mai mốt", "bữa sau", "định", "tính",
                  "sẽ", "về thăm", "hẹn"]


def _negated(norm: str, start: int) -> bool:
    prev = norm[:start].split()[-2:]
    return any(w in NEG for w in prev)


def extract_symptoms(elder_texts: list[str], honorific: str | None = None) -> dict[str, list[str]]:
    """symptom -> verbatim sentences. Negated mentions and mentions about someone else ("thằng cháu té xe") are
    skipped: only what the elder reports about herself counts."""
    out: dict[str, list[str]] = {}
    for text in elder_texts:
        for sent in sentences(text):
            n = normalize(sent)
            for sym, phrases in SYMPTOM_LEXICON.items():
                excl = SYMPTOM_EXCLUDE.get(sym, [])
                found = False
                for p in sorted(phrases, key=len, reverse=True):
                    for st in find_phrase(n, p):
                        if any(s <= st < s + len(e) for e in excl for s in find_phrase(n, e)):
                            continue
                        if p.split()[0] not in NEG and _negated(n, st):
                            continue
                        if is_third_party(sent, st, honorific):
                            continue
                        found = True
                        break
                    if found:
                        break
                if found and sent not in out.get(sym, []):
                    out.setdefault(sym, []).append(sent)
    return {k: v for k, v in out.items() if k in SYMPTOMS}


def mood_score(elder_texts: list[str], symptoms: dict[str, list[str]]) -> int:
    pos = neg = 0
    for t in elder_texts:
        n = normalize(t)
        for w in POSITIVE:
            for st in find_phrase(n, w):
                if _negated(n, st):
                    neg += 1
                else:
                    pos += 1
        for w in NEGATIVE:
            for st in find_phrase(n, w):
                if w.split()[0] in NEG or not _negated(n, st):
                    neg += 1
    score = 3.0 + 0.5 * min(pos, 4) - 0.5 * min(neg, 4)
    if "sadness" in symptoms:
        score -= 0.5
    if len(symptoms) >= 3:
        score -= 0.5
    return int(max(1, min(5, round(score))))


def score_recall(recall: RecallItem | None, free_text: str, cued_text: str,
                 result_hint: str | None = None) -> tuple[int | None, str | None]:
    """exact free recall 3 / partial free recall 2 / correct after cue 1 / failed 0."""
    if recall is None or (not free_text and not cued_text and result_hint is None):
        return None, None
    from .orchestrator import recall_match  # local import to avoid a cycle
    if free_text:
        f = recall_match(free_text, recall.keywords)
        if f >= 0.67:
            return 3, "free"
        if f > 0:
            return 2, "free"
    if cued_text and recall_match(cued_text, recall.cued_keywords()) > 0:
        return 1, "cued"
    if not free_text and not cued_text:
        return None, None
    return 0, "failed"


def _clip(s: str, n: int = 20) -> str:
    w = s.strip().split()
    return " ".join(w[:n]) + ("…" if len(w) > n else "")


def memory_facts_from(elder_texts: list[str], known: list[str]) -> list[str]:
    facts: list[str] = []
    known_n = {normalize(k) for k in known}
    for t in elder_texts:
        for sent in sentences(t):
            n = normalize(sent)
            if word_count(sent) < 6 or n in known_n or any(contains_phrase(n, w) for w in WELLBEING_ONLY):
                continue
            if any(contains_phrase(n, m) for m in NEWS_MARKERS):
                facts.append(_clip(sent, 20).rstrip(".!?…") + ".")
            if len(facts) >= 2:
                return facts
    return facts


def followup_hooks_from(elder_texts: list[str]) -> list[str]:
    hooks: list[str] = []
    for t in elder_texts:
        for sent in sentences(t):
            n = normalize(sent)
            if word_count(sent) >= 4 and any(contains_phrase(n, m) for m in FUTURE_MARKERS):
                hooks.append(_clip(sent, 20).rstrip(".!?…"))
            if len(hooks) >= 2:
                return hooks
    return hooks


SYM_VI = {"pain": "đau nhức", "insomnia": "ngủ không ngon", "skipped_meal": "ăn uống ít / bỏ bữa",
          "dizziness": "chóng mặt", "fall": "có nhắc tới té ngã", "sadness": "buồn / cô đơn",
          "missed_medication": "quên hoặc chưa uống thuốc"}
SYM_EN = {"pain": "aches or pain", "insomnia": "poor sleep", "skipped_meal": "eating little / skipped meals",
          "dizziness": "dizziness", "fall": "mentioned a fall", "sadness": "feeling sad or lonely",
          "missed_medication": "missed or delayed medication"}
MOOD_VI = {1: "rất buồn", 2: "hơi buồn", 3: "bình thường", 4: "vui vẻ", 5: "rất vui vẻ"}
MOOD_EN = {1: "very low", 2: "somewhat low", 3: "neutral", 4: "cheerful", 5: "very cheerful"}
RECALL_VI = {3: "nhớ chuyện hôm trước rất rõ", 2: "nhớ được một phần chuyện hôm trước",
             1: "nhớ ra chuyện hôm trước khi được gợi ý", 0: "chưa nhớ ra chuyện hôm trước"}
RECALL_EN = {3: "recalled the earlier story clearly", 2: "partly recalled the earlier story",
             1: "recalled the earlier story with a cue", 0: "did not recall the earlier story today"}


def summaries(name_vi: str, name_en: str, mood: int, symptoms: dict, recall: int | None, emergency: bool,
              opted_out: bool, n_elder_turns: int, concerns: list[str] | None = None) -> tuple[str, str]:
    if emergency:
        return (f"{name_vi} có nói điều cần chú ý ngay trong cuộc gọi; Út Thương đã hướng dẫn gọi 115 và báo gia đình.",
                f"{name_en} said something that needs attention now; the assistant advised calling 115 and notified the family.")
    if opted_out:
        return (f"{name_vi} đã yêu cầu ngưng các cuộc gọi buổi sáng. Hệ thống đã ghi nhận.",
                f"{name_en} asked to stop the morning calls. This has been recorded.")
    if n_elder_turns == 0:
        return (f"{name_vi} chưa trò chuyện trong cuộc gọi hôm nay.", f"{name_en} did not talk during today's call.")
    vi = [f"{name_vi} trò chuyện, tâm trạng {MOOD_VI[mood]}"]
    en = [f"{name_en} chatted and seemed {MOOD_EN[mood]}"]
    if symptoms:
        vi.append("có kể: " + ", ".join(SYM_VI[s] for s in symptoms))
        en.append("mentioned " + ", ".join(SYM_EN[s] for s in symptoms))
    else:
        vi.append("không kể điều gì đáng lo")
        en.append("no worrying mentions")
    s_vi = "; ".join(vi) + "."
    s_en = "; ".join(en) + "."
    cs = [c for c in dict.fromkeys(concerns or [])]
    if cs:
        s_vi = (f"{name_vi} kể đã bị {', '.join(CATEGORY_VI.get(c, c) for c in cs)} (không phải lúc gọi); Út Thương đã "
                f"hỏi lại và đề nghị gia đình gọi hỏi thăm trong hôm nay. " + s_vi)
        s_en = (f"{name_en} mentioned an earlier episode of {', '.join(CATEGORY_EN.get(c, c) for c in cs)} (not "
                f"ongoing during the call); the assistant checked and asked the family to check in today. " + s_en)
    if recall is not None:
        s_vi += f" {RECALL_VI[recall].capitalize()}."
        s_en += f" {RECALL_EN[recall].capitalize()}."
    return s_vi, s_en


def _safe_text(s: str) -> str:
    n = normalize(s)
    for w in FORBIDDEN_IN_REPLY:
        if contains_phrase(n, w):
            return re.sub(re.escape(w), "thay đổi so với bình thường", s, flags=re.IGNORECASE)
    return s


def analyze_rule_based(turns: list[Turn], elder_profile: dict, recall: RecallItem | None = None,
                       recall_free_text: str = "", recall_cued_text: str = "", emergency: bool = False,
                       opted_out: bool = False, recall_result_hint: str | None = None,
                       concerns: list[str] | None = None) -> CallAnalysis:
    elder_texts = [t.text for t in turns if t.speaker == "elder" and t.text.strip()]
    # The recall answers are not symptom reports and not new facts; keep them out of those extractors.
    symptoms = extract_symptoms(elder_texts, (elder_profile.get("honorific") or "bà").lower())
    mood = mood_score(elder_texts, symptoms)
    rscore, cue = score_recall(recall, recall_free_text, recall_cued_text, recall_result_hint)
    other_texts = [t for t in elder_texts if t not in (recall_free_text, recall_cued_text)]
    facts = memory_facts_from(other_texts, list(elder_profile.get("memory_facts") or []))
    hooks = followup_hooks_from(other_texts)
    name_vi = elder_profile.get("display_name", "Người thân")
    name_en = elder_profile.get("name_en", name_vi)
    s_vi, s_en = summaries(name_vi, name_en, mood, symptoms, rscore, emergency, opted_out, len(elder_texts), concerns)
    return CallAnalysis(summary_vi=_safe_text(s_vi), summary_en=_safe_text(s_en), mood=mood, symptoms=symptoms,
                        recall_score=rscore, recall_cue_level=cue, memory_facts_new=facts, followup_hooks=hooks,
                        emergency=emergency, prompt_version=PROMPT_VERSION)


# --------------------------------------------------------------------------------------------- Claude Opus
ANALYSIS_SCHEMA = {
    "type": "object",
    "properties": {
        "summary_vi": {"type": "string"},
        "summary_en": {"type": "string"},
        "mood": {"type": "integer", "enum": [1, 2, 3, 4, 5]},
        "symptoms": {
            "type": "object",
            "properties": {s: {"type": "array", "items": {"type": "string"}} for s in SYMPTOMS},
            "required": list(SYMPTOMS),
            "additionalProperties": False,
        },
        "recall_score": {"anyOf": [{"type": "integer", "enum": [0, 1, 2, 3]}, {"type": "null"}]},
        "recall_cue_level": {"anyOf": [{"type": "string", "enum": ["free", "cued", "failed"]}, {"type": "null"}]},
        "memory_facts_new": {"type": "array", "items": {"type": "string"}},
        "followup_hooks": {"type": "array", "items": {"type": "string"}},
        "emergency": {"type": "boolean"},
    },
    "required": ["summary_vi", "summary_en", "mood", "symptoms", "recall_score", "recall_cue_level",
                 "memory_facts_new", "followup_hooks", "emergency"],
    "additionalProperties": False,
}

ANALYSIS_INSTRUCTIONS = """You analyse one daily check-in call between a virtual companion ("Út Thương") and an older
Vietnamese adult. Produce family-facing structured output.
Rules:
- Never diagnose or name diseases/conditions (no "dementia", "sa sút trí tuệ", "trầm cảm", etc.). Describe only what the
  elder said and how they seemed, relative to their usual self.
- symptoms: for each key, list VERBATIM elder quotes that report it (empty list if none). Negated mentions
  ("hổng đau gì hết") do not count. Only what the elder reports about THEMSELF counts: events of other people
  ("thằng cháu té xe") are not the elder's symptoms.
- recall_score: compare the elder's answers to the HIDDEN recall fact. 3 = exact free recall, 2 = partial free recall,
  1 = correct only after the cue, 0 = failed, null if the recall question was not asked.
- mood: 1 very low .. 5 very good.
- summary_vi (Southern-Vietnamese-friendly, 1-2 sentences) and summary_en (1-2 sentences).
- memory_facts_new: up to 2 short new facts from the elder's life useful to ask about in 1-2 days.
- followup_hooks: up to 2 short things to follow up on in the next call.
- emergency: true only if the elder described a possible emergency."""


def analyze_with_claude(client, turns: list[Turn], elder_profile: dict, recall: RecallItem | None,
                        emergency: bool) -> CallAnalysis:
    transcript = "\n".join(f"{'ELDER' if t.speaker == 'elder' else 'AGENT'}: {t.text}" for t in turns)
    hidden = f"HIDDEN recall fact: {recall.fact_vi}\nCue used: {recall.cue_vi}" if recall else "No recall question."
    resp = client.beta.messages.create(
        model=ANALYSIS_MODEL,
        max_tokens=4000,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        system=[{"type": "text", "text": ANALYSIS_INSTRUCTIONS, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content":
                   f"Elder: {elder_profile.get('display_name')} ({elder_profile.get('name_en')}), "
                   f"age {elder_profile.get('age')}.\n{hidden}\nSystem emergency flag: {emergency}\n\n"
                   f"Transcript:\n{transcript}"}],
        output_config={"effort": "medium",
                       "format": {"type": "json_schema", "schema": ANALYSIS_SCHEMA}},
        timeout=60.0,
    )
    if resp.stop_reason == "refusal":
        raise RuntimeError("analysis refused")
    text = next(b.text for b in resp.content if getattr(b, "type", None) == "text")
    d = json.loads(text)
    syms = {k: v for k, v in (d.get("symptoms") or {}).items() if k in SYMPTOMS and v}
    return CallAnalysis(
        summary_vi=_safe_text(d["summary_vi"]), summary_en=_safe_text(d["summary_en"]), mood=int(d["mood"]),
        symptoms=syms, recall_score=d.get("recall_score"), recall_cue_level=d.get("recall_cue_level"),
        memory_facts_new=list(d.get("memory_facts_new") or [])[:2], followup_hooks=list(d.get("followup_hooks") or [])[:2],
        emergency=bool(d.get("emergency")) or emergency, prompt_version=PROMPT_VERSION)


def analyze_call(turns: list[Turn], elder_profile: dict, recall: RecallItem | None = None,
                 recall_free_text: str = "", recall_cued_text: str = "", emergency: bool = False,
                 opted_out: bool = False, use_llm: bool | None = None, client=None,
                 concerns: list[str] | None = None) -> CallAnalysis:
    """``concerns`` = categories of non-acute (past) episodes the spotter raised during the call."""
    rb = analyze_rule_based(turns, elder_profile, recall, recall_free_text, recall_cued_text, emergency, opted_out,
                            concerns=concerns)
    if use_llm is None:
        use_llm = bool(os.environ.get("ANTHROPIC_API_KEY"))
    if not use_llm or opted_out:
        return rb
    try:
        if client is None:
            import anthropic
            client = anthropic.Anthropic()
        ca = analyze_with_claude(client, turns, elder_profile, recall, emergency)
        # Safety net: the deterministic emergency flag can only add, never be removed by the LLM.
        ca.emergency = ca.emergency or rb.emergency
        if concerns and not ca.emergency:   # keep the deterministic "check in today" sentence
            ca.summary_vi = rb.summary_vi.split(". ")[0] + ". " + ca.summary_vi
            ca.summary_en = rb.summary_en.split(". ")[0] + ". " + ca.summary_en
        return ca
    except Exception as e:
        log.warning("Claude analysis failed (%s); using rule-based analyzer", e)
        return rb
