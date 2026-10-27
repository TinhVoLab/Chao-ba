from chaoba.core.control_chart import evaluate_series
from chaoba.core.dmaic import compute_cycle
from chaoba.core.evaluation import DISCLAIMER, run_evaluation
from chaoba.core.synth import generate_cohort

from core_helpers import series


def test_compute_cycle_with_intervention():
    ov = {d: {"speech_rate_sps": 3.6} for d in range(30, 40)}
    recs = series(80, ov)
    lights = evaluate_series(recs)
    c = compute_cycle(recs, lights, {"goals": ["a"]}, intervention_day=40)
    assert [p["phase"] for p in c["phases"]] == ["define", "measure", "analyze", "improve", "control"]
    for p in c["phases"]:
        assert p["summary_vi"] and p["summary_en"] and p["day_from"] <= p["day_to"]
    assert [p["status"] for p in c["phases"]] == ["done", "done", "done", "done", "current"]
    assert c["first_alert_day"] >= 30
    assert c["green_day"] is not None and c["days_to_green"] == c["green_day"] - 40
    e = c["effect"]["speech_rate_sps"]
    assert e["pre"] < e["post"] and e["change_pct"] > 0
    assert c["new_baseline_day"] == c["green_day"] + 21


def test_compute_cycle_without_intervention():
    recs = series(40)
    c = compute_cycle(recs, evaluate_series(recs), {}, intervention_day=None)
    assert len(c["phases"]) == 5 and c["effect"] == {} and c["new_baseline_day"] is None
    st = {p["phase"]: p for p in c["phases"]}
    assert st["analyze"]["status"] == "not_started" and st["analyze"]["day_from"] is None
    assert st["improve"]["status"] == "not_started" and st["improve"]["day_to"] is None
    assert st["control"]["status"] == "current" and st["define"]["status"] == "done"


def test_evaluation_runs():
    cohort = generate_cohort(n=40, days=100, seed=5)
    rep = run_evaluation(cohort)
    o = rep["overall"]
    assert rep["simulated"] and rep["disclaimer"] == DISCLAIMER
    assert 0 <= o["sensitivity"] <= 1 and 0 <= o["specificity_day"] <= 1
    assert o["false_alarms_per_person_month"] >= 0
    assert set(rep["by_channel"]) <= {"pstn", "web"} and rep["by_dialect"]
    assert "population" in rep["ablation"]
    assert DISCLAIMER in rep["markdown"] and "| Group |" in rep["markdown"]
    # personal baseline keeps far fewer stable days in alarm than a population norm
    assert rep["ablation"]["personal_detail"]["stable_alarm_day_share"] < rep["ablation"]["population_detail"]["stable_alarm_day_share"]
