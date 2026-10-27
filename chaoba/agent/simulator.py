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
import re

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
    "share": ["Ừ, được con, kể cho nó nghe đi, chuyện xưa mà, cho tụi nhỏ biết hồi đó nhà mình sống sao.",
              "Ừ được, kể nó nghe cho vui, nó cũng hay hỏi chuyện hồi xưa lắm đó con.",
              "Thôi, chuyện đó con giữ riêng giùm bà nha, để bữa nào bà tự kể với nó."],
}
# Memory-book answers (simulated): a first answer per bank question, then a theme-level reflection, then a short
# closer (too short to enter the memoir). Said in "bà" voice and adapted for "ông" by _adapt.
LIFE_FIRST = {
    "c1": "Hồi nhỏ bà hay theo mấy đứa trong xóm ra ruộng bắt cá lia thia, chiều nào cũng đi hết trơn.",
    "c2": "Hồi nhỏ bà học trường làng, đi chân đất qua mấy bờ ruộng, mùa mưa trơn trợt mà vui lắm.",
    "c3": "Má dạy bà làm người phải thật thà, có chén cơm cũng chia cho hàng xóm.",
    "c4": "Có lần bà lén hái xoài nhà hàng xóm, bị má bắt quỳ trước bàn thờ cả buổi.",
    "h1": "Nhà bà ở quê mái lá, trước nhà có cây dừa, sau nhà có cái mương nhỏ.",
    "h2": "Hồi xưa đi đâu cũng bơi xuồng, muốn lên chợ huyện phải đi đò máy cả buổi.",
    "h3": "Mùa nước lên thì cả xóm bơi xuồng đi thăm nhau, giăng lưới bắt cá linh.",
    "h4": "Chợ quê họp từ sáng sớm dưới mấy gốc bần, người ta bán cá, bán rau, ồn ào vui lắm.",
    "f1": "Món bà nhớ nhất là canh chua bông điên điển má nấu mỗi mùa nước nổi.",
    "f2": "Món tủ của bà là thịt kho nước dừa, hồi đó má dạy nấu cho đều lửa.",
    "f3": "Hồi đó thiếu thốn, cơm độn khoai mì, có chén mắm kho quẹt là ngon rồi.",
    "f4": "Bà mê nhất trái mận hồng đào trong vườn nội, chín đỏ cả cây.",
    "w1": "Hồi trẻ bà đi bán vải ngoài chợ, sáng nào cũng dậy từ bốn giờ chèo xuồng đi.",
    "w2": "Bà tự hào nhất là nuôi mấy đứa nhỏ ăn học, đứa nào cũng ra trường đàng hoàng.",
    "w3": "Nhà bà làm ruộng, mùa lúa chín cả nhà ra đồng gặt từ sáng tới tối.",
    "w4": "Có cô chủ tiệm may dạy bà cắt may, cô hiền lắm, dạy tận tình.",
    "w5": "Lớp đầu tiên của bà đông lắm, mấy đứa học trò lém lỉnh mà ham học.",
    "l1": "Bà gặp ông nhà ở đám cưới người họ hàng, ổng đờn ca tài tử hay lắm.",
    "l2": "Hồi đó có người dì trong xóm mai mối, hai bên gặp nhau ở đám giỗ.",
    "l3": "Ông nhà tặng bà cây kẹp tóc mua ngoài chợ, bà cất kỹ lắm.",
    "l4": "Nhớ nhất là lần hai người chèo xuồng đi coi hát bội, về tới nhà gần sáng.",
    "d1": "Đám cưới bà làm ở nhà, dựng rạp lá dừa trước sân, cả xóm tới phụ.",
    "d2": "Bà mặc áo dài đỏ má may cho, tay run quá trời.",
    "d3": "Hồi xưa rước dâu bằng ghe, nhà trai phải qua mấy lễ mới được rước dâu về.",
    "d4": "Mới về nhà chồng bà lạ nước lạ cái, mà má chồng thương lắm.",
    "p1": "Hồi con Lan mới sinh, nhà còn nghèo, ông nhà đi làm thuê ngoài đồng.",
    "p2": "Nuôi con hồi xưa cực lắm, bà vừa làm ruộng vừa may đồ thuê ban đêm.",
    "p3": "Bà hay kể chuyện Tấm Cám với Thạch Sanh cho tụi nhỏ nghe, đứa nào cũng mê.",
    "p4": "Có lần mấy đứa nhỏ về làm sinh nhật cho bà, bà mừng quá trời.",
    "t1": "Tết hồi xưa nhà bà gói bánh tét cả đêm, mấy đứa nhỏ ngồi canh nồi bánh.",
    "t2": "Tết được má may cho bộ đồ mới, mặc đi khoe cả xóm.",
    "t3": "Trung thu ba làm lồng đèn ngôi sao bằng tre, tụi nhỏ rước đèn đi vòng xóm.",
    "t4": "Đám giỗ nội đông lắm, họ hàng tới từ sớm, mấy cô mấy dì lo nấu nướng.",
    "k1": "Hồi khó khăn nhất là mấy năm bao cấp, nhờ lối xóm giúp nhau mới qua được.",
    "k2": "Hồi đó nhà bà phải dời đi chỗ khác mấy lần, mà cả nhà vẫn ở bên nhau.",
    "k3": "Năm đó bà đang ở quê, cả nhà ngồi nghe radio, rồi từ từ cuộc sống cũng yên.",
    "k4": "Xếp hàng mua gạo từ khuya, có bữa tới lượt thì hết hàng.",
    "b1": "Hồi trẻ bà có người bạn thân là cô Sáu, hai đứa đi cấy chung với nhau.",
    "b2": "Xóm bà có ông Tám vui tính nhất, kể chuyện tiếu lâm ai cũng cười.",
    "b3": "Tối nào cũng có đờn ca tài tử dưới gốc me đầu xóm, bà hay ca vọng cổ.",
    "b4": "Có lần bà nấu cơm giúp nhà hàng xóm có đám, họ nhớ ơn hoài.",
}
LIFE_MORE = {
    "childhood": "Hồi đó nghèo mà vui, mấy đứa trong xóm thương nhau lắm. Tụi nhỏ bây giờ đâu có được chơi vậy.",
    "hometown": "Giờ về quê thấy khác nhiều rồi, đường xá tráng nhựa hết trơn. Ở quê thì ai cũng biết mặt nhau hết trơn.",
    "food": "Tụi nhỏ trong nhà ăn món đó khen hoài, kêu bà nấu hoài. Món đó phải ăn với cơm nóng mới đúng điệu.",
    "work": "Cực lắm con, mà nhờ vậy mới có ngày hôm nay. Ai hỏi thì bà nói là cực mà vui.",
    "love": "Ổng hiền, ít nói, mà thương bà lắm. Có gì ngon ổng cũng để dành cho bà.",
    "wedding": "Giờ đám cưới đãi nhà hàng, đâu còn cảnh cả xóm phụ nhau như hồi đó. Hồi đó đơn sơ mà tình nghĩa lắm.",
    "family": "Giờ tụi nó lớn rồi, lo cho bà chu đáo, bà thấy mừng. Mỗi lần tụi nó về là nhà cửa rộn ràng.",
    "festivals": "Giờ Tết đơn giản hơn nhiều rồi, mà bà vẫn nhớ hồi xưa. Nhà nào cũng chưng một cây mai vàng trước cửa.",
    "hardship": "Nghĩ lại thấy nhờ có lối xóm thương nhau mới qua được. Hồi đó ai cũng cực, mà lòng người tốt lắm.",
    "friends": "Giờ lâu lâu gọi điện thăm nhau, nhắc chuyện xưa là cười hoài. Tình bạn hồi xưa bền lắm, giờ vẫn còn thăm nhau.",
}
DEFAULT_SPS = 3.8           # used only when the persona has no baseline yet
DEFAULT_PAUSE_RATIO = 0.12


def _pick(opts: list[str], seed: str) -> str:
    return random.Random(int(hashlib.sha256(seed.encode()).hexdigest()[:10], 16)).choice(opts)


def _adapt(text: str, honorific: str) -> str:
    if honorific == "ông":
        text = text.replace("bà ", "tui ").replace("Bà ", "Tui ").replace("con Lan", "thằng Khoa") \
                   .replace("Ông nhà", "Bà nhà").replace("ông nhà", "bà nhà")
        text = re.sub(r"(?<!\w)ổng(?!\w)", "bả", text)   # not the "ổng" inside "hổng"
        text = re.sub(r"(?<!\w)Ổng(?!\w)", "Bả", text)
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

LIFE_MORE2 = {
    "childhood": "Tối về má rầy quá trời, mà bữa sau mấy đứa lại rủ nhau đi tiếp.",
    "hometown": "Hồi đó nhà nào cũng trồng dừa, trồng chuối, chiều chiều khói bếp bay khắp xóm.",
    "food": "Bây giờ chợ có bán sẵn mà ăn hổng ngon bằng hồi xưa má nấu.",
    "work": "Mấy chục năm trời, mưa nắng gì cũng đi, chưa nghỉ bữa nào.",
    "love": "Hai người quen nhau gần một năm mới dám thưa chuyện với ba má.",
    "wedding": "Bữa đó có gỏi gà với cà ri, khách ăn uống tới khuya mới về.",
    "family": "Tụi nhỏ đứa nào cũng ngoan, đi học về là phụ nhà phụ cửa.",
    "festivals": "Sáng mùng một mặc đồ mới đi chúc Tết, vui hết biết.",
    "hardship": "Ai có gì thì chia nhau, chén gạo củ khoai cũng san sẻ.",
    "friends": "Hai đứa hay hát hò trên ruộng, ai nghe cũng cười.",
}
LIFE_MORE3 = {
    "childhood": "Hồi đó đâu có đồ chơi gì, lấy lá dừa làm chong chóng, lấy vỏ lon làm xe kéo, vậy mà chơi cả ngày hổng biết chán.",
    "hometown": "Sáng sớm nghe tiếng gà gáy, tiếng xuồng ba lá chèo ngang qua mương, giờ nhớ lại thấy thương cái quê mình quá trời.",
    "food": "Má nấu món gì cũng đơn sơ, rau trong vườn, cá dưới mương, mà cả nhà ngồi quây quần ăn với nhau là vui rồi.",
    "work": "Hồi đó làm từ sáng tới tối, trưa ăn vội chén cơm nguội, mà ai cũng vui vẻ, có khi vừa làm vừa hát nữa.",
    "love": "Hồi đó đâu có điện thoại, muốn gặp nhau phải chờ tới đám giỗ đám cưới trong xóm, gặp được là mừng lắm.",
    "wedding": "Cả xóm ai cũng tới phụ, người dựng rạp, người làm gà, người nấu xôi, vui như ngày hội, ai cũng cười nói rộn ràng.",
    "family": "Hồi đó nhà chật mà vui, tối nào cả nhà cũng ngồi ăn cơm chung, kể chuyện trong ngày cho nhau nghe.",
    "festivals": "Chiều ba mươi cả nhà dọn dẹp bàn thờ, cắm bông, nấu nồi thịt kho, tụi nhỏ chạy tới chạy lui mừng lắm.",
    "hardship": "Hồi đó nhà nào cũng thiếu, mà có gì cũng chia nhau, nhà này có rau thì cho nhà kia, nhà kia có cá thì cho lại.",
    "friends": "Mấy đứa bạn hồi đó giờ đứa còn đứa mất, gặp lại là ngồi nói chuyện xưa hoài hổng muốn về.",
}
LIFE_CLOSER = "Ừ, vậy đó con, chuyện xưa kể hoài hổng hết. Mai mốt con hỏi nữa thì bà kể tiếp nghen con."


def _game_answer(state: CallState, seed: str) -> str:
    """Mostly right (the demo shows the praise), sometimes only partly."""
    g = state.ctx.game
    rnd = random.Random(int(hashlib.sha256(seed.encode()).hexdigest()[:10], 16))
    if g.category == "ca_dao":
        return f"À, {g.answer_vi[:1].lower() + g.answer_vi[1:]} chớ gì. Câu này hồi nhỏ má hay đọc cho bà nghe đó con."
    words = [grp[0] for grp in g.expected]
    n = g.need if rnd.random() < 0.8 else max(1, g.need - 1)
    picked = words[:n] if g.category == "family" else rnd.sample(words, min(n, len(words)))
    return "Để coi... " + ", ".join(picked) + " đó con. Chơi vầy cũng vui ghê."


def _next_text(state: CallState) -> str:
    h = state.ev.honorific
    seed = f"{state.call_id}:{len(state.turns)}"
    last_agent = next((t.text for t in reversed(state.turns) if t.speaker == "agent"), "")
    n = normalize(last_agent)
    if state.phase == "greeting":
        key = "consent"
    elif state.step == "story_share":
        key = "share"
    elif state.step == "activity_game" and state.ctx.game is not None:
        return _adapt(_game_answer(state, seed), h)
    elif (state.step in ("story_open", "story_follow", "recall_close") and state.life_q_asked
          and state.ctx.life_question is not None and state.share_stage == "none"):
        lq = state.ctx.life_question
        i = len(state.story_texts)
        theme = lq.theme if lq.theme in LIFE_MORE else "childhood"
        if i == 0:
            return _adapt(f"{LIFE_FIRST.get(lq.id, LIFE_FIRST['c1'])} {LIFE_MORE2[theme]}", h)
        return _adapt({1: LIFE_MORE, 2: LIFE_MORE3}[i][theme] if i in (1, 2) else LIFE_CLOSER, h)
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
