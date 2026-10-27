"""Bilingual (Vietnamese / English) family-facing explanation of a ``DailyLight``.

* **Template first.** Code turns the structured reasons into facts (numbers rounded to whole
  percents / counts) and fills fixed sentence templates. Vietnamese wording is warm, plain and
  Southern-neutral ("bà", "té ngã", "đi khám"), always framed as *change relative to the person's own
  usual pattern*, never as a diagnosis.
* **Safety blocklist.** Output must never contain diagnostic labels (``BLOCKLIST``). Templates are
  checked in tests; any LLM output is checked at runtime.
* **Optional LLM rewording** (``use_llm=True`` and ``ANTHROPIC_API_KEY`` set): ``claude-haiku-5-5``
  rewrites the template text for warmth only. The result is accepted only if (a) it contains no
  number that is not in the template, (b) no blocklisted word, (c) it is non-empty and not much longer.
  Any failure (no SDK, no key, network, timeout, post-check) falls back to the template silently.
"""
from __future__ import annotations

import os
import re
import unicodedata

from .models import DailyLight

BLOCKLIST = (
    "sa sút trí tuệ", "alzheimer", "trầm cảm", "dementia", "depression", "parkinson", "đột quỵ",
    "stroke", "mất trí", "chẩn đoán", "diagnos",
)
LLM_MODEL = "claude-haiku-5-5"

METRIC_VI = {
    # (worse-direction phrase, generic phrase)
    "speech_rate_sps": "nói chậm hơn",
    "pause_ratio": "ngập ngừng, ngừng nghỉ nhiều hơn",
    "filled_pause_rate": "hay “ờ, à” nhiều hơn",
    "mattr": "dùng từ ngữ ít phong phú hơn",
    "recall_score": "nhớ lại chuyện đã kể kém hơn",
}
METRIC_EN = {
    "speech_rate_sps": "speaking slower",
    "pause_ratio": "pausing more",
    "filled_pause_rate": "using more fillers (“uh, um”)",
    "mattr": "using a narrower range of words",
    "recall_score": "recalling earlier conversations less well",
}
SYMPTOM_VI = {
    "pain": "đau nhức", "insomnia": "mất ngủ", "skipped_meal": "bỏ bữa", "dizziness": "chóng mặt",
    "fall": "té ngã", "sadness": "buồn trong người", "missed_medication": "quên uống thuốc",
}
SYMPTOM_EN = {
    "pain": "pain", "insomnia": "poor sleep", "skipped_meal": "skipped meals", "dizziness": "dizziness",
    "fall": "a fall", "sadness": "feeling sad", "missed_medication": "missed medication",
}
COGNITIVE = {"recall_score", "mattr", "pause_ratio", "filled_pause_rate"}
SEVERITY = {"fall": 0, "unanswered": 1, "multi_symptom": 2, "multi_metric": 3, "metric_shift": 4,
            "metric_trend": 5, "symptom_repeat": 6, "low_mood": 7}


def _pronouns(name_vi: str, name_en: str):
    first = (name_vi or "").strip().split(" ")[0].lower() if name_vi else "bà"
    hon = first if first in {"bà", "ông", "cô", "chú", "dì", "bác", "cậu", "mợ"} else "bà"
    en = (name_en or "").lower()
    if en.startswith("mr ") or en.startswith("mr.") or hon in {"ông", "chú", "cậu", "bác"} and not en.startswith("mrs"):
        he, his = "he", "his"
    else:
        he, his = "she", "her"
    return hon, he, his


def _span_vi(days: int) -> str:
    if days <= 4:
        return "Mấy ngày nay"
    if days <= 10:
        return "Khoảng một tuần nay"
    if days <= 17:
        return "Hai tuần nay"
    return "Mấy tuần nay"


def _span_en(days: int) -> str:
    if days <= 4:
        return "Over the last few days"
    if days <= 10:
        return "Over about a week"
    if days <= 17:
        return "Over two weeks"
    return "Over several weeks"


def _pct(x) -> int | None:
    if x is None:
        return None
    return int(round(abs(float(x))))


def _metric_items(reasons):
    """Collect (metric, days, change_pct) from metric reasons, most-changed first, deduplicated."""
    items: dict[str, tuple[int, float | None]] = {}
    for r in reasons:
        if r.get("code") in ("metric_trend", "metric_shift") and r.get("metric"):
            items[r["metric"]] = (int(r.get("days", 0)), r.get("change_pct"))
        elif r.get("code") == "multi_metric":
            for d in r.get("details", []) or [{"metric": m} for m in r.get("metrics", [])]:
                items.setdefault(d["metric"], (int(d.get("days", r.get("days", 0)) or 0), d.get("change_pct")))
    # speech rate and recall first (easiest for families to recognise), then by size of change
    prio = {"speech_rate_sps": 0, "recall_score": 1}
    return sorted(items.items(), key=lambda kv: (prio.get(kv[0], 2), -abs(kv[1][1] or 0)))


def template_explain(light: DailyLight, elder_name_vi: str, elder_name_en: str) -> tuple[str, str]:
    hon, he, his = _pronouns(elder_name_vi, elder_name_en)
    He = he.capitalize()
    him = "her" if he == "she" else "him"
    reasons = list(light.reasons or [])
    codes = {r.get("code") for r in reasons}
    vi: list[str] = []
    en: list[str] = []

    if light.light == "gray":
        bb = next((r for r in reasons if r.get("code") == "building_baseline"), None)
        if bb:
            n, need = int(bb.get("days", 0)), int(bb.get("needed", 14))
            vi.append(f"Chào Bà đang làm quen với giọng nói và nhịp sinh hoạt bình thường của {hon} "
                      f"({min(n, need)}/{need} ngày). Chưa so sánh được, gia đình cứ yên tâm.")
            en.append(f"Chào Bà is still learning {his} usual voice and routine ({min(n, need)}/{need} days). "
                      f"No comparison yet.")
        elif "missed_call" in codes:
            vi.append(f"Hôm nay {hon} chưa bắt máy nên chưa có thông tin mới.")
            en.append(f"{He} did not answer today, so there is no new information.")
        else:
            vi.append(f"Cuộc gọi hôm nay hơi ngắn nên chưa đủ để so sánh với bình thường của {hon}.")
            en.append(f"Today's call was too short to compare with {his} usual pattern.")
        return " ".join(vi), " ".join(en)

    if light.light == "green":
        vi.append(f"Hôm nay {hon} nói chuyện, trí nhớ và tâm trạng vẫn như bình thường của {hon}.")
        en.append(f"Today {his} speech, memory and mood are in line with {his} usual pattern.")
        return " ".join(vi), " ".join(en)

    # ---- yellow / red ---------------------------------------------------------------------
    if "fall" in codes:
        vi.append(f"Hôm nay {hon} có nhắc chuyện bị té ngã.")
        en.append(f"Today {he} mentioned having a fall.")

    un = next((r for r in reasons if r.get("code") == "unanswered"), None)
    if un:
        d = int(un.get("days", 2))
        vi.append(f"{d} ngày liền {hon} không bắt máy.")
        en.append(f"{He} has not answered for {d} days in a row.")

    metrics = _metric_items(reasons)
    if metrics:
        days = max(d for _, (d, _) in metrics)
        parts_vi, parts_en = [], []
        for m, (_, c) in metrics[:2]:
            p = _pct(c)
            if p and p >= 3:
                parts_vi.append(f"{METRIC_VI[m]} khoảng {p}%")
                parts_en.append(f"{METRIC_EN[m]} (about {p}% change)")
            else:
                parts_vi.append(METRIC_VI[m])
                parts_en.append(METRIC_EN[m])
        span_days = days + 7  # trend becomes visible on the chart ~a week before it crosses the limit
        sym_vi = ""
        sym_en = ""
        rep = [r for r in reasons if r.get("code") == "symptom_repeat"]
        if rep:
            s = rep[0]
            sym_vi = f" và {int(s.get('quotes', 2))} lần nhắc {SYMPTOM_VI.get(s['symptom'], s['symptom'])}"
            sym_en = f", and mentioned {SYMPTOM_EN.get(s['symptom'], s['symptom'])} {int(s.get('quotes', 2))} times"
        vi.append(f"{_span_vi(span_days)} {hon} " + " và ".join(parts_vi)
                  + f" so với bình thường của {hon}{sym_vi}.")
        en.append(f"{_span_en(span_days)} {he} has been " + " and ".join(parts_en)
                  + f" compared with {his} own usual pattern{sym_en}.")
        used_rep = bool(rep)
    else:
        used_rep = False

    ms = next((r for r in reasons if r.get("code") == "multi_symptom"), None)
    if ms:
        names_vi = ", ".join(SYMPTOM_VI.get(s, s) for s in ms.get("symptoms", []))
        names_en = ", ".join(SYMPTOM_EN.get(s, s) for s in ms.get("symptoms", []))
        vi.append(f"Trong 7 ngày qua {hon} nhắc tới {int(ms.get('count', 3))} chuyện sức khỏe: {names_vi}.")
        en.append(f"In the last 7 days {he} mentioned {int(ms.get('count', 3))} different health complaints: {names_en}.")
    elif not used_rep:
        for s in [r for r in reasons if r.get("code") == "symptom_repeat"][:2]:
            vi.append(f"Tuần này {hon} {int(s.get('quotes', 2))} lần nhắc {SYMPTOM_VI.get(s['symptom'], s['symptom'])}.")
            en.append(f"This week {he} mentioned {SYMPTOM_EN.get(s['symptom'], s['symptom'])} "
                      f"{int(s.get('quotes', 2))} times.")

    lm = next((r for r in reasons if r.get("code") == "low_mood"), None)
    if lm:
        vi.append(f"{int(lm.get('days', 3))} trong 7 ngày qua {hon} nghe có vẻ buồn, mệt.")
        en.append(f"On {int(lm.get('days', 3))} of the last 7 days {he} sounded low or tired.")

    if "recovering" in codes:
        rc = next(r for r in reasons if r.get("code") == "recovering")
        vi.append(f"Đã có {int(rc.get('days', 1))} ngày khá hơn, Chào Bà đang theo dõi thêm.")
        en.append(f"{int(rc.get('days', 1))} better day(s) so far; still watching before lowering the light.")

    # ---- action -------------------------------------------------------------------------
    cognitive_only = bool(metrics) and all(m in COGNITIVE for m, _ in metrics) and not (
        codes & {"fall", "multi_symptom", "symptom_repeat", "unanswered"})
    if light.light == "red":
        if "fall" in codes:
            vi.append(f"Nên gọi cho {hon} ngay và nhờ người gần nhà qua xem {hon}.")
            en.append(f"Please call {him} now and ask someone nearby to check in person.")
        elif un:
            vi.append(f"Nên gọi lại hoặc nhờ hàng xóm ghé nhà xem {hon} ngay hôm nay.")
            en.append("Please call again or ask a neighbour to check in person today.")
        else:
            vi.append(f"Nên gọi hỏi thăm và cân nhắc đưa {hon} đi khám.")
            en.append(f"Please call {him} and consider arranging a doctor's visit.")
    else:
        if cognitive_only:
            vi.append(f"Nên gọi hỏi thăm {hon} nhiều hơn và đưa {hon} đi khám để bác sĩ đánh giá; "
                      f"mang theo báo cáo xu hướng này.")
            en.append(f"Consider calling more often and arranging a doctor's visit so a doctor can assess; "
                      f"bring this trend report.")
        else:
            vi.append(f"Nên gọi hỏi thăm {hon} trong hôm nay hoặc ngày mai.")
            en.append(f"Consider giving {him} a call today or tomorrow.")

    text_vi = " ".join(vi)
    text_vi = text_vi[0].upper() + text_vi[1:] if text_vi else text_vi
    return text_vi, " ".join(en)


def contains_blocked(text: str) -> bool:
    t = unicodedata.normalize("NFC", (text or "").lower())
    return any(unicodedata.normalize("NFC", w) in t for w in BLOCKLIST)


_NUM = re.compile(r"\d+(?:[.,]\d+)?")


def _numbers(text: str) -> set[str]:
    return {n.replace(",", ".") for n in _NUM.findall(text or "")}


def postcheck(candidate: str, template: str) -> bool:
    """True if an LLM rewording is safe to show instead of the template."""
    if not candidate or not candidate.strip():
        return False
    if contains_blocked(candidate):
        return False
    if not _numbers(candidate) <= _numbers(template):
        return False
    if len(candidate) > 2.0 * len(template) + 80:
        return False
    return True


def _llm_reword(vi: str, en: str) -> tuple[str, str] | None:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return None
    try:
        import anthropic  # noqa: WPS433

        client = anthropic.Anthropic(timeout=10.0, max_retries=1)
        system = (
            "You reword short family notifications about an older adult so they sound warm and natural. "
            "Keep exactly the same facts and numbers; add no new numbers, no medical terms, no diagnosis. "
            "Vietnamese: plain Southern-neutral family wording. Reply with exactly two lines: "
            "line 1 starts with 'VI: ', line 2 starts with 'EN: '."
        )
        msg = client.messages.create(
            model=LLM_MODEL, max_tokens=400, system=system,
            messages=[{"role": "user", "content": f"VI: {vi}\nEN: {en}"}],
        )
        text = "".join(getattr(b, "text", "") for b in msg.content)
        out_vi = out_en = None
        for line in text.splitlines():
            line = line.strip()
            if line.startswith("VI:"):
                out_vi = line[3:].strip()
            elif line.startswith("EN:"):
                out_en = line[3:].strip()
        if not out_vi or not out_en:
            return None
        if not (postcheck(out_vi, vi) and postcheck(out_en, en)):
            return None
        return out_vi, out_en
    except Exception:  # any SDK / network / parsing failure -> template
        return None


def explain(light: DailyLight, elder_name_vi: str, elder_name_en: str, use_llm: bool = False) -> tuple[str, str]:
    """(vi, en) explanation of a daily light. Deterministic unless ``use_llm`` and a key is configured."""
    vi, en = template_explain(light, elder_name_vi, elder_name_en)
    if use_llm:
        res = _llm_reword(vi, en)
        if res:
            return res
    return vi, en
