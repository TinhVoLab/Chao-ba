"""Scripted *elder* side for hands-free demos and tests (clearly simulated; never mixed into real data silently).

`next_elder_line(state)` looks at what the agent just asked (state.step / last agent turn) and returns a natural
Southern-Vietnamese answer. For recall it first fails free recall, then succeeds after the cue, so the demo shows
the cue path and a recall score of 1.
"""
from __future__ import annotations

import hashlib
import random

from .orchestrator import CallState
from .textnorm import normalize, contains_phrase

LINES = {
    "consent": ["Dạ rảnh chớ con, bà đang ngồi uống trà ngoài hiên nè.", "Ừ, được con, nói chuyện chút cho vui."],
    "sleep": ["Đêm qua ngủ cũng được con, ờ, tới gần sáng có thức dậy một lần đi vệ sinh rồi ngủ lại.",
              "Cũng ngủ được con, mà nửa đêm nghe tiếng chó sủa ờ thức dậy một hồi mới ngủ lại."],
    "food": ["Sáng nay ăn cháo trắng với hột vịt muối, con Lan gửi về đó con, ăn cũng ngon miệng.",
             "Bữa nay ăn bánh mì với ly sữa đậu nành, ăn hết luôn đó con."],
    "feel": ["Trong người cũng khỏe con, chỉ có hơi mỏi cái lưng chút xíu, mà hổng sao.",
             "Hôm nay thấy khỏe re con, sáng ra vườn tưới mấy cây kiểng rồi."],
    "recall_free": ["Ờ... để coi... chuyện gì ta... ờ, quên mất tiêu rồi con ơi.",
                    "À... ờ... cái đó... nhớ hổng ra con."],
    "story": ["Hồi nhỏ ở quê, chiều nào cũng theo mấy đứa trong xóm ra ruộng bắt cá lia thia, tối về bị má rầy quá trời, "
              "mà bữa sau cũng đi nữa à con.",
              "Hồi đó nhà nghèo lắm con, ờ, mùa nước nổi thì cả xóm đi giăng lưới bắt cá linh, nấu canh chua bông điên điển, "
              "ăn với cơm nóng ngon hết biết.",
              "Chủ nhật này con Lan về thăm, bà tính nấu nồi canh chua cá lóc với kho tộ cho nó ăn, "
              "tại hồi nhỏ nó mê món đó lắm con.",
              "Ông nhà hồi xưa ổng hát vọng cổ hay lắm, đám cưới trong xóm ai cũng mời ổng hát, "
              "có bữa hát tới khuya mới về."],
    "closing": ["Ừ, bà nhớ rồi. Cảm ơn con nha, chào con.", "Ờ, chào con, mai nói chuyện tiếp nghen."],
}


def _pick(opts: list[str], seed: str) -> str:
    return random.Random(int(hashlib.sha256(seed.encode()).hexdigest()[:10], 16)).choice(opts)


def _adapt(text: str, honorific: str) -> str:
    if honorific == "ông":
        text = text.replace("bà ", "tui ").replace("Bà ", "Tui ").replace("con Lan", "thằng Khoa") \
                   .replace("Ông nhà", "Bà nhà").replace("ổng", "bả")
    return text


def next_elder_line(state: CallState) -> dict:
    """{"text": str, "pauses": [sec,...]} - pauses are synthetic VAD gaps for the simulated utterance."""
    h = state.ev.honorific
    seed = f"{state.call_id}:{len(state.turns)}"
    last_agent = next((t.text for t in reversed(state.turns) if t.speaker == "agent"), "")
    n = normalize(last_agent)
    if state.phase == "greeting":
        key = "consent"
    elif state.step == "recall_free":
        key = "recall_free"
    elif state.step == "recall_cue" and state.ctx.recall:
        fact = state.ctx.recall.fact_vi.rstrip(".")
        line = f"À, nhớ rồi! {fact[:1].upper() + fact[1:]} đó con, đúng hông?"
        return {"text": _adapt(line, h), "pauses": [0.6, 0.9], "simulated": True}
    elif state.step == "closing" or state.phase == "closing":
        key = "closing"
    elif state.step in ("ask_sleep", "ask_food", "ask_feel"):
        key = state.step[4:]
    elif contains_phrase(n, "ngủ"):
        key = "sleep"
    else:
        key = "story"
    opts = LINES[key]
    if key == "story":
        used = {t.text for t in state.turns if t.speaker == "elder"}
        opts = [o for o in opts if _adapt(o, h) not in used] or opts
    text = _adapt(_pick(opts, seed), h)
    rnd = random.Random(seed)
    pauses = [round(rnd.uniform(0.45, 1.2), 2) for _ in range(max(1, len(text.split()) // 9))]
    return {"text": text, "pauses": pauses, "simulated": True}
