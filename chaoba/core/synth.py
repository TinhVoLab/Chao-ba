"""Synthetic daily records for demo personas and an evaluation cohort. ALL OUTPUT IS SIMULATED.

Generative model (per elder, per day):

* Each metric = personal level x weekday effect x (1 + AR(1) noise) x decline effect.
  AR(1) phi = 0.3 on a standard-normal innovation, scaled to the marginal relative SD of the metric
  (speech rate 4.5 %, pause ratio 12 %, filler rate 18 %, MATTR 2.5 %, times the person's noise level).
  Weekday effects (e.g. Sunday family visits -> livelier talk) are small fixed per-person offsets.
* Recall (0..3 items recalled from the previous call) = round(2.85 + N(0, 0.35) - decline shift),
  not asked on ~10 % of days. Mood 1..5 = round(N(mood_mean - shift, 0.55)).
* Missed calls (~3 %) and invalid/too-short calls (~3 %, pstn ~5 %) occur at random; invalid days
  carry no speech metrics. Background symptom mentions are rare (pain/insomnia ~1 %/day).
* Decline effects are deterministic functions of the day (ramps) so persona timelines are tunable;
  symptom days in the persona stories are scripted.

Personas: ``hanh`` (medication side-effect episode, recovered after a doctor visit, re-baselined on
day 77), ``tu`` (slow cognitive-type drift from ~day 30, ends yellow), ``control`` (stable).
Signal sizes (not rules) were tuned so the light timeline lands near the story targets; the
actual days are verified in ``tests/core/test_core_synth.py``.
"""
from __future__ import annotations

import math
from datetime import date, timedelta
from typing import Literal

import numpy as np

from .control_chart import ControlConfig, evaluate_series
from .dmaic import compute_cycle
from .explain import explain
from .models import DailyRecord, METRICS, SYMPTOMS, to_dict

# Internal calendar of the generator: day 1 = 2026-07-18 (a Saturday), day 90 = 2026-10-15. Only the weekday matters
# to the generator (small weekday effects), so moving this by whole weeks leaves every value unchanged. The demo
# server re-labels the dates at seed time (``end_date``) so that day 90 is the day before the server's current date;
# day indices, values and lights never depend on the anchor.
START_DATE = date(2026, 7, 18)
PHI = 0.3
REL_SD = {"speech_rate_sps": 0.045, "pause_ratio": 0.12, "filled_pause_rate": 0.18, "mattr": 0.025}
BG_SYMPTOM_RATE = {"pain": 0.010, "insomnia": 0.007, "skipped_meal": 0.003, "dizziness": 0.002,
                   "fall": 0.0003, "sadness": 0.003, "missed_medication": 0.003}


def _ramp(day, start, length):
    if day < start:
        return 0.0
    if length <= 0:
        return 1.0
    return min(1.0, (day - start) / float(length))


class _Person:
    def __init__(self, rng: np.random.Generator, level: dict, noise: float = 1.0, ch_noise: dict | None = None,
                 p_missed: float = 0.03, p_invalid: float = 0.03, mood_mean: float = 4.0,
                 weekday: dict | None = None, recall_ask: float = 0.9, bg_symptom_mult: float = 1.0):
        self.rng = rng
        self.level = level
        self.noise = noise
        self.ch_noise = ch_noise or {}
        self.p_missed = p_missed
        self.p_invalid = p_invalid
        self.mood_mean = mood_mean
        self.weekday = weekday or {}
        self.recall_ask = recall_ask
        self.bg = {s: r * bg_symptom_mult for s, r in BG_SYMPTOM_RATE.items()}
        self.ar = {m: rng.normal() for m in REL_SD}

    def day(self, elder_id: str, d: int, eff: dict, start: date, scripted_symptoms: dict | None = None,
            force_missed: bool = False, force_valid: bool = False) -> DailyRecord:
        rng = self.rng
        dt = start + timedelta(days=d - 1)
        wd = dt.weekday()
        # AR(1) update every day (latent state evolves even when no call)
        for m in REL_SD:
            self.ar[m] = PHI * self.ar[m] + math.sqrt(1 - PHI ** 2) * rng.normal()
        p_miss = min(0.95, self.p_missed + eff.get("p_missed", 0.0))
        p_inv = min(0.95, self.p_invalid + eff.get("p_invalid", 0.0))
        answered = not force_missed and (force_valid or rng.random() >= p_miss)
        rec = DailyRecord(elder_id=elder_id, day=d, date=dt.isoformat(), channel="sim", answered=answered,
                          valid=False, simulated=True)
        if not answered:
            return rec
        valid = force_valid or rng.random() >= p_inv
        rec.valid = valid
        wk = self.weekday.get(wd, {})
        if valid:
            for m in REL_SD:
                sd = REL_SD[m] * self.noise * self.ch_noise.get(m, 1.0)
                x = self.level[m] * (1 + wk.get(m, 0.0)) * (1 + sd * self.ar[m]) * (1 + eff.get(m, 0.0))
                rec.__setattr__(m, round(max(0.0, x), 4))
            rec.mattr = round(min(0.98, rec.mattr), 4)
        # recall (asked on most answered days, even short calls)
        if rng.random() < self.recall_ask and valid:
            r = 2.85 + rng.normal(0, 0.35) - eff.get("recall_shift", 0.0)
            rec.recall_score = float(min(3, max(0, round(r))))
        mood = rng.normal(self.mood_mean + wk.get("mood", 0.0) - eff.get("mood_shift", 0.0), 0.55)
        rec.mood = int(min(5, max(1, round(mood))))
        sym: dict[str, int] = {}
        rates = dict(self.bg)
        for s, r in (eff.get("symptoms") or {}).items():
            rates[s] = rates.get(s, 0.0) + r
        for s, r in rates.items():
            if rng.random() < r:
                sym[s] = 1
        if scripted_symptoms is not None:
            sym = dict(scripted_symptoms)
        rec.symptoms = sym
        return rec


def _weekday_effects(rng, scale=1.0):
    """Small per-person weekday offsets; Sunday = family visit day (livelier, better mood)."""
    eff = {}
    for wd in range(7):
        eff[wd] = {"speech_rate_sps": rng.normal(0, 0.008 * scale), "mattr": rng.normal(0, 0.004 * scale),
                   "pause_ratio": rng.normal(0, 0.02 * scale), "mood": 0.0}
    eff[6]["speech_rate_sps"] += 0.02 * scale
    eff[6]["mattr"] += 0.008 * scale
    eff[6]["mood"] += 0.3
    return eff


# ---------------------------------------------------------------------------------------------
# Persona content
# ---------------------------------------------------------------------------------------------
ACTS = {
    "hanh": [
        ("ăn cháo cá", "had fish porridge"), ("tưới cây mai trước nhà", "watered the apricot-blossom tree"),
        ("kể chuyện chợ Giồng Trôm", "talked about Giồng Trôm market"), ("nấu canh chua", "cooked sour soup"),
        ("xem cải lương trên tivi", "watched cải lương opera on TV"), ("ra vườn hái dừa", "picked coconuts in the garden"),
        ("ngồi nói chuyện với bà Năm hàng xóm", "chatted with her neighbour Mrs Năm"),
        ("đi lễ chùa buổi sáng", "went to the pagoda in the morning"), ("ngủ trưa một giấc", "took an afternoon nap"),
        ("kể chuyện hồi con gái còn nhỏ", "told stories about her daughter as a child"),
        ("làm bánh tét", "made bánh tét rice cakes"), ("cho gà ăn", "fed the chickens"),
    ],
    "tu": [
        ("đọc báo Tuổi Trẻ", "read the Tuổi Trẻ newspaper"), ("chơi cờ tướng ở công viên", "played Chinese chess in the park"),
        ("kể chuyện học trò cũ", "talked about former students"), ("đi bộ với vợ buổi sáng", "walked with his wife in the morning"),
        ("tưới chậu lan", "watered his orchids"), ("nghe đài", "listened to the radio"),
        ("xem thời sự", "watched the news"), ("uống cà phê với bạn", "had coffee with a friend"),
        ("giảng bài cho cháu", "helped his grandson with homework"), ("viết thư pháp", "practised calligraphy"),
    ],
    "control": [
        ("cho cá ăn", "fed the fish"), ("đi chợ nổi Cái Răng", "went to Cái Răng floating market"),
        ("uống trà với bạn", "had tea with friends"), ("sửa lại cái xuồng", "repaired his boat"),
        ("coi đá banh", "watched football"), ("làm vườn", "worked in the garden"),
        ("đi đám giỗ bà con", "went to a relative's memorial meal"), ("câu cá ngoài sông", "went fishing on the river"),
        ("ăn cơm với cháu", "had a meal with his grandchildren"), ("nghe vọng cổ", "listened to vọng cổ songs"),
    ],
}
SYM_SENT = {
    "dizziness": ("{H} nói hơi chóng mặt khi đứng dậy.", "{He} mentioned feeling dizzy when standing up."),
    "pain": ("{H} than đau lưng.", "{He} complained of back pain."),
    "insomnia": ("{H} kể đêm qua khó ngủ.", "{He} said {he} slept badly last night."),
    "skipped_meal": ("{H} bỏ bữa trưa vì không thấy ngon miệng.", "{He} skipped lunch because of poor appetite."),
    "fall": ("{H} kể bị té trong nhà tắm.", "{He} said {he} fell in the bathroom."),
    "sadness": ("{H} nói thấy buồn buồn trong người.", "{He} said {he} felt a bit down."),
    "missed_medication": ("{H} quên uống thuốc buổi sáng.", "{He} forgot the morning medication."),
}


def _summary(key, rec: DailyRecord, rng, hon_vi: str, he: str):
    H = hon_vi.capitalize()
    He = he.capitalize()
    if not rec.answered:
        return f"{H} không bắt máy.", f"{He} did not answer the call."
    if not rec.valid:
        return (f"Cuộc gọi ngắn, {hon_vi} đang bận nấu cơm.", f"Short call - {he} was busy cooking.")
    acts = ACTS.get(key, ACTS["control"])
    idx = rng.choice(len(acts), size=2 if rng.random() < 0.5 else 3, replace=False)
    a = [acts[i] for i in idx]
    vi = f"{H} " + ", ".join(x[0] for x in a) + "."
    en_list = [x[1] for x in a]
    en = f"{He} " + (", ".join(en_list[:-1]) + " and " + en_list[-1]) + "."
    for s in rec.symptoms or {}:
        sv, se = SYM_SENT.get(s, ("", ""))
        vi += " " + sv.format(H=H, He=He, he=he)
        en += " " + se.format(H=H, He=He, he=he)
    if rec.recall_score is not None and rec.recall_score <= 1:
        vi += f" {H} cần gợi ý mới nhớ chuyện hôm trước."
        en += f" {He} needed hints to recall the previous chat."
    if rec.mood is not None and rec.mood <= 2:
        vi += f" Giọng {hon_vi} nghe hơi mệt."
        en += f" {He} sounded a bit tired."
    return vi, en


CONSENTS = [
    {"type": "daily_call", "granted": True, "by": "self", "witness": "family", "scope_vi": "Nhận cuộc gọi hỏi thăm hằng ngày",
     "scope_en": "Receive daily check-in calls"},
    {"type": "voice_metrics", "granted": True, "by": "self", "scope_vi": "Đo tốc độ nói, ngừng nghỉ từ văn bản và thời gian (không lưu âm thanh)",
     "scope_en": "Derive speech timing metrics from text and timings (no audio stored)"},
    {"type": "family_sharing", "granted": True, "by": "self", "scope_vi": "Chia sẻ đèn tín hiệu và tóm tắt với con cháu",
     "scope_en": "Share daily light and summaries with family"},
    {"type": "clinician_sharing", "granted": True, "by": "self", "scope_vi": "Chia sẻ báo cáo với bác sĩ khi gia đình yêu cầu",
     "scope_en": "Share report with clinician on family request"},
    {"type": "research_use", "granted": False, "by": "self", "scope_vi": "Dùng dữ liệu ẩn danh cho nghiên cứu",
     "scope_en": "Use de-identified data for research"},
]


def _profiles():
    return {
        "hanh": {
            "id": "hanh", "display_name": "Bà Hạnh", "name_en": "Mrs Hanh", "honorific": "bà", "self_ref": "con",
            "age": 72, "province": "Bến Tre", "dialect": "south", "lives_alone": True, "channel_pref": "pstn",
            "conditions": ["hypertension"], "medications": [{"name": "Amlodipine 5mg", "time": "07:00"}],
            "family": [{"id": "lan", "name": "Lan", "relation": "daughter", "role": "primary"},
                       {"id": "minh", "name": "Minh", "relation": "son", "role": "secondary"}],
            "goals": ["Ngủ đủ 6 tiếng", "Uống thuốc huyết áp đúng giờ", "Giữ trí nhớ ổn định"],
            "memory_facts": ["Cây mai trước nhà sắp ra nụ", "Con gái Lan làm ở TP.HCM", "Thích nghe cải lương"],
        },
        "tu": {
            "id": "tu", "display_name": "Ông Tư", "name_en": "Mr Tu", "honorific": "ông", "self_ref": "con",
            "age": 76, "province": "TP.HCM", "dialect": "south", "lives_alone": False, "channel_pref": "web",
            "conditions": ["type 2 diabetes"], "medications": [{"name": "Metformin 500mg", "time": "08:00"}],
            "family": [{"id": "ba_tu", "name": "Bà Tư", "relation": "wife", "role": "primary"},
                       {"id": "khoa", "name": "Khoa", "relation": "son", "role": "secondary"}],
            "goals": ["Giữ trí nhớ ổn định", "Đi bộ 30 phút mỗi sáng", "Đọc báo mỗi ngày"],
            "memory_facts": ["Từng dạy Văn ở trường Lê Quý Đôn 30 năm", "Thích chơi cờ tướng", "Có 2 chậu lan quý"],
        },
        "control": {
            "id": "control", "display_name": "Ông Bảy", "name_en": "Mr Bay", "honorific": "ông", "self_ref": "con",
            "age": 69, "province": "Cần Thơ", "dialect": "south", "lives_alone": False, "channel_pref": "pstn",
            "conditions": ["mild osteoarthritis"], "medications": [{"name": "Paracetamol 500mg (khi đau)", "time": "as needed"}],
            "family": [{"id": "thao", "name": "Thảo", "relation": "daughter", "role": "primary"}],
            "goals": ["Đi bộ mỗi chiều", "Ăn uống đều bữa"],
            "memory_facts": ["Nuôi cá trong ao sau nhà", "Hay đi chợ nổi Cái Răng"],
        },
    }


# ---- persona effect functions -----------------------------------------------------------------
HANH = {"onset": 33, "intervention": 44, "rebaseline": 77,
        "symptoms": {35: {"dizziness": 1}, 38: {"dizziness": 1}, 41: {"dizziness": 1, "insomnia": 1},
                     43: {"dizziness": 1, "skipped_meal": 1}}}


def _hanh_eff(d):
    up = _ramp(d, HANH["onset"], 6)
    down = 1.0 - _ramp(d, HANH["intervention"] + 1, 5)
    k = up * down
    return {"speech_rate_sps": -0.17 * k, "pause_ratio": 0.50 * k, "filled_pause_rate": 0.35 * k,
            "mattr": -0.03 * k, "recall_shift": 0.9 * k, "mood_shift": 0.6 * k}


def _tu_eff(d):
    k = _ramp(d, 30, 60)  # linear drift day 30 -> 90
    return {"recall_shift": 0.8 * k, "mattr": -0.028 * k, "pause_ratio": 0.15 * k, "filled_pause_rate": 0.15 * k,
            "speech_rate_sps": -0.015 * k, "symptoms": {"missed_medication": 0.03 * k}}


def _control_eff(d):
    return {}


PERSONA_CFG = {
    "hanh": dict(level={"speech_rate_sps": 4.6, "pause_ratio": 0.11, "filled_pause_rate": 0.045, "mattr": 0.71},
                 noise=0.75, p_missed=0.03, p_invalid=0.04, mood_mean=4.0, eff=_hanh_eff),
    "tu": dict(level={"speech_rate_sps": 4.3, "pause_ratio": 0.13, "filled_pause_rate": 0.05, "mattr": 0.75},
               noise=0.85, p_missed=0.02, p_invalid=0.02, mood_mean=4.1, eff=_tu_eff),
    "control": dict(level={"speech_rate_sps": 4.9, "pause_ratio": 0.10, "filled_pause_rate": 0.04, "mattr": 0.72},
                    noise=0.8, p_missed=0.03, p_invalid=0.03, mood_mean=4.2, eff=_control_eff),
}


# Sub-seeds of the persona noise streams (chosen so the default seed=7 story lands on the targets;
# the light rules themselves were not tuned per persona).
PERSONA_SUB = {"hanh": 26, "tu": 45, "control": 3}


def _light_events(lights, from_day=22):
    ev = []
    prev = None
    for l in lights:
        if l.day < from_day:
            prev = l.light
            continue
        rank = {"green": 0, "yellow": 1, "red": 2}
        if l.light in ("yellow", "red") and rank[l.light] > rank.get(prev, 0):
            ev.append({"day": l.day, "type": f"alert_{l.light}",
                       "label_vi": "Đèn vàng: cần hỏi thăm" if l.light == "yellow" else "Đèn đỏ: cần liên hệ ngay",
                       "label_en": "Yellow light: check in" if l.light == "yellow" else "Red light: contact now"})
        if l.light == "green" and prev in ("yellow", "red"):
            ev.append({"day": l.day, "type": "recovered", "label_vi": "Đèn xanh trở lại", "label_en": "Back to green"})
        if l.light != "gray":
            prev = l.light
    return ev


def generate_persona(key: Literal["hanh", "tu", "control"], days: int = 90, seed: int = 7,
                     end_date: date | None = None) -> dict:
    """One demo persona: profile, daily records, lights, notes, events, consents, family contacts, DMAIC cycle.

    ``end_date`` re-anchors the calendar so that the last day (``days``) falls on that date. Values are generated on
    the fixed internal calendar (``START_DATE``) first, so the story is identical whatever the anchor.
    """
    if key not in PERSONA_CFG:
        raise ValueError(f"unknown persona {key!r}")
    profile = _profiles()[key]
    pc = PERSONA_CFG[key]
    rng = np.random.default_rng([seed, PERSONA_SUB[key]])
    person = _Person(rng, pc["level"], noise=pc["noise"], p_missed=pc["p_missed"], p_invalid=pc["p_invalid"],
                     mood_mean=pc["mood_mean"], weekday=_weekday_effects(rng))
    srng = np.random.default_rng([seed, 99, len(key)])
    hon = profile["honorific"]
    he = "she" if hon == "bà" else "he"
    records: list[DailyRecord] = []
    for d in range(1, days + 1):
        eff = pc["eff"](d)
        scripted = None
        force_valid = False
        if key == "hanh":
            if d in HANH["symptoms"]:
                scripted, force_valid = HANH["symptoms"][d], True
            elif 30 <= d <= 60:
                scripted = {}  # story period: only scripted symptoms
        rec = person.day(profile["id"], d, eff, START_DATE, scripted_symptoms=scripted, force_valid=force_valid)
        rec.summary_vi, rec.summary_en = _summary(key, rec, srng, hon, he)
        records.append(rec)

    rebase = [HANH["rebaseline"]] if key == "hanh" and days >= HANH["rebaseline"] else []
    lights = evaluate_series(records, ControlConfig(), rebaseline_days=rebase)
    for l in lights:
        l.explanation_vi, l.explanation_en = explain(l, profile["display_name"], profile["name_en"], records=records)

    notes, events = [], [
        {"day": 1, "type": "enrolment", "label_vi": "Bắt đầu cuộc gọi hằng ngày", "label_en": "Daily calls start"},
    ]
    ready = next((l.day for l in lights if l.baseline_ready), None)
    if ready:
        events.append({"day": ready, "type": "baseline_ready", "label_vi": "Đã có mức bình thường riêng",
                       "label_en": "Personal baseline ready"})
    define = {"goals": profile["goals"]}
    intervention_day = None
    fam = profile["family"][0]["name"]
    if key == "hanh":
        intervention_day = HANH["intervention"]
        notes += [
            {"day": 30, "author": "Lan", "text": "Bác sĩ đổi thuốc huyết áp cho má từ tuần này (đổi thuốc huyết áp)."},
            {"day": 39, "author": "Lan", "text": "Má nói hơi chóng mặt khi đứng dậy, con sẽ để ý thêm."},
            {"day": 44, "author": "Lan", "text": "Đã đưa má đi khám, bác sĩ chỉnh lại liều thuốc huyết áp. Con sẽ gọi má 3 lần mỗi tuần."},
            {"day": 60, "author": "Minh", "text": "Má ăn ngủ tốt lại rồi, lại ra vườn tưới cây mai."},
        ]
        events += [
            {"day": 30, "type": "medication_change", "label_vi": "Đổi thuốc huyết áp", "label_en": "Blood-pressure medication changed"},
            {"day": 44, "type": "doctor_visit", "label_vi": "Đi khám, bác sĩ chỉnh liều thuốc",
             "label_en": "Doctor visit, medication adjusted"},
            {"day": 44, "type": "care_plan", "label_vi": "Con gọi bà 3 lần/tuần", "label_en": "Daughter calls 3x/week"},
        ]
        if days >= HANH["rebaseline"]:
            events.append({"day": HANH["rebaseline"], "type": "rebaseline", "label_vi": "Lập mức bình thường mới",
                           "label_en": "New baseline set"})
        define.update({
            "concern_vi": "huyết áp, giấc ngủ và trí nhớ của bà khi sống một mình",
            "concern_en": "blood pressure, sleep and memory while living alone",
            "context_vi": "Thay đổi bắt đầu vài ngày sau khi đổi thuốc huyết áp (ngày 30).",
            "context_en": "Changes began a few days after the blood-pressure medication change (day 30).",
            "intervention_vi": "đi khám, bác sĩ chỉnh liều thuốc huyết áp; con gái gọi 3 lần/tuần",
            "intervention_en": "doctor visit, blood-pressure dose adjusted; daughter calls 3x/week",
            "new_baseline_day": HANH["rebaseline"] if days >= HANH["rebaseline"] else None,
        })
    elif key == "tu":
        notes += [
            {"day": 45, "author": "Bà Tư", "text": "Dạo này ổng hay hỏi lại một chuyện hai lần."},
            {"day": 70, "author": "Khoa", "text": "Ba quên tên một người bạn cờ quen lâu năm."},
        ]
        define.update({
            "concern_vi": "trí nhớ và sự minh mẫn của ông",
            "concern_en": "memory and mental sharpness",
            "context_vi": "Thay đổi diễn ra chậm, từ từ qua nhiều tuần, chủ yếu ở trí nhớ và cách dùng từ.",
            "context_en": "Change is slow and gradual over weeks, mainly in recall and word use.",
            "recommendation_vi": "gia đình gọi trò chuyện với ông thường xuyên hơn; nếu thay đổi kéo dài, mang báo cáo xu hướng này khi ông đi khám định kỳ.",
            "recommendation_en": "family to call and talk with him more often; if the change persists, bring this trend report to his next routine check-up.",
        })
    else:
        notes += [{"day": 50, "author": "Thảo", "text": "Ba khỏe, tuần này đi đám giỗ bên ngoại."}]
        define.update({"concern_vi": "sức khỏe chung khi tuổi cao", "concern_en": "general wellbeing in later life"})
    for n in notes:
        n["date"] = (START_DATE + timedelta(days=n["day"] - 1)).isoformat()
    events += _light_events(lights)
    events.sort(key=lambda e: e["day"])

    contacts = family_contacts(key, profile, days, seed)
    cycle = compute_cycle(records, lights, define, intervention_day, contacts=contacts, simulated=True)
    from .control_chart import current_baseline
    out = {
        "elder": profile,
        "records": [to_dict(r) for r in records],
        "lights": [to_dict(l) for l in lights],
        "baseline": current_baseline(records, ControlConfig(), rebase),
        "rebaseline_days": rebase,
        "notes": notes,
        "events": events,
        "consents": [dict(c, date=START_DATE.isoformat()) for c in CONSENTS],
        "contacts": contacts,
        "dmaic": cycle,
        "simulated": True,
    }
    return reanchor(out, end_date) if end_date is not None else out


def _shift(iso: str, delta: timedelta) -> str:
    return (date.fromisoformat(iso[:10]) + delta).isoformat()


def reanchor(persona: dict, end_date: date) -> dict:
    """Re-label every calendar date in a persona so its last record falls on ``end_date`` (day indices unchanged)."""
    recs = persona.get("records") or []
    if not recs:
        return persona
    delta = end_date - date.fromisoformat(recs[-1]["date"])
    if not delta:
        return persona
    for key in ("records", "lights", "notes", "contacts"):
        for x in persona.get(key) or []:
            if x.get("date"):
                x["date"] = _shift(x["date"], delta)
    for c in persona.get("consents") or []:
        if c.get("date"):
            c["date"] = _shift(c["date"], delta)
    return persona


# ---------------------------------------------------------------------------------------------
# Family contact log (simulated): calls and visits from the family, the measurable side of the care plan
# ---------------------------------------------------------------------------------------------
def family_contacts(key: str, profile: dict, days: int = 90, seed: int = 7) -> list[dict]:
    """Simulated family calls/visits with realistic gaps. ALL SIMULATED.

    * ``hanh``: Lan calls about once a week; brother Minh visits now and then. From the doctor visit (day 44) the care
      plan is "Lan calls 3x/week", which holds for about a month and then fades (last call day 85 -> on day 90 the
      app shows "5 days since anyone called").
    * ``tu``: lives with his wife; son Khoa calls about twice a week and visits some Sundays.
    * ``control``: daughter Thảo calls every few days and visits on Sundays.
    """
    rng = np.random.default_rng([seed, 501, len(key)])
    fam = {f["id"]: f["name"] for f in profile.get("family") or []}
    out: list[dict] = []

    def add(d, member, kind):
        if 1 <= d <= days and not any(c["day"] == d and c["member_id"] == member for c in out):
            out.append({"day": int(d), "date": (START_DATE + timedelta(days=int(d) - 1)).isoformat(),
                        "member_id": member, "member_name": fam.get(member, member), "kind": kind,
                        "duration_min": int(rng.integers(20, 120)) if kind == "visit" else int(rng.integers(3, 15)),
                        "source": "simulated", "simulated": True})

    def sunday(d):  # weekday of the generator calendar
        return (START_DATE + timedelta(days=d - 1)).weekday() == 6

    if key == "hanh":
        d = 3
        while d < HANH["intervention"]:
            add(d, "lan", "call")
            d += int(rng.integers(6, 10))
        for d in (20, 41):
            add(d, "minh", "visit")
        for d in range(HANH["intervention"], 79):  # care plan: Mon/Wed/Fri-like rhythm, the odd one missed
            if (d - HANH["intervention"]) % 7 in (0, 2, 4) and rng.random() > 0.1:
                add(d, "lan", "call")
        add(60, "minh", "visit")
        for d in (81, 85):  # the habit fades
            add(d, "lan", "call")
    elif key == "tu":
        d = 2
        while d <= days - 1:
            add(d, "khoa", "call")
            d += int(rng.integers(2, 6))
        for d in range(1, days + 1):
            if sunday(d) and rng.random() < 0.5:
                add(d, "khoa", "visit")
        add(days - 1, "khoa", "call")
    else:
        d = 1
        while d <= days - 1:
            add(d, "thao", "call")
            d += int(rng.integers(2, 5))
        for d in range(1, days + 1):
            if sunday(d) and rng.random() < 0.6:
                add(d, "thao", "visit")
        add(days - 1, "thao", "call")
    out = [c for c in out if c["day"] <= days]
    out.sort(key=lambda c: (c["day"], c["member_id"]))
    return out


# ---------------------------------------------------------------------------------------------
# Cohort
# ---------------------------------------------------------------------------------------------
DECLINE_TYPES = ("cognitive_drift", "frailty_symptom", "mood_withdrawal", "missed_calls")
DIALECT_SPEECH = {"south": 4.6, "central": 4.3, "north": 4.9}  # syllables / s (assumed population means)
# Education level of each simulated elder, drawn from its OWN RNG stream ([seed, i, EDU_STREAM]) so adding it left every
# other draw - and every existing evaluation number - unchanged. The mix is an illustrative assumption, not a census
# figure: low = no schooling / primary, mid = lower or upper secondary, high = post-secondary.
EDUCATION_LEVELS = ("low", "mid", "high")
EDUCATION_P = (0.45, 0.40, 0.15)
EDU_STREAM = 7001
AGE_BANDS = (("62-69", 62, 69), ("70-79", 70, 79), ("80-89", 80, 89))
# Optional between-person LEVEL effects (generate_cohort(level_effects=True)); OFF by default, so the headline
# evaluation has no education or age effect. Simulation assumptions sized below the existing between-person SD
# (MATTR SD 0.04, speech-rate SD 0.5 syll/s), in the spirit of the dialect speech-rate means above; not literature
# values. They shift a person's usual level only, not their day-to-day noise, and never their decline.
EDU_MATTR_SHIFT = {"low": -0.02, "mid": 0.0, "high": 0.02}   # absolute MATTR
AGE_SPEECH_SLOPE = -0.02                                       # syll/s per year of age above 75


def age_band(age: int | None) -> str | None:
    if age is None:
        return None
    for name, lo, hi in AGE_BANDS:
        if lo <= age <= hi:
            return name
    return "90+" if age > 89 else "<62"
FAMILY = ["Nguyễn", "Trần", "Lê", "Phạm", "Huỳnh", "Võ", "Phan", "Đặng"]
GIVEN_F = ["Hoa", "Lan", "Mai", "Cúc", "Huệ", "Nga", "Thu", "Sáu", "Năm", "Tám"]
GIVEN_M = ["Hùng", "Minh", "Tâm", "Bảy", "Ba", "Sơn", "Phúc", "Lộc", "Hải", "Chín"]
PROVINCES = {"south": ["TP.HCM", "Cần Thơ", "Bến Tre", "Long An", "Đồng Tháp"],
             "central": ["Huế", "Đà Nẵng", "Quảng Nam", "Nghệ An", "Quảng Ngãi"],
             "north": ["Hà Nội", "Hải Phòng", "Nam Định", "Thái Bình", "Bắc Ninh"]}


def _decline_eff(kind, onset, ramp, mag):
    def f(d):
        k = _ramp(d, onset, ramp) * mag
        if k <= 0:
            return {}
        if kind == "cognitive_drift":
            return {"recall_shift": 1.1 * k, "mattr": -0.05 * k, "pause_ratio": 0.35 * k,
                    "filled_pause_rate": 0.40 * k, "speech_rate_sps": -0.04 * k}
        if kind == "frailty_symptom":
            return {"speech_rate_sps": -0.08 * k, "pause_ratio": 0.20 * k, "mood_shift": 0.4 * k,
                    "symptoms": {"pain": 0.10 * k, "dizziness": 0.06 * k, "insomnia": 0.06 * k,
                                 "skipped_meal": 0.05 * k, "fall": 0.008 * k}}
        if kind == "mood_withdrawal":
            return {"mood_shift": 1.3 * k, "speech_rate_sps": -0.06 * k, "mattr": -0.03 * k,
                    "p_invalid": 0.12 * k, "symptoms": {"sadness": 0.10 * k, "insomnia": 0.04 * k,
                                                        "skipped_meal": 0.04 * k}}
        if kind == "missed_calls":
            return {"p_missed": 0.35 * k, "p_invalid": 0.08 * k}
        return {}
    return f


def generate_cohort(n: int = 200, days: int = 120, seed: int = 11, level_effects: bool = False) -> list[dict]:
    """n simulated elders (~40 % with an injected decline). Each item: elder, records, truth, simulated.

    Every elder carries ``age`` (main stream, as before) and ``education`` (own stream, see EDU_STREAM). With
    ``level_effects=True`` the usual MATTR level depends on education and the usual speech rate on age
    (EDU_MATTR_SHIFT, AGE_SPEECH_SLOPE; simulation assumptions); all random draws stay identical.
    """
    rng = np.random.default_rng(seed)
    out = []
    for i in range(n):
        prng = np.random.default_rng([seed, i])
        dialect = str(rng.choice(["south", "central", "north"], p=[0.45, 0.25, 0.30]))
        channel = str(rng.choice(["pstn", "web"], p=[0.6, 0.4]))
        female = bool(rng.random() < 0.6)
        noise = float(rng.uniform(0.7, 1.5))
        decline = bool(rng.random() < 0.4)
        kind = str(rng.choice(DECLINE_TYPES)) if decline else "stable"
        lo = max(22, min(35, days // 3))
        onset = int(rng.integers(lo, max(lo + 1, days - 34))) if decline else None
        ramp = int(rng.integers(14, 36)) if decline else 0
        mag = float(rng.uniform(0.3, 1.2)) if decline else 0.0
        level = {
            "speech_rate_sps": float(max(3.0, rng.normal(DIALECT_SPEECH[dialect], 0.5))),
            "pause_ratio": float(np.clip(rng.lognormal(math.log(0.12), 0.3), 0.04, 0.35)),
            "filled_pause_rate": float(np.clip(rng.lognormal(math.log(0.045), 0.35), 0.01, 0.15)),
            "mattr": float(np.clip(rng.normal(0.72, 0.04), 0.6, 0.85)),
        }
        ch_noise = {}
        if channel == "pstn":  # 8 kHz phone audio -> noisier VAD timings and ASR
            ch_noise = {"speech_rate_sps": 1.2, "pause_ratio": 1.3, "filled_pause_rate": 1.2, "mattr": 1.15}
        if dialect == "central":  # weaker ASR on central accents -> noisier lexical metrics (assumption)
            ch_noise = {m: v * {"mattr": 1.2, "filled_pause_rate": 1.2}.get(m, 1.0)
                        for m, v in ({**{k: 1.0 for k in REL_SD}, **ch_noise}).items()}
        person = _Person(prng, level, noise=noise, ch_noise=ch_noise,
                         p_missed=float(rng.uniform(0.01, 0.06)),
                         p_invalid=(0.05 if channel == "pstn" else 0.03),
                         mood_mean=float(rng.uniform(3.6, 4.4)), weekday=_weekday_effects(prng, noise))
        eff = _decline_eff(kind, onset, ramp, mag) if decline else (lambda d: {})
        eid = f"c{i + 1:03d}"
        education = str(np.random.default_rng([seed, i, EDU_STREAM]).choice(EDUCATION_LEVELS, p=EDUCATION_P))
        # records use only the person's own stream (prng), so building them after the profile draws changes nothing
        given = str(rng.choice(GIVEN_F if female else GIVEN_M))
        hon = "bà" if female else "ông"
        profile = {
            "id": eid, "display_name": f"{hon.capitalize()} {given}", "name_en": f"{'Mrs' if female else 'Mr'} {given}",
            "honorific": hon, "self_ref": "con", "age": int(rng.integers(62, 90)),
            "province": str(rng.choice(PROVINCES[dialect])), "dialect": dialect, "lives_alone": bool(rng.random() < 0.3),
            "channel_pref": channel, "conditions": [], "medications": [], "family": [], "goals": [], "memory_facts": [],
            "noise_level": round(noise, 3), "education": education,
        }
        if level_effects:
            level["mattr"] = float(np.clip(level["mattr"] + EDU_MATTR_SHIFT[education], 0.6, 0.85))
            level["speech_rate_sps"] = float(max(3.0, level["speech_rate_sps"]
                                                 + AGE_SPEECH_SLOPE * (profile["age"] - 75)))
        records = [person.day(eid, d, eff(d), START_DATE) for d in range(1, days + 1)]
        out.append({
            "elder": profile,
            "records": [to_dict(r) for r in records],
            "notes": [], "events": [], "dmaic": {},
            "truth": {"decline": decline, "onset_day": onset, "type": kind, "magnitude": round(mag, 3),
                      "ramp_days": ramp},
            "simulated": True,
        })
    return out
