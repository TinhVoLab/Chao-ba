"""Sổ ký ức (memory book): the life-story question bank, question selection, and story extraction.

Each call Út Thương asks ONE life-story question in the story phase (after a follow-up hook, if there is one).
After a few exchanges she asks whether she may retell the story to the family ("Bà cho con kể lại chuyện này cho
chị Lan nghe được hông?"). The answer is the per-story consent: stories default to private (``shared=False``).

Only text is kept. No audio is stored; keeping a voice clip would be a future, per-clip opt-in feature.

Selection (``choose_question``): never repeats a question the elder was already asked; prefers the theme used least
(and never the same theme twice in a row); skips sensitive themes (war, hard times) when recent mood is low or the
profile lists them in ``avoid_themes``; adapts wording to the profile (spouse word by honorific, a child's name,
a teacher-specific question when the profile says so).

Extraction (``extract_story``): with ANTHROPIC_API_KEY, Claude Opus 5.5 with a JSON schema (title, retelling in the
elder's voice VI + EN translation, people, places, era); otherwise a transparent rule-based fallback that keeps the
elder's own sentences (fillers removed), finds people / places / era with small lexicons, and writes an English
gist (no machine translation without the LLM; ``translation: "gist"``).
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import random
import re
from dataclasses import dataclass, field, asdict
from datetime import date as Date

from .persona import family_ref
from .textnorm import normalize, contains_phrase, sentences, word_count

log = logging.getLogger("chaoba.lifestory")

STORY_MODEL = "claude-opus-5-5"

THEMES: dict[str, tuple[str, str]] = {
    "childhood": ("Tuổi thơ", "Childhood"),
    "hometown": ("Quê nhà", "Hometown"),
    "food": ("Món ăn xưa", "Food and cooking"),
    "work": ("Công việc hồi trẻ", "Working life"),
    "love": ("Chuyện tình", "Love and marriage"),
    "wedding": ("Đám cưới", "The wedding"),
    "family": ("Nuôi con", "Raising a family"),
    "festivals": ("Tết và lễ hội", "Tết and festivals"),
    "hardship": ("Thời gian khó", "Hard times"),
    "friends": ("Bạn bè, xóm giềng", "Friends and neighbours"),
}
THEME_ORDER = list(THEMES)


@dataclass
class LifeQuestion:
    id: str
    theme: str
    era_hint: str                 # childhood | youth | adult | 1975 | 1976-1986 | wartime
    question_vi: str              # template: {h} honorific, {H} capitalised, {sp} spouse, {child} a child, {newly}
    follow_up_vi: str
    title_vi: str
    title_en: str
    sensitive: bool = False
    requires: str | None = None   # profile tag that must be present (e.g. "teacher")


@dataclass
class ChosenQuestion:
    """A bank question rendered for one elder."""
    id: str
    theme: str
    era_hint: str
    question_vi: str
    follow_up_vi: str
    title_vi: str
    title_en: str
    sensitive: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


Q = LifeQuestion
QUESTION_BANK: list[LifeQuestion] = [
    # childhood
    Q("c1", "childhood", "childhood", "Hồi nhỏ {h} hay chơi trò gì với mấy đứa trong xóm vậy {h}?",
      "Hồi đó ai chơi thân với {h} nhất vậy {h}?", "Trò chơi tuổi nhỏ", "Childhood games"),
    Q("c2", "childhood", "childhood", "Hồi nhỏ {h} có đi học hông, trường của {h} ra sao {h}?",
      "{H} còn nhớ thầy cô nào hông {h}?", "Những ngày đi học", "School days"),
    Q("c3", "childhood", "childhood", "Hồi nhỏ má của {h} hay dạy {h} điều gì vậy {h}?",
      "Bây giờ nhớ lại {h} thấy lời đó đúng hông {h}?", "Lời má dạy", "What my mother taught me"),
    Q("c4", "childhood", "childhood", "Hồi nhỏ {h} có bị ba má rầy vì chuyện gì vui hông {h}?",
      "Rồi lần đó {h} có chừa hông {h}?", "Một lần bị rầy", "The time I got scolded"),
    # hometown
    Q("h1", "hometown", "childhood", "Quê của {h} hồi xưa ra sao, nhà cửa vườn tược thế nào {h}?",
      "Trong vườn hồi đó có cây gì {h} thích nhất?", "Ngôi nhà ở quê", "The house back home"),
    Q("h2", "hometown", "youth", "Hồi xưa ở quê mình đi lại bằng gì vậy {h}, xuồng hay xe đạp?",
      "Có chuyến đi nào {h} nhớ hoài hông {h}?", "Đi lại ngày xưa", "Getting around in the old days"),
    Q("h3", "hometown", "childhood", "Mùa nước nổi hồi xưa ở quê {h} làm gì vậy {h}?",
      "Mùa đó nhà mình hay ăn món gì vậy {h}?", "Mùa nước nổi", "Flood season"),
    Q("h4", "hometown", "youth", "Cái chợ quê hồi xưa {h} hay đi ra sao, kể con nghe với?",
      "Hồi đó đi chợ {h} hay mua món gì vậy {h}?", "Chợ quê", "The village market"),
    # food
    Q("f1", "food", "childhood", "Món ăn nào hồi nhỏ {h} nhớ nhất, ai nấu cho {h} ăn vậy?",
      "Món đó nấu sao vậy {h}, chỉ con với?", "Món ăn nhớ đời", "The dish I never forgot"),
    Q("f2", "food", "adult", "Món tủ của {h} là món gì, hồi đó ai dạy {h} nấu vậy?",
      "Nhà mình ai ăn món đó khen nhất vậy {h}?", "Món tủ", "My signature dish"),
    Q("f3", "food", "youth", "Hồi xưa thiếu thốn, nhà mình ăn uống ra sao vậy {h}?",
      "Bữa cơm nào hồi đó làm {h} nhớ nhất?", "Bữa cơm ngày khó", "Meals in lean years"),
    Q("f4", "food", "childhood", "Trái cây nào ở quê {h} thích nhất hồi nhỏ vậy {h}?",
      "Hồi đó {h} có leo cây hái trái hông {h}?", "Trái cây quê nhà", "Fruit from home"),
    # work
    Q("w1", "work", "youth", "Hồi trẻ {h} làm nghề gì vậy {h}, công việc đầu tiên đó?",
      "Hồi đó làm vậy có cực hông {h}?", "Công việc đầu tiên", "My first job"),
    Q("w2", "work", "adult", "Trong đời làm việc, chuyện gì làm {h} tự hào nhất vậy {h}?",
      "Hồi đó ai giúp {h} nhiều nhất vậy {h}?", "Điều tự hào", "What I am proud of"),
    Q("w3", "work", "youth", "Hồi đó {h} có làm ruộng, làm vườn hay buôn bán gì hông {h}?",
      "Một ngày làm việc hồi đó bắt đầu từ mấy giờ vậy {h}?", "Một ngày làm lụng", "A working day"),
    Q("w4", "work", "youth", "Có người thầy hay người chủ nào hồi trẻ {h} nhớ ơn hông {h}?",
      "Người đó dạy {h} điều gì vậy {h}?", "Người nâng đỡ", "Someone who helped me"),
    Q("w5", "work", "youth", "Hồi mới đi dạy, lớp học đầu tiên của {h} ra sao vậy {h}?",
      "Có học trò nào {h} nhớ hoài hông {h}?", "Lớp học đầu tiên", "My first class", requires="teacher"),
    # love
    Q("l1", "love", "youth", "{H} gặp {sp} lần đầu ở đâu vậy {h}, kể con nghe với?",
      "Lúc đó {h} thấy {sp} ra sao vậy {h}?", "Lần đầu gặp nhau", "How we met"),
    Q("l2", "love", "youth", "Hồi đó ai mai mối cho {h} với {sp} vậy {h}?",
      "Ba má hai bên có ưng liền hông {h}?", "Chuyện mai mối", "The matchmaking"),
    Q("l3", "love", "youth", "Hồi mới quen, {sp} có tặng {h} món quà gì hông {h}?",
      "Món quà đó giờ {h} còn giữ hông {h}?", "Món quà đầu tiên", "The first gift"),
    Q("l4", "love", "adult", "Sống với nhau lâu vậy, kỷ niệm nào với {sp} {h} nhớ nhất?",
      "Hồi đó hai người hay đi đâu chơi vậy {h}?", "Kỷ niệm vợ chồng", "Memories of us"),
    # wedding
    Q("d1", "wedding", "youth", "Đám cưới của {h} hồi xưa tổ chức ở đâu vậy {h}?",
      "Bữa đó có món gì ngon hông {h}?", "Ngày cưới", "Our wedding day"),
    Q("d2", "wedding", "youth", "Ngày cưới {h} mặc đồ gì vậy {h}, ai may cho {h}?",
      "Bữa đó {h} có hồi hộp hông {h}?", "Đồ cưới", "What I wore that day"),
    Q("d3", "wedding", "youth", "Đám cưới hồi xưa ở quê có tục lệ gì vui hông {h}?",
      "Giờ so với hồi đó {h} thấy khác nhiều hông {h}?", "Phong tục cưới xưa", "Old wedding customs"),
    Q("d4", "wedding", "youth", "Hồi {newly}, {h} có bỡ ngỡ gì hông {h}?",
      "Ai trong nhà thương {h} nhất hồi đó vậy {h}?", "Những ngày mới cưới", "Newly married"),
    # family
    Q("p1", "family", "adult", "Hồi {child} mới sinh, nhà mình ra sao vậy {h}?",
      "Hồi nhỏ {child} có lì hông {h}?", "Đứa con đầu lòng", "When my first child was born"),
    Q("p2", "family", "adult", "Nuôi con hồi xưa cực lắm hông {h}, {h} lo cho tụi nhỏ sao?",
      "Có lúc nào {h} thấy vui nhất hông {h}?", "Nuôi con ngày xưa", "Raising children back then"),
    Q("p3", "family", "adult", "Hồi đó {h} hay kể chuyện gì cho con nghe trước khi ngủ?",
      "Chuyện đó ai kể cho {h} nghe vậy {h}?", "Chuyện kể trước giờ ngủ", "Bedtime stories"),
    Q("p4", "family", "adult", "Có lần nào con cháu làm {h} cảm động nhất hông {h}?",
      "Lúc đó {h} nói gì với tụi nhỏ vậy {h}?", "Lúc cảm động", "A moment that moved me"),
    # festivals
    Q("t1", "festivals", "childhood", "Tết hồi xưa nhà mình chuẩn bị những gì vậy {h}?",
      "Tết đó {h} thích nhất cái gì vậy {h}?", "Tết xưa", "Tết in the old days"),
    Q("t2", "festivals", "childhood", "Hồi nhỏ Tết {h} được lì xì hay mặc đồ mới hông {h}?",
      "Bộ đồ Tết đó màu gì vậy {h}?", "Đồ mới ngày Tết", "New clothes for Tết"),
    Q("t3", "festivals", "childhood", "Trung thu hồi xưa ở quê có rước đèn hông {h}?",
      "Lồng đèn hồi đó ai làm cho {h} vậy?", "Trung thu ngày nhỏ", "Mid-Autumn as a child"),
    Q("t4", "festivals", "adult", "Đám giỗ trong nhà hồi xưa đông vui ra sao vậy {h}?",
      "Bữa giỗ đó {h} hay lo món gì vậy {h}?", "Ngày giỗ trong nhà", "Remembrance days"),
    # hard times (sensitive: skipped when mood has been low; always invited gently)
    Q("k1", "hardship", "adult", "Hồi khó khăn nhất, điều gì giúp {h} vượt qua vậy {h}?",
      "Hồi đó ai ở bên {h} vậy {h}?", "Vượt qua ngày khó", "Getting through hard times", sensitive=True),
    Q("k2", "hardship", "wartime", "Hồi chiến tranh nhà mình sống sao, {h} kể chuyện nhẹ nhàng thôi nha?",
      "Có ai giúp đỡ nhà mình hồi đó hông {h}?", "Những năm chiến tranh", "The war years", sensitive=True),
    Q("k3", "hardship", "1975", "Năm 1975 {h} đang ở đâu, làm gì vậy {h}?",
      "Hồi đó {h} có lo lắng gì hông {h}?", "Năm 1975", "The year 1975", sensitive=True),
    Q("k4", "hardship", "1976-1986", "Hồi bao cấp, xếp hàng mua gạo mua đường {h} nhớ hông {h}?",
      "Hồi đó nhà mình xoay xở sao vậy {h}?", "Thời bao cấp", "The ration years", sensitive=True),
    # friends and neighbours
    Q("b1", "friends", "youth", "Hồi trẻ {h} có người bạn thân nào, giờ còn liên lạc hông {h}?",
      "Hai người hay làm gì chung vậy {h}?", "Người bạn thân", "An old friend"),
    Q("b2", "friends", "childhood", "Xóm mình hồi xưa ai vui tính nhất vậy {h}?",
      "Người đó hay làm gì cho cả xóm cười vậy {h}?", "Người trong xóm", "The neighbours"),
    Q("b3", "friends", "youth", "Hồi xưa xóm mình có đờn ca tài tử hay hát hò gì hông {h}?",
      "{H} có thuộc bài nào hông, bài gì vậy {h}?", "Đờn ca trong xóm", "Music in the village"),
    Q("b4", "friends", "adult", "Có lần nào {h} giúp người khác mà nhớ hoài hông {h}?",
      "Người đó giờ ra sao rồi {h}?", "Một lần giúp người", "A time I helped someone"),
]
BANK_BY_ID = {q.id: q for q in QUESTION_BANK}


# --------------------------------------------------------------------------------------------- profile adaptation
def profile_tags(profile: dict) -> set[str]:
    tags: set[str] = set()
    text = normalize(" ".join(list(profile.get("memory_facts") or []) + [str(profile.get("occupation") or "")]))
    if any(contains_phrase(text, w) for w in ("dạy", "giáo viên", "thầy giáo", "cô giáo", "teacher")):
        tags.add("teacher")
    return tags


def _child(profile: dict) -> dict | None:
    fam = profile.get("family") or []
    return next((f for f in fam if (f.get("relation") or "") in ("daughter", "son", "child")), None)


def render(q: LifeQuestion, profile: dict) -> ChosenQuestion:
    h = (profile.get("honorific") or "bà").lower()
    sp = "ông nhà" if h == "bà" else "bà nhà"
    child = _child(profile)
    child_ref = family_ref(child) if child else "đứa con đầu"
    newly = "mới về làm dâu" if h == "bà" else "mới lập gia đình"
    fmt = dict(h=h, H=h.capitalize(), sp=sp, child=child_ref, newly=newly)

    def f(s: str) -> str:
        out = s.format(**fmt)
        return out[:1].upper() + out[1:]
    return ChosenQuestion(id=q.id, theme=q.theme, era_hint=q.era_hint, question_vi=f(q.question_vi),
                          follow_up_vi=f(q.follow_up_vi), title_vi=q.title_vi, title_en=q.title_en,
                          sensitive=q.sensitive)


def _rng(*parts) -> random.Random:
    return random.Random(int(hashlib.sha256(":".join(map(str, parts)).encode()).hexdigest()[:12], 16))


def choose_question(profile: dict, asked: list[str], recent_moods: list[float] | None = None,
                    day: int | None = None, last_theme: str | None = None) -> ChosenQuestion | None:
    """Next life-story question for this elder.

    ``asked``: ids already asked, oldest first (never repeated while unasked questions remain; once the bank is
    exhausted the least recently asked come back). ``recent_moods``: last few mood scores (1..5); sensitive themes are
    skipped when their mean is below 3. Deterministic for (elder, day)."""
    tags = profile_tags(profile)
    avoid = set(profile.get("avoid_themes") or [])
    low_mood = bool(recent_moods) and sum(recent_moods) / len(recent_moods) < 3.0
    eligible = [q for q in QUESTION_BANK
                if (q.requires is None or q.requires in tags) and q.theme not in avoid
                and not (q.sensitive and low_mood)]
    if not eligible:
        return None
    asked_set = set(asked)
    fresh = [q for q in eligible if q.id not in asked_set]
    if not fresh:   # bank exhausted: cycle back to the least recently asked
        order = {qid: i for i, qid in enumerate(asked)}
        oldest = min(eligible, key=lambda q: order.get(q.id, -1))
        return render(oldest, profile)
    theme_count = {t: 0 for t in THEMES}
    for qid in asked:
        if qid in BANK_BY_ID:
            theme_count[BANK_BY_ID[qid].theme] += 1
    if last_theme is None and asked and asked[-1] in BANK_BY_ID:
        last_theme = BANK_BY_ID[asked[-1]].theme
    themes = sorted({q.theme for q in fresh}, key=lambda t: (t == last_theme, theme_count[t], THEME_ORDER.index(t)))
    theme = themes[0]
    pool = [q for q in fresh if q.theme == theme]
    preferred = [q for q in pool if q.requires and q.requires in tags]   # profile-specific questions first
    rnd = _rng(profile.get("id", "?"), day, len(asked))
    return render(preferred[0] if preferred else rnd.choice(pool), profile)


# --------------------------------------------------------------------------------------------- per-story consent
SHARE_NO = ["giữ riêng", "đừng kể", "khỏi kể", "thôi khỏi", "hổng cần kể", "không cần kể", "đừng nói", "để riêng",
            "chuyện riêng", "hổng được", "không được", "hông được", "đừng con", "thôi con"]
SHARE_UNSURE = ["để coi", "để bà coi", "để tui coi", "coi lại", "chưa biết", "suy nghĩ", "tính sau", "để sau", "từ từ"]
SHARE_YES = ["kể đi", "kể cho", "được chớ", "được con", "ừ được", "dạ được", "cho nó nghe", "kể nó nghe", "nói nó nghe",
             "được mà", "ừ kể", "kể giùm"]


def share_question(profile: dict) -> str:
    h = (profile.get("honorific") or "bà").lower()
    fam = profile.get("family") or []
    primary = next((f for f in fam if f.get("role") == "primary"), fam[0] if fam else None)
    who = family_ref(primary) or "gia đình"
    return f"Chuyện hay quá. {h.capitalize()} cho con kể lại chuyện này cho {who} nghe được hông {h}?"


def parse_share_answer(text: str) -> str:
    """yes | no | unclear. Anything unclear keeps the story private."""
    from .guardrails import is_yes, is_no
    n = normalize(text)
    if not n:
        return "unclear"
    if any(contains_phrase(n, p) for p in SHARE_NO):
        return "no"
    if any(contains_phrase(n, p) for p in SHARE_UNSURE):
        return "unclear"
    if any(contains_phrase(n, p) for p in SHARE_YES):
        return "yes"
    if is_no(text):
        return "no"
    if is_yes(text):
        return "yes"
    return "unclear"


def share_ack(answer: str, profile: dict) -> str:
    h = (profile.get("honorific") or "bà").lower()
    fam = profile.get("family") or []
    primary = next((f for f in fam if f.get("role") == "primary"), fam[0] if fam else None)
    who = family_ref(primary) or "gia đình"
    if answer == "yes":
        return f"Dạ, con sẽ kể {who} nghe."
    return f"Dạ, con giữ riêng cho {h} nha."


# --------------------------------------------------------------------------------------------- extraction
CLOSERS = ["kể hoài hổng hết", "kể hoài không hết", "có vậy thôi", "chỉ vậy thôi", "hổng nhớ nữa", "không nhớ nữa",
           "nhớ hổng ra", "quên mất rồi"]
FILLERS = ("ờ", "à", "ừ", "ừm", "ừa", "dạ", "thì", "ơ", "hmm", "ủa")
PEOPLE_LEX: list[tuple[str, str]] = [
    ("ông nội", "paternal grandfather"), ("bà nội", "paternal grandmother"), ("ông ngoại", "maternal grandfather"),
    ("bà ngoại", "maternal grandmother"), ("ông nhà", "her husband"), ("bà nhà", "his wife"), ("má", "mother"),
    ("mẹ", "mother"), ("ba", "father"), ("tía", "father"), ("anh hai", "eldest brother"), ("chị hai", "eldest sister"),
    ("thầy giáo", "a teacher"), ("cô giáo", "a teacher"), ("học trò", "students"), ("bạn thân", "a close friend"),
    ("hàng xóm", "neighbours"), ("bà mai", "the matchmaker"), ("ông mai", "the matchmaker"),
    ("con gái", "daughter"), ("con trai", "son"), ("cháu", "grandchildren"), ("mấy đứa trong xóm", "village children"),
]
PLACE_LEX = ["Bến Tre", "Cần Thơ", "Sài Gòn", "Chợ Lớn", "Mỹ Tho", "Vĩnh Long", "Trà Vinh", "Long An", "Hà Nội", "Huế",
             "Đà Lạt", "Châu Đốc", "Cà Mau", "Sóc Trăng", "Bạc Liêu", "Rạch Giá", "An Giang", "Đồng Tháp", "Tiền Giang",
             "Cái Răng", "Cái Bè", "Cù lao Minh", "Mỏ Cày", "Gò Công", "Thủ Đức", "Biên Hòa", "Vũng Tàu"]
PLACE_RE = re.compile(r"\b(?:chợ|sông|xã|làng|ấp|chùa|trường|vàm|kênh|rạch|cồn|đình|bến)\s+((?:[A-ZĐÀ-Ỹ][\wÀ-ỹ]*)"
                      r"(?:\s+[A-ZĐÀ-Ỹ][\wÀ-ỹ]*){0,2})")
NAME_RE = re.compile(r"\b(?:con|thằng|chị|anh|cô|chú|ông|bà|thầy|dì|cậu|bạn)\s+([A-ZĐ][a-zà-ỹđ]+)\b")
_NOT_NAMES = {"Tết", "Trời", "Phật", "Út"}


def _clean_sentence(s: str) -> str:
    s = s.replace("…", " ").replace("...", " ")
    words = s.split()
    while words and normalize(words[0]).strip(",.!?") in FILLERS:
        words.pop(0)
    out = " ".join(words).strip(" ,")
    out = re.sub(r"\s*,\s*(con|con ơi|nha con|đó con|à con)([.!?]?)$", r"\2", out)
    out = re.sub(r"\s+(con|con ơi|nha con|đó con|à con)([.!?]?)$", r"\2", out)
    out = re.sub(r"\b(cái|thì|là|ờ|à|mà)(?:,?\s+\1\b)+", r"\1", out)   # "cái cái" stammer (not "từ từ")
    out = re.sub(r"\s+(ờ|à|ừm),?\s+", " ", out)
    if out and out[-1] not in ".!?":
        out += "."
    return out[:1].upper() + out[1:] if out else out


def _people(text: str, profile: dict) -> list[dict]:
    n = normalize(text)
    out: list[dict] = []
    seen: set[str] = set()
    h = (profile.get("honorific") or "bà").lower()
    for vi, en in PEOPLE_LEX:
        if vi == "ba" and not re.search(r"\b(ba má|ba mẹ|ba tui|ba của|ba dạy|ba rầy|ba nói)\b", n):
            continue                                   # "ba" is also the number three
        if contains_phrase(n, vi) and vi not in seen:
            if vi == "ông nhà" and h != "bà" or vi == "bà nhà" and h != "ông":
                continue
            seen.add(vi)
            out.append({"vi": vi, "en": en})
    for m in NAME_RE.finditer(text):
        name = m.group(1)
        if name in _NOT_NAMES or any(p in name for p in PLACE_LEX):
            continue
        full = m.group(0)
        if normalize(full) not in seen:
            seen.add(normalize(full))
            out.append({"vi": full[:1].lower() + full[1:], "en": name})
    return out[:6]


def _places(text: str) -> list[str]:
    out: list[str] = []
    for p in PLACE_LEX:
        if p in text and p not in out:
            out.append(p)
    for m in PLACE_RE.finditer(text):
        full = m.group(0)
        if full not in out and not any(full in o or o in full for o in out):
            out.append(full)
    return out[:5]


def era_of(text: str, era_hint: str, age: int | None, today: Date | None = None) -> dict:
    """{label_vi, label_en, decade}: explicit years / events in the text win over the question's era hint."""
    n = normalize(text)
    m = re.search(r"\b(19[3-9]\d|20[0-2]\d)\b", text)
    if m:
        y = int(m.group(1))
        return {"label_vi": f"Năm {y}", "label_en": str(y), "decade": y // 10 * 10}
    if contains_phrase(n, "giải phóng") or contains_phrase(n, "năm bảy lăm") or era_hint == "1975":
        return {"label_vi": "Năm 1975", "label_en": "1975", "decade": 1970}
    if contains_phrase(n, "bao cấp") or era_hint == "1976-1986":
        return {"label_vi": "Thời bao cấp (1976–1986)", "label_en": "The subsidy years (1976–1986)", "decade": 1980}
    if contains_phrase(n, "chiến tranh") or era_hint == "wartime":
        return {"label_vi": "Thời chiến tranh", "label_en": "The war years", "decade": 1960}
    born = ((today or Date.today()).year - int(age)) if age else None
    if contains_phrase(n, "hồi nhỏ") or era_hint == "childhood":
        d = (born + 8) // 10 * 10 if born else None
        return {"label_vi": f"Tuổi nhỏ{f' (thập niên {d})' if d else ''}",
                "label_en": f"Childhood{f' ({d}s)' if d else ''}", "decade": d}
    if contains_phrase(n, "hồi trẻ") or contains_phrase(n, "mới cưới") or era_hint == "youth":
        d = (born + 20) // 10 * 10 if born else None
        return {"label_vi": f"Tuổi trẻ{f' (thập niên {d})' if d else ''}",
                "label_en": f"Young adulthood{f' ({d}s)' if d else ''}", "decade": d}
    d = (born + 32) // 10 * 10 if born else None
    return {"label_vi": f"Những năm lập nghiệp{f' (thập niên {d})' if d else ''}",
            "label_en": f"Adult years{f' ({d}s)' if d else ''}", "decade": d}


def _gist_en(name_en: str, title_en: str, people: list[dict], places: list[str], era: dict) -> str:
    bits = [f"{name_en} told a story about “{title_en.lower()}”"]
    if era.get("label_en"):
        bits[0] += f", from {era['label_en'][:1].lower() + era['label_en'][1:]}"
    s = bits[0] + "."
    if people:
        s += " People mentioned: " + ", ".join(p["en"] for p in people) + "."
    if places:
        s += " Places: " + ", ".join(places) + "."
    return s + " (English gist; a full translation is written when the language model is enabled.)"


def extract_story_rule_based(question: ChosenQuestion | dict, elder_texts: list[str], profile: dict,
                             today: Date | None = None) -> dict | None:
    """Story entry from the elder's story-phase answers, or None when there is too little to retell
    (fewer than ~12 words of narrative)."""
    q = question if isinstance(question, dict) else question.to_dict()
    sents: list[str] = []
    for t in elder_texts:
        for s in sentences(t):
            c = _clean_sentence(s)
            n = normalize(c)
            if any(contains_phrase(n, x) for x in CLOSERS) or n.startswith(("vậy đó", "có vậy", "hết rồi")):
                continue                      # "vậy đó con, chuyện xưa kể hoài hổng hết": a closer, not the story
            if word_count(c) >= 4 and c not in sents:
                sents.append(c)
    if not sents or sum(word_count(s) for s in sents) < 12:
        return None
    kept = sents[:5]
    while len(kept) > 2 and sum(word_count(s) for s in kept) > 110:
        kept.pop()
    text_vi = " ".join(kept)
    people = _people(text_vi, profile)
    places = _places(text_vi)
    era = era_of(text_vi, q.get("era_hint", "adult"), profile.get("age"), today)
    name_en = profile.get("name_en") or profile.get("display_name") or "The elder"
    return {"question_id": q.get("id"), "theme": q.get("theme"), "title_vi": q.get("title_vi"),
            "title_en": q.get("title_en"), "text_vi": text_vi,
            "text_en": _gist_en(name_en, q.get("title_en", "a memory"), people, places, era),
            "people": people, "places": places, "era": era, "word_count": word_count(text_vi),
            "translation": "gist", "engine": "rules"}


STORY_SCHEMA = {
    "type": "object",
    "properties": {
        "title_vi": {"type": "string"}, "title_en": {"type": "string"},
        "text_vi": {"type": "string"}, "text_en": {"type": "string"},
        "people": {"type": "array", "items": {"type": "object", "properties": {"vi": {"type": "string"},
                                                                            "en": {"type": "string"}},
                                              "required": ["vi", "en"], "additionalProperties": False}},
        "places": {"type": "array", "items": {"type": "string"}},
        "era_vi": {"type": "string"}, "era_en": {"type": "string"},
        "decade": {"anyOf": [{"type": "integer"}, {"type": "null"}]},
    },
    "required": ["title_vi", "title_en", "text_vi", "text_en", "people", "places", "era_vi", "era_en", "decade"],
    "additionalProperties": False,
}
STORY_INSTRUCTIONS = """You turn an older Vietnamese adult's spoken answers into one short memoir entry for their
family's memory book. Write the retelling in the ELDER'S OWN VOICE (first person, the words they use for themselves,
Southern Vietnamese), 2-5 sentences, keeping only what they actually said: never invent names, places, dates or
feelings. Remove fillers and repetitions. text_en is a faithful English translation of text_vi. title: 2-6 words.
people: people they mentioned (Vietnamese as said + English). places: places they named. era: when it happened
(e.g. "Thập niên 1960" / "1960s"), decade as an integer or null. Never mention health, diagnosis or memory ability."""


def extract_story_with_claude(client, question: ChosenQuestion | dict, elder_texts: list[str], profile: dict,
                              today: Date | None = None) -> dict | None:
    q = question if isinstance(question, dict) else question.to_dict()
    resp = client.beta.messages.create(
        model=STORY_MODEL, max_tokens=1500, betas=["server-side-fallback-2026-07-01"], fallbacks="default",
        system=[{"type": "text", "text": STORY_INSTRUCTIONS, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content":
                   f"Elder: {profile.get('display_name')} ({profile.get('name_en')}), age {profile.get('age')}, "
                   f"refers to self as \"{'tui' if (profile.get('honorific') or 'bà') == 'ông' else 'bà'}\".\n"
                   f"Question asked: {q.get('question_vi')}\nSuggested title: {q.get('title_vi')} / {q.get('title_en')}"
                   f"\n\nElder's answers:\n" + "\n".join(f"- {t}" for t in elder_texts)}],
        output_config={"effort": "medium", "format": {"type": "json_schema", "schema": STORY_SCHEMA}},
        timeout=60.0,
    )
    if getattr(resp, "stop_reason", None) == "refusal":
        raise RuntimeError("story extraction refused")
    d = json.loads(next(b.text for b in resp.content if getattr(b, "type", None) == "text"))
    text_vi = d["text_vi"].strip()
    return {"question_id": q.get("id"), "theme": q.get("theme"), "title_vi": d["title_vi"], "title_en": d["title_en"],
            "text_vi": text_vi, "text_en": d["text_en"].strip(), "people": d.get("people") or [],
            "places": d.get("places") or [],
            "era": {"label_vi": d.get("era_vi") or "", "label_en": d.get("era_en") or "", "decade": d.get("decade")},
            "word_count": word_count(text_vi), "translation": "llm", "engine": "claude"}


def extract_story(question: ChosenQuestion | dict | None, elder_texts: list[str], profile: dict,
                  use_llm: bool | None = None, client=None, today: Date | None = None) -> dict | None:
    """Claude when a key is set (falls back to rules on any error); rules otherwise."""
    if question is None:
        return None
    rb = extract_story_rule_based(question, elder_texts, profile, today)
    if rb is None:
        return None
    if use_llm is None:
        use_llm = bool(os.environ.get("ANTHROPIC_API_KEY"))
    if not use_llm:
        return rb
    try:
        if client is None:
            import anthropic
            client = anthropic.Anthropic()
        return extract_story_with_claude(client, question, elder_texts, profile, today) or rb
    except Exception as e:
        log.warning("Claude story extraction failed (%s); using rules", e)
        return rb
