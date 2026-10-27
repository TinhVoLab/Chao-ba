"""Emergency detection.

Layer 1 (this module, always on): a Southern-Vietnamese keyword spotter run on every elder turn, before any
LLM is consulted. It is deliberately simple, auditable and fast (<1 ms).
Layer 2 (ClaudeEngine): the `flag_emergency` tool (schema below) lets the LLM raise an emergency for
phrasings the keyword list misses.

Diacritics: we match on diacritic-preserving text so "té" (fall) does not fire on "kinh tế" (economy)
and "ngã" (fall) does not fire on "nước Nga". If the utterance has no diacritics at all (typed without IME),
we fall back to accent-stripped matching but only for multi-word phrases, which are unambiguous enough.

Negation ("hổng có té", "không khó thở") and idioms ("té ra" = it turns out, "ngã ba" = crossroads,
"mệt muốn chết" = dead tired, "sợ té" = afraid of falling) are excluded.

Every hit is classified into a **tier** (see ``classify``):

* ``acute``       - happening now / today, or no time given (safety first): chest pain, can't breathe, stroke signs,
                    seizure, heavy bleeding, fainting, a fall today or "can't get up"; and **any self-harm statement,
                    whatever the tense or subject**. -> calm 115 instruction, family notified now, call ends.
* ``non_acute``   - the elder's own event clearly in the past ("hôm qua", "bữa trước", "hồi...", "tuần rồi") with no
                    sign that it is still going on ("đang", "bây giờ", "còn đau"...). -> calm reply plus one confirming
                    question ("Bà có đang đau hay chảy máu hông?"), red light + "check in today" family alert, no 115.
                    A "yes" to the question escalates to ``acute``.
* ``third_party`` - the subject is someone else ("thằng cháu té xe", "ông nhà tui", "bả", "hàng xóm"...). -> an
                    empathetic reply and nothing recorded against the elder.

Subject heuristic: scan the tokens of the sentence before the keyword; the last subject mention wins. First-person
words ("tui", "tôi", "mình", a bare "bà"/"ông" that matches the elder's honorific) mean the elder, unless they are a
possessive ("cháu tui", "ông nhà tui"). Third-party mentions are kin/other nouns, "con"/"bà"/"ông" followed by a
qualifier or a capitalised name ("con Lan", "bà Tư", "ông nhà"). Time words are read from the same sentence.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, asdict

from .textnorm import normalize, strip_diacritics, has_vietnamese_diacritics, find_phrase, nfc, sentences, contains_phrase

# category -> phrases (diacritic form, already lower-case NFC)
CANT_GET_UP = ["hổng đứng dậy được", "không đứng dậy được", "không ngồi dậy được", "hổng ngồi dậy được",
               "hổng dậy được", "không dậy được", "dậy hổng được", "dậy không được", "hổng dậy nổi", "không dậy nổi",
               "dậy hổng nổi", "dậy không nổi"]
EMERGENCY_LEXICON: dict[str, list[str]] = {
    "chest_pain": ["tức ngực", "đau ngực", "đau tim", "nhói ngực", "thắt ngực", "đè ngực"],
    "breathing": ["khó thở", "thở hổng được", "thở không được", "thở hổng nổi", "thở không nổi",
                  "thở hổng ra hơi", "ngộp thở", "hụt hơi"],
    "fall": ["bị té", "té ngã", "té xuống", "té nhào", "té cầu thang", "té trong nhà tắm", "té", "bị ngã",
             "ngã", "trượt chân"] + CANT_GET_UP,
    "syncope": ["xỉu", "té xỉu", "ngất", "bất tỉnh", "lịm đi"],
    "stroke_signs": ["méo miệng", "nói đớ", "yếu nửa người", "tê nửa người", "liệt nửa người",
                     "cứng lưỡi", "nói hổng ra tiếng"],
    "seizure": ["co giật", "lên cơn giật"],
    "bleeding": ["chảy máu nhiều", "ói ra máu", "nôn ra máu", "đi cầu ra máu"],
    "self_harm": ["hổng muốn sống", "không muốn sống", "chẳng muốn sống", "hông muốn sống", "muốn chết",
                  "tự tử", "quyên sinh", "chết cho rồi", "chết quách", "chết cho xong", "kết thúc cuộc đời"],
}

# Idioms that contain an emergency keyword but are not emergencies.
EXCLUSIONS: list[str] = [
    "té ra", "té nước", "té ghen", "sợ té", "sợ ngã", "coi chừng té", "coi chừng ngã", "kẻo té", "kẻo ngã",
    "ngã ba", "ngã tư", "ngã năm", "ngã sáu", "ngã bảy", "ngã giá", "ngã ngũ", "ngã lòng", "ngã mũ",
    "ngã ngửa", "ngã bệnh", "ngã về", "nghiêng ngã", "ngất ngây", "ngất ngưỡng", "chao đảo ngã nghiêng",
]
# Words that turn "X muốn chết" into hyperbole ("mệt muốn chết" = dead tired).
HYPERBOLE_BEFORE_MUON_CHET = {"mệt", "nóng", "lạnh", "đói", "vui", "mừng", "sướng", "cười", "ngon", "thèm",
                              "nhớ", "ngứa", "khát", "sợ", "hôi", "mắc", "dzui", "quê", "ngán", "ghiền"}
NEGATORS = {"không", "hổng", "hông", "chưa", "chẳng", "chả", "ko", "khong", "hong", "hok", "đâu"}
# A negation directly before the keyword, optionally followed by "có"/"bị" ("hổng có té", "không bị ngã").
_NEG_FILLERS = {"có", "bị", "thấy", "co", "bi", "thay"}

# ------------------------------------------------------------------ time words (read from the hit's sentence)
NOW_MARKERS = ["đang", "bây giờ", "giờ này", "giờ còn", "giờ vẫn", "giờ đang", "tới giờ", "nãy giờ", "còn đau",
               "vẫn còn", "vẫn đau", "đau quá", "ngay bây giờ", "liền bây giờ"]
JUST_MARKERS = ["mới", "vừa", "vừa mới"]          # "just now" unless a past word is also present ("hôm qua mới té")
TODAY_MARKERS = ["sáng nay", "hồi sáng", "hồi nãy", "lúc nãy", "khi nãy", "hồi khuya", "bữa nay", "hôm nay",
                 "trưa nay", "chiều nay", "tối nay"]
PAST_MARKERS = ["hôm qua", "bữa qua", "tối qua", "đêm qua", "hồi hôm", "hôm kia", "bữa kia", "hôm trước", "bữa trước",
                "bữa hổm", "hôm hổm", "hôm bữa", "mấy bữa trước", "mấy hôm trước", "mấy bữa nay", "tuần rồi",
                "tuần trước", "tháng rồi", "tháng trước", "năm rồi", "năm ngoái", "năm trước", "hồi xưa", "hồi trước",
                "hồi nhỏ", "hồi trẻ", "hồi đó", "hồi tết", "hồi năm", "hồi tháng", "hồi còn", "lâu rồi", "bữa đó"]

# ------------------------------------------------------------------ subject words
FIRST_PERSON = {"tui", "tôi", "tao", "mình"}
POSSESSIVE_BEFORE = {"nhà", "của", "cháu", "con", "chồng", "vợ", "em", "anh", "chị", "bạn", "bồ"}
THIRD_PARTY_WORDS = {"cháu", "bả", "ổng", "nó", "chồng", "vợ", "ảnh", "thằng", "đứa", "em", "anh", "chị", "cô", "chú",
                     "dì", "cậu", "mợ", "thím", "bác", "bạn", "dượng", "sui", "chỉ"}
THIRD_PARTY_PHRASES = ["hàng xóm", "người ta", "ông nhà", "bà nhà", "ông xã", "bà xã", "mấy đứa", "tụi nhỏ", "sắp nhỏ",
                       "con gái", "con trai", "con dâu", "con rể", "con nhỏ", "con út", "con cả", "ông sui", "bà sui",
                       "ông hàng xóm", "bà hàng xóm", "ông già", "bà già", "ông bên", "bà bên", "ông kia", "bà kia",
                       "ông đó", "bà đó", "ông ấy", "bà ấy", "ông ngoại", "bà ngoại", "ông nội", "bà nội"]
_VOCATIVE_AFTER = {"ơi", "à", "nè", "ạ", "nghe", "biết", "coi", "nói", "hỏi", "thấy", "nghĩ", "nhớ", "ha", "nha", "hen"}
# "chỉ" is also "only" ("chỉ có hơi mỏi"): count it as "chị ấy" only right before a verb-like keyword phrase.
_AMBIGUOUS_ONLY_BEFORE_KEYWORD = {"chỉ"}

TIERS = ("acute", "non_acute", "third_party")
_TIER_RANK = {"acute": 3, "non_acute": 2, "third_party": 1}


@dataclass
class EmergencyHit:
    category: str
    keyword: str
    quote: str
    tier: str = "acute"        # acute | non_acute | third_party
    subject: str = "self"      # self | other
    time: str = "unknown"      # now | today | past | unknown

    def to_dict(self) -> dict:
        return asdict(self)


def _negated(prefix_tokens: list[str]) -> bool:
    toks = list(prefix_tokens[-3:])
    while toks and toks[-1] in _NEG_FILLERS:
        toks.pop()
    return bool(toks) and toks[-1] in NEGATORS


def _excluded(norm: str, start: int, phrase: str, exclusions: list[str]) -> bool:
    end = start + len(phrase)
    for ex in exclusions:
        for s in find_phrase(norm, ex):
            if s <= start < s + len(ex) or s < end <= s + len(ex):
                return True
    return False


_PUNCT = re.compile(r"[^\w\s]", re.UNICODE)


def _orig_tokens(text: str) -> list[str]:
    """Tokens aligned with normalize(text).split() but keeping case (to spot names: "con Lan", "bà Tư")."""
    return _PUNCT.sub(" ", nfc(text)).split()


def subject_before(prefix: list[str], orig: list[str] | None = None, honorific: str | None = None) -> str | None:
    """Who the clause is about, from the tokens *before* a keyword: "self", "other" or None (unknown -> self).

    The last subject mention wins ("thằng cháu tới chơi, tui bị té" -> self). A first-person word right after a
    third-party noun or "nhà"/"của" is a possessive ("cháu tui té", "ông nhà tui té" -> other)."""
    orig = orig or prefix
    subj: str | None = None
    last_other = -10
    i, n = 0, len(prefix)
    while i < n:
        t = prefix[i]
        nxt = prefix[i + 1] if i + 1 < n else ""
        onxt = orig[i + 1] if i + 1 < len(orig) else ""
        two = f"{t} {nxt}"
        if nxt and two in THIRD_PARTY_PHRASES:
            subj, last_other = "other", i + 1
            i += 2
            continue
        prev = prefix[i - 1] if i else ""
        if t in FIRST_PERSON:
            if not (prev in POSSESSIVE_BEFORE or last_other == i - 1):
                subj = "self"
        elif t in ("bà", "ông"):
            if onxt[:1].isupper():                                       # "bà Tư", "ông Sáu"
                subj, last_other = "other", i + 1
                i += 2
                continue
            if honorific and t != honorific:                             # bare "ông" said by a "bà" elder
                subj, last_other = "other", i
            elif not (prev in POSSESSIVE_BEFORE or last_other == i - 1):  # bare honorific = the elder herself
                subj = "self"
        elif t == "con":
            if onxt[:1].isupper() and nxt not in _VOCATIVE_AFTER:         # "con Lan"
                subj, last_other = "other", i + 1
                i += 2
                continue
        elif t in THIRD_PARTY_WORDS:
            if t in _AMBIGUOUS_ONLY_BEFORE_KEYWORD and (prev in FIRST_PERSON or prev in ("bà", "ông")
                                                        or (i != n - 1 and nxt != "bị")):
                pass   # "tui chỉ bị té nhẹ" = "I only...", not "chị ấy"
            else:
                subj, last_other = "other", i
        i += 1
    return subj


def time_of(norm_sentence: str) -> str:
    """now | today | past | unknown, from time words in one (normalised) sentence."""
    has = lambda ms: any(contains_phrase(norm_sentence, m) for m in ms)  # noqa: E731
    if has(NOW_MARKERS) or has(CANT_GET_UP):
        return "now"
    past = has(PAST_MARKERS)
    if has(JUST_MARKERS) and not past:
        return "now"
    if past and not has(TODAY_MARKERS):
        return "past"
    if has(TODAY_MARKERS):
        return "today"
    return "unknown"


def classify(category: str, subject: str | None, when: str) -> str:
    """Tier for one hit (see module docstring). Self-harm is always acute."""
    if category == "self_harm":
        return "acute"
    if subject == "other":
        return "third_party"
    if when == "past":
        return "non_acute"
    return "acute"


def _spot_sentence(sent: str, honorific: str | None) -> list[tuple[EmergencyHit, int]]:
    norm = normalize(sent)
    accented = has_vietnamese_diacritics(sent)
    if accented:
        lexicon, exclusions, hyper, negators, muon_chet, hay = (EMERGENCY_LEXICON, EXCLUSIONS,
                                                                HYPERBOLE_BEFORE_MUON_CHET, NEGATORS, "muốn chết", norm)
    else:
        # accent-free fallback: only multi-word phrases (single syllables are too ambiguous without tones)
        lexicon = {c: [strip_diacritics(p) for p in ps if " " in p] for c, ps in EMERGENCY_LEXICON.items()}
        exclusions = [strip_diacritics(e) for e in EXCLUSIONS]
        hyper = {strip_diacritics(w) for w in HYPERBOLE_BEFORE_MUON_CHET}
        negators = {strip_diacritics(w) for w in NEGATORS}
        muon_chet = "muon chet"
        hay = strip_diacritics(norm)
    orig = _orig_tokens(sent)
    when = time_of(norm if accented else hay)
    if not accented and when == "unknown":
        when = time_of(norm)
    hits = []
    # Longest phrases first so "té xỉu" wins over "té".
    candidates = sorted(((c, p) for c, ps in lexicon.items() for p in ps), key=lambda cp: -len(cp[1]))
    for order, (category, phrase) in enumerate(candidates):
        for start in find_phrase(hay, phrase):
            if _excluded(hay, start, phrase, exclusions):
                continue
            prefix = hay[:start].split()
            starts_with_neg = phrase.split()[0] in negators
            if not starts_with_neg and (_negated(prefix) if accented else bool(prefix) and prefix[-1] in negators):
                continue
            if phrase == muon_chet and prefix and prefix[-1] in hyper:
                continue
            subj = subject_before(norm.split()[:len(prefix)], orig[:len(prefix)], honorific)
            t = "now" if (category == "fall" and phrase in [strip_diacritics(x) if not accented else x
                                                            for x in CANT_GET_UP]) else when
            tier = classify(category, subj, t)
            hits.append((EmergencyHit(category=category, keyword=phrase, quote="", tier=tier,
                                      subject=subj or "self", time=t), order))
            break
    return hits


def spot(text: str, honorific: str | None = None) -> EmergencyHit | None:
    """Return the most serious emergency hit in an elder utterance (acute > non_acute > third_party), or None.

    ``honorific`` ("bà"/"ông") lets a bare "ông" said by a "bà" elder count as someone else."""
    if not text or not text.strip():
        return None
    best: tuple[int, int, EmergencyHit] | None = None
    for sent in sentences(text):
        for hit, order in _spot_sentence(sent, honorific):
            key = (_TIER_RANK[hit.tier], -order)
            if best is None or key > best[:2]:
                best = (key[0], key[1], hit)
    if best is None:
        return None
    hit = best[2]
    hit.quote = text.strip()
    return hit


def is_third_party(sentence: str, phrase_start: int, honorific: str | None = None) -> bool:
    """For other modules (symptom extraction): is the phrase at ``phrase_start`` of normalize(sentence) about
    someone other than the elder?"""
    norm = normalize(sentence)
    prefix = norm[:phrase_start].split()
    return subject_before(prefix, _orig_tokens(sentence)[:len(prefix)], honorific) == "other"


CATEGORY_VI = {"chest_pain": "tức hoặc đau ngực", "breathing": "khó thở", "fall": "té ngã", "syncope": "xỉu",
               "stroke_signs": "méo miệng / nói đớ / yếu một bên", "seizure": "co giật", "bleeding": "chảy máu",
               "self_harm": "ý nghĩ không muốn sống", "other": "điều đáng lo"}
CATEGORY_EN = {"chest_pain": "chest pain or pressure", "breathing": "trouble breathing", "fall": "a fall",
               "syncope": "fainting", "stroke_signs": "drooping mouth / slurred speech / one-sided weakness",
               "seizure": "a seizure", "bleeding": "bleeding", "self_harm": "thoughts of not wanting to live",
               "other": "something worrying"}


def emergency_reply(category: str, honorific: str = "bà", family_ref: str | None = None) -> str:
    """Acute tier: calm, short instruction (115 + family notified). Never diagnoses.

    ``family_ref`` is how the family member is named mid-sentence ("chị Lan", "bà Tư"), see persona.family_ref."""
    fam = family_ref or "người nhà"
    h = honorific
    if category == "self_harm":
        return (f"Dạ, con nghe {h} nói rồi, con thương {h} lắm. Con đang báo {fam} gọi {h} liền. "
                f"Nếu {h} thấy nguy, {h} gọi 115 hoặc kêu hàng xóm giùm con nha {h}.")
    return (f"Dạ {h} ơi, {h} bình tĩnh nha. {h.capitalize()} gọi ngay 115 hoặc kêu người gần nhà giúp liền nghen. "
            f"Con đang báo cho {fam} biết rồi.")


def non_acute_reply(category: str, honorific: str = "bà") -> str:
    """Non-acute tier: calm acknowledgement plus ONE confirming question (answer decides acute or not)."""
    h = honorific
    what = {"fall": f"{h} bị té", "chest_pain": f"{h} bị tức ngực", "breathing": f"{h} bị khó thở",
            "syncope": f"{h} bị xỉu"}.get(category, f"{h} thấy không khỏe")
    return f"Dạ, {what} hả {h}, tội {h} quá. Giờ {h} có đang đau hay chảy máu gì hông {h}?"


def non_acute_settled(honorific: str = "bà", family_ref: str | None = None) -> str:
    """Said when the elder answers the confirming question with "no": reassure, family will check in today."""
    fam = family_ref or "người nhà"
    return f"Dạ, vậy con mừng. Con nhắn {fam} hôm nay gọi hỏi thăm {honorific} nha."


def third_party_reply(honorific: str = "bà") -> str:
    return f"Dạ, tội nghiệp quá, mong là mau lành nha {honorific}."


CONFIRM_NOW = ["đang đau", "còn đau", "đau quá", "đau lắm", "chảy máu", "ra máu", "đang chảy", "khó thở", "tức ngực",
               "chóng mặt", "hổng đi được", "không đi được", "sưng", "có đau", "đau chút", "hơi đau", "nhức lắm"]


def confirms_now(text: str) -> bool:
    """Does an answer to "có đang đau hay chảy máu hông?" confirm a current problem?"""
    from .guardrails import is_yes, is_no
    n = normalize(text)
    if not n:
        return False
    for p in CONFIRM_NOW:
        for st in find_phrase(n, p):
            if not _negated(n[:st].split()):
                return True
    return is_yes(text) and not is_no(text)


# Layer 2: tool exposed to ClaudeEngine.
FLAG_EMERGENCY_TOOL = {
    "name": "flag_emergency",
    "description": (
        "Call this immediately if the elder describes a possible medical emergency or risk of self-harm "
        "happening to THEM (chest pain/pressure, trouble breathing, a fall, fainting, stroke signs such as a drooping "
        "mouth or slurred speech or one-sided weakness, seizure, heavy bleeding, or wanting to die). Set acute=true "
        "if it is happening now or today, or the elder cannot get up, or it is about self-harm: the system then tells "
        "the elder to call 115 and notifies the family. Set acute=false for the elder's own event that is clearly over "
        "(e.g. a fall yesterday, chest tightness last week): the system asks one confirming question and asks the "
        "family to check in today. Do NOT call it for events that happened to someone else (a grandchild, a "
        "neighbour) or for mild, everyday aches."
    ),
    "strict": True,
    "input_schema": {
        "type": "object",
        "properties": {
            "category": {"type": "string", "enum": sorted(EMERGENCY_LEXICON.keys()) + ["other"]},
            "quote": {"type": "string", "description": "The elder's words, verbatim."},
            "acute": {"type": "boolean", "description": "true = now/today/can't get up/self-harm; false = clearly past."},
        },
        "required": ["category", "quote", "acute"],
        "additionalProperties": False,
    },
}
