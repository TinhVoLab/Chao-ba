"""Family micro-interactions relayed in the morning call ("Gửi yêu thương", phone-only package).

Adult children send small cards from the family app (a check-in question, a "thương má", a request for the elder's
advice, a caring tip). On the standing screen the elder answers by tapping; on an ordinary phone the morning call
relays the cards that the elder has not seen yet, in one short slot right after the consent answer:

    "Chị Lan gửi thương bà nè. Chị Lan hỏi bà nấu canh chua sao cho ngon, bà chỉ giùm với?"

The elder's next turn is the reply (parsed into a structured choice for check-ins, kept as text for advice), and the
agent confirms "Dạ, con nhắn lại cho chị Lan liền nha." before carrying on with the usual wellbeing questions. A
check-in on eating / sleep / feeling also counts as that wellbeing topic, so the call does not ask it twice.

Pure functions only (no storage); the server builds the items (chaoba/server/kudos.py) and stores the replies.
Structured answers are the elder's self-reports: shown to the family, never scored into the light.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .textnorm import normalize, contains_phrase, word_count

MAX_QUESTIONS = 2          # at most two relay questions per call (the call stays ~4-5 minutes)
MAX_ANNOUNCE = 2           # at most two one-way cards announced ("Lan gửi thương bà nè")


@dataclass
class RelayItem:
    id: int
    kind: str                       # checkin | love | advice | care_tip | message
    template_id: str | None
    sender: str                     # "Lan"
    sender_ref: str                 # how Út Thương names the sender: "chị Lan", "cháu Vy", "bà Tư"
    spoken_vi: str                  # the card as Út Thương says it (question or announcement), no honorific slots
    choices: list[dict] = field(default_factory=list)   # [{id, vi, en}] for check-ins
    topic: str | None = None        # wellbeing topic a check-in covers: food | sleep | feel | None

    @property
    def asks(self) -> bool:
        """Does this card wait for an answer (a question), or is it one-way (announced)?"""
        return self.kind in ("checkin", "advice")


def plan(items: list[RelayItem]) -> tuple[list[RelayItem], list[RelayItem]]:
    """(questions, announcements) for one call: advice first (it makes the elder feel valued), then check-ins."""
    qs = sorted([i for i in items if i.asks], key=lambda i: (i.kind != "advice", i.id))[:MAX_QUESTIONS]
    ann = [i for i in items if not i.asks][:MAX_ANNOUNCE]
    return qs, ann


def _cap(s: str) -> str:
    return s[:1].upper() + s[1:] if s else s


def _join(names: list[str]) -> str:
    names = list(dict.fromkeys(names))
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " với " + names[-1]


def announce_text(ann: list[RelayItem], h: str) -> str:
    """One sentence for the one-way cards: "Chị Lan với anh Minh gửi thương bà nè. Cháu Vy dặn bà nhớ uống nước nha." """
    parts: list[str] = []
    loves = [a for a in ann if a.kind == "love"]
    if loves:
        parts.append(f"{_cap(_join([a.sender_ref for a in loves]))} gửi thương {h} nè.")
    for a in ann:
        if a.kind != "love":
            parts.append(a.spoken_vi.format(s=_cap(a.sender_ref), h=h).strip())
    return " ".join(parts)


def question_text(q: RelayItem, h: str) -> str:
    return q.spoken_vi.format(s=_cap(q.sender_ref), h=h).strip()


def first_text(questions: list[RelayItem], ann: list[RelayItem], h: str) -> str:
    """The first relay line: announcements, then the first question (or "nhắn gì lại hông" if there is none)."""
    lead = announce_text(ann, h)
    if questions:
        q = questions[0]
        if not ann:
            lead = f"{_cap(q.sender_ref)} gửi thương {h} nè."
        return f"{lead} {question_text(q, h)}".strip()
    who = _join([a.sender_ref for a in ann])
    return f"{lead} {_cap(h)} có muốn nhắn gì lại cho {who} hông {h}?".strip()


def ack_text(item: RelayItem | None, answer: dict, h: str, ann: list[RelayItem] | None = None) -> str:
    """Confirmation after the elder answered a relay question."""
    who = item.sender_ref if item else _join([a.sender_ref for a in ann or []]) or "nhà mình"
    if answer.get("choice") == "call_back":
        return f"Dạ, để con nhắn {who} gọi {h} nghe {h} nói nha."
    if answer.get("declined"):
        return "Dạ, hổng sao đâu."
    if item is not None and item.kind == "advice":
        return f"Dạ, {h} chỉ kỹ quá, con nhắn lại cho {who} liền nha."
    return f"Dạ, con nhắn lại cho {who} liền nha."


# ------------------------------------------------------------------------------------- answer parsing
# Check-in answers -> one of the card's structured choices. Order matters: negated / specific phrases first.
CHOICE_RULES: dict[str, list[tuple[str, list[str]]]] = {
    "ate": [("not_yet", ["chưa ăn", "hổng ăn", "không ăn", "hông ăn", "ăn hổng vô", "ăn không vô", "chưa đói",
                         "bỏ bữa"]),
            ("ate", ["ăn rồi", "ăn cơm rồi", "ăn sáng rồi", "ăn cháo", "ăn cơm", "ăn bánh", "ăn no", "ăn được",
                     "ăn hết", "rồi"]),
            ("not_yet", ["chưa"])],
    "slept": [("awake", ["thức nhiều", "thức hoài", "mất ngủ", "thức trắng", "hổng ngủ được", "không ngủ được",
                         "ngủ hổng được", "ngủ không được", "hông ngủ được"]),
              ("meh", ["hơi khó ngủ", "khó ngủ", "trằn trọc", "ngủ ít", "hổng ngon", "không ngon", "hông ngon",
                       "thức dậy", "chập chờn"]),
              ("good", ["ngủ ngon", "ngon", "ngủ được", "thẳng giấc", "ngủ khỏe", "ngủ say"])],
    "feeling": [("tired", ["hơi mệt", "mệt", "đuối", "yếu", "hổng khỏe", "không khỏe", "hông khỏe", "nhức", "đau"]),
                ("ok", ["bình thường", "thường thường", "cũng được", "tàm tạm", "tạm tạm"]),
                ("well", ["khỏe", "khoẻ", "khỏe re", "vui", "ổn"])],
    "meds": [("no", ["chưa uống", "quên uống", "quên", "chưa"]),
             ("yes", ["uống rồi", "rồi", "uống liền", "đã uống"])],
}
CALL_BACK = ["để bà gọi", "để tui gọi", "để má gọi", "để ba gọi", "gọi lại", "gọi cho nó", "nói sau", "để sau",
             "biểu nó gọi", "kêu nó gọi"]
DECLINE = ["thôi khỏi", "hổng cần", "không cần", "khỏi nhắn", "thôi con"]


def parse_choice(template_id: str | None, text: str) -> str | None:
    n = normalize(text)
    for choice, phrases in CHOICE_RULES.get(template_id or "", []):
        if any(contains_phrase(n, p) for p in phrases):
            return choice
    return None


def parse_answer(item: RelayItem | None, text: str) -> dict:
    """{text, choice?, call_back?, declined?} for the elder's answer to a relay line."""
    n = normalize(text)
    out: dict = {"text": (text or "").strip()}
    if not out["text"]:
        out["declined"] = True
        return out
    if item is not None and item.kind == "checkin":
        out["choice"] = parse_choice(item.template_id, text)
        return out
    if item is not None and item.kind == "advice" and word_count(text) <= 14 \
            and any(contains_phrase(n, p) for p in CALL_BACK):
        out["choice"] = "call_back"
        return out
    if item is None and word_count(text) <= 6 and any(contains_phrase(n, p) for p in DECLINE):
        out["declined"] = True
    return out
