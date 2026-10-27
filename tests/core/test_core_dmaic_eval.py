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
    assert e["diff"] > 0 and e["diff_ci95"][0] <= e["diff"] <= e["diff_ci95"][1] and e["n_pre"] > 0
    # helper records are flagged simulated -> the pre/post effect is illustrative
    assert c["effect_illustrative"] is True and "Illustrative" in c["effect_note_en"]
    recs[-1].simulated = False  # a live call appended to a scripted history: the scripted effect stays illustrative
    assert compute_cycle(recs, lights, {"goals": ["a"]}, intervention_day=40)["effect_illustrative"] is True
    for r in recs:
        r.simulated = False
    assert compute_cycle(recs, lights, {"goals": ["a"]}, intervention_day=40)["effect_illustrative"] is False
    real = compute_cycle(recs, lights, {"goals": ["a"]}, intervention_day=40, simulated=False)
    assert real["effect_illustrative"] is False and "regression to the mean" in real["effect_note_en"]
    assert "Minh họa" not in next(p for p in real["phases"] if p["phase"] == "improve")["summary_vi"]
    for p in c["phases"]:  # recall (0-3) never shown as a percentage
        assert "nhớ chuyện hôm trước" not in p["summary_vi"] and "/3" not in p["summary_vi"]


def test_compute_cycle_without_intervention():
    recs = series(40)
    c = compute_cycle(recs, evaluate_series(recs), {}, intervention_day=None)
    assert len(c["phases"]) == 5 and c["effect"] == {} and c["new_baseline_day"] is None
    assert c["effect_illustrative"] is False and c["effect_note_vi"] == "" and c["effect_note_en"] == ""
    st = {p["phase"]: p for p in c["phases"]}
    assert st["analyze"]["status"] == "not_started" and st["analyze"]["day_from"] is None
    assert st["improve"]["status"] == "not_started" and st["improve"]["day_to"] is None
    assert st["control"]["status"] == "current" and st["define"]["status"] == "done"


def test_evaluation_runs():
    cohort = generate_cohort(n=40, days=100, seed=5)
    rep = run_evaluation(cohort, n_boot=50)
    o = rep["overall"]
    assert rep["simulated"] and rep["disclaimer"] == DISCLAIMER
    assert 0 <= o["sensitivity"] <= 1 and 0 <= o["specificity_day"] <= 1 and 0 <= o["chance_rate"] <= 1
    assert abs(o["excess_sensitivity"] - (o["sensitivity"] - o["chance_rate"])) < 2e-3
    lo, hi = o["sensitivity_ci"]
    assert lo <= o["sensitivity"] <= hi
    assert o["false_alarms_per_person_month"] >= 0
    assert set(rep["by_channel"]) <= {"pstn", "web"} and rep["by_dialect"]
    assert "missed_calls" in rep["by_decline_type"] and rep["operational"]["n_decline"] >= 0
    assert "population" in rep["ablation"]
    assert DISCLAIMER in rep["markdown"] and "| Group |" in rep["markdown"] and "Definition change" in rep["markdown"]
    # personal baseline keeps far fewer stable days in alarm than a population norm
    assert rep["ablation"]["personal_detail"]["stable_alarm_day_share"] < rep["ablation"]["population_detail"]["stable_alarm_day_share"]


def test_attribution_requires_matching_rule_and_window():
    from chaoba.core.evaluation import _first_in, _rule_events
    from chaoba.core.models import DailyLight

    def L(day, light, codes):
        return DailyLight(elder_id="x", day=day, date="", light=light, z={}, baseline_ready=True,
                          reasons=[{"code": c, "level": light} for c in codes])
    lights = [L(1, "green", []), L(2, "yellow", ["unanswered"]), L(3, "yellow", ["unanswered", "metric_trend"]),
              L(4, "yellow", ["metric_trend"]), L(5, "green", []), L(6, "yellow", ["metric_trend"])]
    assert _rule_events(lights, {"metric_trend"}) == [3, 6]
    assert _rule_events(lights, {"unanswered"}) == [2]
    assert _first_in([3, 6], 4, 10) == 6 and _first_in([3, 6], 4, 5) is None


def test_chance_rate_without_decline_is_reported():
    """Stable elders given pseudo-onsets: the chance rate is the same attribution rule with no decline."""
    from chaoba.core.evaluation import _hit_matrix
    stable = [{"events": {"cognitive_drift": [50]}, "last_day": 100}, {"events": {"cognitive_drift": []}, "last_day": 100}]
    dec = [{"type": "cognitive_drift", "onset": 40}, {"type": "cognitive_drift", "onset": 60}]
    m = _hit_matrix(stable, dec, lambda r: r["type"], 45)
    assert m.tolist() == [[1.0, 0.0], [0.0, 0.0]]


def test_holdout_curve_and_selection_deterministic(tmp_path):
    from chaoba.core.evaluation import curve_svg, run_holdout, select_threshold, write_curve_csv
    dev = generate_cohort(n=30, days=90, seed=3)
    test = generate_cohort(n=30, days=90, seed=4)
    a = run_holdout(dev, test, grid=(2.0, 3.0), n_boot=20, dev_seed=3, test_seed=4)
    b = run_holdout(dev, test, grid=(2.0, 3.0), n_boot=20, dev_seed=3, test_seed=4)
    assert a["markdown"] == b["markdown"] and a["overall"] == b["overall"]
    h = a["holdout"]
    assert h["chosen_L_yellow"] in (2.0, 3.0) and h["chosen_L_yellow"] == select_threshold(a["operating_curve"]["dev"])
    assert a["config"]["L_yellow"] == h["chosen_L_yellow"]
    assert {r["baseline"] for r in a["operating_curve"]["test"]} == {"personal", "population"}
    write_curve_csv(a, str(tmp_path / "c.csv"))
    assert len((tmp_path / "c.csv").read_text().splitlines()) == 1 + 2 * 2 * 2
    assert curve_svg(a).startswith("<svg") and DISCLAIMER in curve_svg(a)
