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
"""
from __future__ import annotations

from dataclasses import dataclass, asdict

from .textnorm import normalize, strip_diacritics, has_vietnamese_diacritics, find_phrase

# category -> phrases (diacritic form, already lower-case NFC)
EMERGENCY_LEXICON: dict[str, list[str]] = {
    "chest_pain": ["tức ngực", "đau ngực", "đau tim", "nhói ngực", "thắt ngực", "đè ngực"],
    "breathing": ["khó thở", "thở hổng được", "thở không được", "thở hổng nổi", "thở không nổi",
                  "thở hổng ra hơi", "ngộp thở", "hụt hơi"],
    "fall": ["bị té", "té ngã", "té xuống", "té nhào", "té cầu thang", "té trong nhà tắm", "té", "bị ngã",
             "ngã", "trượt chân", "hổng đứng dậy được", "không đứng dậy được", "không ngồi dậy được"],
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


@dataclass
class EmergencyHit:
    category: str
    keyword: str
    quote: str

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


def spot(text: str) -> EmergencyHit | None:
    """Return the first emergency hit in an elder utterance, or None."""
    if not text or not text.strip():
        return None
    norm = normalize(text)
    accented = has_vietnamese_diacritics(text)
    if accented:
        lexicon = EMERGENCY_LEXICON
        exclusions = EXCLUSIONS
        hyper = HYPERBOLE_BEFORE_MUON_CHET
        negators = NEGATORS
        muon_chet = "muốn chết"
        hay = norm
    else:
        # accent-free fallback: only multi-word phrases (single syllables are too ambiguous without tones)
        lexicon = {c: [strip_diacritics(p) for p in ps if " " in p] for c, ps in EMERGENCY_LEXICON.items()}
        exclusions = [strip_diacritics(e) for e in EXCLUSIONS]
        hyper = {strip_diacritics(w) for w in HYPERBOLE_BEFORE_MUON_CHET}
        negators = {strip_diacritics(w) for w in NEGATORS}
        muon_chet = "muon chet"
        hay = strip_diacritics(norm)

    # Longest phrases first so "té xỉu" wins over "té".
    candidates = sorted(((c, p) for c, ps in lexicon.items() for p in ps), key=lambda cp: -len(cp[1]))
    for category, phrase in candidates:
        for start in find_phrase(hay, phrase):
            if _excluded(hay, start, phrase, exclusions):
                continue
            prefix = hay[:start].split()
            starts_with_neg = phrase.split()[0] in negators
            if not starts_with_neg and (_negated(prefix) if accented else
                                        bool(prefix) and prefix[-1] in negators):
                continue
            if phrase == muon_chet and prefix and prefix[-1] in hyper:
                continue
            return EmergencyHit(category=category, keyword=phrase, quote=text.strip())
    return None


def emergency_reply(category: str, honorific: str = "bà", family_name: str | None = None) -> str:
    """Calm, short instruction. Never diagnoses."""
    fam = f"cô {family_name}" if family_name else "người nhà"
    h = honorific
    if category == "self_harm":
        return (f"Dạ, con nghe {h} nói rồi, con thương {h} lắm. Con đang báo {fam} gọi {h} liền. "
                f"Nếu {h} thấy nguy, {h} gọi 115 hoặc kêu hàng xóm giùm con nha {h}.")
    return (f"Dạ {h} ơi, {h} bình tĩnh nha. {h.capitalize()} gọi ngay 115 hoặc kêu người gần nhà giúp liền nghen. "
            f"Con đang báo cho {fam} biết rồi.")


# Layer 2: tool exposed to ClaudeEngine.
FLAG_EMERGENCY_TOOL = {
    "name": "flag_emergency",
    "description": (
        "Call this immediately if the elder describes a possible medical emergency or risk of self-harm "
        "(chest pain/pressure, trouble breathing, a fall, fainting, stroke signs such as a drooping mouth or "
        "slurred speech or one-sided weakness, seizure, heavy bleeding, or wanting to die). The system will "
        "tell the elder to call 115 and notify the family. Do not use it for mild, everyday aches."
    ),
    "strict": True,
    "input_schema": {
        "type": "object",
        "properties": {
            "category": {"type": "string", "enum": sorted(EMERGENCY_LEXICON.keys()) + ["other"]},
            "quote": {"type": "string", "description": "The elder's words, verbatim."},
        },
        "required": ["category", "quote"],
        "additionalProperties": False,
    },
}
