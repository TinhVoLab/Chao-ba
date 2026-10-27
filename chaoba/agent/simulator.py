"""Scripted *elder* side for hands-free demos and tests (clearly simulated; never mixed into real data silently).

`next_elder_line(state)` looks at what the agent just asked (state.step / last agent turn) and returns a natural
Southern-Vietnamese answer. For recall it first fails free recall, then succeeds after the cue, so the demo shows
the cue path and a recall score of 1.

Timing is calibrated to the persona's own baseline: given the baseline speech rate (syllables / voiced second) and
pause ratio, each line comes with synthetic VAD pauses and a ``duration_sec`` so that a rehearsal call measures close
to the person's usual values (instead of a fixed 3.8 syll/s that turned Bà Hạnh yellow after three rehearsals).
Rehearsal days are also excluded from scoring by the server, so this only keeps the displayed numbers plausible.
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
    "food": ["Sáng nay ăn cháo trắng với hột vịt muối, con Lan gửi về đó con, ăn cũng ngon miệng, "
             "còn uống thêm ly trà nóng nữa.",
             "Bữa nay ăn bánh mì với ly sữa đậu nành, ăn hết luôn đó con, trưa nay tính nấu canh bí với tôm khô."],
    "feel": ["Trong người cũng khỏe con, chỉ có hơi mỏi cái lưng chút xíu, mà hổng sao.",
             "Hôm nay thấy khỏe re con, sáng ra vườn tưới mấy cây kiểng rồi, còn quét cái sân trước nhà nữa."],
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
    "followup": ["Mới mấy bữa nay thôi con, mà đỡ nhiều rồi, hổng sao đâu.",
                 "Cũng lâu lâu mới bị con, nghỉ chút là đỡ hà."],
    "confirm": ["Dạ hổng có đau gì nữa đâu con, khỏe rồi."],
}
DEFAULT_SPS = 3.8           # used only when the persona has no baseline yet
DEFAULT_PAUSE_RATIO = 0.12


def _pick(opts: list[str], seed: str) -> str:
    return random.Random(int(hashlib.sha256(seed.encode()).hexdigest()[:10], 16)).choice(opts)


def _adapt(text: str, honorific: str) -> str:
    if honorific == "ông":
        text = text.replace("bà ", "tui ").replace("Bà ", "Tui ").replace("con Lan", "thằng Khoa") \
                   .replace("Ông nhà", "Bà nhà").replace("ổng", "bả")
    return text


def calibrated_timing(text: str, target_sps: float | None, target_pause_ratio: float | None,
                      seed: str = "") -> tuple[list[float], float]:
    """(pauses, duration_sec) so that syllables / voiced time = target_sps and pauses / turn time = target_pause_ratio
    (pauses kept inside the 0.4-3 s band the metrics count)."""
    from chaoba.core.metrics import count_syllables
    sps = target_sps if target_sps and target_sps > 0.5 else DEFAULT_SPS
    pr = target_pause_ratio if target_pause_ratio is not None and 0 <= target_pause_ratio < 0.8 else DEFAULT_PAUSE_RATIO
    n = max(1, count_syllables(text))
    voiced = n / sps
    total_pause = pr * voiced / (1.0 - pr)
    pauses: list[float] = []
    if total_pause >= 0.2:   # one short pause when the line is short (keeps the call-level ratio on target)
        k = max(1, round(total_pause / 0.9))
        each = total_pause / k
        while each > 2.8:
            k += 1
            each = total_pause / k
        if each < 0.42:
            k = max(1, int(total_pause / 0.42))
            each = total_pause / k
        rnd = random.Random(seed)
        jit = [rnd.uniform(-0.03, 0.03) for _ in range(k)]
        jit = [j - sum(jit) / k for j in jit]            # zero-mean jitter keeps the total exact
        pauses = [round(max(0.41, each + j), 3) for j in jit]
    return pauses, round(voiced + sum(pauses), 3)


def next_elder_line(state: CallState, target_sps: float | None = None,
                    target_pause_ratio: float | None = None) -> dict:
    """{"text", "pauses": [sec,...], "duration_sec", "target_sps", "simulated": True}.

    ``pauses`` are synthetic VAD gaps and ``duration_sec`` the modelled turn length, both calibrated to the persona's
    baseline (``target_sps`` / ``target_pause_ratio``, usually the current baseline centers)."""
    line = _next_text(state)
    seed = f"{state.call_id}:{len(state.turns)}:t"
    pauses, dur = calibrated_timing(line, target_sps, target_pause_ratio, seed)
    return {"text": line, "pauses": pauses, "duration_sec": dur,
            "target_sps": round(target_sps or DEFAULT_SPS, 3), "simulated": True}


def _next_text(state: CallState) -> str:
    h = state.ev.honorific
    seed = f"{state.call_id}:{len(state.turns)}"
    last_agent = next((t.text for t in reversed(state.turns) if t.speaker == "agent"), "")
    n = normalize(last_agent)
    if state.phase == "greeting":
        key = "consent"
    elif state.step == "recall_free":
        key = "recall_free"
    elif state.awaiting_confirm is not None:
        key = "confirm"
    elif state.step == "symptom_followup":
        key = "followup"
    elif state.step == "recall_cue" and state.ctx.recall:
        fact = state.ctx.recall.fact_vi.rstrip(".")
        return _adapt(f"À, nhớ rồi! {fact[:1].upper() + fact[1:]} đó con, đúng hông?", h)
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
    return _adapt(_pick(opts, seed), h)
