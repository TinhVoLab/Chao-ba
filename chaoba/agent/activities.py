"""Prevention activities woven into the call: one short memory game and one healthy-habit / social nudge.

Games (closing phase, before the goodbye; skipped when time is short):
  - ``ca_dao``      finish a familiar line of ca dao / tục ngữ (level 1 = the most familiar, 3 = less common)
  - ``naming``      name a few things in a familiar category (fruits, fish, dishes...): 2 / 3 / 4 items by level
  - ``family``      name your children (only if the profile lists any): 1 / 2 / all by level
  Framed as play ("chơi chút cho vui"), never as a test; a miss is answered warmly with the answer, never "sai".

Adaptive difficulty (``next_level``): per elder, from the history of outcomes. A miss lowers the level by one
(min 1); two successes in a row raise it by one (max 3); a partial answer keeps it. So the game gets easier right
after a miss and never feels like an exam.

Nudges (one sentence in the closing): water, morning walk / sunlight, chair exercises, regular sleep, call an old
friend, the elders' association (Hội người cao tuổi). Chosen from the profile goals and recent signals (poor sleep ->
regular sleep; low mood or lives alone -> social), never the same as the last two.

Outcomes are logged per call (server: activity_log) and feed the DMAIC Improve phase: which activities coincided
with better mood / sleep (association, not causation).
"""
from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass, field, asdict

from .persona import family_ref
from .textnorm import normalize, contains_phrase, strip_diacritics, has_vietnamese_diacritics

LEVELS = (1, 2, 3)
START_LEVEL = 2
GAME_KINDS = ("ca_dao", "naming", "family")


@dataclass
class Activity:
    kind: str                     # game | nudge
    id: str                       # item id, e.g. "cd_cong_cha", "nm_fruit_2", "nudge_water"
    category: str                 # game: ca_dao | naming | family; nudge: water | walk_sun | chair | sleep | friend | club
    prompt_vi: str                # what Út Thương says (game question, or the nudge sentence)
    level: int | None = None
    expected: list[list[str]] = field(default_factory=list)   # game: groups of alternative keywords
    need: int = 1                 # game: groups that must be hit for a full success
    answer_vi: str = ""           # game: gentle reveal after a miss
    label_vi: str = ""
    label_en: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


# --------------------------------------------------------------------------------------------- game content
# (id, level, stem said by Út Thương, expected keyword groups, need, full line for the gentle reveal)
CA_DAO = [
    ("cd_cong_cha", 1, "Công cha như núi Thái Sơn", [["nghĩa mẹ"], ["nguồn"]], 2,
     "Nghĩa mẹ như nước trong nguồn chảy ra"),
    ("cd_bau_bi", 1, "Bầu ơi thương lấy bí cùng", [["khác giống"], ["giàn"]], 2,
     "Tuy rằng khác giống nhưng chung một giàn"),
    ("cd_an_qua", 1, "Ăn quả nhớ kẻ", [["trồng cây"]], 1, "Ăn quả nhớ kẻ trồng cây"),
    ("cd_uong_nuoc", 1, "Uống nước nhớ", [["nguồn"]], 1, "Uống nước nhớ nguồn"),
    ("cd_mot_cay", 2, "Một cây làm chẳng nên non", [["ba cây", "chụm"], ["núi cao"]], 2,
     "Ba cây chụm lại nên hòn núi cao"),
    ("cd_nhieu_dieu", 2, "Nhiễu điều phủ lấy giá gương", [["một nước", "trong một"], ["thương nhau"]], 2,
     "Người trong một nước phải thương nhau cùng"),
    ("cd_gio_dua", 2, "Gió đưa cây cải về trời", [["rau răm"], ["đắng cay"]], 2,
     "Rau răm ở lại chịu lời đắng cay"),
    ("cd_thuong_nguoi", 2, "Thương người như thể", [["thương thân"]], 1, "Thương người như thể thương thân"),
    ("cd_vi_dau", 3, "Ví dầu cầu ván đóng đinh", [["cầu tre"], ["gập ghềnh", "lắc lẻo"]], 2,
     "Cầu tre lắc lẻo gập ghềnh khó đi"),
    ("cd_chieu_chieu", 3, "Chiều chiều ra đứng ngõ sau", [["quê mẹ"], ["chín chiều", "ruột đau"]], 2,
     "Trông về quê mẹ ruột đau chín chiều"),
    ("cd_ra_di", 3, "Ra đi anh nhớ quê nhà", [["canh rau muống", "rau muống"], ["cà dầm tương", "dầm tương"]], 2,
     "Nhớ canh rau muống, nhớ cà dầm tương"),
    ("cd_con_co", 3, "Con cò mà đi ăn đêm", [["cành mềm"], ["xuống ao", "lộn cổ"]], 2,
     "Đậu phải cành mềm lộn cổ xuống ao"),
]
NAMING = {
    "fruit": ("trái cây miền Tây", ["xoài", "mận", "chôm chôm", "sầu riêng", "măng cụt", "bưởi", "chuối", "dừa",
                                     "nhãn", "vú sữa", "mít", "ổi", "khóm", "thơm", "đu đủ", "cam", "quýt", "chanh",
                                     "sapoche", "hồng xiêm", "dưa hấu", "mãng cầu", "me", "cóc", "sơ ri", "táo"]),
    "fish": ("loại cá ở sông rạch", ["cá lóc", "cá rô", "cá trê", "cá linh", "cá kèo", "cá tra", "cá basa", "cá chép",
                                      "cá điêu hồng", "cá bống", "cá thát lát", "cá chạch", "lươn", "cá sặc", "cá lia thia",
                                      "cá mè", "cá rô phi", "cá hú", "cá ba sa", "cá chốt"]),
    "dish": ("món ăn ngày Tết", ["bánh tét", "bánh chưng", "thịt kho", "dưa giá", "dưa món", "củ kiệu", "canh khổ qua",
                                  "lạp xưởng", "mứt", "bánh ít", "bánh phồng", "giò", "chả lụa", "nem", "tôm khô",
                                  "khổ qua", "hột vịt", "gỏi"]),
    "flower": ("loại bông trong vườn", ["mai", "cúc", "vạn thọ", "hồng", "lan", "sen", "súng", "bông giấy", "huệ",
                                        "lài", "điên điển", "mười giờ", "trang", "dâm bụt", "bông bụp", "sứ", "đào",
                                        "cẩm chướng", "thược dược", "ngọc lan"]),
}
NAMING_NEED = {1: 2, 2: 3, 3: 4}
FAMILY_NEED = {1: 1, 2: 2, 3: 3}

GAME_PRAISE = {
    "success": ["Dạ đúng rồi, {h} thuộc hay quá!", "Dạ hay quá, {h} nhớ giỏi ghê!", "Dạ trúng y chang, giỏi quá {h}!"],
    "partial": ["Dạ gần trọn rồi đó {h}, hay lắm!", "Dạ được vậy là hay lắm rồi {h}!"],
}

NUDGES = {
    "water": ("Trời nóng, {h} nhớ uống nước đều đều trong ngày nha {h}.", "Uống đủ nước", "Drink enough water"),
    "walk_sun": ("Sáng mai {h} ra sân đi bộ chút, phơi nắng sớm cho khỏe nha.", "Đi bộ, phơi nắng sáng",
                 "Morning walk and sunlight"),
    "chair": ("Lúc rảnh {h} ngồi ghế đưa tay đưa chân chừng mười lần cho dẻo nha.", "Tập tay chân trên ghế",
              "Chair exercises"),
    "sleep": ("Tối nay {h} đi ngủ đúng giờ quen thuộc cho giấc ngủ đều nha.", "Ngủ đúng giờ", "Regular bedtime"),
    "friend": ("Bữa nào rảnh {h} gọi hỏi thăm một người bạn cũ cho vui nha.", "Gọi hỏi thăm bạn cũ",
               "Call an old friend"),
    "club": ("Hội người cao tuổi trong xóm có sinh hoạt, {h} ghé chơi cho vui nha.", "Sinh hoạt hội người cao tuổi",
             "Elders' association"),
}
GAME_LABEL = {"ca_dao": ("Nối câu ca dao", "Finish a folk verse"), "naming": ("Kể tên theo chủ đề", "Name things in a category"),
              "family": ("Kể tên con cháu", "Name family members")}


def _rng(*parts) -> random.Random:
    return random.Random(int(hashlib.sha256(":".join(map(str, parts)).encode()).hexdigest()[:12], 16))


# --------------------------------------------------------------------------------------------- difficulty
def next_level(outcomes: list[str], start: int = START_LEVEL) -> int:
    """Level for the next game from past game outcomes (oldest first): miss -> one level easier; two successes in a
    row -> one level harder; partial -> unchanged."""
    lvl, streak = start, 0
    for o in outcomes:
        if o == "miss":
            lvl, streak = max(LEVELS[0], lvl - 1), 0
        elif o == "success":
            streak += 1
            if streak >= 2:
                lvl, streak = min(LEVELS[-1], lvl + 1), 0
        elif o == "partial":
            streak = 0
    return lvl


def _children(profile: dict) -> list[dict]:
    return [f for f in profile.get("family") or [] if (f.get("relation") or "") in ("daughter", "son", "child")]


def build_game(kind: str, level: int, profile: dict, used_ids: list[str], seed: str = "") -> Activity | None:
    h = (profile.get("honorific") or "bà").lower()
    label_vi, label_en = GAME_LABEL[kind]
    rnd = _rng(profile.get("id"), seed, kind, level)
    if kind == "ca_dao":
        pool = [c for c in CA_DAO if c[1] == level] or [c for c in CA_DAO if c[1] <= level]
        fresh = [c for c in pool if c[0] not in used_ids[-20:]] or pool
        cid, lvl, stem, exp, need, full = rnd.choice(fresh)
        return Activity(kind="game", id=cid, category="ca_dao", level=level, expected=exp, need=need,
                        prompt_vi=f"Mình chơi chút nha {h}: {stem}... {h} nói tiếp giùm con?", answer_vi=full,
                        label_vi=label_vi, label_en=label_en)
    if kind == "naming":
        cats = list(NAMING)
        fresh = [c for c in cats if f"nm_{c}" not in used_ids[-len(cats) + 1:]] or cats
        cat = rnd.choice(fresh)
        what, words = NAMING[cat]
        n = NAMING_NEED[level]
        num = {2: "hai", 3: "ba", 4: "bốn"}[n]
        return Activity(kind="game", id=f"nm_{cat}", category="naming", level=level, expected=[[w] for w in words],
                        need=n, prompt_vi=f"Chơi chút cho vui nha {h}: {h} kể con nghe {num} {what} coi?",
                        answer_vi=", ".join(words[:3]), label_vi=label_vi, label_en=label_en)
    if kind == "family":
        kids = _children(profile)
        if not kids:
            return None
        n = min(FAMILY_NEED[level], len(kids))
        return Activity(kind="game", id=f"fm_{level}", category="family", level=level,
                        expected=[[k["name"]] for k in kids if k.get("name")], need=n,
                        prompt_vi=f"Chơi chút nha {h}: {h} kể con nghe tên mấy người con của {h} coi?",
                        answer_vi=", ".join(family_ref(k) or k["name"] for k in kids),
                        label_vi=label_vi, label_en=label_en)
    return None


def choose_game(profile: dict, history: list[dict], day: int | None = None) -> Activity | None:
    """Pick today's game. ``history``: past game log entries (oldest first) with ``outcome``, ``category``,
    ``activity_id``. Rotates kinds so the same game never comes twice in a row."""
    outcomes = [h["outcome"] for h in history if h.get("outcome") in ("success", "partial", "miss")]
    level = next_level(outcomes)
    used = [h.get("activity_id", "") for h in history]
    kinds = [k for k in GAME_KINDS if k != "family" or _children(profile)]
    last = history[-1]["category"] if history else None
    order = sorted(kinds, key=lambda k: (k == last, sum(1 for x in history[-9:] if x.get("category") == k),
                                         GAME_KINDS.index(k)))
    return build_game(order[0], level, profile, used, seed=str(day))


def plays_game_today(day: int | None) -> bool:
    """Games on two days out of three; the third day keeps the call shorter (nudge only)."""
    return day is None or day % 3 != 0


def _match(text: str, kw: str) -> bool:
    n = normalize(text)
    if contains_phrase(n, normalize(kw)):
        return True
    return not has_vietnamese_diacritics(text) and contains_phrase(strip_diacritics(n), strip_diacritics(normalize(kw)))


def score_game(act: Activity | dict, text: str) -> str:
    """success | partial | miss."""
    a = act if isinstance(act, dict) else act.to_dict()
    if not (text or "").strip():
        return "miss"
    hits = sum(1 for group in a.get("expected") or [] if any(_match(text, k) for k in group))
    if hits >= max(1, a.get("need") or 1):
        return "success"
    return "partial" if hits >= 1 else "miss"


def game_reaction(act: Activity | dict, outcome: str, h: str, seed: str = "") -> str:
    a = act if isinstance(act, dict) else act.to_dict()
    if outcome in GAME_PRAISE:
        return _rng(seed, outcome).choice(GAME_PRAISE[outcome]).format(h=h)
    if a.get("category") == "ca_dao":
        return f"Dạ câu đó là “{a.get('answer_vi')}” đó {h}, con cũng hay quên hoài hà."
    if a.get("category") == "family":
        return f"Dạ, con nhớ có {a.get('answer_vi')} nè {h}, mai mình kể tiếp nha."
    return f"Dạ hổng sao, như {a.get('answer_vi')} đó {h}, mai mình chơi tiếp nha."


# --------------------------------------------------------------------------------------------- nudges
def choose_nudge(profile: dict, recent_nudges: list[str], recent_records: list[dict] | None = None,
                 day: int | None = None, focus: list[str] | None = None) -> Activity:
    """One nudge for the closing. ``focus``: categories from an active care plan (DMAIC Improve) tried first."""
    h = (profile.get("honorific") or "bà").lower()
    recs = recent_records or []
    goals = normalize(" ".join(profile.get("goals") or []))
    cand: list[str] = list(focus or [])
    if any((r.get("symptoms") or {}).get("insomnia") for r in recs[-5:]):
        cand.append("sleep")
    moods = [r["mood"] for r in recs[-5:] if r.get("mood") is not None]
    if moods and sum(moods) / len(moods) < 3.2:
        cand += ["friend", "club"]
    if contains_phrase(goals, "đi bộ"):
        cand.append("walk_sun")
    if contains_phrase(goals, "ngủ"):
        cand.append("sleep")
    if profile.get("lives_alone"):
        cand.append("club")
    rest = [k for k in NUDGES if k not in cand]
    _rng(profile.get("id"), day, "nudge").shuffle(rest)
    cand += rest
    recent = recent_nudges[-2:]
    pick = next((k for k in dict.fromkeys(cand) if k not in recent), cand[0])
    text, vi, en = NUDGES[pick]
    return Activity(kind="nudge", id=f"nudge_{pick}", category=pick, prompt_vi=text.format(h=h), label_vi=vi,
                    label_en=en)


ACTIVITY_LABELS = {**{k: (v[1], v[2]) for k, v in NUDGES.items()}, **GAME_LABEL}
