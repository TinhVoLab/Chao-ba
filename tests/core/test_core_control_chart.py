import math

import pytest

from chaoba.core.control_chart import ControlConfig, current_baseline, evaluate_series, inflation
from chaoba.core.models import to_dict

from core_helpers import rec, series


def lights_by_day(recs, **kw):
    return {l.day: l for l in evaluate_series(recs, **kw)}


def codes(light):
    return {r["code"] for r in light.reasons}


def test_baseline_gray_then_green():
    L = lights_by_day(series(30))
    assert all(L[d].light == "gray" and not L[d].baseline_ready for d in range(1, 22))
    assert "building_baseline" in codes(L[5])
    assert all(L[d].light == "green" and L[d].baseline_ready for d in range(22, 31))


def test_baseline_estimates_and_floor():
    b = current_baseline(series(30))
    assert b["speech_rate_sps"]["center"] == pytest.approx(4.5, abs=0.06)
    assert b["speech_rate_sps"]["scale"] == pytest.approx(0.15)   # MAD tiny -> sigma floor
    assert b["recall_score"]["center"] == pytest.approx(3.0)


def test_baseline_needs_min_valid():
    recs = [rec(d, answered=(d % 2 == 0)) for d in range(1, 41)]  # half missed -> 10 valid in 21 days
    L = lights_by_day(recs)
    first_ready = min(d for d, l in L.items() if l.baseline_ready)
    assert first_ready > 21


def test_ewma_math_and_sign():
    cfg = ControlConfig()
    recs = series(25, {22: {"speech_rate_sps": 4.2}})
    L = lights_by_day(recs, cfg=cfg)
    k = inflation(21, cfg)
    center = current_baseline(recs[:21])["speech_rate_sps"]["center"]
    z = -(4.2 - center) / (0.15 * k)
    expected = cfg.lam * z / math.sqrt(cfg.lam / (2 - cfg.lam))
    assert L[22].z["speech_rate_sps"] == pytest.approx(expected, abs=1e-2)
    assert L[22].z["speech_rate_sps"] > 0  # slower speech = worse = positive
    # improvement (faster speech) gives negative z and never alerts
    L2 = lights_by_day(series(40, {d: {"speech_rate_sps": 6.0} for d in range(22, 41)}))
    assert all(L2[d].light == "green" for d in range(22, 41))
    assert L2[30].z["speech_rate_sps"] < 0


def drop(days, metric="speech_rate_sps", value=3.6):
    return {d: {metric: value} for d in days}


def test_metric_trend_yellow_after_three_days():
    L = lights_by_day(series(40, drop(range(22, 41), value=4.15)))
    ylw = [d for d, l in L.items() if l.light != "green" and d >= 22]
    first = min(ylw)
    assert L[first].light == "yellow"
    r = next(x for x in L[first].reasons if x["code"] == "metric_trend")
    assert r["metric"] == "speech_rate_sps" and r["days"] == 3
    assert r["change_pct"] < 0


def test_metric_shift_red_after_five_days_beyond_red():
    L = lights_by_day(series(40, drop(range(22, 41), value=3.2)))   # deep enough to pass L_red=4.0 on day 22
    reds = [d for d, l in L.items() if l.light == "red"]
    assert reds and "metric_shift" in codes(L[min(reds)])
    assert min(reds) == 26  # beyond L_red from day 22 -> 5 days


def test_multi_metric_red():
    ov = {d: {"pause_ratio": 0.16, "mattr": 0.69} for d in range(22, 41)}
    L = lights_by_day(series(40, ov))
    red = [d for d, l in L.items() if l.light == "red"]
    assert red
    assert any("multi_metric" in codes(L[d]) or "metric_shift" in codes(L[d]) for d in red)


def test_multi_metric_rule_isolated():
    # two metrics just beyond yellow but below red -> multi_metric red
    cfg = ControlConfig(L_red=50)
    ov = {d: {"pause_ratio": 0.15, "mattr": 0.69} for d in range(22, 41)}
    L = lights_by_day(series(40, ov), cfg=cfg)
    red = [d for d, l in L.items() if l.light == "red"]
    assert red and "multi_metric" in codes(L[min(red)])


def test_symptom_repeat_yellow_and_window():
    ov = {25: {"symptoms": {"dizziness": 1}}, 28: {"symptoms": {"dizziness": 1}}}
    L = lights_by_day(series(45, ov))
    assert L[27].light == "green"
    assert L[28].light == "yellow" and "symptom_repeat" in codes(L[28])
    # window: day 31 still includes day 25 (25..31); day 32 drops it -> raw green, hysteresis needs 3 days
    assert L[31].light == "yellow"
    assert L[33].light == "yellow" and "recovering" in codes(L[33])  # raw green on 32, 33: held
    assert L[34].light == "green"  # third consecutive better day -> steps down


def test_symptoms_outside_window_do_not_trigger():
    ov = {23: {"symptoms": {"pain": 1}}, 31: {"symptoms": {"pain": 1}}}
    L = lights_by_day(series(40, ov))
    assert all(L[d].light == "green" for d in range(22, 41))


def test_multi_symptom_red():
    ov = {30: {"symptoms": {"pain": 1}}, 32: {"symptoms": {"insomnia": 1}}, 34: {"symptoms": {"skipped_meal": 1}}}
    L = lights_by_day(series(40, ov))
    assert L[33].light == "green"
    assert L[34].light == "red" and "multi_symptom" in codes(L[34])


def test_fall_red_even_during_baseline():
    L = lights_by_day(series(40, {10: {"symptoms": {"fall": 1}}, 30: {"symptoms": {"fall": 1}}}))
    assert L[10].light == "red" and "fall" in codes(L[10])
    assert L[30].light == "red"


def test_unanswered_rules():
    ov = {d: {"answered": False} for d in (30, 31, 32)}
    L = lights_by_day(series(45, ov))
    assert L[30].light == "gray" and "missed_call" in codes(L[30])
    assert L[31].light == "yellow" and "unanswered" in codes(L[31])
    assert L[32].light == "red"
    # recovery: 3 consecutive valid better days (33,34,35) -> green on 35
    assert L[34].light == "red" and "recovering" in codes(L[34])
    assert L[35].light == "green"


def test_low_mood_yellow():
    ov = {d: {"mood": 2} for d in (30, 32, 34)}
    L = lights_by_day(series(45, ov))
    assert L[33].light == "green"
    assert L[34].light == "yellow" and "low_mood" in codes(L[34])


def test_hysteresis_requires_three_better_days():
    ov = drop(range(22, 35), value=3.5)  # deep drop then back to normal from day 35
    L = lights_by_day(series(50, ov))
    assert L[34].light == "red"
    seq = [L[d].light for d in range(35, 50)]
    # never jumps straight back on the first normal day
    assert seq[0] == "red"
    # once green, it stays green
    gi = seq.index("green")
    assert all(s == "green" for s in seq[gi:])
    # each step down was preceded by >= 3 days at the higher level after recovery started
    assert gi >= 3


def test_invalid_day_gray_but_alarm_held():
    ov = drop(range(22, 31), value=3.5)
    ov[31] = {"valid": False}
    ov[25] = {"answered": True, "valid": False}
    L = lights_by_day(series(40, ov))
    assert L[31].light == "red" and "invalid_call" in codes(L[31])
    L2 = lights_by_day(series(30, {25: {"valid": False}}))
    assert L2[25].light == "gray"


def test_rebaseline_accepts_new_normal():
    ov = {d: {"speech_rate_sps": 4.1} for d in range(30, 91)}  # permanent new level
    recs = series(90, ov)
    L = lights_by_day(recs)
    assert L[70].light in ("yellow", "red")
    L2 = lights_by_day(recs, rebaseline_days=[70])
    assert L2[70].light in ("green",)
    assert all(L2[d].light == "green" for d in range(70, 91))
    assert current_baseline(recs, rebaseline_days=[70])["speech_rate_sps"]["center"] == pytest.approx(4.1, abs=0.06)


def test_dict_records_and_reason_shape():
    recs = [to_dict(r) for r in series(40, drop(range(22, 41), value=3.6))]
    L = evaluate_series(recs)
    assert len(L) == 40
    r = next(x for l in L for x in l.reasons if x["code"] in ("metric_trend", "metric_shift"))
    assert {"code", "metric", "days", "change_pct", "level"} <= set(r)


def test_emergency_record_is_red_and_survives_recompute():
    """An emergency persisted on the record (DailyRecord.emergency) forces red via the `emergency` event rule, also
    during baseline building, and hysteresis holds it until recover_days better valid days."""
    from dataclasses import replace
    recs = series(40)
    recs[34] = replace(recs[34], emergency=True)            # day 35
    lb = lights_by_day(recs)
    assert lb[35].light == "red" and "emergency" in codes(lb[35])
    assert lb[34].light == "green"
    assert lb[36].light == "red" and "recovering" in codes(lb[36])    # held
    assert lb[38].light == "green"                                    # 3 better valid days -> steps down
    early = series(5)
    early[2] = replace(early[2], emergency=True)
    assert lights_by_day(early)[3].light == "red"                     # safety first: no baseline needed


def test_health_concern_key_is_red_and_not_a_symptom():
    recs = series(40, {35: {"symptoms": {"concern:chest_pain": 1}}, 36: {"symptoms": {"pain": 1}},
                       37: {"symptoms": {"insomnia": 1}}})
    lb = lights_by_day(recs)
    r = next(x for x in lb[35].reasons if x["code"] == "health_concern")
    assert lb[35].light == "red" and r["symptom"] == "chest_pain"
    # the concern key does not count towards multi_symptom (only pain + insomnia = 2 distinct)
    assert "multi_symptom" not in codes(lb[37])


def test_rapid_change_latency_of_existing_rules():
    """Documents (TECHNICAL_DOCUMENTATION §5.5) how fast the existing rules escalate an abrupt change; there is no
    separate rate-of-change rule. A ~20 % overnight drop in speech rate: yellow on its 3rd valid day (3 days over
    L_yellow 3.0), red `metric_shift` on its 6th (5 days over L_red 4.0). Acute events are red the same day."""
    step = series(60, {d: {"speech_rate_sps": 3.6} for d in range(30, 61)})
    lights = {l.day: l for l in evaluate_series(step)}
    assert all(lights[d].light == "green" for d in range(22, 32))
    first_yellow = min(d for d, l in lights.items() if l.light in ("yellow", "red"))
    first_red = min(d for d, l in lights.items() if l.light == "red")
    assert (first_yellow, first_red) == (32, 35)
    assert any(r["code"] == "metric_shift" for r in lights[first_red].reasons)
    fall = {l.day: l for l in evaluate_series(series(40, {33: {"symptoms": {"fall": 1}}}))}
    assert fall[33].light == "red" and fall[32].light == "green"
